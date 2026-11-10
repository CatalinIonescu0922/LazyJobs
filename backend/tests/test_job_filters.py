from datetime import timedelta

from app.models import Job, utcnow
from app.routers.jobs import _filter_jobs


def job(title: str, expires_in_days: float | None) -> Job:
    expires = utcnow() + timedelta(days=expires_in_days) if expires_in_days is not None else None
    return Job(
        id=1, source="x.ro", external_id=title, url="https://x.ro/1", title=title, company="Acme", locations=["Timisoara"],
        work_mode="onsite", eligible_countries=[], description="", expires_at=expires,
        apply_url="", employment_type="", salary_currency="",
    )


def search(jobs: list[Job]):
    return _filter_jobs(jobs, [], "", "RO", "all", None)


def test_expired_postings_are_hidden_and_counted():
    shown, rejected = search([job("Open", 5), job("Closed", -1), job("No end date", None)])
    assert [item.title for item in shown] == ["Open", "No end date"]
    assert rejected["expired"] == 1
