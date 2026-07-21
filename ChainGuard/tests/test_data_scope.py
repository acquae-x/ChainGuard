"""行级数据范围的强制执行验收。

这是「数据范围只存不生效」的补课：此前 `User.data_scope` 被存储、被回显，
但没有任何查询按它过滤。下面每个测试都在证明"过滤真的发生了"，
而不只是"配置写进去了"。
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from src.api import app
from src.webapi.auth.security import AuthContext, create_tokens
from src.webapi.data_scope import descendant_departments, effective_scope, is_visible
from src.webapi.database import SessionLocal
from src.webapi.entity_mapping import activate_tenant_config
from src.webapi.models import Department, Incident, Risk, Role, Task, Tenant, User
from src.webapi.repository import get_tenant_record, list_tenant_records
from src.webapi.errors import ApiError
from src.webapi.seed import seed


seed()
client = TestClient(app)


def _ctx(user: User, scope: str) -> AuthContext:
    return AuthContext(
        user.id, user.tenant_id, user.name, user.role_code, ("*",),
        dept_id=user.dept_id, data_scope=scope,
    )


def _fixture(db):
    """一个带两级部门树、两个用户、三条事件的独立租户。"""
    tenant_id = f"t-scope-{uuid.uuid4().hex[:8]}"
    db.merge(Tenant(id=tenant_id, name=tenant_id, industry="制造", scale="small",
                    status="active", plan="trial", trial_end_at="", demo_data_flag=False))
    db.flush()
    db.add(Role(id=f"role-{tenant_id}", tenant_id=tenant_id, code="scm_lead", name="供应链", builtin=True, permissions=["*"]))
    db.flush()

    # 部门树：华东 → 华东采购；华南（同级，不相交）
    db.add(Department(id=f"{tenant_id}-east", tenant_id=tenant_id, code="EAST", name="华东", parent_id=None))
    db.flush()
    db.add(Department(id=f"{tenant_id}-east-buy", tenant_id=tenant_id, code="EASTBUY", name="华东采购", parent_id=f"{tenant_id}-east"))
    db.add(Department(id=f"{tenant_id}-south", tenant_id=tenant_id, code="SOUTH", name="华南", parent_id=None))
    db.flush()

    east = User(id=f"u-east-{tenant_id}", tenant_id=tenant_id, account=f"east@{tenant_id}", password_hash="x",
                name="华东负责人", dept_id=f"{tenant_id}-east", role_id=f"role-{tenant_id}", role_code="scm_lead",
                status="active", data_scope="all")
    south = User(id=f"u-south-{tenant_id}", tenant_id=tenant_id, account=f"south@{tenant_id}", password_hash="x",
                 name="华南负责人", dept_id=f"{tenant_id}-south", role_id=f"role-{tenant_id}", role_code="scm_lead",
                 status="active", data_scope="all")
    db.add_all([east, south])
    db.flush()

    def incident(suffix, owner_id, dept_id):
        item = Incident(id=f"inc-{tenant_id}-{suffix}", tenant_id=tenant_id, code=f"INC-{suffix}",
                        title=suffix, type="supplier_shutdown", level="high", status="open",
                        owner="", owner_id=owner_id, dept_id=dept_id,
                        source_risk_ids=[], loss=0, cost=0, notes=[])
        db.add(item)
        return item

    # 华东本部一条、华东采购（子部门）一条、华南一条、无归属一条
    incident("east", east.id, f"{tenant_id}-east")
    incident("eastbuy", None, f"{tenant_id}-east-buy")
    incident("south", south.id, f"{tenant_id}-south")
    incident("orphan", None, None)
    db.flush()
    return tenant_id, east, south


def _titles(rows) -> set[str]:
    return {row.title for row in rows}


# ------------------------------------------------------------------ 部门树


def test_descendant_departments_includes_children():
    with SessionLocal() as db:
        tenant_id, east, _ = _fixture(db)
        visible = descendant_departments(db, tenant_id, f"{tenant_id}-east")

    assert visible == {f"{tenant_id}-east", f"{tenant_id}-east-buy"}, "本部门必须包含子部门"


def test_descendant_departments_excludes_siblings():
    with SessionLocal() as db:
        tenant_id, east, _ = _fixture(db)
        visible = descendant_departments(db, tenant_id, f"{tenant_id}-east")

    assert f"{tenant_id}-south" not in visible


# -------------------------------------------------------------- 范围过滤


def test_all_scope_sees_everything():
    with SessionLocal() as db:
        tenant_id, east, _ = _fixture(db)
        rows = list_tenant_records(db, Incident, tenant_id, _ctx(east, "all"))

    assert _titles(rows) == {"east", "eastbuy", "south", "orphan"}


def test_dept_scope_includes_subdepartments_and_excludes_siblings():
    """核心断言：本部门及子部门可见，兄弟部门不可见。"""
    with SessionLocal() as db:
        tenant_id, east, _ = _fixture(db)
        rows = list_tenant_records(db, Incident, tenant_id, _ctx(east, "dept"))

    titles = _titles(rows)
    assert "east" in titles
    assert "eastbuy" in titles, "子部门记录必须可见"
    assert "south" not in titles, "兄弟部门记录必须不可见"


def test_own_scope_only_sees_owned_records():
    with SessionLocal() as db:
        tenant_id, east, _ = _fixture(db)
        rows = list_tenant_records(db, Incident, tenant_id, _ctx(east, "own"))

    titles = _titles(rows)
    assert "east" in titles
    assert "south" not in titles
    assert "eastbuy" not in titles, "同部门但非本人负责，own 范围下不可见"


def test_unassigned_records_stay_visible_to_everyone():
    """未归属记录（系统重算出的风险）不得因为没有负责人就对所有人消失。"""
    with SessionLocal() as db:
        tenant_id, east, south = _fixture(db)
        for scope in ("dept", "own", "custom"):
            for user in (east, south):
                titles = _titles(list_tenant_records(db, Incident, tenant_id, _ctx(user, scope)))
                assert "orphan" in titles, f"{scope} 范围下未归属记录消失了"


def test_custom_scope_uses_configured_department_list():
    with SessionLocal() as db:
        tenant_id, east, south = _fixture(db)
        activate_tenant_config(db, tenant_id, "data_scope", {
            "roles": {},
            # 给华南的人显式勾选华东采购部
            "customDepartments": {south.id: [f"{tenant_id}-east-buy"]},
        }, source="expert")
        db.flush()

        titles = _titles(list_tenant_records(db, Incident, tenant_id, _ctx(south, "custom")))

    assert "eastbuy" in titles, "被勾选的部门必须可见"
    assert "east" not in titles, "未勾选的部门不可见"
    assert "south" in titles, "本人负责的记录始终可见"


def test_custom_scope_without_configuration_falls_back_to_own():
    with SessionLocal() as db:
        tenant_id, east, south = _fixture(db)
        titles = _titles(list_tenant_records(db, Incident, tenant_id, _ctx(south, "custom")))

    assert titles == {"south", "orphan"}


# ---------------------------------------------------- 单条读取必须 404 而非 403


def test_out_of_scope_detail_read_raises_404_not_403():
    """越权读单条必须 404：403 等于确认"这条记录存在"，本身就是信息泄漏。"""
    with SessionLocal() as db:
        tenant_id, east, _ = _fixture(db)
        with pytest.raises(ApiError) as excinfo:
            get_tenant_record(db, Incident, f"inc-{tenant_id}-south", tenant_id, _ctx(east, "dept"))

    assert excinfo.value.status_code == 404
    assert excinfo.value.code == "CG-2001"


def test_in_scope_detail_read_succeeds():
    with SessionLocal() as db:
        tenant_id, east, _ = _fixture(db)
        item = get_tenant_record(db, Incident, f"inc-{tenant_id}-east", tenant_id, _ctx(east, "dept"))

    assert item.title == "east"


# ------------------------------------------------------------ 生效优先级


def test_role_default_applies_when_user_scope_absent():
    with SessionLocal() as db:
        tenant_id, east, _ = _fixture(db)
        activate_tenant_config(db, tenant_id, "data_scope", {"roles": {"scm_lead": "own"}}, source="expert")
        db.flush()
        ctx = AuthContext(east.id, tenant_id, east.name, east.role_code, ("*",), dept_id=east.dept_id, data_scope="")

        assert effective_scope(db, ctx) == "own"


def test_user_scope_overrides_role_default():
    with SessionLocal() as db:
        tenant_id, east, _ = _fixture(db)
        activate_tenant_config(db, tenant_id, "data_scope", {"roles": {"scm_lead": "own"}}, source="expert")
        db.flush()

        assert effective_scope(db, _ctx(east, "all")) == "all"


# -------------------------------------------------------- 端到端 HTTP 验证


def _headers(user_id: str) -> dict[str, str]:
    with SessionLocal() as db:
        return {"Authorization": f"Bearer {create_tokens(db.get(User, user_id))['token']}"}


def test_demo_tenant_incident_visible_under_dept_scope_for_owner():
    """演示租户：把供应链负责人调成 dept 范围后，他仍然看得到自己的事件。

    如果 seed 忘了写 owner_id/dept_id，这里会直接空掉——防止演示数据被行级隔离吃掉。
    """
    with SessionLocal() as db:
        user = db.get(User, "u-scm_lead")
        rows = list_tenant_records(db, Incident, "tenant-demo", _ctx(user, "dept"))

    assert any(row.id == "inc-supplier-shutdown" for row in rows)


def test_create_incident_rejects_out_of_scope_risks():
    """不能用看不见的风险去建事件——否则等于借建事件间接读取越权数据。"""
    original = None
    risk_id = f"risk-scope-{uuid.uuid4().hex[:8]}"
    try:
        with SessionLocal() as db:
            owner = db.get(User, "u-scm_lead")
            # 一条明确归属给 scm_lead 的风险
            db.add(Risk(id=risk_id, tenant_id="tenant-demo", code=risk_id, level="high", type="供应",
                        object_type="供应商", object_name="越权测试", score=90, rule="test",
                        found_at="2026-07-20 00:00", status="new", details={},
                        owner_id=owner.id, dept_id=owner.dept_id))
            buyer = db.get(User, "u-buyer")
            original = buyer.data_scope
            buyer.data_scope = "own"
            db.commit()

        response = client.post(
            "/api/v1/incidents",
            headers=_headers("u-buyer"),
            json={"riskIds": [risk_id], "title": "越权建事件", "type": "manual", "loss": 0, "cost": 0},
        )
        assert response.status_code == 404, "越权风险必须按不存在处理"
        assert response.json()["code"] == "CG-2001"
    finally:
        with SessionLocal() as db:
            buyer = db.get(User, "u-buyer")
            buyer.data_scope = original or "custom"
            item = db.get(Risk, risk_id)
            if item is not None:
                db.delete(item)
            db.commit()


def test_created_incident_is_visible_to_its_creator_under_own_scope():
    """新建事件必须落 owner_id，否则创建者自己在 own 范围下都看不到它。"""
    original = None
    created_id = None
    try:
        with SessionLocal() as db:
            user = db.get(User, "u-scm_lead")
            original = user.data_scope
            user.data_scope = "own"
            db.commit()

        created = client.post(
            "/api/v1/incidents",
            headers=_headers("u-scm_lead"),
            json={"riskIds": [], "title": "自建事件可见性", "type": "manual", "loss": 0, "cost": 0},
        )
        assert created.status_code == 201
        created_id = created.json()["id"]

        listed = client.get("/api/v1/incidents", headers=_headers("u-scm_lead"))
        assert created_id in {row["id"] for row in listed.json()["data"]}
    finally:
        with SessionLocal() as db:
            user = db.get(User, "u-scm_lead")
            user.data_scope = original or "all"
            if created_id:
                item = db.get(Incident, created_id)
                if item is not None:
                    db.delete(item)
            db.commit()


def test_incidents_endpoint_respects_scope():
    """HTTP 层验证：改用户数据范围后，列表接口返回的行数真的会变。"""
    original = None
    try:
        with SessionLocal() as db:
            user = db.get(User, "u-buyer")
            original = user.data_scope
            user.data_scope = "own"  # buyer 不是演示事件的负责人
            db.commit()

        response = client.get("/api/v1/incidents", headers=_headers("u-buyer"))
        assert response.status_code == 200
        ids = {row["id"] for row in response.json()["data"]}
        assert "inc-supplier-shutdown" not in ids, "own 范围下不该看到别人负责的事件"

        detail = client.get("/api/v1/incidents/inc-supplier-shutdown", headers=_headers("u-buyer"))
        assert detail.status_code == 404, "越权单条读取必须 404"
    finally:
        with SessionLocal() as db:
            user = db.get(User, "u-buyer")
            user.data_scope = original or "custom"
            db.commit()
