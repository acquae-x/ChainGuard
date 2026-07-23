from __future__ import annotations

import os
from dataclasses import dataclass

from .env_file import load_env_file

# 必须在 Settings 定义之前执行：下面的字段默认值是在类定义时求值的，
# 那时 os.getenv 就已经被调用，晚一步加载 .env 就不生效了。
# 已存在的环境变量优先，因此测试/CI/start-demo 显式设的值不会被覆盖。
load_env_file()


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
    # 账号维度防爆破。IP 限流（login_ip_rate_limit）与账号锁定是两条独立防线，互不替代：
    # 前者挡单机高频，后者挡分布式撞库。验收时可放宽 IP 预算以单独观测账号锁定，默认值不变。
    login_ip_rate_limit: str = os.getenv("LOGIN_IP_RATE_LIMIT", "5/minute")
    account_lock_threshold: int = int(os.getenv("ACCOUNT_LOCK_THRESHOLD", "5"))
    account_lock_minutes: int = int(os.getenv("ACCOUNT_LOCK_MINUTES", "15"))
    # 找回密码投递通道；未配置（none）时只走"管理员兜底重置"，绝不谎称已发送邮件。
    password_reset_channel: str = os.getenv("PASSWORD_RESET_CHANNEL", "none").strip().lower()
    password_reset_token_minutes: int = int(os.getenv("PASSWORD_RESET_TOKEN_MINUTES", "30"))
    smtp_host: str = os.getenv("SMTP_HOST", "")
    smtp_port: int = int(os.getenv("SMTP_PORT", "587"))
    smtp_username: str = os.getenv("SMTP_USERNAME", "")
    smtp_password: str = os.getenv("SMTP_PASSWORD", "")
    smtp_sender: str = os.getenv("SMTP_SENDER", "")
    smtp_starttls: bool = os.getenv("SMTP_STARTTLS", "true").lower() in {"1", "true", "yes"}
    password_reset_link_base: str = os.getenv("PASSWORD_RESET_LINK_BASE", "http://localhost:8000/user/reset")
    sso_state_minutes: int = int(os.getenv("SSO_STATE_MINUTES", "10"))
    sso_http_timeout: float = float(os.getenv("SSO_HTTP_TIMEOUT", "10"))
    countersign_timeout_hours: float = float(os.getenv("COUNTERSIGN_TIMEOUT_HOURS", "4"))
    scheduler_disabled: bool = os.getenv("CHAINGUARD_DISABLE_SCHEDULER", "false").lower() in {"1", "true", "yes", "on"}
    cors_origins: tuple[str, ...] = tuple(
        value.strip() for value in os.getenv(
            "CORS_ORIGINS", "http://localhost:8000,http://localhost:8080"
        ).split(",") if value.strip()
    )


settings = Settings()
# phase2-sync-probe
