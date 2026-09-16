import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import Identity, Profile, User, utcnow
from ..oauth import (
    ExternalIdentity,
    authorization_url,
    clear_flow_cookie,
    fetch_identity,
    get_provider,
    pkce_pair,
    read_flow_cookie,
    set_flow_cookie,
    sign_flow,
)
from ..session import clear_session_cookie, current_user, set_session_cookie

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/me")
def me(user: User = Depends(current_user)) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "avatar_url": user.avatar_url,
    }


@router.post("/logout")
def logout() -> Response:
    response = Response(status_code=204)
    clear_session_cookie(response)
    return response


@router.get("/{provider}/login")
def login(provider: str) -> RedirectResponse:
    chosen = get_provider(provider)
    state = secrets.token_urlsafe(32)
    verifier, challenge = pkce_pair()
    response = RedirectResponse(
        authorization_url(chosen, state, challenge),
        status_code=302,
    )
    set_flow_cookie(response, sign_flow(chosen.name, state, verifier))
    return response


@router.get("/{provider}/callback")
def callback(
    provider: str,
    request: Request,
    db: Session = Depends(get_db),
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    flow = read_flow_cookie(request)
    if (
        flow is None
        or not state
        or flow.get("state") != state
        or flow.get("provider") != provider
    ):
        raise HTTPException(status_code=400, detail="Invalid or expired sign-in state")
    if error or not code:
        raise HTTPException(status_code=400, detail="Sign-in was cancelled or incomplete")

    chosen = get_provider(provider)
    identity = fetch_identity(chosen, code, flow["verifier"])
    user = find_or_create_user(db, identity)
    db.commit()

    response = RedirectResponse(url=settings.frontend_origin, status_code=302)
    clear_flow_cookie(response)
    set_session_cookie(response, user.id)
    return response


def find_or_create_user(db: Session, ext: ExternalIdentity) -> User:
    existing_identity = db.scalars(
        select(Identity).where(
            Identity.provider == ext.provider,
            Identity.subject == ext.subject,
        )
    ).first()
    now = utcnow()
    if existing_identity is not None:
        user = existing_identity.user
        user.name = ext.name or user.name
        user.avatar_url = ext.avatar_url or user.avatar_url
        user.last_login_at = now
        return user

    email = ext.email.strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="Provider did not return an email")

    user = db.scalars(select(User).where(User.email == email)).first()
    if user is None:
        user = User(
            email=email,
            name=ext.name,
            avatar_url=ext.avatar_url,
            last_login_at=now,
        )
        db.add(user)
        db.flush()
        db.add(Profile(user_id=user.id))
    elif not ext.email_verified:
        # Linking on an unverified email is an account-takeover path.
        raise HTTPException(
            status_code=400,
            detail="Cannot link this login to an existing account because the email is not verified",
        )
    else:
        user.name = ext.name or user.name
        user.avatar_url = ext.avatar_url or user.avatar_url
        user.last_login_at = now

    db.add(
        Identity(
            user_id=user.id,
            provider=ext.provider,
            subject=ext.subject,
        )
    )
    return user
