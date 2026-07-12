from src.security.view_roles import (
    DEFAULT_VIEW,
    VIEW_ROLE,
    mask_for_view,
    mask_rows_for_view,
    role_for_view,
)


def test_role_for_view_known():
    assert role_for_view("管理者") == "admin"
    assert role_for_view("供应链经理") == "operator"
    assert role_for_view("一线从业者") == "viewer"


def test_role_for_view_unknown_is_lowest():
    assert role_for_view("陌生视角") == VIEW_ROLE[DEFAULT_VIEW]


def test_mask_for_view_frontline_masks():
    record = {
        "supplier_name": "宁波精密供应商",
        "unit_price": 128.5,
        "material_id": "MAT-001",
    }

    result = mask_for_view(record, "一线从业者")

    assert result["supplier_name"] == "***"
    assert result["unit_price"] == "***"
    assert result["material_id"] == "MAT-001"


def test_mask_for_view_manager_admin_plain():
    record = {
        "supplier_name": "宁波精密供应商",
        "unit_price": 128.5,
        "amount": 56000,
    }

    assert mask_for_view(record, "管理者") == record


def test_mask_rows_for_view():
    rows = [
        {"supplier_name": "供应商 A", "amount": 8000},
        {"customer_name": "客户 B", "unit_price": 12.5},
        {"vendor_name": "承运商 C", "cost": 125000},
    ]

    result = mask_rows_for_view(rows, "一线从业者")

    assert result[0]["supplier_name"] == "***"
    assert result[0]["amount"] == "<1万"
    assert result[1]["customer_name"] == "***"
    assert result[1]["unit_price"] == "***"
    assert result[2]["vendor_name"] == "***"
    assert result[2]["cost"] == ">10万"


def test_mask_rows_empty():
    assert mask_rows_for_view([], "一线从业者") == []
    assert mask_rows_for_view(None, "一线从业者") == []


def test_input_changes_output():
    record = {
        "supplier_name": "宁波精密供应商",
        "amount": 56000,
    }

    manager_result = mask_for_view(record, "管理者")
    frontline_result = mask_for_view(record, "一线从业者")

    assert manager_result != frontline_result
    assert manager_result["supplier_name"] == "宁波精密供应商"
    assert frontline_result["supplier_name"] == "***"


def test_role_for_view_emoji_label():
    assert role_for_view("🏢 管理者") == "admin"
    assert role_for_view("🛠 一线从业者") == "viewer"
