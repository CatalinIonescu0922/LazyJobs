from datetime import datetime

from app.models import Job
from app.routers.jobs import _without_duplicates


def job(source: str, title: str, company: str, location: str, seen: str = "2026-11-01", **extra) -> Job:
    return Job(source=source, external_id=f"{source}/{title}", url="", title=title, company=company, locations=[location], first_seen_at=datetime.fromisoformat(seen), **extra)


def test_the_same_job_on_two_boards_is_kept_once_even_when_locations_are_written_differently():
    ejobs = job("ejobs.ro", "DevOps Engineer", "Acme SRL", "București, Bucuresti, RO")
    hipo = job("hipo.ro", "DevOps Engineer (m/f)", "ACME", "BUCURESTI ,, RO")
    assert _without_duplicates([ejobs, hipo], set()) == [ejobs]


def test_the_earliest_seen_posting_is_the_original_when_no_employer_is_involved():
    later = job("hipo.ro", "DevOps Engineer", "Acme", "Timisoara", seen="2026-11-05")
    earlier = job("ejobs.ro", "DevOps Engineer", "Acme", "Timisoara", seen="2026-10-20")
    assert _without_duplicates([later, earlier], set()) == [earlier]


def test_the_employers_own_posting_wins_over_an_earlier_board_copy():
    board = job("ejobs.ro", "DevOps Engineer", "Acme", "Timisoara", seen="2026-10-01")
    own = job("acme.greenhouse.io", "DevOps Engineer", "Acme", "Timisoara", seen="2026-11-05")
    assert _without_duplicates([board, own], {"acme.greenhouse.io"}) == [own]


def test_the_same_title_in_another_city_is_a_different_job():
    cluj = job("ejobs.ro", "Support Engineer", "Acme", "Cluj-Napoca, Cluj, RO")
    timisoara = job("ejobs.ro", "Support Engineer", "Acme", "Timișoara, Timiș, RO")
    assert _without_duplicates([cluj, timisoara], set()) == [cluj, timisoara]


def test_the_same_title_at_another_company_is_a_different_job():
    acme = job("ejobs.ro", "Support Engineer", "Acme", "Timisoara")
    other = job("hipo.ro", "Support Engineer", "Other Ltd", "Timisoara")
    assert _without_duplicates([acme, other], set()) == [acme, other]


def test_jobs_with_no_company_are_never_merged():
    first = job("ejobs.ro", "Sales Manager", "", "Bucuresti")
    second = job("hipo.ro", "Sales Manager", "  ", "Bucuresti")
    assert _without_duplicates([first, second], set()) == [first, second]


def test_the_order_of_the_remaining_jobs_is_kept():
    a = job("ejobs.ro", "Role A", "Acme", "Arad")
    b = job("ejobs.ro", "Role B", "Acme", "Arad")
    a_again = job("hipo.ro", "Role A", "Acme", "Arad", seen="2026-11-07")
    c = job("hipo.ro", "Role C", "Acme", "Arad")
    assert _without_duplicates([a, b, a_again, c], set()) == [a, b, c]


def test_a_job_with_no_location_still_compares_by_company_and_title():
    first = job("ejobs.ro", "Remote Engineer", "Acme", "")
    second = Job(source="hipo.ro", external_id="x", url="", title="Remote Engineer", company="Acme", locations=[], first_seen_at=datetime(2026, 11, 2))
    assert _without_duplicates([first, second], set()) == [first]
