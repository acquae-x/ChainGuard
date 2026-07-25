"""双轨阈值在租户 API 上的行为（node_health 端到端）。

纯函数层的安全属性在 tests/test_threshold_calibration.py 里证明；本文件证明
它们在真实数据路径上仍然成立——即相对轨确实接进了产品，且没有把低风险节点
误判成异常。

断言写成**不变量**而不是硬编码分数：库存风险指数由多因子加权得出，把某个具体
分值抄进断言会在权重配置调整后变成假失败。这里断言的是"低于地板的节点不得带
相对离群原因"这类恒成立的性质。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api import app
from src.threshold_calibration import (
    MIN_CALIBRATION_NODES,
    RELATIVE_ESCALATION_FLOOR,
)
from src.webapi.auth.security import create_tokens
from src.webapi.database import SessionLocal
from src.webapi.models import (
    InventoryEntity,
    Material,
    Role,
    Tenant,
    User,
)
from src.webapi.seed import seed

seed()
client = TestClient(app)

OVERVIEW = "/api/v1/dashboard/node-health"
TENANT = "tenant-dualtrack"
TINY_TENANT = "tenant-dualtrack-tiny"

# 10 个物料 > MIN_CALIBRATION_NODES(8)，保证相对轨真的被激活而不是回退专家常量。
HEALTHY_COUNT = 10


@pytest.fixture(scope="module")
def account() -> str:
    """一个全部物料都健康的租户：无缺口、无在途延误、无关键订单。

    库存量按公式反推，不是随手填的：日消耗 24 → 每小时 1，故支撑小时数 = 可用量。
    inventory_monitor 的 shortage_urgency_score = _linear_score(support, low=24, high=72)，
    支撑超过 72 小时即饱和为 0——若把库存堆到几千小时，10 个物料的风险指数会完全
    相同（σ=0），相对轨直接回退成专家常量，就测不到数据驱动那条路径了。

    因此取支撑 50~68 小时：
    - 全部高于黄线 48 → 绝对轨判定正常（这是"全线健康"场景）
    - 全部低于饱和点 72 → 风险指数有离散度，相对轨真的被激活
    """
    with SessionLocal() as db:
        db.merge(Tenant(id=TENANT, name=TENANT, industry="制造", scale="small",
                        status="active", plan="trial", trial_end_at="", demo_data_flag=False))
        db.flush()
        db.add(Role(id="role-dualtrack", tenant_id=TENANT, code="dualtrack",
                    name="双轨测试角色", builtin=False,
                    permissions=["dashboard:view", "data:manage"]))
        db.flush()
        db.add(User(id="user-dualtrack", tenant_id=TENANT, account="dualtrack@test",
                    password_hash="x", name="双轨测试用户", phone="", email="",
                    dept_id="dept-1", role_id="role-dualtrack", role_code="dualtrack",
                    status="active", data_scope="all", must_change_password=False))
        db.flush()

        for index in range(HEALTHY_COUNT):
            code = f"MAT-OK-{index:02d}"
            db.add(Material(
                id=f"m-dual-{index}", tenant_id=TENANT, material_id=code,
                material_name=f"充裕物料{index:02d}", category="通用", unit="个",
                daily_consumption=24, unit_cost=5, is_critical=False,
            ))
        db.flush()
        for index in range(HEALTHY_COUNT):
            code = f"MAT-OK-{index:02d}"
            stock = 50 + index * 2  # 支撑 50~68 小时：高于黄线 48，低于饱和点 72
            db.add(InventoryEntity(
                id=f"inv-dual-{index}", tenant_id=TENANT,
                inventory_id=f"INV-OK-{index:02d}", material_id=code,
                warehouse_id="WH-DUAL", warehouse_name="双轨测试仓",
                on_hand_qty=stock, available_qty=stock, safety_stock_qty=10,
                in_transit_qty=0,
            ))
        db.commit()
    return "user-dualtrack"


@pytest.fixture(scope="module")
def tiny() -> str:
    """物料数不足 8 的小租户，且含一个高风险物料。

    数值按引擎口径反推：日消耗 480 → 每小时 20，库存 300 → 支撑 15 小时 < 红线 24
    → 绝对轨判 critical，风险指数会高到越过专家常量 action 线 70。修复前，回退出来的
    专家常量会被当成"数据推导阈值"再判一次并输出 calibrated 原因——本夹具就是为了
    抓住那个情况。
    """
    with SessionLocal() as db:
        db.merge(Tenant(id=TINY_TENANT, name=TINY_TENANT, industry="制造", scale="small",
                        status="active", plan="trial", trial_end_at="", demo_data_flag=False))
        db.flush()
        db.add(Role(id="role-tiny", tenant_id=TINY_TENANT, code="tiny", name="小租户角色",
                    builtin=False, permissions=["dashboard:view", "data:manage"]))
        db.flush()
        db.add(User(id="user-tiny", tenant_id=TINY_TENANT, account="tiny@test",
                    password_hash="x", name="小租户用户", phone="", email="",
                    dept_id="dept-1", role_id="role-tiny", role_code="tiny",
                    status="active", data_scope="all", must_change_password=False))
        db.flush()
        db.add(Material(id="m-tiny", tenant_id=TINY_TENANT, material_id="MAT-TINY",
                        material_name="紧缺物料", category="电子", unit="片",
                        daily_consumption=480, unit_cost=45, is_critical=True))
        db.flush()
        db.add(InventoryEntity(id="inv-tiny", tenant_id=TINY_TENANT,
                               inventory_id="INV-TINY", material_id="MAT-TINY",
                               warehouse_id="WH-TINY", warehouse_name="小仓",
                               on_hand_qty=300, available_qty=300, safety_stock_qty=960,
                               in_transit_qty=0))
        db.commit()
    return "user-tiny"


def _overview(user_id: str) -> dict:
    with SessionLocal() as db:
        token = create_tokens(db.get(User, user_id))["token"]
    response = client.get(OVERVIEW, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200, response.text
    return response.json()


def _materials(payload: dict) -> list[dict]:
    return [node for node in payload["nodes"] if node["nodeType"] == "material"]


def test_threshold_calibration_is_reported(account: str):
    """响应必须带阈值来源元数据——UI 要据此区分专家阈值与数据推导阈值。"""
    payload = _overview(account)
    calibration = payload["thresholdCalibration"]

    assert calibration is not None
    assert calibration["sampleSize"] == HEALTHY_COUNT
    assert calibration["minSamples"] == MIN_CALIBRATION_NODES
    assert calibration["source"] in ("calibrated", "expert")
    assert calibration["escalationFloor"] == RELATIVE_ESCALATION_FLOOR


def test_relative_track_is_actually_active(account: str):
    """样本量够且分布有离散度 → 必须走数据推导，否则本文件其余断言测不到东西。"""
    calibration = _overview(account)["thresholdCalibration"]

    assert calibration["sampleSize"] >= MIN_CALIBRATION_NODES
    assert calibration["source"] == "calibrated"
    # 数据推导出的三档必须严格递增，否则分档失效。
    assert calibration["watch"] < calibration["warning"] < calibration["action"]


def test_no_node_below_floor_is_flagged_as_outlier(account: str):
    """全线健康不虚报：低于绝对地板的节点不得带相对离群原因。

    这是纯 z-score 最危险的失效模式——一批都安全时，批内最高的那个仍会被判成
    高危。地板必须把它挡住。
    """
    for node in _materials(_overview(account)):
        risk_index = node["metrics"].get("riskIndex")
        if risk_index is None:
            continue
        codes = {reason["code"] for reason in node["reasons"]}
        if float(risk_index) < RELATIVE_ESCALATION_FLOOR:
            assert "risk_index_relative_outlier" not in codes, (
                f"{node['id']} 风险 {risk_index} 低于地板 {RELATIVE_ESCALATION_FLOOR}，"
                "不应被相对轨升级"
            )


def test_healthy_batch_stays_healthy(account: str):
    """整批库存充裕 → 不应产生任何异常/预警节点。"""
    materials = _materials(_overview(account))

    assert len(materials) == HEALTHY_COUNT
    assert {node["health"] for node in materials} == {"healthy"}


def test_fallback_tenant_reports_no_calibrated_reason(account: str, tiny: str):
    """回退时相对轨必须完全停用——不得出现"本批数据推导"的原因。

    真机验收发现的缺陷：样本不足时 calibrate 回退成专家常量 (35/55/70)，而相对轨
    仍在用这组常量判定并输出一条 source=calibrated、文案称"本批数据推导的离群线"的
    原因。于是界面同屏出现"已回退为专家阈值"与"本批数据推导"两句自相矛盾的话。
    """
    payload = _overview(tiny)
    calibration = payload["thresholdCalibration"]

    assert calibration["source"] == "expert", "本夹具物料数不足，应当回退"
    for node in _materials(payload):
        codes = {reason["code"] for reason in node["reasons"]}
        assert "risk_index_relative_outlier" not in codes, (
            "回退时不得输出相对离群原因——它会谎称阈值来自数据推导"
        )
        assert node["metrics"]["relativeHealth"] == "healthy", (
            "回退时相对轨不参与升级，否则界面文案'等价于仅绝对红线生效'即为假"
        )


def test_dual_track_records_both_verdicts(account: str):
    """每个物料都要能看到两轨各自的结论，判定过程可追溯而不是一个黑盒结果。"""
    for node in _materials(_overview(account)):
        metrics = node["metrics"]
        assert metrics["expertHealth"] == "healthy"
        assert metrics["relativeHealth"] in ("healthy", "warning", "critical")
        # 最终健康度不得低于（宽松于）任何一轨——取较严者。
        assert node["health"] == "healthy"
