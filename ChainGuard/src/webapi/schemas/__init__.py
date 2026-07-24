from __future__ import annotations

from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, field_validator
from pydantic.alias_generators import to_camel


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class LoginRequest(ApiModel):
    account: str
    password: str


class RegisterRequest(ApiModel):
    phone: str
    password: str
    company_name: str
    industry: str
    scale: str
    owner_role: str
    plan: str = "trial"
    timezone: str = "UTC"

    @field_validator("timezone")
    @classmethod
    def timezone_must_be_an_iana_name(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as error:
            raise ValueError("timezone must be a valid IANA timezone") from error
        return value


class TenantSettingsUpdate(ApiModel):
    """Administrator-managed tenant fields; omitted values remain unchanged."""

    name: str | None = None
    industry: str | None = None
    scale: str | None = None
    timezone: str | None = None

    @field_validator("timezone")
    @classmethod
    def timezone_must_be_an_iana_name(cls, value: str | None) -> str | None:
        if value is None:
            return value
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as error:
            raise ValueError("timezone must be a valid IANA timezone") from error
        return value


class PasswordResetRequestBody(ApiModel):
    account: str


class PasswordResetConfirmRequest(ApiModel):
    token: str
    new_password: str


class InvitationRedeemRequest(ApiModel):
    code: str
    name: str
    password: str
    phone: str = ""
    email: str = ""


class SsoCallbackRequest(ApiModel):
    state: str
    code: str


class RefreshRequest(ApiModel):
    # 仅为兼容空请求体保留；刷新令牌只从 HttpOnly Cookie 读取。
    pass


class IncidentCreate(ApiModel):
    risk_ids: list[str]
    title: str | None = None
    type: str = "manual"
    loss: float = 0
    cost: float = 0


class PatchRequest(ApiModel):
    status: str | None = None
    reason: str | None = None
    note: str | None = None
    assignee: str | None = None
    overrides: dict[str, Any] = {}
    values: dict[str, Any] = {}
