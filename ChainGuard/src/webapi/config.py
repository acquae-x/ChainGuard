from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./chainguard.db")
    # 部署环境必须通过 .env 注入签名密钥，避免镜像或源码携带可预测密钥。
    jwt_secret: str = os.getenv("JWT_SECRET", "")
    jwt_algorithm: str = os.getenv("JWT_ALGORITHM", "HS256")
    jwt_rs256_public_key: str = os.getenv("JWT_RS256_PUBLIC_KEY", "")
    jwt_rs256_private_key: str = os.getenv("JWT_RS256_PRIVATE_KEY", "")
    access_token_minutes: int = int(os.getenv("ACCESS_TOKEN_MINUTES", "30"))
    refresh_token_days: int = int(os.getenv("REFRESH_TOKEN_DAYS", "7"))
    refresh_cookie_secure: bool = os.getenv("REFRESH_COOKIE_SECURE", "false").lower() in {"1", "true", "yes"}
    max_import_bytes: int = int(os.getenv("MAX_IMPORT_BYTES", str(20 * 1024 * 1024)))
    countersign_timeout_hours: float = float(os.getenv("COUNTERSIGN_TIMEOUT_HOURS", "4"))
    cors_origins: tuple[str, ...] = tuple(
        value.strip() for value in os.getenv(
            "CORS_ORIGINS", "http://localhost:8000,http://localhost:8080"
        ).split(",") if value.strip()
    )


settings = Settings()
# phase2-sync-probe
