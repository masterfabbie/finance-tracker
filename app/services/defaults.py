from sqlalchemy.orm import Session

from app import models

# Categories from the original standalone tracker, plus "Transfer" for moves between own accounts.
DEFAULT_CATEGORIES = [
    ("Food & Dining", "#FF6384", "expense"),
    ("Transportation", "#36A2EB", "expense"),
    ("Shopping", "#FFCE56", "expense"),
    ("Cash withdrawal", "#4BC0C0", "expense"),
    ("Entertainment", "#9966FF", "expense"),
    ("Monthly Bills", "#FF9F40", "expense"),
    ("Health & Medical", "#E74C3C", "expense"),
    ("Salary", "#28A745", "income"),
    ("Travel", "#1ABC9C", "expense"),
    ("Investment", "#2C3E50", "income"),
    ("Other", "#C9CBCF", "expense"),
    ("Transfer", "#95A5A6", "transfer"),
]

# Aliases used by the old HTML version's category keys (e.g. in its CSV export).
LEGACY_CATEGORY_KEYS = {
    "food": "Food & Dining",
    "transport": "Transportation",
    "shopping": "Shopping",
    "cash withdrawal": "Cash withdrawal",
    "entertainment": "Entertainment",
    "monthly-bills": "Monthly Bills",
    "health": "Health & Medical",
    "salary": "Salary",
    "travel": "Travel",
    "investment": "Investment",
    "other": "Other",
}


def seed_user_defaults(db: Session, user: models.User) -> None:
    for name, color, kind in DEFAULT_CATEGORIES:
        db.add(models.Category(user_id=user.id, name=name, color=color, kind=kind))
    db.add(models.Account(user_id=user.id, name="Main account"))
    db.flush()
