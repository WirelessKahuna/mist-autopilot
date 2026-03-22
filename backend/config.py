from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    mist_api_token: str
    mist_api_base_url: str = "https://api.mist.com"
    mist_org_id: str
    cache_ttl_seconds: int = 300
    log_level: str = "INFO"

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    return Settings()
