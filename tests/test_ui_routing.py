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
