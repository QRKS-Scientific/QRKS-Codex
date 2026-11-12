"""Settings come from environment variables (prefix QRKS_) or a .env file. Secrets never live in the repository."""
from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="QRKS_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./data/qrksdock.db"
    jwt_secret: str = Field(min_length=32)                   # required: the server refuses to start without a strong secret
    pepper: str = ""                                          # optional extra secret mixed into password hashing
    issuer: str = "qrksdock-server"
    audience: str = "qrksdock-app"

    access_minutes: int = 15
    refresh_idle_days: int = 14
    refresh_absolute_days: int = 30
    refresh_reuse_grace_seconds: int = 10                     # tolerates a lost response; older reuse revokes the session
    temp_password_days: int = 7
    max_devices: int = 3

    lock_free_attempts: int = 5
    lock_base_seconds: int = 30
    lock_max_seconds: int = 900
    login_rate_per_minute: int = 10                           # per IP
    api_rate_per_minute: int = 240                            # per IP

    min_app_version: str = "0.5.0"
    timezone: str = "Asia/Manila"                             # the date inside QDOCK-YYMMDD-NNN
    trust_proxy_headers: bool = False                         # true only behind our own reverse proxy

    argon2_time_cost: int = 3
    argon2_memory_kib: int = 32768                            # 32 MiB: safe on a 1 GB free VM
    argon2_parallelism: int = 1
    debug: bool = False                                       # enables /docs
