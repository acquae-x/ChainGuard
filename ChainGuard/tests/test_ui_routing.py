import csv

import app


def test_resolve_selected_event_prefers_session():
    assert (
        app._resolve_selected_event({"cg_selected_event_id": "EVT-9"}, "EVT-1")
        == "EVT-9"
    )


def test_resolve_selected_event_falls_back():
    assert app._resolve_selected_event({}, "EVT-1") == "EVT-1"


def test_resolve_selected_event_both_none():
    assert app._resolve_selected_event({}, None) is None


def test_app_module_imports():
    assert hasattr(app, "main")
    assert hasattr(app, "_resolve_selected_event")


def test_app_has_three_persona_helpers():
    assert hasattr(app, "render_node_detail")
    assert hasattr(app, "render_data_intake_placeholder")
    assert hasattr(app, "_resolve_selected_event")


def test_write_normalized_csv_writes_union_of_keys(tmp_path):
    """数据接入的上传分支会走这里；此前它引用了模块作用域没有的 `csv`，
    必然 NameError，而异常被 render_data_intake 的 except 吞成一行提示。
    表头取各行键的首次出现顺序，缺失键补空串——期望值按此推导，不看实现输出。"""
    target = tmp_path / "out.csv"

    app._write_normalized_csv(target, [{"b": 1, "a": 2}, {"a": 3, "c": 4}])

    with target.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0] == {"b": "1", "a": "2", "c": ""}
    assert rows[1] == {"b": "", "a": "3", "c": "4"}


def test_write_normalized_csv_handles_empty_rows(tmp_path):
    """空批次不该炸——ingest_files 对没抽出内容的表会给空列表。

    只断言「能写出、读回零条记录」：空表头下 writeheader() 会落一个空行，
    那是 csv 模块的实现细节，不是本函数的契约，不该被断言钉死。
    """
    target = tmp_path / "empty.csv"

    app._write_normalized_csv(target, [])

    with target.open(encoding="utf-8", newline="") as handle:
        assert list(csv.DictReader(handle)) == []
