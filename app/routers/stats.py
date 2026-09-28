from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import models
from app.auth import get_current_user
from app.db import get_db
from app.services import stats
from app.services.queries import TxFilters, tx_filters

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("/summary")
def summary(f: TxFilters = Depends(tx_filters), db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    return stats.summary(db, user.id, f)


@router.get("/monthly")
def monthly(f: TxFilters = Depends(tx_filters), db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    return stats.monthly(db, user.id, f)


@router.get("/by-category")
def by_category(f: TxFilters = Depends(tx_filters), db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    return stats.by_category(db, user.id, f)


@router.get("/balances")
def balances(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    return stats.account_balances(db, user.id)


@router.get("/balance-history")
def balance_history(
    account_id: int | None = None, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)
):
    return stats.balance_history(db, user.id, account_id)
