from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parents[2]


class Config(BaseSettings):
    MENU_BACKEND_URL: str
    PORT: int
    GOOGLE_API_KEY: str
    DATABASE_URL: str

    # Authentication.
    JWT_SECRET_KEY: str
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # Comma-separated frontend origins.
    # Example:
    # http://localhost:5173,https://your-production-domain.com
    FRONTEND_ORIGINS: str = "http://localhost:5173"

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        case_sensitive=True,
    )


config = Config()