"""Parsing of bank CSV exports.

Handles the quirks of German and international bank exports: Latin-1/cp1252 encoding,
metadata lines before the real header (DKB, ING), `;` or `,` delimiters, European number
formats (`1.234,56`, `12,50-`, `100,00 S`), and `dd.mm.yy` dates.
"""

import csv
import hashlib
import io
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

DELIMITERS = [";", ",", "\t", "|"]
MAPPING_FIELDS = ["date", "description", "amount", "debit", "credit", "payer", "iban", "type", "category", "tags"]


class ParseError(ValueError):
    pass


@dataclass
class ParsedCSV:
    encoding: str
    delimiter: str
    header_line: int  # 1-based line number of the header row in the file
    headers: list[str]
    rows: list[list[str]] = field(default_factory=list)

    @property
    def signature(self) -> str:
        norm = "|".join(h.strip().lower() for h in self.headers)
        return hashlib.sha256(norm.encode()).hexdigest()


# --------------------------------------------------------------------------- file level


def decode(raw: bytes) -> tuple[str, str]:
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1"), "latin-1"


def _read_rows(text: str, delimiter: str) -> list[list[str]]:
    return [row for row in csv.reader(io.StringIO(text), delimiter=delimiter) if any(c.strip() for c in row)]


def _strip_trailing_empty(row: list[str]) -> list[str]:
    while row and not row[-1].strip():
        row = row[:-1]
    return row


def _column_profile(rows: list[list[str]]) -> tuple[int, int]:
    """Return (table width, how many rows have it), ignoring trailing empty cells.

    Scored by rows x columns so a few short metadata lines before the header (DKB, ING)
    don't outvote a small table. Widths seen only once are ignored when possible.
    """
    counts = Counter(len(_strip_trailing_empty(r)) for r in rows)
    candidates = {w: f for w, f in counts.items() if f >= 2} or counts
    width, freq = max(candidates.items(), key=lambda kv: (kv[1] * kv[0], kv[0]))
    return width, freq


def detect_delimiter(text: str) -> str:
    sample_rows = text.splitlines()[:200]
    sample = "\n".join(sample_rows)
    best, best_score = ";", (-1, -1)
    for delim in DELIMITERS:
        rows = _read_rows(sample, delim)
        if not rows:
            continue
        width, freq = _column_profile(rows)
        if width < 2:
            continue
        score = (freq * width, width)
        if score > best_score:
            best, best_score = delim, score
    return best


def parse_csv(raw: bytes, encoding: str | None = None, delimiter: str | None = None) -> ParsedCSV:
    if encoding:
        text = raw.decode(encoding, errors="replace")
    else:
        text, encoding = decode(raw)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    delimiter = delimiter or detect_delimiter(text)

    # Keep original line numbers so errors can be reported like a spreadsheet would show them.
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    numbered: list[tuple[int, list[str]]] = []
    for row in reader:
        if any(c.strip() for c in row):
            numbered.append((reader.line_num, row))
    if not numbered:
        raise ParseError("The file is empty")

    width, _ = _column_profile([r for _, r in numbered])
    if width < 2:
        raise ParseError("Could not detect columns; is this a CSV file?")

    # The header is the first row at least as wide as the table (skips bank metadata preambles).
    # It can be wider than the data rows when their last columns are empty (DKB).
    header_idx = next(i for i, (_, r) in enumerate(numbered) if len(_strip_trailing_empty(r)) >= width)
    header_line, header = numbered[header_idx]
    width = len(_strip_trailing_empty(header))
    headers = [h.strip() or f"Column {i + 1}" for i, h in enumerate(header[:width])]
    headers = _dedupe_headers(headers)

    rows = []
    for _, r in numbered[header_idx + 1 :]:
        r = [c.strip() for c in r]
        if len(_strip_trailing_empty(r)) < 2:
            continue  # footer lines such as "Kontostand;1.234,56" or totals
        rows.append((r + [""] * width)[:width])
    return ParsedCSV(encoding=encoding, delimiter=delimiter, header_line=header_line, headers=headers, rows=rows)


def _dedupe_headers(headers: list[str]) -> list[str]:
    seen: Counter[str] = Counter()
    out = []
    for h in headers:
        seen[h] += 1
        out.append(h if seen[h] == 1 else f"{h} ({seen[h]})")
    return out


# --------------------------------------------------------------------------- value level


_CURRENCY_RE = re.compile(r"(EUR|USD|GBP|CHF|€|\$|£)", re.IGNORECASE)


def parse_amount(value: str, decimal_style: str = "auto") -> int:
    """Parse a money string into signed cents.

    decimal_style: "auto", "comma" (1.234,56) or "dot" (1,234.56).
    """
    s = (value or "").strip()
    if not s:
        raise ParseError("Missing amount")
    s = _CURRENCY_RE.sub("", s).replace(" ", "").replace(" ", "").replace("'", "")
    negative = False

    if s.startswith("(") and s.endswith(")"):
        negative, s = True, s[1:-1]
    upper = s.upper()
    if len(s) > 1 and upper[-1] in "SH" and (s[-2].isdigit() or s[-2] in ".,"):
        negative, s = upper[-1] == "S", s[:-1]
    if s.endswith("-"):
        negative, s = True, s[:-1]
    elif s.endswith("+"):
        s = s[:-1]
    if s.startswith("-"):
        negative, s = not negative, s[1:]
    elif s.startswith("+"):
        s = s[1:]

    if not re.fullmatch(r"[\d.,]+", s or "x"):
        raise ParseError(f"Invalid amount: {value!r}")

    if decimal_style == "comma":
        s = s.replace(".", "").replace(",", ".")
    elif decimal_style == "dot":
        s = s.replace(",", "")
    elif "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        # One comma is a decimal separator (German style); several are thousands separators.
        s = s.replace(",", ".") if s.count(",") == 1 else s.replace(",", "")
    elif "." in s:
        # "1.234" (exactly three digits after a single dot) is a German thousands separator.
        if s.count(".") > 1 or re.fullmatch(r"\d{1,3}\.\d{3}", s):
            s = s.replace(".", "")

    try:
        amount = Decimal(s)
    except InvalidOperation as exc:
        raise ParseError(f"Invalid amount: {value!r}") from exc
    cents = int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return -cents if negative else cents


def _year(y: int) -> int:
    # Same pivot as the original tracker: 51-99 -> 19xx, 00-50 -> 20xx.
    if y < 100:
        return 1900 + y if y > 50 else 2000 + y
    return y


def parse_date(value: str, date_order: str = "auto") -> date:
    """Parse a date without any timezone conversion.

    date_order: "auto", "DMY", "MDY" or "YMD". Slash dates default to DMY in auto mode.
    """
    s = (value or "").strip()
    if not s:
        raise ParseError("Missing date")
    s = re.split(r"[ T]", s, maxsplit=1)[0]  # drop a time part

    m = re.fullmatch(r"(\d{4})[-./](\d{1,2})[-./](\d{1,2})", s)
    if m:
        y, mo, d = int(m[1]), int(m[2]), int(m[3])
    else:
        m = re.fullmatch(r"(\d{1,2})([./-])(\d{1,2})\2(\d{2}|\d{4})", s)
        if not m:
            raise ParseError(f"Invalid date: {value!r}")
        a, b, y = int(m[1]), int(m[3]), _year(int(m[4]))
        if date_order == "MDY" or (date_order == "auto" and m[2] == "/" and b > 12 >= a):
            mo, d = a, b
        else:
            d, mo = a, b
    try:
        return date(y, mo, d)
    except ValueError as exc:
        raise ParseError(f"Invalid date: {value!r}") from exc


def parse_tags(value: str) -> list[str]:
    return [t for t in (p.strip().lower() for p in re.split(r"[,;|]", value or "")) if t][:10]


INCOME_WORDS = ("income", "credit", "deposit", "gutschrift", "haben", "eingang", "einzahlung", "zins")
EXPENSE_WORDS = ("expense", "debit", "withdrawal", "lastschrift", "soll", "abbuchung", "ausgang", "belastung")


def type_from_value(value: str) -> str | None:
    v = (value or "").strip().lower()
    if v in ("h", "+", "cr"):
        return "income"
    if v in ("s", "-", "dr", "d"):
        return "expense"
    if any(w in v for w in INCOME_WORDS):
        return "income"
    if any(w in v for w in EXPENSE_WORDS):
        return "expense"
    return None


# --------------------------------------------------------------------------- mapping suggestion

_SUGGEST_KEYWORDS: dict[str, list[str]] = {
    "date": ["buchungstag", "buchungsdatum", "booking date", "transaction date", "datum", "date", "valuta", "wertstellung"],
    "amount": ["betrag", "amount", "umsatz", "sum", "value"],
    "description": ["verwendungszweck", "zweck", "description", "beschreibung", "memo", "reference", "details", "note"],
    "payer": [
        "beguenstigter", "begünstigter", "zahlungspflichtiger", "zahlungsempf", "auftraggeber", "empfänger",
        "empfaenger", "payee", "payer", "counterparty", "zahlung", "name", "who",
    ],
    "iban": ["kontonummer/iban", "iban"],
    "type": ["type", "kind", "soll/haben"],
    "category": ["kategorie", "category", "kat", "cat"],
    "tags": ["buchungstext", "umsatzart", "tags"],
    "debit": ["soll", "debit", "ausgang", "belastung"],
    "credit": ["haben", "credit", "eingang", "gutschrift"],
}
_EXCLUDE = {"date": ["buchungstext"], "iban": ["auftragskonto"], "payer": ["iban", "bic", "konto"]}


def suggest_mapping(headers: list[str]) -> dict[str, str]:
    lower = [h.lower() for h in headers]
    used: set[int] = set()
    mapping: dict[str, str] = {}
    for fld in ["date", "amount", "description", "iban", "payer", "category", "tags", "type", "debit", "credit"]:
        if fld in ("debit", "credit") and "amount" in mapping:
            continue
        for kw in _SUGGEST_KEYWORDS[fld]:
            idx = next(
                (
                    i for i, h in enumerate(lower)
                    if i not in used and kw in h and not any(x in h for x in _EXCLUDE.get(fld, []))
                ),
                None,
            )
            if idx is not None:
                mapping[fld] = headers[idx]
                used.add(idx)
                break
    return mapping
