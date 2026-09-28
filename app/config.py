from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./data/finance.db"
    admin_username: str = "admin"
    admin_password: str = ""
    cookie_secure: bool = False
    allow_registration: bool = False
    session_days: int = 14
    max_upload_mb: int = 10


@lru_cache
def get_settings() -> Settings:
    return Settings()
