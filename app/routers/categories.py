from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app import models, schemas
from app.auth import get_current_user
from app.db import get_db
from app.routers.common import owned

router = APIRouter(prefix="/api", tags=["categories"])


def _name_taken(db: Session, user: models.User, name: str, exclude_id: int | None = None) -> bool:
    q = select(models.Category.id).where(
        models.Category.user_id == user.id, func.lower(models.Category.name) == name.strip().lower()
    )
    if exclude_id:
        q = q.where(models.Category.id != exclude_id)
    return db.scalar(q) is not None


@router.get("/categories", response_model=list[schemas.CategoryOut])
def list_categories(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    return db.scalars(
        select(models.Category).where(models.Category.user_id == user.id).order_by(models.Category.name)
    ).all()


@router.post("/categories", response_model=schemas.CategoryOut, status_code=201)
def create_category(data: schemas.CategoryIn, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    if _name_taken(db, user, data.name):
        raise HTTPException(status.HTTP_409_CONFLICT, "A category with this name already exists")
    cat = models.Category(user_id=user.id, **data.model_dump())
    db.add(cat)
    db.commit()
    return cat


@router.put("/categories/{category_id}", response_model=schemas.CategoryOut)
def update_category(
    category_id: int, data: schemas.CategoryIn, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)
):
    cat = owned(db, models.Category, category_id, user)
    if _name_taken(db, user, data.name, exclude_id=cat.id):
        raise HTTPException(status.HTTP_409_CONFLICT, "A category with this name already exists")
    for k, v in data.model_dump().items():
        setattr(cat, k, v)
    db.commit()
    return cat


@router.delete("/categories/{category_id}", status_code=204)
def delete_category(
    category_id: int,
    move_to: int | None = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    cat = owned(db, models.Category, category_id, user)
    target = owned(db, models.Category, move_to, user).id if move_to else None
    db.execute(
        update(models.Transaction)
        .where(models.Transaction.category_id == cat.id, models.Transaction.user_id == user.id)
        .values(category_id=target)
    )
    db.delete(cat)
    db.commit()


@router.get("/tags", response_model=list[str])
def list_tags(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    return db.scalars(select(models.Tag.name).where(models.Tag.user_id == user.id).order_by(models.Tag.name)).all()
