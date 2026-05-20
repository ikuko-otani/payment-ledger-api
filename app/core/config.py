from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    secret_key: str  # no default — required from .env
    algorithm: str  # JSON Web Token signing algorithm ("HS256")
    access_token_expire_minutes: int
    debug: bool = False
    redis_url: str = "redis://redis:6379"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()  # type: ignore[call-arg]
