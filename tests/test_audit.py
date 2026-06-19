import json
import uuid
from pathlib import Path

import pytest

import src.orchestrator as orchestrator_module
from src.audit import AuditEntry, AuditLog, approval_required, build_audit_entry
from src.orchestrator import DecisionOrchestrator


RUNTIME_TMP = Path(__file__).parent / "_runtime_tmp"


def _runtime_path(name: str) -> Path:
    RUNTIME_TMP.mkdir(parents=True, exist_ok=True)
    stem = Path(name).stem
    suffix = Path(name).suffix
    return RUNTIME_TMP / f"{stem}_{uuid.uuid4().hex}{suffix}"


def _audit_payload(
    *,
    risk_index: float = 70.0,
    converged: bool = True,
    feasible_count: int = 5,
) -> dict:
    return {
        "context": {
            "events": [
                {
                    "event_type": "typhoon_port_shutdown",
                    "severity": "high",
                }
            ]
        },
        "inventory_risk": {"inventory_risk_index": risk_index},
        "debate_result": {"converged": converged},
        "constraint_analysis": {"feasible_count": feasible_count},
    }


def test_approval_required_when_risk_index_above_80():
    assert approval_required(_audit_payload(risk_index=85.0)) is True


def test_approval_not_required_for_standard_risk():
    assert approval_required(_audit_payload(risk_index=70.0, converged=True, feasible_count=5)) is False


def test_approval_required_when_debate_not_converged():
    assert approval_required(_audit_payload(converged=False)) is True


def test_approval_required_when_no_feasible_combo():
    assert approval_required(_audit_payload(feasible_count=0)) is True


def test_audit_entry_is_json_serializable():
    entry = build_audit_entry({})

    assert json.dumps(entry.to_dict(), ensure_ascii=False)


def test_audit_log_appends_and_loads():
    path = _runtime_path("audit_log.jsonl")
    log = AuditLog(path)
    first = build_audit_entry(_audit_payload(risk_index=70.0))
    second = build_audit_entry(_audit_payload(risk_index=85.0))

    log.append(first)
    log.append(second)
    entries = log.load()

    assert len(entries) == 2
    assert all(isinstance(entry, AuditEntry) for entry in entries)
    assert entries[0].decision_id == first.decision_id
    assert entries[1].human_approval_required is True


def test_audit_log_missing_file_returns_empty():
    path = _runtime_path("missing_audit_log.jsonl")

    assert AuditLog(path).load() == []


def test_audit_log_skips_corrupted_json_lines():
    path = _runtime_path("corrupt_audit_log.jsonl")
    entry = build_audit_entry(_audit_payload())
    path.write_text(
        json.dumps(entry.to_dict(), ensure_ascii=False) + "\nnot-json\n",
        encoding="utf-8",
    )

    entries = AuditLog(path).load()

    assert len(entries) == 1
    assert entries[0].decision_id == entry.decision_id


def test_orchestrator_result_has_audit_entry_field():
    payload = DecisionOrchestrator().run_demo().to_dict()

    assert "audit_entry" in payload


def test_audit_entry_has_required_keys():
    audit_entry = DecisionOrchestrator().run_demo().to_dict()["audit_entry"]

    assert {
        "decision_id",
        "timestamp",
        "human_approval_required",
        "decision_status",
        "inventory_risk_index",
    } <= set(audit_entry)


def test_fixed_demo_approval_not_required():
    result = DecisionOrchestrator().run_demo()

    assert result.audit_entry["human_approval_required"] is False
    assert result.audit_entry["decision_status"] == "ok"


def test_error_audit_entry_records_status_and_message():
    entry = build_audit_entry({}, status="error", error_message="boom")

    assert entry.decision_status == "error"
    assert entry.error_message == "boom"


def test_orchestrator_logs_error_audit_entry(monkeypatch):
    path = _runtime_path("orchestrator_error_audit.jsonl")
    original_generate = orchestrator_module.generate_all_proposals

    def generate_without_logistics(context):
        return [
            proposal
            for proposal in original_generate(context)
            if "物流" not in proposal["agent_name"]
        ]

    monkeypatch.setattr(
        orchestrator_module,
        "generate_all_proposals",
        generate_without_logistics,
    )
    monkeypatch.setattr(
        orchestrator_module,
        "AuditLog",
        lambda: AuditLog(path),
    )

    with pytest.raises(ValueError):
        DecisionOrchestrator().run_demo()

    entries = AuditLog(path).load()

    assert len(entries) == 1
    assert entries[0].decision_status == "error"
    assert "ValueError" in entries[0].error_message
