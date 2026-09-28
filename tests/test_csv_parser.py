from datetime import date

import pytest

from app.services import csv_parser as cp


@pytest.mark.parametrize(
    "value,cents",
    [
        ("12,50", 1250),
        ("-12,50", -1250),
        ("1.234,56", 123456),
        ("-1.234,56 €", -123456),
        ("1,234.56", 123456),
        ("12.50", 1250),
        ("1.234", 123400),
        ("12,50-", -1250),
        ("100,00 S", -10000),
        ("100,00 H", 10000),
        ("(45.00)", -4500),
        ("EUR 3,00", 300),
        ("+7,1", 710),
        ("1.234.567,89", 123456789),
    ],
)
def test_parse_amount(value, cents):
    assert cp.parse_amount(value) == cents


def test_parse_amount_styles():
    assert cp.parse_amount("1.234", "dot") == 123
    assert cp.parse_amount("1,5", "comma") == 150


@pytest.mark.parametrize("value", ["", "abc", "12,50x", "--"])
def test_parse_amount_invalid(value):
    with pytest.raises(cp.ParseError):
        cp.parse_amount(value)


@pytest.mark.parametrize(
    "value,expected",
    [
        ("01.05.2025", date(2025, 5, 1)),
        ("1.5.25", date(2025, 5, 1)),
        ("31.12.99", date(1999, 12, 31)),
        ("2025-05-01", date(2025, 5, 1)),
        ("2025-05-01T23:30:00", date(2025, 5, 1)),
        ("01/05/2025", date(2025, 5, 1)),
        ("05/13/2025", date(2025, 5, 13)),
    ],
)
def test_parse_date(value, expected):
    # Dates come straight out as date objects: no timezone shift is possible.
    assert cp.parse_date(value) == expected


def test_parse_date_mdy():
    assert cp.parse_date("05/01/2025", "MDY") == date(2025, 5, 1)


def test_parse_date_invalid():
    with pytest.raises(cp.ParseError):
        cp.parse_date("32.01.2025")


def test_type_from_value():
    assert cp.type_from_value("Gutschrift") == "income"
    assert cp.type_from_value("Lastschrift") == "expense"
    assert cp.type_from_value("S") == "expense"
    assert cp.type_from_value("H") == "income"
    assert cp.type_from_value("whatever") is None


SPARKASSE = (
    '"Auftragskonto";"Buchungstag";"Valutadatum";"Buchungstext";"Verwendungszweck";'
    '"Beguenstigter/Zahlungspflichtiger";"Kontonummer/IBAN";"BIC (SWIFT-Code)";"Betrag";"Waehrung";"Info"\n'
    '"DE001";"01.05.25";"01.05.25";"LASTSCHRIFT";"Einkauf Müller";"REWE Markt GmbH";"DE89370400440532013000";"COBADEFF";"-45,30";"EUR";"Umsatz gebucht"\n'
    '"DE001";"02.05.25";"02.05.25";"GUTSCHRIFT";"Gehalt Mai";"Arbeitgeber AG";"DE02120300000000202051";"BYLADEM1";"3.100,00";"EUR";"Umsatz gebucht"\n'
).encode("cp1252")

DKB = (
    '"Kontonummer:";"DE12 3456 7890";\n'
    '"Von:";"01.05.2025";\n'
    '"Bis:";"31.05.2025";\n'
    '"Kontostand vom 31.05.2025:";"1.234,56 EUR";\n'
    "\n"
    '"Buchungsdatum";"Wertstellung";"Status";"Zahlungspflichtige*r";"Zahlungsempfänger*in";"Verwendungszweck";"Umsatztyp";"IBAN";"Betrag (€)";"Gläubiger-ID";"Mandatsreferenz";"Kundenreferenz"\n'
    '"03.05.25";"03.05.25";"Gebucht";"Max";"Netflix";"Abo";"Ausgang";"DE11";"-12,99";"";"";""\n'
    '"04.05.25";"04.05.25";"Gebucht";"Max";"Spotify";"Abo";"Ausgang";"DE22";"-9,99";"";"";""\n'
).encode("utf-8-sig")


def test_parse_sparkasse_cp1252():
    parsed = cp.parse_csv(SPARKASSE)
    assert parsed.encoding == "cp1252"
    assert parsed.delimiter == ";"
    assert parsed.header_line == 1
    assert len(parsed.rows) == 2
    assert parsed.rows[0][4] == "Einkauf Müller"
    m = cp.suggest_mapping(parsed.headers)
    assert m["date"] == "Buchungstag"
    assert m["amount"] == "Betrag"
    assert m["description"] == "Verwendungszweck"
    assert m["payer"] == "Beguenstigter/Zahlungspflichtiger"
    assert m["iban"] == "Kontonummer/IBAN"
    assert m["tags"] == "Buchungstext"


def test_parse_dkb_preamble():
    parsed = cp.parse_csv(DKB)
    assert parsed.encoding == "utf-8-sig"
    assert parsed.headers[0] == "Buchungsdatum"
    assert parsed.header_line == 6
    assert len(parsed.rows) == 2
    m = cp.suggest_mapping(parsed.headers)
    assert m["date"] == "Buchungsdatum"
    assert m["amount"] == "Betrag (€)"


def test_parse_comma_csv_with_quotes():
    raw = b'Date,Description,Amount\n2025-05-01,"Coffee, large",-3.50\n2025-05-02,Refund,"1,200.00"\n'
    parsed = cp.parse_csv(raw)
    assert parsed.delimiter == ","
    assert parsed.rows[0][1] == "Coffee, large"
    assert cp.parse_amount(parsed.rows[1][2]) == 120000


def test_old_tracker_export_roundtrip():
    """The CSV exported by the original HTML tracker imports cleanly."""
    raw = (
        "Date;Description;Payer/Payee;Amount;Type;Category;Tags\n"
        '2025-05-02;"Groceries";"John";150;expense;food;"essential; weekly"\n'
        '2025-05-01;"Salary";"Employer";5000;income;salary;"work; monthly"\n'
    ).encode()
    parsed = cp.parse_csv(raw)
    m = cp.suggest_mapping(parsed.headers)
    assert m["type"] == "Type"
    assert m["category"] == "Category"
    assert m["tags"] == "Tags"
    assert m["payer"] == "Payer/Payee"


def test_empty_file():
    with pytest.raises(cp.ParseError):
        cp.parse_csv(b"")
