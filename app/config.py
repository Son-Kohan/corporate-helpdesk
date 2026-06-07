from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Corporate Help Desk"
    app_version: str = "1.0.0"
    database_url: str = Field(
        default="sqlite+aiosqlite:///./helpdesk.db",
        alias="HELPDESK_DATABASE_URL",
    )
    secret_key: str = Field(default="change-me-in-production", alias="HELPDESK_SECRET_KEY")
    algorithm: str = "HS256"
    access_token_expire_minutes: int = Field(default=480, alias="HELPDESK_TOKEN_MINUTES")
    default_admin_username: str = Field(default="admin", alias="HELPDESK_ADMIN_USERNAME")
    default_admin_password: str = Field(default="admin123", alias="HELPDESK_ADMIN_PASSWORD")
    default_admin_email: str = Field(default="admin@helpdesk.local", alias="HELPDESK_ADMIN_EMAIL")
    upload_dir: str = Field(default="uploads", alias="HELPDESK_UPLOAD_DIR")
    max_attachment_bytes: int = Field(default=10 * 1024 * 1024, alias="HELPDESK_MAX_ATTACHMENT_BYTES")
    notification_log: str = Field(default="logs/notifications.log", alias="HELPDESK_NOTIFICATION_LOG")
    smtp_host: str | None = Field(default=None, alias="HELPDESK_SMTP_HOST")
    smtp_port: int = Field(default=25, alias="HELPDESK_SMTP_PORT")
    smtp_user: str | None = Field(default=None, alias="HELPDESK_SMTP_USER")
    smtp_password: str | None = Field(default=None, alias="HELPDESK_SMTP_PASSWORD")
    notification_from: str = Field(default="helpdesk@localhost", alias="HELPDESK_NOTIFICATION_FROM")
    login_attempt_limit: int = Field(default=8, alias="HELPDESK_LOGIN_ATTEMPT_LIMIT")
    login_lock_seconds: int = Field(default=300, alias="HELPDESK_LOGIN_LOCK_SECONDS")
    cors_origins: str = Field(default="http://127.0.0.1:8000,http://localhost:8000", alias="HELPDESK_CORS_ORIGINS")

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
