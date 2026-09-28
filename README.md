# 💰 Finance Tracker

A self-hosted personal finance tracker. You upload the CSV exports from your bank, and it gives you:
- charts,
- budgets,
- automatic categorization,
- subscription detection.

It supports multiple users, and each user's data is private. Everything runs in one Docker container with a SQLite database.

It replaces the old single-file version, which is kept at `legacy/financetracker_rework.html`.

## Features

- **CSV import** for most German and international bank exports, including Sparkasse, DKB, ING, Volksbank, comdirect and N26.
  - Detects UTF-8 or Windows-1252 encoding, the delimiter, and metadata lines before the header row.
  - Understands German number and date formats such as `1.234,56`, `12,50-`, `100,00 S` and `01.05.25`.
  - Suggests the column mapping and remembers it for each account.
  - Has a "Check parsing" dry run.
- **Duplicate detection:** re-importing overlapping exports never creates doubles, and genuinely identical transactions within one file are kept.
- **Undo** for a whole import from the import history.
- **Multiple accounts** with opening balances, a balance-over-time chart, and automatic detection of transfers between your own accounts.
- **Categories** with colours, and **rules** for auto-categorization:
  - A rule can match on payer, description or IBAN, using contains, equals or regex.
  - When you change a category in the list, the app offers to create a rule and apply it to similar transactions.
- **Budgets** per category per month, with progress bars and over-budget warnings.
- **Subscriptions and recurring payments:**
  - Detected automatically for weekly, monthly, quarterly and yearly intervals.
  - Shows your fixed costs per month and year.
  - The dashboard forecasts the payments still due this month and your month-end balance.
- **Dashboard:**
  - Income, expense and balance cards.
  - A monthly line chart with a category filter.
  - An expenses-by-category pie chart.
  - A balance chart.
  - Filters for account, year and month.
- **Transactions:** search, filters, inline category editing, tags, notes, manual entry and pagination.
- **Export** to CSV (semicolon-separated with comma decimals, like the old version), to Excel (`.xlsx`), and as a full JSON backup.
- **User management:**
  - The admin creates, deactivates, promotes and deletes users and resets passwords.
  - Users change their own passwords.
  - Self-registration is optional.

## Quick start (Docker)

```bash
cp .env.example .env        # then edit ADMIN_PASSWORD
docker compose up -d --build
```

Open http://localhost:8000 and log in with `ADMIN_USERNAME` / `ADMIN_PASSWORD`. The admin is created only on the first start, when the database has no users yet. After that you can change the password under **Settings**.

The data lives in the Docker volume `ft-data`, in the file `/data/finance.db` inside the container.

### Configuration (`.env`)

| Variable | Default | Meaning |
|---|---|---|
| `ADMIN_USERNAME` | `admin` | First admin's username (first start only) |
| `ADMIN_PASSWORD` | – | First admin's password (first start only) |
| `COOKIE_SECURE` | `false` | Set to `true` when served over HTTPS |
| `ALLOW_REGISTRATION` | `false` | Show a "Create an account" link on the login page |
| `SESSION_DAYS` | `14` | How long a login lasts |
| `MAX_UPLOAD_MB` | `10` | Maximum CSV size |

### HTTPS / reverse proxy

Run the app behind a reverse proxy that provides TLS, and set `COOKIE_SECURE=true`. Example `Caddyfile`:

```
finance.example.com {
    reverse_proxy localhost:8000
}
```

The app runs a single worker on purpose. SQLite, the pending-upload store and the login rate limiter all assume one process, which is plenty for a household.

### Backups

```bash
# consistent copy of the database, then copy it out of the container
docker compose exec app sqlite3 /data/finance.db ".backup /data/backup.db"
docker compose cp app:/data/backup.db ./finance-backup.db
```

Each user can also download a JSON backup of their own data under **Settings**.

### Updating

```bash
docker compose up -d --build   # database migrations run automatically on start
```

## Development

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest
ADMIN_PASSWORD=admin123 DATABASE_URL=sqlite:///./data/finance.db alembic upgrade head
ADMIN_PASSWORD=admin123 uvicorn app.main:app --reload
```

The API docs are at http://localhost:8000/api/docs.

### Project layout

```
app/
  main.py, config.py, db.py, models.py, schemas.py, auth.py
  routers/     REST endpoints (/api/...)
  services/    csv_parser, importer, rules, recurring, stats, queries
  static/      frontend (vanilla JS modules + Chart.js, no build step)
alembic/       database migrations
tests/         pytest suite
```

To change the schema, edit `app/models.py`, then run `alembic revision --autogenerate -m "describe change"` and commit the new file in `alembic/versions/`.

### Importing data from the old HTML version

The old version kept its data only in the browser. Its **Export CSV** file (`Date;Description;Payer/Payee;Amount;Type;Category;Tags`) can be imported directly. The columns are recognised automatically, and the old category keys (`food`, `monthly-bills`, …) are mapped to the new categories.
