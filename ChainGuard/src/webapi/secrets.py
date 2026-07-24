"""Small seam for retrieving deployment secrets.

The application currently resolves secrets during startup from the environment.
Keeping that lookup behind this protocol lets a future deployment wire a KMS or
Vault provider without changing JWT callers or the settings schema.
"""

from __future__ import annotations

import os
from typing import Protocol


class SecretProvider(Protocol):
    """Returns one named deployment secret, or an empty string when absent."""

    def get(self, name: str) -> str: ...


class EnvSecretProvider:
    """Default provider: read secrets from the process environment."""

    def get(self, name: str) -> str:
        return os.getenv(name, "")
