from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="WOHNWERK_",
        extra="ignore",
    )

    env: str = "development"
    host: str = "0.0.0.0"
    port: int = 8000
    database_url: str = "postgresql+psycopg://wohnwerk:wohnwerk@localhost:5432/wohnwerk"

    country_code: str = "AT"

    ai_enabled: bool = False
    ai_base_url: str = "http://ai-vm:8001"
    ai_timeout_seconds: int = 120

    routing_enabled: bool = False
    routing_base_url: str = "http://127.0.0.1:5000"
    routing_timeout_seconds: float = 3.0
    routing_max_table_coordinates: int = 100
    routing_prefilter_properties_per_job: int = 75

    # The write-capable admin surface stays fail-closed until a password is configured.
    admin_username: str = "admin"
    admin_password: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
