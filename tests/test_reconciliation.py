"""
test_reconciliation.py — 银行对账与模糊匹配单元测试
"""

from decimal import Decimal
from pathlib import Path

import pytest

from reconciliation import (
    BankTransaction,
    InvoiceRecord,
    MissingInvoice,
    _fuzzy_score,
    _normalize_text,
    _tokenize,
    _parse_german_number,
    parse_bank_csv,
    filter_expenses,
    fuzzy_match_invoices,
    generate_reminder_emails,
)


# ╔══════════════════════════════════════════════════════════════╗
# ║                 德语数字解析                                ║
# ╚══════════════════════════════════════════════════════════════╝

class TestParseGermanNumber:
    def test_standard_format(self):
        assert _parse_german_number("1.234,56") == Decimal("1234.56")

    def test_negative_prefix(self):
        assert _parse_german_number("-1.234,56") == Decimal("-1234.56")

    def test_dtaus_trailing_minus(self):
        """DTAUS 标准：尾置负号"""
        assert _parse_german_number("1.234,56-") == Decimal("-1234.56")

    def test_simple_trailing_minus(self):
        assert _parse_german_number("42,00-") == Decimal("-42.00")

    def test_zero(self):
        assert _parse_german_number("0,00") == Decimal("0.00")

    def test_eur_symbol(self):
        assert _parse_german_number("€345,00") == Decimal("345.00")

    def test_empty_returns_none(self):
        assert _parse_german_number("") is None

    def test_plain_text_returns_none(self):
        assert _parse_german_number("EUR") is None

    def test_whitespace_handling(self):
        assert _parse_german_number("  1.500,00-  ") == Decimal("-1500.00")


# ╔══════════════════════════════════════════════════════════════╗
# ║                 文本规范化与模糊匹配                        ║
# ╚══════════════════════════════════════════════════════════════╝

class TestNormalizeText:
    def test_umlauts_stripped(self):
        result = _normalize_text("Deutsche Getränke GmbH")
        assert "getranke" in result  # ä → a

    def test_case_insensitive(self):
        assert _normalize_text("ABC") == _normalize_text("abc")

    def test_special_chars_removed(self):
        result = _normalize_text("Hello! World? #123.")
        assert "!" not in result
        assert "?" not in result

    def test_whitespace_collapsed(self):
        result = _normalize_text("foo    bar\n\tbaz")
        assert result == "foo bar baz"


class TestFuzzyScore:
    def test_exact_match(self):
        score = _fuzzy_score("Deutsche Getränke GmbH", "Deutsche Getränke GmbH")
        assert score >= 0.85  # Jaccard + substring bonus yields ~0.9

    def test_no_match(self):
        score = _fuzzy_score("ABC GmbH", "XYZ Corp")
        assert score < 0.2

    def test_substring_bonus(self):
        score = _fuzzy_score("Deutsche Getränke", "Deutsche Getränke GmbH München")
        assert score > 0.4  # 子串加分


# ╔══════════════════════════════════════════════════════════════╗
# ║                 银行 CSV 解析                               ║
# ╚══════════════════════════════════════════════════════════════╝

class TestParseBankCsv:
    def test_standard_csv(self, temp_bank_csv: Path):
        txns = parse_bank_csv(temp_bank_csv)
        assert len(txns) == 4
        assert all(isinstance(t, BankTransaction) for t in txns)

    def test_expenses_are_negative(self, temp_bank_csv: Path):
        txns = parse_bank_csv(temp_bank_csv)
        expenses = filter_expenses(txns)
        assert len(expenses) == 4
        for e in expenses:
            assert e.betrag < 0


# ╔══════════════════════════════════════════════════════════════╗
# ║                 模糊发票匹配                                ║
# ╚══════════════════════════════════════════════════════════════╝

class TestFuzzyMatchInvoices:
    def test_known_supplier_matched(self, temp_bank_csv: Path, mock_invoices):
        txns = parse_bank_csv(temp_bank_csv)
        expenses = filter_expenses(txns)
        missing, matched = fuzzy_match_invoices(expenses, mock_invoices)
        # 3 of 4 should match (Deutsche Getränke, Metro, Fischhandel)
        assert matched == 3
        assert len(missing) == 1  # Unbekannter Lieferant

    def test_unknown_supplier_flagged(self, temp_bank_csv: Path, mock_invoices):
        txns = parse_bank_csv(temp_bank_csv)
        expenses = filter_expenses(txns)
        missing, _ = fuzzy_match_invoices(expenses, mock_invoices)
        unknown = next(m for m in missing if "Unbekannter" in m.transaction.empfaenger)
        assert unknown.match_score < 0.3


# ╔══════════════════════════════════════════════════════════════╗
# ║                 邮件生成测试                                 ║
# ╚══════════════════════════════════════════════════════════════╝

class TestGenerateReminderEmails:
    def test_generates_file(self, tmp_path: Path):
        txn = BankTransaction(
            buchungstag=__import__("datetime").date(2026, 6, 5),
            empfaenger="Test Lieferant GmbH",
            verwendungszweck="Rechnung 12345",
            betrag=Decimal("-299.00"),
        )
        missing = [MissingInvoice(transaction=txn, match_score=0.0)]
        result = generate_reminder_emails(missing, output_dir=tmp_path)
        assert result[0].email_sent is True
        files = list(tmp_path.glob("*.txt"))
        assert len(files) == 1
        content = files[0].read_text(encoding="utf-8")
        assert "Test Lieferant GmbH" in content
        assert "299.00 EUR" in content
