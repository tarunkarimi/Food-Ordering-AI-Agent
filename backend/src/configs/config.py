from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parents[2]


class Config(BaseSettings):
    MENU_BACKEND_URL: str
    MENU_SERVICE_API_KEY: str = Field(min_length=32)
    PORT: int
    GOOGLE_API_KEY: str
    DATABASE_URL: str
    MIGRATION_DATABASE_URL: str = ""

    # Authentication.
    JWT_SECRET_KEY: str = Field(min_length=32)
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=30, gt=0)

    # AI reliability.
    AI_REQUEST_TIMEOUT_SECONDS: float = Field(default=30.0, gt=0)
    AI_MAX_CONCURRENT_REQUESTS: int = Field(default=8, gt=0)

    # Downstream HTTP reliability.
    DOWNSTREAM_REQUEST_TIMEOUT_SECONDS: float = Field(default=10.0, gt=0)
    DOWNSTREAM_READ_RETRIES: int = Field(default=1, ge=0)

    # Database resource limits.
    DB_POOL_SIZE: int = Field(default=5, gt=0)
    DB_MAX_OVERFLOW: int = Field(default=10, ge=0)
    DB_POOL_TIMEOUT_SECONDS: float = Field(default=30.0, gt=0)
    DB_POOL_RECYCLE_SECONDS: int = Field(default=1800, gt=0)

    # Comma-separated frontend origins.
    FRONTEND_ORIGINS: str = "http://localhost:5173"

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        case_sensitive=True,
    )


config = Config()
