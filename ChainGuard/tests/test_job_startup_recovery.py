"""1-3 回归：启动期必须回收上次进程遗留的 pending / running 作业。

缺陷形态：作业执行体是进程内 ``ThreadPoolExecutor``，worker 崩溃/容器重建会带走
线程池，数据库里的 ``pending`` 队列项与 ``running`` 执行项却留了下来。由于 ``enqueue_decision_job``
的去重条件是 ``status.in_(["pending","running"])``，这条僵尸作业会永久占住该事件的
决策入口——用户再也无法重新发起决策，且没有任何报错。

覆盖三件事：
1. 超阈值的 running 作业被判死，未超阈值的不受影响（不能误杀正在跑的作业）；
2. 判死之后重新入队真的能通（即缺陷描述的那个死锁确实被解开）；
3. **幂等**——多 worker 下四个进程都会执行启动逻辑，重复执行与并发执行都不得
   产生重复回收或重复副作用。
"""

from __future__ import annotations

import dataclasses
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from src.webapi.config import settings
from src.webapi.database import Base, SessionLocal, engine
from src.webapi.job_recovery import (
    DECISION_RECOVERY_CODE,
    IMPORT_RECOVERY_CODE,
    recover_stale_jobs,
    recover_stale_jobs_on_startup,
)
from src.webapi.models import ImportJob, Job


STALE_MINUTES = 15


@pytest.fixture()
def db():
    Base.metadata.create_all(engine)
    with SessionLocal() as session:
        yield session


def _make_job(db, *, status: str, age_minutes: float, tenant_id: str, resource_id: str) -> str:
    """直接写 updated_at：它是"上一次状态变更时刻",也是判死依据。"""
    moment = datetime.now(timezone.utc) - timedelta(minutes=age_minutes)
    job = Job(
        id=f"job-{uuid.uuid4().hex}", tenant_id=tenant_id, kind="decision", resource_id=resource_id,
        idempotency_key=f"decision:{resource_id}", status=status, progress=10, result={},
    )
    db.add(job)
    db.flush()
    job.created_at = moment
    job.updated_at = moment
    db.commit()
    return job.id


def test_stale_active_jobs_are_failed_and_fresh_ones_are_untouched(db):
    tenant = f"tenant-{uuid.uuid4().hex[:8]}"
    stale = _make_job(db, status="running", age_minutes=STALE_MINUTES + 1, tenant_id=tenant, resource_id="inc-stale")
    stale_pending = _make_job(db, status="pending", age_minutes=STALE_MINUTES + 1, tenant_id=tenant, resource_id="inc-stale-pending")
    fresh = _make_job(db, status="running", age_minutes=1, tenant_id=tenant, resource_id="inc-fresh")
    fresh_pending = _make_job(db, status="pending", age_minutes=1, tenant_id=tenant, resource_id="inc-fresh-pending")
    # 多 worker 下"别的进程正在跑的作业"对本进程也只是一行 running，唯一的区分
    # 依据就是年龄；阈值必须显著大于作业自身 60s 的执行超时预算。
    recovered = recover_stale_jobs(db, stale_after_minutes=STALE_MINUTES)

    # 断言按"这三条各自的归宿"来写，而不是按整表回收列表——回收是全表扫描，
    # 锁死列表内容等于把同一个库里别的用例的遗留数据也写进契约。
    assert stale in recovered["decision"]
    assert stale_pending in recovered["decision"]
    assert fresh not in recovered["decision"] and fresh_pending not in recovered["decision"]
    db.expire_all()
    assert db.get(Job, stale).status == "failed"
    assert db.get(Job, stale).error_code == DECISION_RECOVERY_CODE
    assert db.get(Job, stale).progress == 100
    assert db.get(Job, stale).result["message"]
    assert db.get(Job, fresh).status == "running"
    assert db.get(Job, stale_pending).status == "failed"
    assert db.get(Job, fresh_pending).status == "pending"


@pytest.mark.parametrize("blocked_status", ["pending", "running"])
def test_recovery_unblocks_re_enqueueing_the_same_incident(db, blocked_status):
    """判死的目的不是把状态改好看,而是解开去重条件造成的死锁。"""
    tenant = f"tenant-{uuid.uuid4().hex[:8]}"
    incident = f"inc-{uuid.uuid4().hex[:8]}"
    _make_job(db, status=blocked_status, age_minutes=STALE_MINUTES + 1, tenant_id=tenant, resource_id=incident)

    blocking = select(Job).where(
        Job.tenant_id == tenant, Job.kind == "decision",
        Job.resource_id == incident, Job.status.in_(["pending", "running"]),
    )
    assert db.scalar(blocking) is not None, "前置条件：僵尸作业确实会命中去重条件"

    recover_stale_jobs(db, stale_after_minutes=STALE_MINUTES)

    db.expire_all()
    assert db.scalar(blocking) is None, "回收后该事件必须能重新发起决策"


def test_stale_import_job_is_recovered_too(db):
    """导入作业跑在同一个进程内线程池上,缺陷同源。"""
    tenant = f"tenant-{uuid.uuid4().hex[:8]}"
    moment = datetime.now(timezone.utc) - timedelta(minutes=STALE_MINUTES + 1)
    item = ImportJob(
        id=f"import-{uuid.uuid4().hex}", tenant_id=tenant, file_name="a.csv",
        import_type="material", status="running", progress=60, options={}, result={},
    )
    db.add(item)
    db.flush()
    item.created_at = item.updated_at = moment
    db.commit()

    recovered = recover_stale_jobs(db, stale_after_minutes=STALE_MINUTES)

    assert recovered["import"] == [item.id]
    db.expire_all()
    assert db.get(ImportJob, item.id).status == "failed"
    assert db.get(ImportJob, item.id).result["code"] == IMPORT_RECOVERY_CODE


def test_stale_pending_import_job_is_recovered(db):
    """execute 已提交 pending 后线程池若随进程消失，同样不能永久占住导入批次。"""
    tenant = f"tenant-{uuid.uuid4().hex[:8]}"
    moment = datetime.now(timezone.utc) - timedelta(minutes=STALE_MINUTES + 1)
    item = ImportJob(
        id=f"import-{uuid.uuid4().hex}", tenant_id=tenant, file_name="queued.csv",
        import_type="material", status="pending", progress=50, options={}, result={},
    )
    db.add(item)
    db.flush()
    item.created_at = item.updated_at = moment
    db.commit()

    recovered = recover_stale_jobs(db, stale_after_minutes=STALE_MINUTES)

    assert recovered["import"] == [item.id]
    db.expire_all()
    assert db.get(ImportJob, item.id).status == "failed"
    assert db.get(ImportJob, item.id).result["code"] == IMPORT_RECOVERY_CODE


def test_recovery_does_not_claim_a_job_that_changed_after_candidate_scan(db, monkeypatch):
    """扫描后被活跃 worker 推进的作业必须由 updated_at CAS 守卫保护。"""
    tenant = f"tenant-{uuid.uuid4().hex[:8]}"
    item_id = _make_job(
        db,
        status="pending",
        age_minutes=STALE_MINUTES + 1,
        tenant_id=tenant,
        resource_id="inc-raced",
    )

    from src.webapi import job_recovery

    original_claim = job_recovery._claim

    def advance_then_claim(session, model, job_id, observed_status, observed_updated_at, values):
        if job_id == item_id:
            session.execute(
                job_recovery.update(model)
                .where(model.id == job_id)
                .values(status="running", updated_at=datetime.now(timezone.utc)),
                execution_options={"synchronize_session": False},
            )
            session.commit()
        return original_claim(
            session,
            model,
            job_id,
            observed_status,
            observed_updated_at,
            values,
        )

    monkeypatch.setattr(job_recovery, "_claim", advance_then_claim)

    recovered = recover_stale_jobs(db, stale_after_minutes=STALE_MINUTES)

    assert item_id not in recovered["decision"]
    db.expire_all()
    assert db.get(Job, item_id).status == "running"


def test_repeated_recovery_is_idempotent(db):
    """同一进程重复执行：第二次起必须回收 0 条,且不得再改动已判死的行。"""
    tenant = f"tenant-{uuid.uuid4().hex[:8]}"
    stale = _make_job(db, status="running", age_minutes=STALE_MINUTES + 1, tenant_id=tenant, resource_id="inc-1")

    first = recover_stale_jobs(db, stale_after_minutes=STALE_MINUTES)
    db.expire_all()
    fingerprint = (db.get(Job, stale).status, db.get(Job, stale).error_code, db.get(Job, stale).updated_at)

    second = recover_stale_jobs(db, stale_after_minutes=STALE_MINUTES)
    third = recover_stale_jobs(db, stale_after_minutes=STALE_MINUTES)

    assert stale in first["decision"]
    assert stale not in second["decision"] and stale not in third["decision"]
    db.expire_all()
    assert (db.get(Job, stale).status, db.get(Job, stale).error_code, db.get(Job, stale).updated_at) == fingerprint


def test_concurrent_workers_each_job_is_recovered_exactly_once(db):
    """多 worker 幂等性：4 个并发执行者,每条僵尸作业只能被其中一个认领。

    这正是 --workers 4 的现场——四个进程各自跑一遍启动回收。断言锁的是
    "认领结果不重不漏",而不是"哪个 worker 抢到"。
    """
    tenant = f"tenant-{uuid.uuid4().hex[:8]}"
    stale_ids = {
        _make_job(db, status="running", age_minutes=STALE_MINUTES + 1, tenant_id=tenant, resource_id=f"inc-{index}")
        for index in range(6)
    }

    def worker() -> list[str]:
        # 每个 worker 用自己的 Session,与四个进程各自建连接同构
        with SessionLocal() as session:
            return recover_stale_jobs(session, stale_after_minutes=STALE_MINUTES)["decision"]

    with ThreadPoolExecutor(max_workers=4) as pool:
        claims = [item for future in [pool.submit(worker) for _ in range(4)] for item in future.result()]

    assert len(claims) == len(set(claims)), f"同一作业被多个 worker 重复回收：{claims}"
    assert stale_ids <= set(claims), "有僵尸作业无人认领"
    db.expire_all()
    assert all(db.get(Job, job_id).status == "failed" for job_id in stale_ids)


def test_startup_hook_respects_the_disable_switch(db, monkeypatch):
    """e2e/演示需要一个确定性开关,与既有 CHAINGUARD_DISABLE_SCHEDULER 同款。"""
    tenant = f"tenant-{uuid.uuid4().hex[:8]}"
    stale = _make_job(db, status="running", age_minutes=STALE_MINUTES * 10, tenant_id=tenant, resource_id="inc-off")
    # settings 是 frozen dataclass，只能整体替换
    monkeypatch.setattr(
        "src.webapi.job_recovery.settings",
        dataclasses.replace(settings, job_recovery_disabled=True),
    )

    assert recover_stale_jobs_on_startup() == {"decision": [], "import": []}
    db.expire_all()
    assert db.get(Job, stale).status == "running"

    # 这条用例故意留下一个"永远够老"的 running 作业，跑完必须收走：
    # 同一个 SQLite 库被整轮 pytest 共用，留着它会让后续任何触发启动钩子的
    # 用例多回收一条，形成难查的跨模块耦合。
    db.delete(db.get(Job, stale))
    db.commit()


def test_startup_hook_is_registered_on_the_app():
    """回收必须挂在进程启动上——只有函数存在、没人调用是这类缺陷的常见复发形态。"""
    import src.api as api

    handlers = {handler.__name__ for handler in api.app.router.on_startup}
    assert "recover_stale_jobs_on_startup" in handlers
