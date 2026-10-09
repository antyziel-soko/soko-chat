from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    app_secret: str
    database_url: str = "sqlite+aiosqlite:///./data/app.db"
    app_environment: str = "development"
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

# Hosting providers commonly expose PostgreSQL URLs without a SQLAlchemy
# driver. psycopg 3 supports SQLAlchemy's async engine and Neon SSL URLs.
if settings.database_url.startswith("postgres://"):
    settings.database_url = "postgresql://" + settings.database_url.removeprefix("postgres://")
if settings.database_url.startswith("postgresql://"):
    settings.database_url = make_url(settings.database_url).set(
        drivername="postgresql+psycopg"
    ).render_as_string(hide_password=False)
if settings.app_environment == "production" and not settings.database_url.startswith("postgresql+psycopg://"):
    raise RuntimeError("W środowisku produkcyjnym ustaw DATABASE_URL na PostgreSQL.")
