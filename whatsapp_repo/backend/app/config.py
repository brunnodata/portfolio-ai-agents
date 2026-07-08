from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    app_name: str = "GastoZap"
    debug: bool = False
    api_secret_key: str = "change-me"
    cors_origins: str = "http://localhost:3000"

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/gastozap"

    # Evolution API
    evolution_api_url: str = "http://localhost:8080"
    evolution_api_key: str = ""
    evolution_instance: str = "gastozap"
    webhook_secret: str = ""

    # OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    whisper_model: str = "whisper-1"

    # Security
    allowed_phone_numbers: str = ""
    dashboard_username: str = "admin"
    dashboard_password: str = "change-me"

    # Business rules
    always_confirm_mode: bool = True
    high_value_threshold: float = 500.0
    daily_alert_hour: int = 20
    daily_alert_minute: int = 0
    card_expiry_alert_months: int = 3

    # Redis (optional queue)
    redis_url: str = "redis://localhost:6379/0"
    use_redis_queue: bool = False

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def whitelist_phones(self) -> List[str]:
        return [p.strip() for p in self.allowed_phone_numbers.split(",") if p.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
