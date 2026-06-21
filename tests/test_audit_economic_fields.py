def test_build_audit_entry_includes_economic_fields():
    from src.audit import build_audit_entry

    context = {
        "events": [{"event_id": "EV-X", "event_type": "typhoon", "title": "台风"}],
        "orders": [
            {
                "order_id": "A1",
                "priority": "A",
                "demand_qty": 5000,
                "penalty_cost": 180000,
                "gross_profit": 420000,
                "due_hours": 48,
            },
        ],
        "inventory": {"current_stock": 3600},
        "suppliers": [
            {
                "supplier_id": "S1",
                "available_qty": 5000,
                "lead_time_hours": 36,
                "delay_hours": 0,
                "reliability_score": 85,
            },
        ],
    }
    entry = build_audit_entry({"context": context})
    d = entry.to_dict()
    assert d["event_key"] == "EV-X"
    assert d["net_benefit"] == 600000
    assert d["penalty_savings"] == 180000
    assert d["profit_protected"] == 420000


def test_old_audit_record_still_loads_without_new_fields():
    """向后兼容：缺新字段的旧 JSON 行仍能构造 AuditEntry（默认值）。"""
    from src.audit import AuditEntry

    old = {
        "decision_id": "x",
        "timestamp": "2026-01-01T00:00:00",
        "event_type": "typhoon",
        "event_severity": "high",
        "inventory_risk_index": 50.0,
        "constraint_feasible_count": 3,
        "debate_converged": True,
        "human_approval_required": False,
        "decision_status": "ok",
        "error_message": "",
    }
    entry = AuditEntry(**old)
    assert entry.net_benefit == 0.0
    assert entry.event_key == ""


def test_build_audit_entry_economic_exception_falls_back_to_zero(monkeypatch):
    import src.economic_impact as economic_impact
    from src.audit import build_audit_entry

    def raise_error(context):
        raise RuntimeError("boom")

    monkeypatch.setattr(economic_impact, "calculate_economic_impact", raise_error)
    entry = build_audit_entry(
        {
            "context": {
                "events": [
                    {"event_type": "typhoon", "title": "台风"},
                ],
            }
        }
    )

    assert entry.event_key == "typhoon:台风"
    assert entry.net_benefit == 0.0
    assert entry.penalty_savings == 0.0
    assert entry.profit_protected == 0.0
