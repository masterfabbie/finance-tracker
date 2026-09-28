import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import models
from app.config import get_settings
from app.db import get_db

SESSION_COOKIE = "ft_session"
CSRF_COOKIE = "ft_csrf"
CSRF_HEADER = "X-CSRF-Token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def validate_password(password: str) -> None:
    if len(password) < 8:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Password must be at least 8 characters")


def _token_id(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db: DbSession, user: models.User, response: Response) -> models.Session:
    settings = get_settings()
    token = secrets.token_urlsafe(32)
    sess = models.Session(
        id=_token_id(token),
        user_id=user.id,
        csrf_token=secrets.token_urlsafe(32),
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.session_days),
    )
    db.add(sess)
    db.commit()
    max_age = settings.session_days * 86400
    response.set_cookie(
        SESSION_COOKIE, token, max_age=max_age, httponly=True, samesite="lax", secure=settings.cookie_secure
    )
    response.set_cookie(
        CSRF_COOKIE, sess.csrf_token, max_age=max_age, httponly=False, samesite="lax", secure=settings.cookie_secure
    )
    return sess


def destroy_session(db: DbSession, request: Request, response: Response) -> None:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        sess = db.get(models.Session, _token_id(token))
        if sess:
            db.delete(sess)
            db.commit()
    response.delete_cookie(SESSION_COOKIE)
    response.delete_cookie(CSRF_COOKIE)


def get_current_user(request: Request, db: DbSession = Depends(get_db)) -> models.User:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not logged in")
    sess = db.get(models.Session, _token_id(token))
    if sess is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired")
    expires = sess.expires_at if sess.expires_at.tzinfo else sess.expires_at.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc) or not sess.user.is_active:
        db.delete(sess)
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired")
    if request.method not in SAFE_METHODS:
        sent = request.headers.get(CSRF_HEADER, "")
        if not hmac.compare_digest(sent, sess.csrf_token):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "CSRF token missing or invalid")
    return sess.user


def require_admin(user: models.User = Depends(get_current_user)) -> models.User:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin only")
    return user


class LoginThrottle:
    """In-memory limiter: max `limit` failures per key within `window` seconds."""

    def __init__(self, limit: int = 5, window: int = 900):
        self.limit = limit
        self.window = window
        self._failures: dict[str, deque[float]] = defaultdict(deque)

    def _prune(self, key: str) -> deque[float]:
        q = self._failures[key]
        cutoff = time.monotonic() - self.window
        while q and q[0] < cutoff:
            q.popleft()
        return q

    def blocked(self, *keys: str) -> bool:
        return any(len(self._prune(k)) >= self.limit for k in keys)

    def fail(self, *keys: str) -> None:
        now = time.monotonic()
        for k in keys:
            self._prune(k).append(now)

    def reset(self, *keys: str) -> None:
        for k in keys:
            self._failures.pop(k, None)


login_throttle = LoginThrottle()


def ensure_admin(db: DbSession) -> None:
    """Create the first admin from env vars if the users table is empty."""
    settings = get_settings()
    if db.scalar(select(models.User.id).limit(1)) is not None:
        return
    if not settings.admin_password:
        if settings.oidc_enabled:
            print("No users yet: the first person to log in via single sign-on becomes admin.")
        else:
            print("WARNING: no users exist and ADMIN_PASSWORD is not set; cannot create the first admin.")
        return
    from app.services.defaults import seed_user_defaults

    user = models.User(
        username=settings.admin_username, password_hash=hash_password(settings.admin_password), is_admin=True
    )
    db.add(user)
    db.flush()
    seed_user_defaults(db, user)
    db.commit()
