from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    secret_key: str = "dev-secret"
    debug: bool = False
    # TODO: add redis_url field (type: str, default: "redis://redis:6379")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
