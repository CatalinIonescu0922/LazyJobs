from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    database_url: str = "postgresql+psycopg://cv:cv@db:5432/cv_applier"
    jwt_secret: str = "dev-secret-change-me"
    jwt_ttl_hours: int = 24 * 14
    frontend_origin: str = "http://localhost:5173"

    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/api/auth/google/callback"

    google_cloud_project: str = ""
    vertex_location: str = "global"
    vertex_model: str = "gemini-3.1-flash-lite"
    gcs_bucket: str = "cv-applier-local"
    storage_emulator_host: str = ""
    max_cv_bytes: int = 5 * 1024 * 1024
    max_cv_text_chars: int = 100_000

    user_agent: str = "cv-applier/0.1 (+personal job search assistant)"
    source_request_delay: float = 1.0


settings = Settings()
