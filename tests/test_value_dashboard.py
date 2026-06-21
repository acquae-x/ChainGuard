def test_empty_returns_zero():
    from src.value_dashboard import aggregate_timeline_value

    r = aggregate_timeline_value([])
    assert r.cumulative_net_benefit == 0
    assert r.event_count == 0
    assert r.per_event_series == []


def test_dedup_same_event_counts_once_latest_wins():
    """同一 event_key 多条（模拟刷新），只计一次，取最新 timestamp。"""
    from src.value_dashboard import aggregate_timeline_value

    entries = [
        {"event_key": "EV1", "timestamp": "2026-06-21T01:00:00", "net_benefit": 100},
        {"event_key": "EV1", "timestamp": "2026-06-21T02:00:00", "net_benefit": 100},
        {"event_key": "EV1", "timestamp": "2026-06-21T03:00:00", "net_benefit": 100},
    ]
    r = aggregate_timeline_value(entries)
    assert r.event_count == 1
    assert r.cumulative_net_benefit == 100
    assert r.latest_event_timestamp == "2026-06-21T03:00:00"


def test_distinct_events_accumulate():
    from src.value_dashboard import aggregate_timeline_value

    entries = [
        {"event_key": "EV1", "timestamp": "2026-06-21T01:00:00", "net_benefit": 100},
        {"event_key": "EV2", "timestamp": "2026-06-21T02:00:00", "net_benefit": 250},
    ]
    r = aggregate_timeline_value(entries)
    assert r.event_count == 2
    assert r.cumulative_net_benefit == 350
    assert r.average_net_benefit == 175
    assert r.latest_event_key == "EV2"
    assert r.latest_event_net_benefit == 250


def test_old_records_without_net_benefit_skipped():
    """旧 audit 记录无 net_benefit 字段，视为未测量，不计入。"""
    from src.value_dashboard import aggregate_timeline_value

    entries = [
        {"decision_id": "old1", "timestamp": "2026-01-01T00:00:00"},
        {"event_key": "EV1", "timestamp": "2026-06-21T01:00:00", "net_benefit": 500},
    ]
    r = aggregate_timeline_value(entries)
    assert r.event_count == 1
    assert r.cumulative_net_benefit == 500


def test_series_sorted_by_timestamp_ascending():
    from src.value_dashboard import aggregate_timeline_value

    entries = [
        {"event_key": "EV2", "timestamp": "2026-06-21T05:00:00", "net_benefit": 20},
        {"event_key": "EV1", "timestamp": "2026-06-21T01:00:00", "net_benefit": 10},
    ]
    r = aggregate_timeline_value(entries)
    assert [e["event_key"] for e in r.per_event_series] == ["EV1", "EV2"]


def test_missing_event_key_skipped():
    from src.value_dashboard import aggregate_timeline_value

    entries = [
        {"timestamp": "2026-06-21T01:00:00", "net_benefit": 999},
        {"event_key": "EV1", "timestamp": "2026-06-21T02:00:00", "net_benefit": 1},
    ]
    r = aggregate_timeline_value(entries)
    assert r.event_count == 1
    assert r.cumulative_net_benefit == 1
