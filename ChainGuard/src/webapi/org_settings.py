"""审批链与数据范围配置（规格：codex_frontend_spec/02_角色权限体系.md §3、§审批链配置页）。

存储复用 `TenantConfig`（config_type = approval_chain / data_scope），因此不需要新迁移，
并且天然获得版本号 + 单 active 约束 + 审计可追溯。

数据范围的实际执行在 `data_scope.py`：本模块只负责"配置存哪、怎么校验"，
过滤逻辑与查询收口在那边，两边的语义由 tests/test_data_scope.py 一起锁定。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .entity_mapping import activate_tenant_config, active_tenant_config
from .errors import ApiError
from .models import Role, User

APPROVAL_CHAIN_CONFIG = "approval_chain"
DATA_SCOPE_CONFIG = "data_scope"

RISK_LEVELS = ("low", "medium", "high")
VALID_SCOPES = ("all", "dept", "own", "custom")

# 与 seed.py 的内置角色分工一致：低风险供应链负责人直批，高风险老板审批 + 财务会签。
DEFAULT_APPROVAL_CHAIN: dict[str, Any] = {
    "levels": {
        "low": {"approver": "scm_lead", "countersign": []},
        "medium": {"approver": "scm_lead", "countersign": []},
        "high": {"approver": "boss", "countersign": ["finance"]},
    },
    "financeCountersign": True,
}


def _tenant_role_codes(db: Session, tenant_id: str) -> set[str]:
    return {row for row in db.scalars(select(Role.code).where(Role.tenant_id == tenant_id)).all()}


# ------------------------------------------------------------------ 审批链


def approval_chain_view(db: Session, tenant_id: str) -> dict[str, Any]:
    config = active_tenant_config(db, tenant_id, APPROVAL_CHAIN_CONFIG)
    if config is None:
        return {**DEFAULT_APPROVAL_CHAIN, "version": 0, "source": "default", "configured": False}
    payload = dict(config.payload or {})
    return {
        **DEFAULT_APPROVAL_CHAIN,
        **payload,
        "version": config.version,
        "source": config.source,
        "configured": True,
    }


def validate_approval_chain(db: Session, tenant_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """校验并归一化审批链配置；审批人必须是本租户真实存在的角色。"""
    role_codes = _tenant_role_codes(db, tenant_id)
    incoming = body.get("levels")
    if not isinstance(incoming, dict):
        raise ApiError(422, "CG-2810", "审批链配置缺少 levels")

    levels: dict[str, Any] = {}
    for level in RISK_LEVELS:
        entry = incoming.get(level)
        if not isinstance(entry, dict):
            raise ApiError(422, "CG-2810", f"缺少 {level} 风险等级的审批配置")
        approver = str(entry.get("approver") or "").strip()
        if approver not in role_codes:
            raise ApiError(422, "CG-2811", f"审批人角色不存在：{approver or '(空)'}")
        countersign_raw = entry.get("countersign") or []
        if not isinstance(countersign_raw, list):
            raise ApiError(422, "CG-2810", "countersign 必须是角色数组")
        countersign = [str(code).strip() for code in countersign_raw if str(code).strip()]
        unknown = [code for code in countersign if code not in role_codes]
        if unknown:
            raise ApiError(422, "CG-2811", f"会签角色不存在：{', '.join(unknown)}")
        levels[level] = {"approver": approver, "countersign": countersign}

    return {"levels": levels, "financeCountersign": bool(body.get("financeCountersign", True))}


def save_approval_chain(db: Session, tenant_id: str, body: dict[str, Any], *, actor: str | None = None) -> dict[str, Any]:
    payload = validate_approval_chain(db, tenant_id, body)
    config = activate_tenant_config(
        db, tenant_id, APPROVAL_CHAIN_CONFIG, payload, source="expert", approved_by=actor,
    )
    return {**payload, "version": config.version, "source": config.source, "configured": True}


# ---------------------------------------------------------------- 数据范围


def data_scope_view(db: Session, tenant_id: str) -> dict[str, Any]:
    """角色级默认数据范围 + 各角色当前用户数，供配置页展示。"""
    config = active_tenant_config(db, tenant_id, DATA_SCOPE_CONFIG)
    stored: dict[str, str] = dict((config.payload or {}).get("roles", {})) if config else {}

    roles = list(db.scalars(select(Role).where(Role.tenant_id == tenant_id)).all())
    users = list(db.scalars(select(User).where(User.tenant_id == tenant_id)).all())
    user_counts: dict[str, int] = {}
    for user in users:
        user_counts[user.role_code] = user_counts.get(user.role_code, 0) + 1

    rows = [
        {
            "code": role.code,
            "name": role.name,
            "scope": stored.get(role.code, "all" if role.code in {"admin", "boss", "scm_lead", "finance", "auditor"} else "custom"),
            "userCount": user_counts.get(role.code, 0),
        }
        for role in sorted(roles, key=lambda item: item.code)
    ]
    return {
        "roles": rows,
        "version": config.version if config else 0,
        "configured": config is not None,
        # 行级过滤已在 data_scope.py 落地并由 test_data_scope 锁定，前端不再显示"待生效"提示。
        "enforced": True,
    }


def save_data_scope(db: Session, tenant_id: str, body: dict[str, Any], *, actor: str | None = None) -> dict[str, Any]:
    role_codes = _tenant_role_codes(db, tenant_id)
    incoming = body.get("roles")
    if not isinstance(incoming, dict):
        raise ApiError(422, "CG-2812", "数据范围配置缺少 roles")

    normalized: dict[str, str] = {}
    for code, scope in incoming.items():
        code = str(code).strip()
        scope = str(scope).strip()
        if code not in role_codes:
            raise ApiError(422, "CG-2811", f"角色不存在：{code}")
        if scope not in VALID_SCOPES:
            raise ApiError(422, "CG-2813", f"非法数据范围：{scope}")
        normalized[code] = scope

    activate_tenant_config(
        db, tenant_id, DATA_SCOPE_CONFIG, {"roles": normalized}, source="expert", approved_by=actor,
    )
    return data_scope_view(db, tenant_id)
