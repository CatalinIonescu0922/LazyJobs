from google.cloud import storage
from google.auth.credentials import AnonymousCredentials

from .config import settings


_client: storage.Client | None = None


def _get_client() -> storage.Client:
    global _client
    if _client is None:
        kwargs = {}
        if settings.storage_emulator_host:
            kwargs["client_options"] = {"api_endpoint": settings.storage_emulator_host}
            kwargs["project"] = settings.google_cloud_project or "local-project"
            kwargs["credentials"] = AnonymousCredentials()
        _client = storage.Client(**kwargs)
    return _client


def store_cv(user_id: int, filename: str, content: bytes) -> None:
    bucket = _get_client().bucket(settings.gcs_bucket)
    if not bucket.exists():
        bucket.create(location="EU")
    blob = bucket.blob(f"cv/{user_id}/{filename}")
    blob.upload_from_string(content, content_type=_content_type(filename))


def _content_type(filename: str) -> str:
    return "application/pdf" if filename.lower().endswith(".pdf") else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
