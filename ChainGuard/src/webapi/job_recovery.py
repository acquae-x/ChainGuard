"""启动期回收上次进程遗留的 pending / running 作业（1-3）。

背景：``jobs.py`` 的 ``job_executor`` / ``decision_executor`` 是**进程内**
``ThreadPoolExecutor``。worker 崩溃、容器重建、``docker compose down`` 都会带走
线程池，但数据库里已经入队的 ``pending`` 与正在执行的 ``running`` 行都会留
下来，而且再没有任何代码会去动它。

后果不止是"一条脏记录"：``enqueue_decision_job`` 的去重条件是
``status.in_(["pending", "running"])``，命中即直接返回既有作业。于是该事件的决策
入口被一条永远不会推进的作业永久占住，用户再也无法为它重新发起决策——表现为
点了没反应、进度条停在 10%，且没有任何错误提示。

修法：进程启动时把"超过阈值仍处于 pending / running"的作业判死，标记为 failed 并给出可读
的错误码，用户即可重新发起。不选择"重新入队"，因为多 worker 下四个进程会同时
执行启动逻辑，重新入队需要额外的选主机制才能避免同一作业被跑四遍；而判死 + 让
用户重试是幂等的、无副作用的，也更诚实（作业确实没有结果）。

**多 worker 幂等性**是这里的核心约束。四个 uvicorn worker 各自执行一次启动回收，
必须保证：同一作业只被回收一次、并发执行不产生重复副作用、重复调用无额外效果。
实现上用"带状态守卫的条件 UPDATE"（compare-and-swap）：

    UPDATE jobs SET status='failed' ...
    WHERE id=:id AND status=:observed_status AND updated_at=:observed_updated_at

状态与更新时间都参与 compare-and-swap：先抢到的进程 rowcount=1，其余进程的
WHERE 已不匹配、rowcount=0；若扫描后活跃 worker 已把 pending 推进为 running，
或刷新了作业时间，本次回收同样会放弃该候选。这在 SQLite 与 PostgreSQL 上都是
单语句原子的，不需要额外的锁或 advisory lock。函数只把 ``rowcount=1`` 的作业
计入自己的回收结果，因此日志与返回值也不会重复计数。

同理，这里刻意**不**发通知：一是几小时前就死掉的作业此刻再弹一条消息只是噪音，
二是通知属于不可回滚的外部副作用，一旦某个 worker 在 commit 与发通知之间崩溃，
幂等保证就断了。回收事件只落 ``log_event``。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

from src.observability import log_event

from .config import settings
from .database import SessionLocal
from .models import ImportJob, Job

# 与 CG-25xx（决策）/ CG-26xx（导入）编码段一致；前端按码展示文案。
DECISION_RECOVERY_CODE = "CG-2503"
IMPORT_RECOVERY_CODE = "CG-2603"
DECISION_RECOVERY_MESSAGE = "决策作业因服务重启中断，请重新发起"
IMPORT_RECOVERY_MESSAGE = "导入作业因服务重启中断，请重新上传"
ACTIVE_JOB_STATUSES = ("pending", "running")


def _as_utc(value: datetime | None) -> datetime | None:
    """SQLite 把 ``DateTime(timezone=True)`` 读回来是 naive 的，先补 UTC 再比较。"""
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _claim(
    db,
    model,
    job_id: str,
    observed_status: str,
    observed_updated_at: datetime,
    values: dict,
) -> bool:
    """条件 UPDATE：只有把扫描时未再变化的活跃行翻走的进程返回 True。

    ``synchronize_session=False``：这里不需要 ORM 回写内存对象，关掉它可以确保
    语句就是一条纯 UPDATE，不会为了同步会话先补一次 SELECT——那次 SELECT 会在
    SQLite 上把事务变成"先持读锁再升级写锁"，多 worker 并发时直接撞 SQLITE_BUSY。
    """
    result = db.execute(
        update(model)
        .where(
            model.id == job_id,
            model.status == observed_status,
            model.updated_at == observed_updated_at,
        )
        .values(**values),
        execution_options={"synchronize_session": False},
    )
    return bool(result.rowcount)


def recover_stale_jobs(db, *, stale_after_minutes: float | None = None, now: datetime | None = None) -> dict[str, list[str]]:
    """把超时仍处于 pending / running 的作业判死，返回**本次调用真正回收**的作业 id。

    幂等：重复调用（或多个 worker 并发调用）只有第一次会返回非空列表。

    注意本函数会在 ``db`` 上提交事务（写事务窗口必须尽量短，见下方注释），
    因此调用方不应把未提交的业务改动挂在同一个 Session 上。
    """
    threshold = settings.job_recovery_stale_minutes if stale_after_minutes is None else stale_after_minutes
    moment = _as_utc(now) or datetime.now(timezone.utc)
    cutoff = moment - timedelta(minutes=float(threshold))

    recovered: dict[str, list[str]] = {"decision": [], "import": []}
    for bucket, model, code, message in (
        ("decision", Job, DECISION_RECOVERY_CODE, DECISION_RECOVERY_MESSAGE),
        ("import", ImportJob, IMPORT_RECOVERY_CODE, IMPORT_RECOVERY_MESSAGE),
    ):
        # 先只读地筛出候选。只取列而不取 ORM 实体：避免把一批马上就要被 UPDATE
        # 绕过 ORM 改掉的对象塞进身份映射，留下"内存里还是 running"的陷阱。
        # 年龄判定放在 Python 侧而不是 SQL 侧，因为 updated_at 在 SQLite 上取回是
        # naive 的，直接在 SQL 里与带时区的 cutoff 比较会因后端而异。
        candidates = [
            (row_id, status, updated_at)
            for row_id, status, updated_at in db.execute(
                select(model.id, model.status, model.updated_at).where(
                    model.status.in_(ACTIVE_JOB_STATUSES)
                )
            ).all()
            if (moment_utc := _as_utc(updated_at)) is not None and moment_utc < cutoff
        ]
        # 读事务到此结束。SQLite 下若把读锁一直持到写入,多个 worker 同时升级锁
        # 会立即 SQLITE_BUSY 而不是排队等待。
        db.commit()
        values = {"status": "failed", "progress": 100, "result": {"code": code, "message": message}}
        if model is Job:
            values["error_code"] = code
        # 逐条认领并逐条提交：候选可能已被别的 worker 抢走,_claim 返回 False 即
        # 代表"别人已经回收过了",不是错误。单条提交也把写事务窗口压到最短。
        for job_id, observed_status, observed_updated_at in candidates:
            claimed = _claim(
                db,
                model,
                job_id,
                observed_status,
                observed_updated_at,
                values,
            )
            db.commit()
            if claimed:
                recovered[bucket].append(job_id)

    if recovered["decision"] or recovered["import"]:
        log_event(
            "stale_jobs_recovered",
            decision_jobs=len(recovered["decision"]),
            import_jobs=len(recovered["import"]),
            stale_after_minutes=float(threshold),
        )
    return recovered


def recover_stale_jobs_on_startup() -> dict[str, list[str]]:
    """FastAPI 启动钩子入口：自带 Session，失败不得阻止服务起来。

    回收是尽力而为的清理，不是就绪条件——数据库此刻不可用时 ``/readyz`` 已经会
    如实报不就绪，这里再抛一次只会把一个可自愈的瞬时故障升级成启动崩溃。
    """
    if settings.job_recovery_disabled:
        log_event("job_recovery_disabled")
        return {"decision": [], "import": []}
    try:
        from .jobs import sync_jobs_pending_metric

        with SessionLocal() as db:
            recovered = recover_stale_jobs(db)
            # 判死之后 pending/running 压力指标必须重算，否则 Prometheus 上会一直
            # 留着上个进程遗留的作业计数。
            sync_jobs_pending_metric(db)
            return recovered
    except Exception as error:  # pragma: no cover - 依赖数据库瞬时故障
        log_event("job_recovery_failed", exception=type(error).__name__)
        return {"decision": [], "import": []}
