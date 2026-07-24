from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import format_datetime
from typing import Any

from starlette.datastructures import MutableHeaders


@dataclass(frozen=True)
class EndpointDeprecation:
    """One announced endpoint retirement and its replacement."""

    method: str
    path: str
    deprecated_at: datetime
    sunset_at: datetime
    successor: str

    def __post_init__(self) -> None:
        if self.deprecated_at.tzinfo is None or self.sunset_at.tzinfo is None:
            raise ValueError("deprecation timestamps must include a timezone")
        if self.sunset_at < self.deprecated_at:
            raise ValueError("sunset must not precede deprecation")

    @property
    def key(self) -> tuple[str, str]:
        return self.method.upper(), self.path

    @property
    def deprecation_header(self) -> str:
        """RFC 9745 uses an RFC 9651 structured-field date."""
        return f"@{int(self.deprecated_at.timestamp())}"

    @property
    def sunset_header(self) -> str:
        return format_datetime(self.sunset_at.astimezone(timezone.utc), usegmt=True)

    def openapi_kwargs(self) -> dict[str, Any]:
        """FastAPI decorator arguments documenting the runtime warning."""
        return {
            "deprecated": True,
            "responses": {
                200: {
                    "description": "Deprecated endpoint; migrate to the documented v2 successor.",
                    "headers": {
                        "Deprecation": {
                            "description": "RFC 9745 deprecation date.",
                            "schema": {"type": "string", "example": self.deprecation_header},
                        },
                        "Sunset": {
                            "description": "HTTP-date after which this endpoint may be removed.",
                            "schema": {"type": "string", "example": self.sunset_header},
                        },
                    },
                }
            },
            "openapi_extra": {
                "x-chainguard-deprecation": {
                    "deprecatedAt": self.deprecated_at.isoformat(),
                    "sunsetAt": self.sunset_at.isoformat(),
                    "successor": self.successor,
                }
            },
        }


V1_TOP_RISKS_DEPRECATION = EndpointDeprecation(
    method="GET",
    path="/api/v1/dashboard/top-risks",
    deprecated_at=datetime(2026, 7, 24, tzinfo=timezone.utc),
    sunset_at=datetime(2027, 1, 20, tzinfo=timezone.utc),
    successor="/api/v2/dashboard/top-risks",
)

DEPRECATED_ENDPOINTS = {V1_TOP_RISKS_DEPRECATION.key: V1_TOP_RISKS_DEPRECATION}


class DeprecationHeadersMiddleware:
    """Attach lifecycle headers without changing deprecated endpoint behavior."""

    def __init__(self, app: Any, policies: dict[tuple[str, str], EndpointDeprecation]) -> None:
        self.app = app
        self.policies = policies

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        policy = self.policies.get((scope.get("method", "").upper(), scope.get("path", "")))
        if scope["type"] != "http" or policy is None:
            await self.app(scope, receive, send)
            return

        async def send_with_deprecation_headers(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["Deprecation"] = policy.deprecation_header
                headers["Sunset"] = policy.sunset_header
                successor_link = f'<{policy.successor}>; rel="successor-version"'
                existing_link = headers.get("Link")
                headers["Link"] = (
                    f"{existing_link}, {successor_link}"
                    if existing_link
                    else successor_link
                )
            await send(message)

        await self.app(scope, receive, send_with_deprecation_headers)
