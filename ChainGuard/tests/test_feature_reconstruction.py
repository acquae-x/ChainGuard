"""事前特征还原的验收测试。

核心断言是"用的是事前量，不是事后量"——旧校准正是在这里出的错。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.feature_reconstruction import (
    FACTORS,
    InventoryReconstructor,
    reconstruct_cases,
)

CSV_DIR = Path(__file__).resolve().parents[1] / "demo_assets" / "enterprise" / "csv"


def _decision(**overrides):
    base = {
        "case_id": "CASE-1", "event_id": "EVT-1", "outcome_status": "failed",
        "created_at": "2026-03-01T00:00:00+08:00",
        # 事后字段：还原逻辑绝不能碰这些
        "actual_delay_hours": 999, "covered_demand_rate": 0.01,
        "lost_orders": 99, "production_downtime_hours": 500,
    }
    base.update(overrides)
    return base


def _event(**overrides):
    base = {
        "event_id": "EVT-1", "affected_material_id": "MAT-1", "risk_score": "60",
        "estimated_delay_hours": "36", "started_at": "2026-03-01T00:00:00+08:00",
    }
    base.update(overrides)
    return base


def _material(**overrides):
    base = {"material_id": "MAT-1", "daily_consumption": "240"}
    base.update(overrides)
    return base


def _snapshot(**overrides):
    base = {
        "material_id": "MAT-1", "snapshot_date": "2026-03-01",
        "available_qty": "2400", "safety_stock_qty": "1000", "allocated_qty": "3000",
    }
    base.update(overrides)
    return base


# ------------------------------------------------------------ 只用事前量


def test_uses_estimated_delay_not_actual_delay():
    """transit_delay 必须来自事件的**预计**延误，与事后实际延误无关。"""
    shared = ([_event(estimated_delay_hours="36")], [_snapshot()], [_material()], [])

    high_actual = reconstruct_cases([_decision(actual_delay_hours=999)], *shared)
    low_actual = reconstruct_cases([_decision(actual_delay_hours=0)], *shared)

    assert high_actual.sample_size == 1 and low_actual.sample_size == 1
    assert high_actual.cases[0].features["transit_delay"] == low_actual.cases[0].features["transit_delay"], \
        "事后实际延误变化不应影响事前特征"


def test_transit_delay_tracks_the_forecast():
    snapshots, materials = [_snapshot()], [_material()]
    slow = reconstruct_cases([_decision()], [_event(estimated_delay_hours="72")], snapshots, materials, [])
    fast = reconstruct_cases([_decision()], [_event(estimated_delay_hours="6")], snapshots, materials, [])

    assert slow.cases[0].features["transit_delay"] > fast.cases[0].features["transit_delay"]


def test_outcome_fields_do_not_leak_into_features():
    """把全部事后字段改成极端值，事前特征必须一模一样。"""
    shared = ([_event()], [_snapshot()], [_material()], [])
    clean = reconstruct_cases([_decision(covered_demand_rate=0.99, lost_orders=0, production_downtime_hours=0)], *shared)
    dirty = reconstruct_cases([_decision(covered_demand_rate=0.01, lost_orders=99, production_downtime_hours=500)], *shared)

    assert clean.cases[0].features == dirty.cases[0].features


def test_label_comes_from_outcome_status():
    shared = ([_event()], [_snapshot()], [_material()], [])
    failed = reconstruct_cases([_decision(outcome_status="failed")], *shared)
    partial = reconstruct_cases([_decision(outcome_status="partial_success")], *shared)
    success = reconstruct_cases([_decision(outcome_status="success")], *shared)

    assert failed.cases[0].is_failure == 1
    assert partial.cases[0].is_failure == 1, "部分成功计入未达预期"
    assert success.cases[0].is_failure == 0


# ------------------------------------------------------ 缺数据必须剔除


@pytest.mark.parametrize("missing,reason_fragment", [
    ("event", "扰动事件"),
    ("material", "物料主数据"),
    ("snapshot", "库存快照"),
])
def test_missing_inputs_are_excluded_not_defaulted(missing, reason_fragment):
    events = [] if missing == "event" else [_event()]
    materials = [] if missing == "material" else [_material()]
    snapshots = [] if missing == "snapshot" else [_snapshot()]

    result = reconstruct_cases([_decision()], events, snapshots, materials, [])

    assert result.sample_size == 0, "缺输入时不得用默认值凑出样本"
    assert any(reason_fragment in reason for reason in result.excluded), result.excluded


def test_unknown_outcome_status_excluded():
    result = reconstruct_cases([_decision(outcome_status="")], [_event()], [_snapshot()], [_material()], [])
    assert result.sample_size == 0
    assert "结果状态未知" in result.excluded


# -------------------------------------------------- 库存按流水回滚还原


def test_inventory_rolls_back_through_movements():
    """快照在后、事件在前时，要能沿流水反向还原到事件时点。"""
    snapshots = [_snapshot(snapshot_date="2026-03-10", available_qty="1000")]
    movements = [
        {"material_id": "MAT-1", "movement_at": "2026-03-05T00:00:00", "quantity": "-400"},  # 出库
        {"material_id": "MAT-1", "movement_at": "2026-03-08T00:00:00", "quantity": "300"},   # 入库
    ]
    reconstructor = InventoryReconstructor(snapshots, movements)

    from datetime import datetime
    before = reconstructor.at("MAT-1", datetime(2026, 3, 1))

    # stock(3/1) = stock(3/10) − Σ(3/1, 3/10] = 1000 − (−400 + 300) = 1100
    assert before is not None
    assert before["available"] == pytest.approx(1100.0)


def test_inventory_never_goes_negative():
    snapshots = [_snapshot(snapshot_date="2026-03-10", available_qty="100")]
    movements = [{"material_id": "MAT-1", "movement_at": "2026-03-05T00:00:00", "quantity": "5000"}]
    reconstructor = InventoryReconstructor(snapshots, movements)

    from datetime import datetime
    assert reconstructor.at("MAT-1", datetime(2026, 3, 1))["available"] >= 0.0


# --------------------------------------------------------- 真实数据包


@pytest.mark.skipif(not (CSV_DIR / "historical_decisions.csv").exists(), reason="缺少企业演示数据包")
def test_full_demo_pack_reconstructs_without_exclusions():
    import csv
    import io

    def load(name):
        with io.open(CSV_DIR / name, encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))

    result = reconstruct_cases(
        load("historical_decisions.csv"), load("disruption_events.csv"),
        load("inventory_snapshots.csv"), load("materials.csv"), load("inventory_movements.csv"),
    )

    assert result.sample_size == 600
    assert result.excluded == {}, f"演示数据包不应有剔除：{result.excluded}"
    assert 0 < result.failure_count < result.sample_size, "标签必须两类都有"
    for case in result.cases[:20]:
        assert set(case.features) == set(FACTORS)
        for value in case.features.values():
            assert 0.0 <= value <= 100.0, "分量分数应在 0–100"
