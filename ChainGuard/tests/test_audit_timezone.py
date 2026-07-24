"""审计/审批时间戳的时区回归。

锁住的缺陷：``add_audit`` 及审批历史此前用 ``datetime.now().astimezone()`` 落库，
写进去的是**服务器进程时区**（生产容器 TZ 各异）。同一逻辑事件在 +01 主机与 +08
主机读出不同偏移，且与批次 3 建立的"持久化用 UTC、显示按租户时区"架构相悖——
工作台"最近审计动态"里因此同时出现 +08:00 与 +01:00 两种偏移。

修复分两层，本文件各自锁定：
  1. 存储：一律 UTC（``utc_now_iso``），与服务器时区无关，可确定复现。
  2. 显示：审计读取端点按租户时区本地化（``localize_record_times``），与
     node_health ``generatedAt`` 的既有口径一致。

期望值从第一性原理推导：UTC 存储 ⇒ 偏移恒为 +00:00；上海显示 ⇒ 偏移 +08:00 且
墙钟 = UTC 墙钟 + 8h。不从当前观测反写。
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from src.webapi.auth import AuthContext
from src.webapi.database import Base
from src.webapi.models import AuditLog, Tenant
from src.webapi.repository.base import add_audit
from src.webapi.routers.business import audit_logs, dashboard_audit
from src.webapi.tenant_time import localize_iso, utc_now_iso


@contextmanager
def _sqlite_session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db
    engine.dispose()


def _tenant(db: Session, tz: str) -> str:
    tenant_id = f"tenant-audit-{uuid.uuid4().hex}"
    db.add(Tenant(id=tenant_id, name="T", timezone=tz))
    db.flush()
    return tenant_id


def _ctx(tenant_id: str) -> AuthContext:
    return AuthContext("u-audit", tenant_id, "审计人", "admin", ("*",))


# --- 纯函数层：这是本次修复的正确性内核，完全确定 ------------------------------

def test_utc_now_iso_offset_is_always_utc():
    # 与进程本地时区无关：偏移必须是 +00:00，绝不是 astimezone() 那种服务器偏移。
    assert utc_now_iso().endswith("+00:00")
    fixed = datetime(2026, 2, 1, 16, 30, tzinfo=timezone.utc)
    assert utc_now_iso(fixed) == "2026-02-01T16:30:00+00:00"


def test_localize_iso_shifts_utc_instant_into_tenant_calendar():
    shanghai = ZoneInfo("Asia/Shanghai")
    # 2026-02-01 16:30Z 是上海 2026-02-02 00:30 —— 跨了本地日界。
    assert localize_iso("2026-02-01T16:30:00+00:00", shanghai) == "2026-02-02T00:30:00+08:00"
    # 同一墙钟、无偏移的输入按 UTC 解读（存储契约），结论相同。
    assert localize_iso("2026-02-01T16:30:00", shanghai) == "2026-02-02T00:30:00+08:00"


def test_localize_iso_passes_through_blank_and_garbage():
    shanghai = ZoneInfo("Asia/Shanghai")
    assert localize_iso("", shanghai) == ""
    assert localize_iso(None, shanghai) is None
    # 显示助手绝不能把一条脏数据升级成 500。
    assert localize_iso("not-a-timestamp", shanghai) == "not-a-timestamp"


# --- 存储层：落库的原始 time 必须是 UTC，与服务器时区解耦 ----------------------

def test_add_audit_persists_utc_not_server_local():
    with _sqlite_session() as db:
        tenant_id = _tenant(db, "Asia/Shanghai")
        add_audit(db, _ctx(tenant_id), "登录", "user", "u1", "管理员", {})
        db.flush()
        stored = db.scalar(select(AuditLog).where(AuditLog.tenant_id == tenant_id))
        # 原始存储值——不经端点本地化——必须是 UTC 偏移。
        assert str(stored.time).endswith("+00:00"), f"审计 time 落库带了非 UTC 偏移：{stored.time}"


# --- 显示层：读取端点按租户时区本地化，且与存储偏移无关 ------------------------

def test_dashboard_audit_localizes_time_to_shanghai():
    with _sqlite_session() as db:
        tenant_id = _tenant(db, "Asia/Shanghai")
        add_audit(db, _ctx(tenant_id), "登录", "user", "u1", "管理员", {})
        db.flush()
        rows = dashboard_audit(_ctx(tenant_id), db)
        assert rows, "应至少返回一条审计"
        assert str(rows[0]["time"]).endswith("+08:00")
        assert str(rows[0]["createdAt"]).endswith("+08:00")


def test_audit_logs_endpoint_localizes_to_utc_tenant_as_plus_zero():
    # 探针有效性反证：换一个 UTC 租户，同一套代码必须给出 +00:00，
    # 证明 +08:00 是真的按租户时区算出来的，而不是把所有输出硬编码成上海。
    with _sqlite_session() as db:
        tenant_id = _tenant(db, "UTC")
        add_audit(db, _ctx(tenant_id), "登录", "user", "u1", "管理员", {})
        db.flush()
        result = audit_logs(_ctx(tenant_id), db, current=1, page_size=20, user_id=None, target_type=None, action=None)
        assert result["data"], "应至少返回一条审计"
        assert str(result["data"][0]["time"]).endswith("+00:00")


def test_same_instant_reads_identically_regardless_of_display_zone():
    """跨租户一致性：同一 UTC 存储值，在上海读到的墙钟必须正好比 UTC 读到的多 8 小时。"""
    fixed = "2026-02-01T16:30:00+00:00"
    utc = datetime.fromisoformat(localize_iso(fixed, ZoneInfo("UTC")))
    sh = datetime.fromisoformat(localize_iso(fixed, ZoneInfo("Asia/Shanghai")))
    # 同一时刻
    assert utc == sh
    # 但墙钟相差 8 小时
    assert sh.replace(tzinfo=None) - utc.replace(tzinfo=None) == datetime(2026, 2, 2, 0, 30) - datetime(2026, 2, 1, 16, 30)
