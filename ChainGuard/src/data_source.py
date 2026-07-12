from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
_DEMO_SCENARIO_DB = (
    PROJECT_ROOT
    / "demo_assets"
    / "enterprise"
    / "database"
    / "chainguard_enterprise_demo.db"
)


@dataclass(frozen=True)
class DataSource:
    kind: str
    tenant_id: str
    label: str
    scenario_db_path: str
    experience_cards_path: str
    audit_log_path: str


def demo_source() -> DataSource:
    return DataSource(
        kind="demo",
        tenant_id="default",
        label="演示数据（默认场景）",
        scenario_db_path=str(_DEMO_SCENARIO_DB),
        experience_cards_path="data/experience_cards.json",
        audit_log_path="data/audit_log.jsonl",
    )


def tenant_scenario_db_path(tenant_id: str) -> Path:
    """与 db.py:_sqlite_path_for_tenant 约定一致：xxx.<tenant>.db"""
    base = _DEMO_SCENARIO_DB
    if tenant_id == "default":
        return base
    return base.with_name(f"{base.stem}.{tenant_id}{base.suffix}")


def enterprise_source(tenant_id: str, *, require_exists: bool = True) -> DataSource:
    """构造企业数据源；require_exists=True 时校验租户库已存在，否则抛 ValueError。"""
    tenant_id = _normalize_tenant_id(tenant_id)
    db_path = tenant_scenario_db_path(tenant_id)
    if require_exists and not db_path.exists():
        raise ValueError(f"未知租户数据源：{tenant_id}")
    return DataSource(
        kind="enterprise",
        tenant_id=tenant_id,
        label=f"企业数据 · 租户 {tenant_id}",
        scenario_db_path=str(db_path),
        experience_cards_path=f"data/experience_cards.{tenant_id}.json",
        audit_log_path=f"data/audit_log.{tenant_id}.jsonl",
    )


def _normalize_tenant_id(tenant_id: str | None) -> str:
    import re

    normalized = (tenant_id or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", normalized) or normalized == "default":
        raise ValueError(
            f"非法租户 ID：{tenant_id!r}（仅允许字母数字/下划线/连字符，且不能为 default）"
        )
    return normalized
