from functools import lru_cache
from typing import List
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    app_name: str = "GastoZap"
    debug: bool = False
    api_secret_key: str = "change-me"
    cors_origins: str = "http://localhost:3000"
    port: int = Field(default=8000, validation_alias=AliasChoices("PORT"))

    # Database — aceita postgres:// do Easypanel e converte para asyncpg
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/gastozap"

    # Evolution API
    evolution_api_url: str = "http://localhost:8080"
    evolution_api_key: str = ""
    evolution_instance: str = "gastozap"
    webhook_secret: str = Field(
        default="",
        validation_alias=AliasChoices("WEBHOOK_SECRET", "EVOLUTION_API_TOKEN"),
    )

    # OpenAI
    openai_api_key: str = ""
    openai_model: str = Field(
        default="gpt-4o",
        validation_alias=AliasChoices("OPENAI_MODEL", "OPENAI_VISION_MODEL"),
    )
    whisper_model: str = Field(
        default="whisper-1",
        validation_alias=AliasChoices("WHISPER_MODEL", "WHISPER_API_MODEL"),
    )

    # Security — aceita WHITELIST_NUMBERS (Setup_Ambiente.md) ou ALLOWED_PHONE_NUMBERS
    allowed_phone_numbers: str = Field(
        default="",
        validation_alias=AliasChoices("ALLOWED_PHONE_NUMBERS", "WHITELIST_NUMBERS"),
    )
    dashboard_username: str = "admin"
    dashboard_password: str = "change-me"

    # Business rules
    always_confirm_mode: bool = True
    high_value_threshold: float = 500.0
    daily_alert_hour: int = 20
    daily_alert_minute: int = 0
    alert_time: str = Field(default="", validation_alias=AliasChoices("ALERT_TIME"))
    retry_limit: int = Field(default=3, validation_alias=AliasChoices("RETRY_LIMIT"))
    card_expiry_alert_months: int = 3

    # Redis (optional queue)
    redis_url: str = "redis://localhost:6379/0"
    use_redis_queue: bool = False

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_database_url(cls, value: str) -> str:
        if not isinstance(value, str):
            return value
        if value.startswith("postgres://"):
            value = value.replace("postgres://", "postgresql+asyncpg://", 1)
        elif value.startswith("postgresql://") and "+asyncpg" not in value:
            value = value.replace("postgresql://", "postgresql+asyncpg://", 1)

        # Easypanel adds ?sslmode=disable — libpq-only; asyncpg rejects it as kwarg
        parsed = urlparse(value)
        if parsed.query:
            params = parse_qs(parsed.query, keep_blank_values=True)
            for key in ("sslmode", "sslrootcert", "sslcert", "sslkey"):
                params.pop(key, None)
            query = urlencode(params, doseq=True)
            value = urlunparse(parsed._replace(query=query))

        return value

    @model_validator(mode="after")
    def parse_alert_time(self) -> "Settings":
        if self.alert_time:
            parts = self.alert_time.strip().split(":")
            if parts and parts[0].isdigit():
                self.daily_alert_hour = int(parts[0])
                self.daily_alert_minute = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
        return self

    @property
    def cors_origins_list(self) -> List[str]:
        origins = []
        for origin in self.cors_origins.split(","):
            origin = origin.strip().rstrip("/")
            if origin:
                origins.append(origin)
        return origins

    @property
    def whitelist_phones(self) -> List[str]:
        return [p.strip() for p in self.allowed_phone_numbers.split(",") if p.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
