"""Single sign-on via OpenID Connect (tested against authentik; works with any compliant provider)."""

import re

from authlib.integrations.starlette_client import OAuth
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models
from app.config import get_settings
from app.services.defaults import seed_user_defaults

_oauth: OAuth | None = None


class SSOError(Exception):
    """A login problem to show to the user."""


def client():
    """The registered OIDC client. Provider metadata is fetched lazily on first use,
    so the app starts even when the identity provider is unreachable."""
    global _oauth
    if _oauth is None:
        s = get_settings()
        _oauth = OAuth()
        _oauth.register(
            "sso",
            client_id=s.oidc_client_id,
            client_secret=s.oidc_client_secret or None,
            server_metadata_url=s.oidc_issuer_url.rstrip("/") + "/.well-known/openid-configuration",
            client_kwargs={"scope": s.oidc_scopes, "code_challenge_method": "S256"},
        )
    return _oauth.sso


def reset_client() -> None:
    global _oauth
    _oauth = None


def _free_username(db: Session, wanted: str) -> str:
    base = re.sub(r"[^A-Za-z0-9_.@-]", "_", wanted.strip())[:60] or "user"
    name, n = base, 1
    while db.scalar(select(models.User.id).where(func.lower(models.User.username) == name.lower())):
        n += 1
        name = f"{base}-{n}"
    return name


def _groups(claims: dict, claim: str) -> list[str]:
    value = claims.get(claim) or []
    if isinstance(value, str):
        return [value]
    return [str(g) for g in value]


def provision_user(db: Session, claims: dict) -> models.User:
    """Find or create the local user for an SSO login and sync admin rights."""
    s = get_settings()
    sub = str(claims.get("sub") or "")
    if not sub:
        raise SSOError("The identity provider did not send a user ID (sub claim).")
    wanted = str(claims.get(s.oidc_username_claim) or claims.get("preferred_username") or claims.get("email") or sub)

    user = db.scalar(select(models.User).where(models.User.oidc_sub == sub))
    if user is None and s.oidc_link_existing_users:
        user = db.scalar(
            select(models.User).where(func.lower(models.User.username) == wanted.lower(), models.User.oidc_sub.is_(None))
        )
        if user is not None:
            user.oidc_sub = sub
    if user is None:
        first_user = db.scalar(select(models.User.id).limit(1)) is None
        user = models.User(
            username=_free_username(db, wanted),
            password_hash=models.NO_PASSWORD,
            oidc_sub=sub,
            is_admin=first_user,  # someone has to be able to manage the instance
        )
        db.add(user)
        db.flush()
        seed_user_defaults(db, user)

    if not user.is_active:
        db.rollback()
        raise SSOError("Your account has been deactivated. Please contact an administrator.")
    if s.oidc_admin_group:
        user.is_admin = s.oidc_admin_group in _groups(claims, s.oidc_groups_claim)
    db.commit()
    return user
