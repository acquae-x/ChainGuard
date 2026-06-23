import json
from pathlib import Path
from uuid import uuid4

from src.confirmation import (
    DEFAULT_ROLE,
    ConfirmationItem,
    assign_role,
    build_confirmation_items,
    evaluate_gate,
    record_confirmation,
)


def test_assign_role_procurement():
    assert assign_role("请确认备用供应商可供量") == "采购"


def test_assign_role_logistics():
    assert assign_role("请确认空运交期能覆盖关键订单") == "物流"


def test_assign_role_finance():
    assert assign_role("请确认成本与违约风险可接受") == "财务"


def test_assign_role_default():
    assert assign_role("请确认现场班次已准备") == DEFAULT_ROLE


def test_build_items_has_role_and_risk():
    items = build_confirmation_items(["请确认备用供应商可供量", "请确认交期"])

    assert len(items) == 2
    for item in items:
        assert item.role
        assert item.risk_if_skipped


def test_gate_all_confirmed():
    items = build_confirmation_items(["请确认备用供应商可供量", "请确认交期"])
    flags = {item.point: True for item in items}

    result = evaluate_gate(items, flags)

    assert result.can_execute is True
    assert result.blocked_points == []


def test_gate_blocked():
    items = build_confirmation_items(["请确认备用供应商可供量", "请确认交期"])
    flags = {items[0].point: True, items[1].point: False}

    result = evaluate_gate(items, flags)

    assert result.can_execute is False
    assert result.blocked_points


def test_gate_override_with_reason():
    items = build_confirmation_items(["请确认备用供应商可供量"])
    flags = {items[0].point: False}

    result = evaluate_gate(items, flags, override=True, override_reason="紧急")

    assert result.can_execute is True
    assert result.override is True


def test_gate_override_without_reason():
    items = build_confirmation_items(["请确认备用供应商可供量"])
    flags = {items[0].point: False}

    result = evaluate_gate(items, flags, override=True, override_reason="")

    assert result.can_execute is False


def test_gate_empty_items():
    result = evaluate_gate([], {})

    assert result.can_execute is True
    assert result.total == 0


def test_record_confirmation_roundtrip():
    path = Path("data") / f"confirmation_test_{uuid4().hex}.jsonl"
    items = build_confirmation_items(["请确认备用供应商可供量", "请确认交期"])
    flags = {items[0].point: True, items[1].point: False}

    try:
        record = record_confirmation(
            "decision-1",
            items,
            flags,
            confirmed_by="供应链经理",
            override=True,
            override_reason="紧急",
            path=path,
        )
        saved = json.loads(path.read_text(encoding="utf-8").strip())
    finally:
        path.unlink(missing_ok=True)

    assert saved == record
    assert saved["decision_id"] == "decision-1"
    assert saved["confirmed_by"] == "供应链经理"
    assert len(saved["items"]) == 2
    assert saved["can_execute"] is True


def test_input_changes_output():
    items = [
        ConfirmationItem("请确认备用供应商可供量", "采购", "risk"),
        ConfirmationItem("请确认交期", "物流", "risk"),
    ]
    all_false = {item.point: False for item in items}
    all_true = {item.point: True for item in items}

    blocked = evaluate_gate(items, all_false)
    released = evaluate_gate(items, all_true)

    assert blocked.can_execute is False
    assert released.can_execute is True
