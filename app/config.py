from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "제휴식당 어디지?"
    database_url: str = "sqlite:///./app.db"
    secret_key: str = "dev-only-change-me"
    admin_password_hash: str = ""
    admin_session_days: int = 7
    supabase_url: str = ""
    supabase_anon_key: str = ""
    place_search_provider: str = "kakao"
    google_places_api_key: str = ""
    kakao_rest_api_key: str = ""
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash"
    seed_on_startup: bool = True
    campus_lat: float = 37.6194
    campus_lng: float = 127.0598
    campus_name: str = "광운대학교"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
