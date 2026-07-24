"""Tenant-local calendar boundaries while keeping persisted timestamps in UTC.

Business records remain UTC instants.  This module is the single place that
turns those instants into a tenant's natural day, ISO week, or calendar month.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

from .models import Tenant


DEFAULT_TENANT_TIMEZONE = "UTC"


def zoneinfo_for(name: str | None) -> ZoneInfo:
    """Return an IANA zone, falling back only for legacy/corrupt database data."""
    try:
        return ZoneInfo(name or DEFAULT_TENANT_TIMEZONE)
    except ZoneInfoNotFoundError:
        return ZoneInfo(DEFAULT_TENANT_TIMEZONE)


def tenant_zone(db: Session, tenant_id: str) -> ZoneInfo:
    tenant = db.get(Tenant, tenant_id)
    return zoneinfo_for(tenant.timezone if tenant is not None else None)


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def tenant_now(zone: ZoneInfo, now: datetime | None = None) -> datetime:
    instant = as_utc(now) if now is not None else datetime.now(timezone.utc)
    assert instant is not None
    return instant.astimezone(zone)


def start_of_day(zone: ZoneInfo, now: datetime | None = None) -> datetime:
    local = tenant_now(zone, now)
    return local.replace(hour=0, minute=0, second=0, microsecond=0)


def start_of_week(zone: ZoneInfo, now: datetime | None = None) -> datetime:
    local = start_of_day(zone, now)
    return local - timedelta(days=local.weekday())


def start_of_month(zone: ZoneInfo, now: datetime | None = None) -> datetime:
    local = tenant_now(zone, now)
    return local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def start_of_months_ago(zone: ZoneInfo, months: int, now: datetime | None = None) -> datetime:
    """Start of the inclusive N-calendar-month reporting window."""
    start = start_of_month(zone, now)
    for _ in range(max(1, months) - 1):
        start = (start - timedelta(days=1)).replace(day=1)
    return start


def local_month_key(value: datetime, zone: ZoneInfo) -> str:
    local = as_utc(value)
    assert local is not None
    local = local.astimezone(zone)
    return f"{local.year:04d}-{local.month:02d}"
