from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    database_url: str = "sqlite:///./cv_applier.db"
    jwt_secret: str = "dev-secret-change-me"
    jwt_ttl_hours: int = 24 * 14
    frontend_origin: str = "http://localhost:5173"

    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/api/auth/google/callback"

    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"

    user_agent: str = "cv-applier/0.1 (+personal job search assistant)"
    source_request_delay: float = 1.0


settings = Settings()
