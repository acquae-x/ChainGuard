from __future__ import annotations

import dataclasses as _dataclasses
import os

from fastapi import Depends, FastAPI, HTTPException, Security
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader

from src.notifier import MockNotifier, NotificationPayload, Notifier
from src.orchestrator import DecisionOrchestrator
from src.scenario_loader import ScenarioLoader


app = FastAPI(
    title="ChainGuard Decision API",
    version="1.0.0",
    description="Supply chain disruption decision engine REST interface.",
)

_API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


def _load_api_keys() -> dict[str, str]:
    """
    Parse CHAINGUARD_API_KEYS env var into a key-to-role mapping.

    Format: "key1:role1,key2:role2". Empty or absent env var enables open mode.
    """
    raw = os.environ.get("CHAINGUARD_API_KEYS", "").strip()
    if not raw:
        return {}
    result: dict[str, str] = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if ":" in entry:
            key, role = entry.split(":", 1)
            result[key.strip()] = role.strip()
    return result


_API_KEYS: dict[str, str] = _load_api_keys()
_notifier: Notifier = MockNotifier()


async def check_api_key(api_key: str | None = Security(_API_KEY_HEADER)) -> str:
    """
    Validate request API key and return caller role.

    Open mode returns "admin" for any request. Key mode requires a valid
    X-API-Key header and maps it to its configured role.
    """
    if not _API_KEYS:
        return "admin"
    if not api_key or api_key not in _API_KEYS:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return _API_KEYS[api_key]


@app.get("/health")
def health(role: str = Depends(check_api_key)) -> dict[str, str]:
    return {"status": "ok", "version": "1.0.0"}


@app.get("/scenarios")
def list_scenarios(
    limit: int = 50,
    role: str = Depends(check_api_key),
) -> dict[str, object]:
    """List available enterprise disruption scenarios."""
    try:
        scenarios = ScenarioLoader().list_scenarios(limit=limit)
        return {"scenarios": scenarios, "count": len(scenarios)}
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"{type(error).__name__}: {error}",
        ) from error


@app.post("/decisions/demo")
def run_demo_decision(role: str = Depends(check_api_key)) -> JSONResponse:
    """Run the built-in typhoon demo decision workflow."""
    try:
        result = DecisionOrchestrator().run_demo()
        if result.audit_entry.get("human_approval_required"):
            _notifier.send(NotificationPayload.from_audit_entry(result.audit_entry))
        return JSONResponse(content=result.to_dict())
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"{type(error).__name__}: {error}",
        ) from error


@app.post("/decisions/scenario/{event_id}")
def run_scenario_decision(
    event_id: str,
    role: str = Depends(check_api_key),
) -> JSONResponse:
    """Run decision workflow for an enterprise scenario event."""
    try:
        loader = ScenarioLoader()
        result = DecisionOrchestrator().run_scenario(event_id, loader)
        if result.audit_entry.get("human_approval_required"):
            _notifier.send(NotificationPayload.from_audit_entry(result.audit_entry))
        return JSONResponse(content=result.to_dict())
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"{type(error).__name__}: {error}",
        ) from error


@app.get("/notifications/pending")
def list_pending_notifications(
    role: str = Depends(check_api_key),
) -> dict[str, object]:
    """Return notifications accumulated by MockNotifier (demo only)."""
    if isinstance(_notifier, MockNotifier):
        return {
            "notifications": [_dataclasses.asdict(payload) for payload in _notifier.sent],
            "count": len(_notifier.sent),
        }
    return {
        "notifications": [],
        "count": 0,
        "note": "only available with MockNotifier",
    }


@app.get("/auth/status")
def auth_status(role: str = Depends(check_api_key)) -> dict[str, str]:
    """Return current auth mode and caller's role."""
    mode = "open" if not _API_KEYS else "key-required"
    return {"mode": mode, "role": role}
