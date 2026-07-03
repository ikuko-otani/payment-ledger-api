from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    secret_key: str  # no default — required from .env
    algorithm: str  # JSON Web Token signing algorithm ("HS256")
    access_token_expire_minutes: int
    debug: bool = False
    redis_url: str = "redis://redis:6379"
    balance_cache_ttl_seconds: int = 60  # TTL for balance cache keys (seconds)
    balance_cache_ttl_historical_seconds: int = (
        86400  # TTL for closed-period (as_of < today) balance keys
    )
    db_pool_size: int = 5  # per-worker pool size
    db_max_overflow: int = 10  # per-worker overflow above pool_size
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()  # type: ignore[call-arg]
