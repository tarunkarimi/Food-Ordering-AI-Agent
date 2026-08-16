from pydantic_settings import SettingsConfigDict, BaseSettings


class Config(BaseSettings):
    MENU_BACKEND_URL: str
    PORT: int
    GOOGLE_API_KEY: str
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True)


config = Config()
