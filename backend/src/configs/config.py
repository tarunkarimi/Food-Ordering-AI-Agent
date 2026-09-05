from pydantic_settings import SettingsConfigDict, BaseSettings


class Config(BaseSettings):
    MENU_BACKEND_URL: str
    PORT: int
    GOOGLE_API_KEY: str

    # Comma-separated frontend origins.
    # Example:
    # http://localhost:5173,https://your-production-domain.com
    FRONTEND_ORIGINS: str = "http://localhost:5173"

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
    )


config = Config()