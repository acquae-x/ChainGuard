"""行级数据范围求值与强制执行。

四档范围：
    all    —— 全企业，不加任何过滤
    dept   —— 本部门**及其所有子部门**（按 departments.parent_id 闭包展开）
    own    —— 仅本人负责（owner_id 命中当前用户）
    custom —— 管理员为该用户显式勾选的部门清单

生效优先级：用户自身 `User.data_scope` 优先；用户未单独设定时回落到角色级默认值
（TenantConfig config_type=data_scope 的 roles 映射）。

**未归属记录（dept_id 与 owner_id 皆空）对全租户可见**，这是刻意的选择：
系统自动重算出来的风险没有天然的负责人或部门，若按"缺归属即隐藏"处理，
最需要被看到的风险会对所有人不可见——对一个风险预警产品来说这是最坏的失效方向。
记录一旦有了负责人或部门，就立即进入行级隔离。这条规则由 test_data_scope 显式锁定。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import ColumnElement, Select, and_, or_, select
from sqlalchemy.orm import Session

from .auth import AuthContext
from .entity_mapping import active_tenant_config
from .models import Department

DATA_SCOPE_CONFIG = "data_scope"
VALID_SCOPES = ("all", "dept", "own", "custom")


def _config_payload(db: Session, tenant_id: str) -> dict[str, Any]:
    config = active_tenant_config(db, tenant_id, DATA_SCOPE_CONFIG)
    return dict(config.payload or {}) if config else {}


def effective_scope(db: Session, ctx: AuthContext) -> str:
    """当前用户实际生效的数据范围。

    用户自身设定优先；为空/非法时回落角色默认；再兜底 all。
    """
    if ctx.data_scope in VALID_SCOPES and ctx.data_scope != "":
        return ctx.data_scope
    roles = _config_payload(db, ctx.tenant_id).get("roles") or {}
    candidate = str(roles.get(ctx.role_code) or "all")
    return candidate if candidate in VALID_SCOPES else "all"


def custom_departments(db: Session, ctx: AuthContext) -> list[str]:
    """custom 范围下该用户被勾选的部门清单（管理员配置，落在 TenantConfig 里）。"""
    mapping = _config_payload(db, ctx.tenant_id).get("customDepartments") or {}
    values = mapping.get(ctx.user_id) or []
    return [str(item) for item in values if str(item)]


def descendant_departments(db: Session, tenant_id: str, root_id: str) -> set[str]:
    """root 部门及其全部后代的 id 集合。

    用逐层展开而不是递归 CTE：部门树规模是几十量级，可读性优先，
    且 SQLite / PostgreSQL 行为完全一致，不依赖任一方言。
    """
    if not root_id:
        return set()
    rows = list(db.scalars(select(Department).where(Department.tenant_id == tenant_id)).all())
    children: dict[str, list[str]] = {}
    for row in rows:
        if row.parent_id:
            children.setdefault(row.parent_id, []).append(row.id)

    seen = {root_id}
    frontier = [root_id]
    while frontier:
        current = frontier.pop()
        for child in children.get(current, []):
            if child not in seen:  # 防御自引用/环，避免死循环
                seen.add(child)
                frontier.append(child)
    return seen


def scope_filter(db: Session, ctx: AuthContext, model: type) -> ColumnElement[bool] | None:
    """返回该用户在此模型上的行级过滤条件；None 表示不受限。

    模型没有归属列（dept_id/owner_id）时返回 None——配置/审计一类的表本就不参与行级隔离，
    对它们强行过滤只会把系统弄坏。
    """
    if not (hasattr(model, "dept_id") and hasattr(model, "owner_id")):
        return None

    scope = effective_scope(db, ctx)
    if scope == "all":
        return None

    # 未归属记录（系统自动生成、尚无人认领）对所有人可见，见模块开头说明
    unassigned = and_(model.dept_id.is_(None), model.owner_id.is_(None))
    mine = model.owner_id == ctx.user_id

    if scope == "own":
        return or_(mine, unassigned)

    if scope == "dept":
        visible = descendant_departments(db, ctx.tenant_id, ctx.dept_id)
        if not visible:
            return or_(mine, unassigned)  # 没有部门归属时退化为只看自己的 + 未归属池
        # 本部门（含子部门）的记录，或本人负责的记录（负责人跨部门时不该看不见自己的活）
        return or_(model.dept_id.in_(visible), mine, unassigned)

    if scope == "custom":
        allowed = custom_departments(db, ctx)
        if not allowed:
            return or_(mine, unassigned)
        return or_(model.dept_id.in_(allowed), mine, unassigned)

    return None


def apply_scope(db: Session, ctx: AuthContext, model: type, stmt: Select) -> Select:
    """把行级过滤挂到查询上。查询层唯一入口，避免各处自己拼条件拼漏。"""
    condition = scope_filter(db, ctx, model)
    return stmt if condition is None else stmt.where(condition)


def is_visible(db: Session, ctx: AuthContext, item: Any) -> bool:
    """单条记录是否在范围内。用于详情读取——越权必须 404 而不是 403，避免存在性泄漏。"""
    condition = scope_filter(db, ctx, type(item))
    if condition is None:
        return True
    scope = effective_scope(db, ctx)
    owner_id = getattr(item, "owner_id", None)
    dept_id = getattr(item, "dept_id", None)
    # 与 scope_filter 保持同一套语义，两边必须同进同退
    if owner_id is None and dept_id is None:
        return True
    if owner_id == ctx.user_id:
        return True

    if scope == "own":
        return False
    if scope == "dept":
        visible = descendant_departments(db, ctx.tenant_id, ctx.dept_id)
        return bool(visible) and dept_id in visible
    if scope == "custom":
        return dept_id in custom_departments(db, ctx)
    return True
