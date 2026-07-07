from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = "postgresql://opcg:opcg@postgres:5432/opcg"
    REDIS_URL: str = "redis://redis:6379/0"


settings = Settings()
