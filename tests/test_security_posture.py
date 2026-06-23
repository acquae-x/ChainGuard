import warnings
from dataclasses import fields

from src.data_source import demo_source, enterprise_source
from src.security.encryption import encryption_status
from src.security.posture import (
    masking_preview,
    sample_sensitive_record,
    security_posture,
)


def test_encryption_status_keys():
    status = encryption_status()

    assert set(status) == {
        "library_available",
        "key_configured",
        "active",
        "algorithm",
        "note",
    }
    assert isinstance(status["active"], bool)


def test_encryption_status_no_warning():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", RuntimeWarning)
        encryption_status()

    assert [w for w in caught if issubclass(w.category, RuntimeWarning)] == []


def test_posture_required_fields():
    posture = security_posture("operator")
    field_names = {field.name for field in fields(posture)}

    assert {
        "role",
        "permissions",
        "masking_rules",
        "encryption_active",
        "encryption_note",
        "tenant_id",
        "tenant_isolated",
        "scenario_db_path",
    } <= field_names
    assert posture.role == "operator"
    assert isinstance(posture.permissions, list)
    assert isinstance(posture.masking_rules, dict)
    assert isinstance(posture.encryption_active, bool)
    assert posture.tenant_id


def test_admin_permissions_and_no_masking():
    posture = security_posture("admin")
    sample = sample_sensitive_record()
    preview = masking_preview(sample, "admin")

    assert "admin" in posture.permissions
    assert posture.masking_rules == {}
    assert preview["after"] == preview["before"]


def test_operator_masks_sensitive():
    preview = masking_preview(sample_sensitive_record(), "operator")

    assert preview["after"]["supplier_name"] == "***"


def test_role_changes_output():
    sample = sample_sensitive_record()

    admin_after = masking_preview(sample, "admin")["after"]
    viewer_after = masking_preview(sample, "viewer")["after"]

    assert admin_after != viewer_after


def test_enterprise_source_isolated():
    enterprise = enterprise_source("tenant_i47", require_exists=False)

    assert security_posture("operator", enterprise).tenant_isolated is True
    assert security_posture("operator", demo_source()).tenant_isolated is False


def test_unknown_role_empty_permissions():
    assert security_posture("guest").permissions == []
