from datetime import date

from app import models
from app.services import csv_parser as cp
from app.services import importer
from app.services.defaults import seed_user_defaults
from app.services.rules import rerun_rules

CSV = (
    "Buchungstag;Verwendungszweck;Beguenstigter/Zahlungspflichtiger;Kontonummer/IBAN;Betrag\n"
    "01.05.2025;Kaffee;Cafe;DE1;-3,50\n"
    "01.05.2025;Kaffee;Cafe;DE1;-3,50\n"  # a genuine second identical coffee on the same day
    "02.05.2025;Gehalt;Arbeitgeber;DE2;3.000,00\n"
    "03.05.2025;Umbuchung;Ich;DE99OWN;-500,00\n"
    "kaputt;Fehler;X;;-1,00\n"
).encode()


def _setup(db):
    user = models.User(username="u", password_hash="x")
    db.add(user)
    db.flush()
    seed_user_defaults(db, user)
    account = db.query(models.Account).filter_by(user_id=user.id).one()
    db.add(models.Account(user_id=user.id, name="Savings", iban="DE99OWN"))
    db.commit()
    return user, account


def _import(db, user, account, raw=CSV, mapping=None):
    parsed = cp.parse_csv(raw)
    rows, failures = importer.normalize_rows(parsed, mapping or cp.suggest_mapping(parsed.headers))
    return importer.import_rows(db, user, account, rows, failures, "test.csv")


def test_import_dedup_and_twins(db):
    user, account = _setup(db)
    r1 = _import(db, user, account)
    assert (r1.imported, r1.duplicates, r1.failed) == (4, 0, 1)
    assert r1.failed_rows[0]["line"] == 6

    r2 = _import(db, user, account)
    assert (r2.imported, r2.duplicates) == (0, 4)
    assert r2.batch_id is None

    coffees = db.query(models.Transaction).filter_by(description="Kaffee").all()
    assert len(coffees) == 2
    assert all(t.booking_date == date(2025, 5, 1) and t.amount_cents == -350 for t in coffees)


def test_transfer_to_own_account_is_detected(db):
    user, account = _setup(db)
    _import(db, user, account)
    tx = db.query(models.Transaction).filter_by(description="Umbuchung").one()
    assert tx.category.name == "Transfer"


def test_rules_applied_on_import_and_rerun(db):
    user, account = _setup(db)
    food = db.query(models.Category).filter_by(user_id=user.id, name="Food & Dining").one()
    db.add(models.Rule(user_id=user.id, field="payer", match="contains", pattern="cafe", category_id=food.id, add_tags=["coffee"]))
    db.commit()
    _import(db, user, account)
    tx = db.query(models.Transaction).filter_by(description="Kaffee").first()
    assert tx.category_id == food.id
    assert [t.name for t in tx.tags] == ["coffee"]

    salary = db.query(models.Transaction).filter_by(description="Gehalt").one()
    assert salary.category.name == "Other"
    sal_cat = db.query(models.Category).filter_by(user_id=user.id, name="Salary").one()
    db.add(models.Rule(user_id=user.id, field="description", match="regex", pattern="^geh", category_id=sal_cat.id))
    db.commit()
    assert rerun_rules(db, user.id) == 1
    db.refresh(salary)
    assert salary.category_id == sal_cat.id


def test_type_column_and_category_column(db):
    user, account = _setup(db)
    raw = (
        "Date;Description;Payer/Payee;Amount;Type;Category;Tags\n"
        '2025-05-02;"Groceries";"John";150;expense;food;"essential; weekly"\n'
        '2025-05-01;"Salary";"Employer";5000;income;salary;"work"\n'
        '2025-05-03;"Hobby";"Shop";20;expense;knitting;""\n'
    ).encode()
    r = _import(db, user, account, raw)
    assert r.imported == 3
    groceries = db.query(models.Transaction).filter_by(description="Groceries").one()
    assert groceries.amount_cents == -15000
    assert groceries.category.name == "Food & Dining"  # legacy key "food" maps to the default category
    assert sorted(t.name for t in groceries.tags) == ["essential", "weekly"]
    assert db.query(models.Transaction).filter_by(description="Salary").one().amount_cents == 500000
    assert db.query(models.Category).filter_by(user_id=user.id, name="knitting").count() == 1


def test_debit_credit_columns(db):
    user, account = _setup(db)
    raw = "Datum;Text;Soll;Haben\n01.05.2025;Miete;800,00;\n02.05.2025;Lohn;;2.000,00\n".encode()
    parsed = cp.parse_csv(raw)
    mapping = cp.suggest_mapping(parsed.headers)
    assert mapping["debit"] == "Soll" and mapping["credit"] == "Haben"
    mapping["description"] = "Text"
    r = _import(db, user, account, raw, mapping)
    assert r.imported == 2
    amounts = sorted(t.amount_cents for t in db.query(models.Transaction).all())
    assert amounts == [-80000, 200000]


def test_invert_sign(db):
    user, account = _setup(db)
    raw = b"Date;Description;Amount\n2025-05-01;Card payment;12.00\n"
    r = _import(db, user, account, raw, {"date": "Date", "description": "Description", "amount": "Amount", "invert_sign": True})
    assert r.imported == 1
    assert db.query(models.Transaction).one().amount_cents == -1200
