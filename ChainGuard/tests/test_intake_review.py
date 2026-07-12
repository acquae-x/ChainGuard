from src.intake_review import (
    OCCASIONAL_THRESHOLD,
    ROUTINE_THRESHOLD,
    assess_intake,
    build_history_counts,
    calibrate_intake_thresholds,
    review_batch,
    signature_of,
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


def test_signature_normalized():
    record = {
        "event_type": " Port_Shutdown ",
        "affected_material_id": "MAT-001",
        "affected_supplier_id": "SUP-1",
    }

    assert signature_of(record) == "port_shutdown|mat-001|sup-1"


def test_signature_missing_fields_unknown():
    assert signature_of({}) == "unknown|unknown|unknown"


def test_build_history_counts():
    sig_a_record = _record()
    sig_b_record = _record(event_type="customs_delay")

    counts = build_history_counts([sig_a_record] * 4 + [sig_b_record])

    assert counts[signature_of(sig_a_record)] == 4
    assert counts[signature_of(sig_b_record)] == 1


def test_novel_requires_full_confirmation():
    assessment = assess_intake(_record(), {})

    assert assessment.familiarity == "novel"
    assert assessment.requires_confirmation is True
    assert len(assessment.confirmation_points) >= 3


def test_routine_auto_passes():
    record = _record()
    sig = signature_of(record)

    assessment = assess_intake(record, {sig: 5})

    assert assessment.familiarity == "routine"
    assert assessment.requires_confirmation is False
    assert assessment.confirmation_points == []


def test_occasional_light_confirmation():
    record = _record()
    sig = signature_of(record)

    assessment = assess_intake(record, {sig: 2})

    assert assessment.familiarity == "occasional"
    assert assessment.requires_confirmation is True
    assert len(assessment.confirmation_points) == 1


def test_review_batch_counts():
    routine_a = _record(event_type="typhoon", material="MAT-A", supplier="SUP-A")
    routine_b = _record(event_type="typhoon", material="MAT-B", supplier="SUP-B")
    novel_records = [
        _record(event_type="customs_delay", material="MAT-1", supplier="SUP-1"),
        _record(event_type="customs_delay", material="MAT-2", supplier="SUP-2"),
        _record(event_type="customs_delay", material="MAT-3", supplier="SUP-3"),
    ]
    history_counts = {
        signature_of(routine_a): 5,
        signature_of(routine_b): 5,
    }

    report = review_batch(novel_records + [routine_a, routine_b], history_counts)

    assert report.auto_passed == 2
    assert report.needs_confirmation == 3
    assert report.total == 5


def test_input_changes_output():
    record = _record()
    sig = signature_of(record)

    novel = assess_intake(record, {})
    routine = assess_intake(record, {sig: 5})

    assert novel.requires_confirmation is True
    assert routine.requires_confirmation is False


def test_empty_batch():
    report = review_batch([], {})

    assert report.total == 0
    assert report.auto_passed == 0
    assert report.needs_confirmation == 0
    assert report.novel_count == 0
    assert report.occasional_count == 0
    assert report.routine_count == 0


def test_calibrate_thresholds_from_distribution():
    counts = {f"sig-{index}": value for index, value in enumerate([1, 1, 2, 3, 3, 5, 5, 5, 8, 10])}

    routine_threshold, occasional_threshold = calibrate_intake_thresholds(counts)

    assert routine_threshold != ROUTINE_THRESHOLD
    assert occasional_threshold >= 1
    assert routine_threshold >= occasional_threshold + 1


def test_calibrate_fallback_sparse():
    counts = {"sig-a": 1, "sig-b": 2, "sig-c": 4, "sig-zero": 0}

    assert calibrate_intake_thresholds(counts) == (
        ROUTINE_THRESHOLD,
        OCCASIONAL_THRESHOLD,
    )


def test_calibrated_threshold_affects_assessment():
    record = _record()
    sig = signature_of(record)
    history_counts = {sig: 2}

    routine = assess_intake(
        record,
        history_counts,
        routine_threshold=2,
        occasional_threshold=1,
    )
    occasional = assess_intake(
        record,
        history_counts,
        routine_threshold=3,
        occasional_threshold=1,
    )

    assert routine.familiarity == "routine"
    assert occasional.familiarity == "occasional"
