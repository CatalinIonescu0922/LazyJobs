import json
import re

from fastapi import HTTPException
from google import genai

from .config import settings
from .schemas import ExtractedProfile


PROFILE_SCHEMA = {
    "type": "object",
    "properties": {
        "full_name": {"type": "string"},
        "headline": {"type": "string"},
        "summary": {"type": "string"},
        "titles": {"type": "array", "items": {"type": "string"}},
        "skills": {"type": "array", "items": {"type": "string"}},
        "years_experience": {"type": "number"},
        "country": {"type": "string", "description": "ISO alpha-2 country code"},
        "city": {"type": "string"},
        "salary_currency": {"type": "string", "description": "ISO 4217 currency code"},
    },
    "required": [
        "full_name",
        "headline",
        "summary",
        "titles",
        "skills",
        "years_experience",
        "country",
        "city",
        "salary_currency",
    ],
}


def extract_profile(cv_text: str) -> ExtractedProfile:
    if not settings.google_cloud_project:
        raise HTTPException(status_code=503, detail="CV extraction is not configured")

    prompt = f"""Extract a candidate profile from the CV below.
Return only JSON matching the supplied schema. Do not invent details. Use empty strings,
empty arrays, or zero when the CV does not provide a value. Country must be an ISO
alpha-2 code, city must come from the address when present, and salary_currency must be
an ISO 4217 code only when clearly stated.

CV text:
{cv_text}"""
    try:
        client = genai.Client(
            vertexai=True,
            project=settings.google_cloud_project,
            location=settings.vertex_location,
        )
        response = client.models.generate_content(
            model=settings.vertex_model,
            contents=prompt,
            config={
                "response_mime_type": "application/json",
                "response_schema": PROFILE_SCHEMA,
            },
        )
        return ExtractedProfile.model_validate(json.loads(_response_text(response)))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail="CV profile extraction failed") from exc


def _response_text(response: object) -> str:
    text = getattr(response, "text", None)
    if not text:
        raise ValueError("The model returned an empty response")
    return re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())


def propose_job_boards(country: str) -> list[dict[str, str]]:
    if not settings.google_cloud_project:
        raise HTTPException(status_code=503, detail="Board discovery is not configured")
    prompt = f"""Return popular, publicly crawlable job-board websites for people in {country}.
Include local boards and remote boards open to residents. Return only a JSON array of
objects with domain and kind (local or remote), using domains only and no paths.
Do not return LinkedIn, Indeed, Glassdoor, Jooble, Facebook, or any social network,
general search engine, or site whose job search requires login or blocks ordinary crawlers."""
    return _json_call(prompt, {"type": "array", "items": {"type": "object", "properties": {"domain": {"type": "string"}, "kind": {"type": "string"}}, "required": ["domain", "kind"]}})


def pick_posting_sitemaps(samples: list[str]) -> dict[str, str]:
    if not settings.google_cloud_project:
        return {"prefix": ""}
    prompt = "Choose the URL path prefix containing individual job posting pages from these sitemap samples. Return only JSON with a prefix string. Samples:\n" + "\n".join(samples[:40])
    result = _json_call(prompt, {"type": "object", "properties": {"prefix": {"type": "string"}}, "required": ["prefix"]})
    return result


def _json_call(prompt: str, schema: dict) -> dict | list:
    try:
        client = genai.Client(vertexai=True, project=settings.google_cloud_project, location=settings.vertex_location)
        response = client.models.generate_content(
            model=settings.vertex_model,
            contents=prompt,
            config={"response_mime_type": "application/json", "response_schema": schema},
        )
        return json.loads(_response_text(response))
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Source discovery failed") from exc
