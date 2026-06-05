"""
test_zbon_parser.py — 小票解析与财务校验单元测试
"""

from decimal import Decimal

import pytest

from zbon_parser import (
    ZbonLineItem,
    ZbonPayment,
    ZbonValidationResult,
    _calc_tax,
    _parse_line_item,
    validate_and_calculate_zbon,
)


# ╔══════════════════════════════════════════════════════════════╗
# ║                    纯函数单元测试                           ║
# ╚══════════════════════════════════════════════════════════════╝

class TestCalcTax:
    def test_7_percent(self):
        result = _calc_tax(Decimal("100.00"), Decimal("0.07"))
        assert result == Decimal("7.00")

    def test_19_percent(self):
        result = _calc_tax(Decimal("100.00"), Decimal("0.19"))
        assert result == Decimal("19.00")

    def test_fractional_cent_rounds_half_up(self):
        # 0.07 × 5.55 = 0.3885 → 0.39 (kaufmännische Rundung)
        result = _calc_tax(Decimal("5.55"), Decimal("0.07"))
        assert result == Decimal("0.39")

    def test_small_amount(self):
        result = _calc_tax(Decimal("0.50"), Decimal("0.19"))
        assert result == Decimal("0.10")  # 0.095 → 0.10


class TestParseLineItem:
    def test_standard_item(self):
        raw = {"name": "Ramen", "category": "speisen", "netto": 10.0, "brutto": 10.70}
        item = _parse_line_item(raw, 0)
        assert item.name == "Ramen"
        assert item.category == "speisen"
        assert item.netto == Decimal("10.00")
        assert item.brutto == Decimal("10.70")
        assert item.tax_rate == Decimal("0.07")

    def test_drink_item(self):
        raw = {"name": "Beer", "category": "getraenke", "netto": 4.0, "brutto": 4.76}
        item = _parse_line_item(raw, 0)
        assert item.tax_rate == Decimal("0.19")
        assert item.tax_amount == Decimal("0.76")

    def test_null_netto_brutto(self):
        """VLM 返回 null 时不应崩溃"""
        raw = {"name": "Unknown", "category": "speisen", "netto": None, "brutto": None}
        item = _parse_line_item(raw, 0)
        assert item.netto == Decimal("0")
        assert item.brutto == Decimal("0")

    def test_null_quantity(self):
        raw = {"name": "Item", "category": "speisen", "netto": 5.0, "brutto": 5.35, "quantity": None}
        item = _parse_line_item(raw, 0)
        assert item.quantity == 1

    def test_missing_tax_amount_auto_calculated(self):
        raw = {"name": "Sake", "category": "getraenke", "netto": 9.0, "brutto": 10.71}
        item = _parse_line_item(raw, 0)
        assert item.tax_amount == _calc_tax(Decimal("9.00"), Decimal("0.19"))


# ╔══════════════════════════════════════════════════════════════╗
# ║                    完整校验测试                             ║
# ╚══════════════════════════════════════════════════════════════╝

class TestValidateAndCalculateZbon:
    def test_valid_receipt_passes(self, valid_zbon_json):
        result = validate_and_calculate_zbon(valid_zbon_json)
        assert result.is_valid is True
        assert len(result.errors) == 0

    def test_totals_match(self, valid_zbon_json):
        result = validate_and_calculate_zbon(valid_zbon_json)
        assert result.netto_total == Decimal("19.00")
        assert result.tax_total == Decimal("1.81")
        assert result.brutto_total == Decimal("20.81")

    def test_tax_split(self, valid_zbon_json):
        result = validate_and_calculate_zbon(valid_zbon_json)
        # 7%: Miso 5.00 + Ramen 10.00 = 15.00 netto → 1.05 tax → 16.05 brutto
        assert result.netto_7 == Decimal("15.00")
        assert result.tax_7 == Decimal("1.05")
        assert result.brutto_7 == Decimal("16.05")
        # 19%: Beer 4.00 netto → 0.76 tax → 4.76 brutto
        assert result.netto_19 == Decimal("4.00")
        assert result.tax_19 == Decimal("0.76")
        assert result.brutto_19 == Decimal("4.76")

    def test_payments_match_brutto(self, valid_zbon_json):
        result = validate_and_calculate_zbon(valid_zbon_json)
        assert result.cash_total == Decimal("15.00")
        assert result.card_total == Decimal("5.81")
        assert result.cash_total + result.card_total == result.brutto_total

    def test_empty_items_fails(self, zbon_empty):
        result = validate_and_calculate_zbon(zbon_empty)
        assert result.is_valid is False
        assert any("为空" in e for e in result.errors)

    def test_null_fields_survives(self, zbon_with_null_fields):
        """VLM 返回 null 值时不应崩溃"""
        result = validate_and_calculate_zbon(zbon_with_null_fields)
        assert len(result.errors) == 0
        assert result.netto_total > 0  # Item A + Item C 成功解析

    def test_mismatched_payments_detected(self, zbon_mismatched_payments):
        result = validate_and_calculate_zbon(zbon_mismatched_payments)
        # 支付总额 10.00 ≠ 小票总额 10.70
        assert any("支付校验失败" in e for e in result.errors)


# ╔══════════════════════════════════════════════════════════════╗
# ║                    容差边界测试                             ║
# ╚══════════════════════════════════════════════════════════════╝

class TestTolerance:
    def test_exact_tolerance_boundary(self):
        """差值刚好等于容差 0.02 时应通过校验"""
        data = {
            "receipt_date": "2026-06-05",
            "items": [
                {"name": "X", "category": "speisen", "netto": 100.00,
                 "brutto": 107.02, "tax_amount": 7.00},  # 100+7=107 ≠107.02, diff=0.02
            ],
            "payments": [{"method": "cash", "amount": 107.02}],
        }
        result = validate_and_calculate_zbon(data)
        # 差值为 0.02，刚好在容差边界，应通过
        assert result.is_valid is True

    def test_just_over_tolerance_fails(self):
        """差值 0.03 > 容差 0.02 时应报错"""
        data = {
            "receipt_date": "2026-06-05",
            "items": [
                {"name": "X", "category": "speisen", "netto": 100.00,
                 "brutto": 107.03, "tax_amount": 7.00},  # diff=0.03
            ],
            "payments": [{"method": "cash", "amount": 107.03}],
        }
        result = validate_and_calculate_zbon(data)
        assert result.is_valid is False
