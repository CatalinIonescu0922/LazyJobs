import json
import re
from datetime import timedelta

from sqlalchemy import delete, func, insert, or_, select, update
from sqlalchemy.orm import Session

from ..logging import logger
from ..models import AtsBoard, Company, utcnow
from ..textnorm import normalise
from .fetch import FetchError, SafeFetcher

HOST = "kalebconfer-sys.github.io"
URL = f"https://{HOST}/job-board-directory/job-board-directory.json"
REFRESH_AFTER = timedelta(days=30)
RETRY_AFTER = timedelta(hours=6)
# A real file has more than 12,000 boards; a much smaller one is a truncated or broken download.
MIN_ROWS = 1000
# The providers ats.py can read. A board on any other is stored and shown, but not probed.
READABLE = {"greenhouse", "workday"}

_SLUG = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
_WORKDAY = re.compile(r"wd\d+/[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*")
_retry_not_before = None


def import_directory(db: Session) -> int | None:
    """Download and store the directory when the stored copy is missing or old. Returns the row count, or None when skipped."""
    global _retry_not_before
    latest = db.scalar(select(func.max(AtsBoard.imported_at)))
    if (latest and utcnow() - latest < REFRESH_AFTER) or (_retry_not_before and utcnow() < _retry_not_before):
        return None
    try:
        # sitemap=True is the fetcher's bulk-document limit of 20 MB; the file is about 3.5 MB and growing.
        rows = _valid_rows(json.loads(SafeFetcher(HOST).get(URL, sitemap=True).content))
        if len(rows) < MIN_ROWS:
            raise ValueError(f"only {len(rows)} usable boards")
        db.execute(delete(AtsBoard))
        db.execute(insert(AtsBoard), rows)
        # A new directory can change every match, so every company that is not already a feed is matched again.
        db.execute(update(Company).where(Company.status != "feed").values(board_provider=None, board_token=None))
        db.commit()
    except (FetchError, ValueError) as exc:
        db.rollback()
        _retry_not_before = utcnow() + RETRY_AFTER
        logger.warning("Directory import failed, keeping the stored copy: %s", exc)
        return None
    logger.info("Directory imported: boards=%s", len(rows))
    return len(rows)


def match_companies(db: Session, user_id: int) -> int:
    """Link each company that has not been matched yet to the best board of that name. Returns how many got a board."""
    if not db.scalar(select(AtsBoard.id).limit(1)):
        return 0
    pending = db.scalars(select(Company).where(Company.user_id == user_id, Company.board_provider.is_(None))).all()
    matched = 0
    for company in pending:
        keys = name_keys(company.name)
        boards = db.scalars(select(AtsBoard).where(or_(AtsBoard.key.in_(keys), AtsBoard.token_key.in_(keys)))).all() if keys else []
        # A board we can read beats one we cannot, and the one with the most open roles beats the rest.
        best = min(boards, key=lambda board: (board.provider not in READABLE, -board.open_roles, board.token), default=None)
        company.board_provider, company.board_token = (best.provider, best.token) if best else ("", "")
        matched += best is not None
    db.commit()
    return matched


def name_keys(name: str) -> list[str]:
    # Only a whole name counts. A first word alone would match "ROBERT BOSCH SRL" to a board called "robert".
    words = [word for word in normalise(name).split() if word not in {"romania", "romanian"}] or normalise(name).split()
    keys = ["".join(words)] + (["".join(words[:2])] if len(words) > 2 else [])
    return [key for key in dict.fromkeys(keys) if len(key) >= 3]


def _valid_rows(data) -> list[dict]:
    if not isinstance(data, list):
        raise ValueError("the directory is not a list")
    rows: dict[tuple[str, str], dict] = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        provider, token = str(item.get("platform", "")).lower(), str(item.get("token", ""))
        if not provider or len(provider) > 32 or len(token) > 255 or not (_WORKDAY if provider == "workday" else _SLUG).fullmatch(token):
            continue
        company = str(item.get("company") or "")[:255]
        opened = item.get("open_roles")
        tenant = token.split("/")[1] if provider == "workday" else token
        rows[(provider, token)] = {
            "provider": provider,
            "token": token,
            "company": company,
            "key": re.sub(r"[^a-z0-9]", "", normalise(company)),
            "token_key": re.sub(r"[^a-z0-9]", "", normalise(tenant)),
            "open_roles": opened if isinstance(opened, int) and opened >= 0 else 0,
            "imported_at": utcnow(),
        }
    return list(rows.values())
