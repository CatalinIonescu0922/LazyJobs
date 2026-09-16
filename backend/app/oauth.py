import base64
import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import HTTPException, Request, Response

from .config import settings

OAUTH_COOKIE = "oauth_flow"
OAUTH_TTL = timedelta(minutes=5)
# SameSite=Lax so the cookie is sent on Google's top-level GET back to /callback.
# Secure is off because local development is http://localhost.
OAUTH_COOKIE_KW = {"httponly": True, "samesite": "lax", "secure": False, "path": "/"}


@dataclass(frozen=True)
class ExternalIdentity:
    provider: str
    subject: str
    email: str
    email_verified: bool
    name: str
    avatar_url: str


@dataclass(frozen=True)
class Provider:
    name: str
    auth_url: str
    token_url: str
    userinfo_url: str
    scopes: str
    client_id: str
    client_secret: str
    redirect_uri: str

    def identity_from(self, claims: dict) -> ExternalIdentity:
        subject = claims.get("sub")
        if not subject:
            raise HTTPException(status_code=400, detail="Provider did not return a stable user id")
        return ExternalIdentity(
            provider=self.name,
            subject=str(subject),
            email=str(claims.get("email") or ""),
            email_verified=bool(claims.get("email_verified")),
            name=str(claims.get("name") or ""),
            avatar_url=str(claims.get("picture") or ""),
        )


PROVIDERS = {
    "google": Provider(
        name="google",
        auth_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        userinfo_url="https://openidconnect.googleapis.com/v1/userinfo",
        scopes="openid email profile",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        redirect_uri=settings.google_redirect_uri,
    )
}


def get_provider(name: str) -> Provider:
    provider = PROVIDERS.get(name)
    if provider is None:
        raise HTTPException(status_code=404, detail="Unknown auth provider")
    if not provider.client_id or not provider.client_secret:
        raise HTTPException(status_code=503, detail=f"{name} sign-in is not configured")
    return provider


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = _b64url(digest)
    return verifier, challenge


def authorization_url(provider: Provider, state: str, challenge: str) -> str:
    query = urlencode(
        {
            "client_id": provider.client_id,
            "redirect_uri": provider.redirect_uri,
            "response_type": "code",
            "scope": provider.scopes,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    return f"{provider.auth_url}?{query}"


def sign_flow(provider: str, state: str, verifier: str) -> str:
    return jwt.encode(
        {
            "purpose": "oauth",
            "provider": provider,
            "state": state,
            "verifier": verifier,
            "exp": datetime.utcnow() + OAUTH_TTL,
        },
        settings.jwt_secret,
        algorithm="HS256",
    )


def set_flow_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        OAUTH_COOKIE,
        token,
        max_age=int(OAUTH_TTL.total_seconds()),
        **OAUTH_COOKIE_KW,
    )


def clear_flow_cookie(response: Response) -> None:
    response.delete_cookie(OAUTH_COOKIE, path="/", samesite="lax")


def read_flow_cookie(request: Request) -> dict | None:
    raw = request.cookies.get(OAUTH_COOKIE)
    if not raw:
        return None
    try:
        payload = jwt.decode(raw, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    if payload.get("purpose") != "oauth":
        return None
    return payload


def fetch_identity(provider: Provider, code: str, verifier: str) -> ExternalIdentity:
    try:
        with httpx.Client(timeout=20.0) as client:
            token_resp = client.post(
                provider.token_url,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": provider.redirect_uri,
                    "client_id": provider.client_id,
                    "client_secret": provider.client_secret,
                    "code_verifier": verifier,
                },
                headers={"Accept": "application/json"},
            )
            token_resp.raise_for_status()
            access_token = token_resp.json().get("access_token")
            if not access_token:
                raise HTTPException(status_code=502, detail="Sign-in provider did not return a token")
            info_resp = client.get(
                provider.userinfo_url,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            info_resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Sign-in provider request failed") from exc
    return provider.identity_from(info_resp.json())


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
