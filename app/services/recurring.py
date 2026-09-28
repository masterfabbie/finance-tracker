"""Detects recurring payments (rent, subscriptions, salary) from transaction history."""

import re
from calendar import monthrange
from collections import defaultdict
from datetime import date, timedelta
from statistics import median

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models

# (interval in days, months to add for the next date or 0 for plain days)
PERIODS = [(7, 0), (14, 0), (30, 1), (91, 3), (182, 6), (365, 12)]
MIN_OCCURRENCES = 3
INTERVAL_TOLERANCE = 0.2
AMOUNT_TOLERANCE = 0.1


def payer_key(payer: str, iban: str, description: str) -> str:
    base = payer or iban or " ".join((description or "").split()[:3])
    key = re.sub(r"[^a-zäöüß]+", " ", base.lower())
    return re.sub(r"\s+", " ", key).strip()


def add_months(d: date, months: int) -> date:
    m = d.month - 1 + months
    y, m = d.year + m // 12, m % 12 + 1
    return date(y, m, min(d.day, monthrange(y, m)[1]))


def next_occurrence(d: date, interval_days: int) -> date:
    months = dict(PERIODS).get(interval_days, 0)
    return add_months(d, months) if months else d + timedelta(days=interval_days)


def _detect_period(dates: list[date]) -> int | None:
    gaps = [(b - a).days for a, b in zip(dates, dates[1:]) if (b - a).days > 0]
    if len(gaps) < MIN_OCCURRENCES - 1:
        return None
    m = median(gaps)
    for days, _ in PERIODS:
        if abs(m - days) <= days * INTERVAL_TOLERANCE:
            ok = sum(1 for g in gaps if abs(g - days) <= days * INTERVAL_TOLERANCE * 1.5)
            if ok * 3 >= len(gaps) * 2:
                return days
    return None


def _stable_amount(amounts: list[int]) -> int | None:
    recent = amounts[-6:]
    typical = int(median(recent))
    if typical == 0:
        return None
    ok = sum(1 for a in recent if abs(a - typical) <= abs(typical) * AMOUNT_TOLERANCE)
    return typical if ok * 3 >= len(recent) * 2 else None


def detect(db: Session, user_id: int, today: date | None = None) -> list[models.RecurringSeries]:
    today = today or date.today()
    since = today - timedelta(days=550)
    T, C = models.Transaction, models.Category
    rows = db.execute(
        select(T.booking_date, T.amount_cents, T.payer, T.counterparty_iban, T.description, T.category_id, C.kind)
        .outerjoin(C, T.category_id == C.id)
        .where(T.user_id == user_id, T.booking_date >= since)
        .order_by(T.booking_date)
    ).all()

    groups: dict[str, list] = defaultdict(list)
    names: dict[str, str] = {}
    for d, cents, payer, iban, desc, cat_id, kind in rows:
        if kind == "transfer":
            continue
        key = payer_key(payer, iban, desc)
        if not key:
            continue
        key = f"{'+' if cents > 0 else '-'}{key}"[:255]
        groups[key].append((d, cents, cat_id))
        names.setdefault(key, (payer or desc or iban)[:255])

    existing = {
        s.payer_key: s
        for s in db.scalars(select(models.RecurringSeries).where(models.RecurringSeries.user_id == user_id))
    }
    found: set[str] = set()
    for key, items in groups.items():
        if len(items) < MIN_OCCURRENCES:
            continue
        dates = sorted({d for d, _, _ in items})
        period = _detect_period(dates)
        if period is None:
            continue
        typical = _stable_amount([c for _, c, _ in items])
        if typical is None:
            continue
        last = dates[-1]
        if (today - last).days > period * 2 + 7:
            continue  # stopped: e.g. a cancelled subscription
        found.add(key)
        series = existing.get(key)
        if series is None:
            series = models.RecurringSeries(user_id=user_id, payer_key=key, status="detected")
            db.add(series)
            existing[key] = series
        series.display_name = names[key]
        series.typical_amount_cents = typical
        series.interval_days = period
        series.occurrences = len(items)
        series.last_date = last
        series.next_date = next_occurrence(last, period)
        series.category_id = items[-1][2]

    for key, series in existing.items():
        if key not in found and series.status == "detected":
            db.delete(series)
    db.commit()
    return [s for k, s in existing.items() if k in found or s.status != "detected"]


def forecast(db: Session, user_id: int, current_balance: int, today: date | None = None) -> dict:
    """Payments still expected this month and the resulting end-of-month balance."""
    today = today or date.today()
    month_end = date(today.year, today.month, monthrange(today.year, today.month)[1])
    upcoming = []
    for s in db.scalars(
        select(models.RecurringSeries).where(
            models.RecurringSeries.user_id == user_id, models.RecurringSeries.status != "dismissed"
        )
    ):
        d = s.next_date
        # Skip dates that are overdue by more than a few days; they were probably missed or cancelled.
        while d < today - timedelta(days=3):
            d = next_occurrence(d, s.interval_days)
        while d <= month_end:
            upcoming.append({"series_id": s.id, "name": s.display_name, "date": d.isoformat(), "amount": s.typical_amount_cents})
            d = next_occurrence(d, s.interval_days)
    upcoming.sort(key=lambda u: u["date"])
    expected = sum(u["amount"] for u in upcoming)
    return {
        "current_balance": current_balance,
        "expected_change": expected,
        "expected_month_end_balance": current_balance + expected,
        "upcoming": upcoming,
    }


def monthly_cost(series: models.RecurringSeries) -> int:
    months = dict(PERIODS).get(series.interval_days, 0)
    if months:
        return round(series.typical_amount_cents / months)
    return round(series.typical_amount_cents * 365 / 12 / series.interval_days)
