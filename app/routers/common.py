from typing import TypeVar

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app import models

M = TypeVar("M")


def owned(db: Session, model: type[M], obj_id: int | None, user: models.User) -> M:
    """Fetch a row that belongs to the user, or raise 404 (never reveal other users' rows)."""
    obj = db.get(model, obj_id) if obj_id is not None else None
    if obj is None or getattr(obj, "user_id", None) != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{model.__name__} not found")
    return obj


def owned_account(db: Session, account_id: int | None, user: models.User) -> models.Account:
    return owned(db, models.Account, account_id, user)
