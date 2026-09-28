from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
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
from app.services.defaults import seed_user_defaults

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/config")
def public_config():
    return {"allow_registration": get_settings().allow_registration}


@router.post("/login", response_model=schemas.UserOut)
def login(data: schemas.LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
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
    return user


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db), _=Depends(get_current_user)):
    destroy_session(db, request, response)


@router.post("/register", response_model=schemas.UserOut, status_code=201)
def register(data: schemas.RegisterIn, response: Response, db: Session = Depends(get_db)):
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
    return user


@router.get("/me", response_model=schemas.UserOut)
def me(user: models.User = Depends(get_current_user)):
    return user


@router.post("/password", status_code=204)
def change_password(
    data: schemas.PasswordChange, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)
):
    if not verify_password(user.password_hash, data.current_password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is wrong")
    validate_password(data.new_password)
    user.password_hash = hash_password(data.new_password)
    db.commit()
