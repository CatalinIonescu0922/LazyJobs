from datetime import datetime, timedelta

import jwt
from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import User

COOKIE_NAME = "session"
# Secure is off because local development is http://localhost. SameSite=Lax is
# enough for the session: it is never needed on a cross-site POST.
COOKIE_KW = {"httponly": True, "samesite": "lax", "secure": False, "path": "/"}


def create_session_token(user_id: int) -> str:
    now = datetime.utcnow()
    return jwt.encode(
        {
            "purpose": "session",
            "sub": str(user_id),
            "iat": now,
            "exp": now + timedelta(hours=settings.jwt_ttl_hours),
        },
        settings.jwt_secret,
        algorithm="HS256",
    )


def set_session_cookie(response: Response, user_id: int) -> None:
    response.set_cookie(
        COOKIE_NAME,
        create_session_token(user_id),
        max_age=int(timedelta(hours=settings.jwt_ttl_hours).total_seconds()),
        **COOKIE_KW,
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/", samesite="lax")


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    raw = request.cookies.get(COOKIE_NAME)
    if not raw:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(raw, settings.jwt_secret, algorithms=["HS256"])
        if payload.get("purpose") != "session":
            raise HTTPException(status_code=401, detail="Not authenticated")
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Not authenticated") from exc
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user
