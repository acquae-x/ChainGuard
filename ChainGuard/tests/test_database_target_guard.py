from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.webapi.database import validate_database_target


def test_missing_explicit_database_url_fails_closed() -> None:
    with pytest.raises(RuntimeError, match="DATABASE_URL must be explicit"):
        validate_database_target("sqlite:///./chainguard.db", {})


def test_repository_default_database_requires_explicit_acknowledgement() -> None:
    default = (Path(__file__).resolve().parents[1] / "chainguard.db").resolve()
    url = f"sqlite:///{default.as_posix()}"
    with pytest.raises(RuntimeError, match="refusing repository default database"):
        validate_database_target(url, {"DATABASE_URL": url})
    assert validate_database_target(
        url,
        {"DATABASE_URL": url, "CHAINGUARD_ALLOW_DEFAULT_DB": "1"},
    ) == default


def test_acceptance_database_requires_absolute_guid_path() -> None:
    relative_url = "sqlite:///test_tmp/acceptance.db"
    with pytest.raises(RuntimeError, match="absolute path"):
        validate_database_target(
            relative_url,
            {"DATABASE_URL": relative_url, "CHAINGUARD_REQUIRE_GUID_DB": "1"},
        )

    absolute_without_guid = (Path(__file__).resolve().parents[1] / "test_tmp" / "acceptance.db").resolve()
    without_guid_url = f"sqlite:///{absolute_without_guid.as_posix()}"
    with pytest.raises(RuntimeError, match="must contain a GUID"):
        validate_database_target(
            without_guid_url,
            {"DATABASE_URL": without_guid_url, "CHAINGUARD_REQUIRE_GUID_DB": "1"},
        )


def test_acceptance_database_accepts_absolute_guid_path() -> None:
    target = (Path(__file__).resolve().parents[1] / "test_tmp" / f"acceptance-{uuid4()}.db").resolve()
    url = f"sqlite:///{target.as_posix()}"
    assert validate_database_target(
        url,
        {"DATABASE_URL": url, "CHAINGUARD_REQUIRE_GUID_DB": "1"},
    ) == target


def test_disabled_scheduler_does_not_start_background_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    from src import api

    events: list[str] = []

    def fail_if_thread_created(*_args: object, **_kwargs: object) -> None:
        pytest.fail("disabled scheduler must not create a background thread")

    monkeypatch.setattr(api, "settings", SimpleNamespace(scheduler_disabled=True))
    monkeypatch.setattr(api.threading, "Thread", fail_if_thread_created)
    monkeypatch.setattr(api, "log_event", lambda event, **_fields: events.append(event))

    api.start_countersign_scheduler()

    assert events == ["countersign_scheduler_disabled"]
