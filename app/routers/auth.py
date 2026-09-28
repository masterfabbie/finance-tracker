import logging
from urllib.parse import quote

from authlib.integrations.base_client import OAuthError
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models, schemas
from app.auth import (
    create_session,
    destroy_session,
    get_current_user,
    hash_password,
    login_throttle,
    validate_password,
    verify_password,
)
from app.config import get_settings
from app.db import get_db
from app.services import oidc
from app.services.defaults import seed_user_defaults

router = APIRouter(prefix="/api/auth", tags=["auth"])
log = logging.getLogger(__name__)


@router.get("/config")
def public_config():
    s = get_settings()
    return {
        "allow_registration": s.allow_registration and s.password_login,
        "password_login": s.password_login,
        "oidc_enabled": s.oidc_enabled,
        "oidc_display_name": s.oidc_display_name,
    }


def _require_password_login() -> None:
    if not get_settings().password_login:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Password login is disabled, please use single sign-on")


@router.post("/login", response_model=schemas.UserOut)
def login(data: schemas.LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    _require_password_login()
    username = data.username.strip()
    keys = (f"user:{username.lower()}", f"ip:{request.client.host if request.client else '?'}")
    if login_throttle.blocked(*keys):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many failed attempts, try again in 15 minutes")
    user = db.scalar(select(models.User).where(func.lower(models.User.username) == username.lower()))
    if user is None or not user.is_active or not verify_password(user.password_hash, data.password):
        login_throttle.fail(*keys)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password")
    login_throttle.reset(*keys)
    create_session(db, user, response)
    return schemas.UserOut.of(user)


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db), _=Depends(get_current_user)):
    destroy_session(db, request, response)


@router.post("/register", response_model=schemas.UserOut, status_code=201)
def register(data: schemas.RegisterIn, response: Response, db: Session = Depends(get_db)):
    _require_password_login()
    if not get_settings().allow_registration:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Registration is disabled")
    validate_password(data.password)
    if db.scalar(select(models.User).where(func.lower(models.User.username) == data.username.lower())):
        raise HTTPException(status.HTTP_409_CONFLICT, "Username already taken")
    user = models.User(username=data.username, password_hash=hash_password(data.password))
    db.add(user)
    db.flush()
    seed_user_defaults(db, user)
    db.commit()
    create_session(db, user, response)
    return schemas.UserOut.of(user)


@router.get("/me", response_model=schemas.UserOut)
def me(user: models.User = Depends(get_current_user)):
    return schemas.UserOut.of(user)


@router.post("/password", status_code=204)
def change_password(
    data: schemas.PasswordChange, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)
):
    if user.password_hash == models.NO_PASSWORD:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Your account uses single sign-on and has no password here")
    if not verify_password(user.password_hash, data.current_password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is wrong")
    validate_password(data.new_password)
    user.password_hash = hash_password(data.new_password)
    db.commit()


# ---- single sign-on (OpenID Connect)


def _sso_fail(message: str) -> RedirectResponse:
    return RedirectResponse("/?sso_error=" + quote(message), status_code=303)


def _callback_url(request: Request) -> str:
    public = get_settings().public_url.rstrip("/")
    if public:
        return public + "/api/auth/oidc/callback"
    return str(request.url_for("oidc_callback"))


@router.get("/oidc/login")
async def oidc_login(request: Request):
    if not get_settings().oidc_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Single sign-on is not configured")
    try:
        return await oidc.client().authorize_redirect(request, _callback_url(request))
    except Exception:  # network errors, bad issuer URL, invalid metadata
        log.exception("Could not start the OIDC login")
        return _sso_fail("The identity provider could not be reached. Check OIDC_ISSUER_URL.")


@router.get("/oidc/callback", name="oidc_callback")
async def oidc_callback(request: Request, db: Session = Depends(get_db)):
    s = get_settings()
    if not s.oidc_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Single sign-on is not configured")
    sso = oidc.client()
    try:
        token = await sso.authorize_access_token(request)
        claims = dict(token.get("userinfo") or {})
        # Some providers only put groups (or everything) into the userinfo endpoint.
        if not claims or (s.oidc_admin_group and s.oidc_groups_claim not in claims):
            claims.update(await sso.userinfo(token=token))
    except OAuthError as exc:
        log.warning("OIDC login failed: %s", exc)
        return _sso_fail(f"Login was not completed: {exc.description or exc.error}")
    except Exception:
        log.exception("OIDC callback failed")
        return _sso_fail("Login failed. Please try again.")
    try:
        user = oidc.provision_user(db, claims)
    except oidc.SSOError as exc:
        return _sso_fail(str(exc))
    response = RedirectResponse("/", status_code=303)
    create_session(db, user, response)
    return response
