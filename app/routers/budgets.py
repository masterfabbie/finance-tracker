from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models, schemas
from app.auth import get_current_user
from app.db import get_db
from app.routers.common import owned
from app.services import stats

router = APIRouter(prefix="/api/budgets", tags=["budgets"])


@router.get("")
def list_budgets(
    year: int | None = None,
    month: int | None = Query(None, ge=1, le=12),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    today = date.today()
    return stats.budget_status(db, user.id, year or today.year, month or today.month)


@router.put("")
def upsert_budget(data: schemas.BudgetIn, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    owned(db, models.Category, data.category_id, user)
    budget = db.scalar(
        select(models.Budget).where(models.Budget.user_id == user.id, models.Budget.category_id == data.category_id)
    )
    if budget is None:
        budget = models.Budget(user_id=user.id, category_id=data.category_id, monthly_limit_cents=data.monthly_limit_cents)
        db.add(budget)
    else:
        budget.monthly_limit_cents = data.monthly_limit_cents
    db.commit()
    return {"id": budget.id}


@router.delete("/{budget_id}", status_code=204)
def delete_budget(budget_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    db.delete(owned(db, models.Budget, budget_id, user))
    db.commit()
