"""
conftest.py — 共享测试 fixtures
"""

import os
import sys
import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List

import pytest

# 确保项目根目录在 path 中
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from reconciliation import InvoiceRecord  # noqa: E402


# ╔══════════════════════════════════════════════════════════════╗
# ║                    Z-Bon Parser Fixtures                    ║
# ╚══════════════════════════════════════════════════════════════╝

@pytest.fixture
def valid_zbon_json() -> Dict[str, Any]:
    """标准有效的 Z-Bon VLM 输出"""
    return {
        "receipt_date": "2026-06-05",
        "receipt_number": "TEST-001",
        "items": [
            {
                "name": "Miso Soup",
                "category": "speisen",
                "netto": 5.00,
                "brutto": 5.35,
                "tax_amount": 0.35,
                "quantity": 1,
            },
            {
                "name": "Tonkotsu Ramen",
                "category": "speisen",
                "netto": 10.00,
                "brutto": 10.70,
                "tax_amount": 0.70,
                "quantity": 1,
            },
            {
                "name": "Asahi Beer",
                "category": "getraenke",
                "netto": 4.00,
                "brutto": 4.76,
                "tax_amount": 0.76,
                "quantity": 1,
            },
        ],
        "payments": [
            {"method": "cash", "amount": 15.00},
            {"method": "card", "amount": 5.81},
        ],
        "summary": {
            "netto_total": 19.00,
            "tax_total": 1.81,
            "brutto_total": 20.81,
        },
    }


@pytest.fixture
def zbon_with_null_fields() -> Dict[str, Any]:
    """VLM 返回 null 字段的边缘情况"""
    return {
        "receipt_date": "2026-06-05",
        "items": [
            {"name": "Item A", "category": "speisen", "netto": 10.00, "brutto": 10.70},
            {"name": "Item B", "category": "getraenke", "netto": None, "brutto": None},
            {"name": "Item C", "category": "speisen", "netto": 5.00, "brutto": 5.35, "tax_amount": None},
        ],
        "payments": [],
    }


@pytest.fixture
def zbon_mismatched_payments() -> Dict[str, Any]:
    """支付总额与小票总额不符"""
    return {
        "receipt_date": "2026-06-05",
        "items": [
            {"name": "Ramen", "category": "speisen", "netto": 10.00, "brutto": 10.70, "tax_amount": 0.70},
        ],
        "payments": [
            {"method": "cash", "amount": 5.00},
            {"method": "card", "amount": 5.00},
        ],
    }


@pytest.fixture
def zbon_empty() -> Dict[str, Any]:
    """空小票 — 应报错"""
    return {"receipt_date": "2026-06-05", "items": [], "payments": []}


# ╔══════════════════════════════════════════════════════════════╗
# ║               Reconciliation Fixtures                      ║
# ╚══════════════════════════════════════════════════════════════╝

@pytest.fixture
def mock_invoices() -> List[InvoiceRecord]:
    """标准 mock 发票集合"""
    return [
        InvoiceRecord(
            invoice_id="INV-001",
            lieferant="Deutsche Getränke GmbH",
            betrag=Decimal("345.00"),
            datum=date(2026, 6, 1),
            beschreibung="Getränkelieferung Juni",
            kategorie="getraenke",
        ),
        InvoiceRecord(
            invoice_id="INV-002",
            lieferant="Metro C&C Düsseldorf",
            betrag=Decimal("1240.00"),
            datum=date(2026, 6, 2),
            beschreibung="Lebensmittel Großhandel",
            kategorie="speisen",
        ),
        InvoiceRecord(
            invoice_id="INV-003",
            lieferant="Fischhandel Nordsee GmbH",
            betrag=Decimal("580.00"),
            datum=date(2026, 6, 3),
            beschreibung="Frischfisch Sashimi",
            kategorie="speisen",
        ),
    ]


@pytest.fixture
def sample_bank_csv_content() -> str:
    """模拟德国银行 CSV（分号分隔，UTF-8）"""
    return (
        "Buchungstag;Empfänger/Zahlungspflichtiger;Verwendungszweck;Betrag;Währung\r\n"
        "01.06.2026;Deutsche Getränke GmbH;Rechnung 2026-0451 Getränke;-345,00;EUR\r\n"
        "02.06.2026;Metro C&C Düsseldorf;Einkauf Lebensmittel;-1.240,00;EUR\r\n"
        "03.06.2026;Fischhandel Nordsee GmbH;Rechnung 8842 Fisch;-580,00;EUR\r\n"
        "04.06.2026;Unbekannter Lieferant;Keine Rechnung;-156,80;EUR\r\n"
    )


@pytest.fixture
def sample_bank_csv_dtaus() -> str:
    """模拟 DTAUS 格式（尾置负号）"""
    return (
        "Buchungstag;Empfänger/Zahlungspflichtiger;Verwendungszweck;Betrag;Währung\r\n"
        "01.06.2026;Test AG;Rechnung 001;345,00-;EUR\r\n"
    )


@pytest.fixture
def temp_bank_csv(sample_bank_csv_content: str) -> Path:
    """将示例 CSV 写入临时文件，返回路径"""
    tmp = tempfile.NamedTemporaryFile(
        suffix=".csv", mode="w", encoding="utf-8", delete=False
    )
    tmp.write(sample_bank_csv_content)
    tmp.close()
    yield Path(tmp.name)
    try:
        os.unlink(tmp.name)
    except OSError:
        pass
