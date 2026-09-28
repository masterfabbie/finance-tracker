from datetime import date, timedelta

from app import models
from app.services import recurring
from app.services.defaults import seed_user_defaults


def _user(db):
    user = models.User(username="r", password_hash="x")
    db.add(user)
    db.flush()
    seed_user_defaults(db, user)
    db.commit()
    return user, db.query(models.Account).filter_by(user_id=user.id).one()


def _tx(db, user, account, d, cents, payer, desc="x"):
    db.add(models.Transaction(
        user_id=user.id, account_id=account.id, booking_date=d, amount_cents=cents, payer=payer,
        description=desc, dedup_hash=f"{d}{cents}{payer}{desc}",
    ))


def test_add_months():
    assert recurring.add_months(date(2025, 1, 31), 1) == date(2025, 2, 28)
    assert recurring.add_months(date(2025, 12, 15), 1) == date(2026, 1, 15)


def test_detects_monthly_subscription_and_ignores_irregular(db):
    user, acc = _user(db)
    today = date(2025, 6, 10)
    for m, day in ((2, 3), (3, 1), (4, 2), (5, 3), (6, 2)):
        _tx(db, user, acc, date(2025, m, day), -1299, "Netflix International")
    # irregular shopping at the same shop
    for d in (date(2025, 5, 1), date(2025, 5, 3), date(2025, 5, 20), date(2025, 6, 5)):
        _tx(db, user, acc, d, -2500 - d.day * 100, "REWE")
    # rent with a small change
    for m in (3, 4, 5, 6):
        _tx(db, user, acc, date(2025, m, 1), -80000 if m < 6 else -82000, "Vermieter")
    db.commit()

    series = recurring.detect(db, user.id, today=today)
    names = {s.display_name: s for s in series}
    assert "Netflix International" in names
    assert "Vermieter" in names
    assert "REWE" not in names
    nf = names["Netflix International"]
    assert nf.interval_days == 30
    assert nf.typical_amount_cents == -1299
    assert nf.next_date == date(2025, 7, 2)

    fc = recurring.forecast(db, user.id, current_balance=100000, today=today)
    assert fc["upcoming"] == []  # both next dates are in July

    fc = recurring.forecast(db, user.id, current_balance=100000, today=date(2025, 7, 1))
    assert {u["name"] for u in fc["upcoming"]} == {"Netflix International", "Vermieter"}


def test_stopped_subscription_not_detected(db):
    user, acc = _user(db)
    for m in (1, 2, 3, 4):
        _tx(db, user, acc, date(2025, m, 5), -999, "Spotify")
    db.commit()
    assert recurring.detect(db, user.id, today=date(2025, 9, 1)) == []


def test_dismissed_series_kept(db):
    user, acc = _user(db)
    start = date(2025, 1, 6)
    for i in range(6):
        _tx(db, user, acc, start + timedelta(weeks=i), -500, "Gym")
    db.commit()
    today = start + timedelta(weeks=6)
    [s] = recurring.detect(db, user.id, today=today)
    assert s.interval_days == 7
    s.status = "dismissed"
    db.commit()
    [s2] = recurring.detect(db, user.id, today=today)
    assert s2.status == "dismissed"
    assert recurring.forecast(db, user.id, 0, today=today)["upcoming"] == []
