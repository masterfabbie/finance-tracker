from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models, schemas
from app.auth import get_current_user
from app.db import get_db
from app.routers.common import owned
from app.services import recurring, stats

router = APIRouter(prefix="/api/recurring", tags=["recurring"])


def _out(s: models.RecurringSeries) -> schemas.RecurringOut:
    out = schemas.RecurringOut.model_validate(s)
    out.monthly_cost_cents = recurring.monthly_cost(s)
    return out


@router.get("", response_model=list[schemas.RecurringOut])
def list_series(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    series = db.scalars(
        select(models.RecurringSeries)
        .where(models.RecurringSeries.user_id == user.id)
        .order_by(models.RecurringSeries.next_date)
    )
    return [_out(s) for s in series]


@router.post("/scan", response_model=list[schemas.RecurringOut])
def scan(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    return [_out(s) for s in recurring.detect(db, user.id)]


@router.patch("/{series_id}", response_model=schemas.RecurringOut)
def update_series(
    series_id: int, data: schemas.RecurringPatch, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)
):
    s = owned(db, models.RecurringSeries, series_id, user)
    s.status = data.status
    db.commit()
    return _out(s)


@router.get("/forecast")
def forecast(account_id: int | None = None, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    balances = stats.account_balances(db, user.id)
    current = sum(b["balance"] for b in balances if not account_id or b["account_id"] == account_id)
    return recurring.forecast(db, user.id, current)
