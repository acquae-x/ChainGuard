from pathlib import Path
import shutil
from types import SimpleNamespace
from uuid import uuid4

from src.intake_review import review_batch, signature_of
from src.signature_history import (
    history_path_for,
    load_history,
    merge_counts,
    update_history,
)


def _source(tmp_path, tenant_id: str = "tenant_i53"):
    return SimpleNamespace(
        kind="enterprise",
        tenant_id=tenant_id,
        audit_log_path=str(tmp_path / f"audit_log.{tenant_id}.jsonl"),
    )


def _record(
    event_type: str = "port_shutdown",
    material: str = "MAT-001",
    supplier: str = "SUP-1",
) -> dict:
    return {
        "event_type": event_type,
        "affected_material_id": material,
        "affected_supplier_id": supplier,
    }


def _run_with_temp_dir(test_func):
    root = Path(__file__).parent / "_runtime_tmp" / "signature_history"
    path = root / uuid4().hex
    path.mkdir(parents=True, exist_ok=False)
    try:
        test_func(path)
    finally:
        shutil.rmtree(path, ignore_errors=True)


def test_merge_counts_pure():
    base = {"a": 2}

    merged = merge_counts(base, {"a": 3, "b": 1})

    assert merged == {"a": 5, "b": 1}
    assert base == {"a": 2}


def test_load_missing_returns_empty():
    def check(tmp_path):
        data_source = _source(tmp_path)

        assert load_history(data_source) == {}

    _run_with_temp_dir(check)


def test_update_accumulates_across_batches():
    def check(tmp_path):
        data_source = _source(tmp_path)
        record = _record()
        signature = signature_of(record)

        first_batch = update_history(data_source, [record, record])
        second_batch = update_history(data_source, [record, record, record])

        assert first_batch[signature] == 2
        assert second_batch[signature] == 5

    _run_with_temp_dir(check)


def test_update_persists():
    def check(tmp_path):
        data_source = _source(tmp_path)
        record = _record()

        updated = update_history(data_source, [record])
        loaded = load_history(_source(tmp_path))

        assert loaded == updated

    _run_with_temp_dir(check)


def test_history_path_isolation():
    def check(tmp_path):
        demo_source = SimpleNamespace(
            kind="demo",
            tenant_id="default",
            audit_log_path=str(tmp_path / "audit_log.jsonl"),
        )
        tenant_source = _source(tmp_path, "acme_i53")

        assert history_path_for(demo_source) == tmp_path / "signature_history.json"
        assert history_path_for(tenant_source) == tmp_path / "signature_history.acme_i53.json"
        assert history_path_for(demo_source) != history_path_for(tenant_source)

    _run_with_temp_dir(check)


def test_review_uses_accumulated_history():
    def check(tmp_path):
        data_source = _source(tmp_path)
        record = _record()
        update_history(data_source, [record, record, record])

        report = review_batch([record], load_history(data_source))

        assert report.assessments[0].familiarity == "routine"
        assert report.assessments[0].requires_confirmation is False

    _run_with_temp_dir(check)


def test_input_changes_output():
    def check(tmp_path):
        data_source = _source(tmp_path)
        record = _record()

        novel = review_batch([record], {})
        update_history(data_source, [record] * 5)
        routine = review_batch([record], load_history(data_source))

        assert novel.assessments[0].familiarity == "novel"
        assert novel.assessments[0].requires_confirmation is True
        assert routine.assessments[0].familiarity == "routine"
        assert routine.assessments[0].requires_confirmation is False

    _run_with_temp_dir(check)
