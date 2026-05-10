from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    secret_key: str = "dev-secret"
    debug: bool = False
    redis_url: str = "redis://redis:6379"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
