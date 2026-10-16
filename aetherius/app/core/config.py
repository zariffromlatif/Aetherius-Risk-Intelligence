from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Aetherius"
    env: str = "dev"
    api_prefix: str = "/api/v1"
    database_url: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/aetherius"
    redis_url: str = "redis://localhost:6379/0"
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from: str = "noreply@aetherius.local"
    smtp_use_tls: bool = False
    sec_user_agent: str = "Aetherius Research zarif@aetheriusresearch.tech"
    auth_token: str = "change-me"
    jwt_secret: str = "change-me-jwt"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 120

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
