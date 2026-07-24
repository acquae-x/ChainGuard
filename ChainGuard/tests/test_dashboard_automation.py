from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.webapi.auth import AuthContext, require_permission
from src.webapi.database import Base
from src.webapi.errors import ApiError
from src.webapi.models import DecisionAudit, Tenant
from src.webapi.routers.business import build_dashboard_automation


@contextmanager
def _sqlite_session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db
    engine.dispose()


def _ctx(tenant_id: str, permissions: tuple[str, ...] = ("dashboard:view",)) -> AuthContext:
    return AuthContext("user-a", tenant_id, "Dashboard user", "scm_lead", permissions)


def _audit(audit_id: str, tenant_id: str, human_approval_required: bool, **entry: object) -> DecisionAudit:
    return DecisionAudit(
        id=audit_id,
        tenant_id=tenant_id,
        incident_id=f"incident-{audit_id}",
        decision_id=f"decision-{audit_id}",
        entry={"human_approval_required": human_approval_required, **entry},
    )


def test_dashboard_automation_derives_rate_from_known_decision_outcomes_and_isolates_tenants():
    """Two automatic releases out of three eligible decisions is 2 / 3, not a fixture guess."""
    with _sqlite_session() as db:
        db.add_all([
            Tenant(id="tenant-a", name="A"),
            Tenant(id="tenant-b", name="B"),
            _audit("a-auto-1", "tenant-a", False),
            _audit("a-auto-2", "tenant-a", False),
            _audit("a-escalated", "tenant-a", True, inventory_risk_index=81),
            _audit("b-auto", "tenant-b", False),
        ])
        db.flush()

        payload = build_dashboard_automation(db, _ctx("tenant-a"))

    assert payload["totalDecisions"] == 3
    assert payload["autoApproved"] == 2
    assert payload["escalated"] == 1
    assert payload["automationRate"] == 0.6667
    assert payload["escalationRate"] == 0.3333
    assert {rule["code"] for rule in payload["escalationRules"]} == {
        "inventory_risk_threshold",
        "debate_not_converged",
        "no_feasible_solution",
    }


def test_dashboard_automation_requires_dashboard_view_permission():
    gate = require_permission("dashboard:view")

    assert gate(_ctx("tenant-a")) == _ctx("tenant-a")
    try:
        gate(_ctx("tenant-a", ("audit:view",)))
    except ApiError as error:
        assert error.status_code == 403
    else:
        raise AssertionError("audit:view must not grant access to the dashboard automation card")
