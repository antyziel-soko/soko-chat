from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_secret: str
    database_url: str = "sqlite+aiosqlite:///./data/app.db"
    session_ttl_hours: int = 720
    login_max_attempts: int = 8
    login_window_seconds: int = 300
    message_max_length: int = 4000
    message_rate_count: int = 8
    message_rate_window_seconds: int = 10

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
if len(settings.app_secret) < 32 or settings.app_secret.startswith("replace-"):
    raise RuntimeError("Ustaw APP_SECRET jako losowy sekret o długości co najmniej 32 znaków.")
