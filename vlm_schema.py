"""
vlm_schema.py — Pydantic 模型，用于校验本地 VLM 提取的小票 JSON
===============================================================
使用方法:
    from vlm_schema import VlmReceiptInput
    validated = VlmReceiptInput.model_validate(raw_vlm_output)
    result = validate_and_calculate_zbon(validated.model_dump())
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import List, Literal, Optional

from pydantic import (
    BaseModel,
    Field,
    field_validator,
    model_validator,
)


# ╔══════════════════════════════════════════════════════════════╗
# ║                   Schema Definitions                        ║
# ╚══════════════════════════════════════════════════════════════╝

TAX_CATEGORY_VALUES = Literal[
    "speisen", "getraenke", "food", "drink", "essen", "getränke"
]

PAYMENT_METHOD_VALUES = Literal[
    "cash", "bar", "card", "ec", "visa", "mastercard",
    "american_express", "maestro", "girocard", "debit", "credit",
]


class VlmReceiptItem(BaseModel):
    """小票单行条目"""
    name: str = Field(..., min_length=1, description="条目名称")
    category: TAX_CATEGORY_VALUES = Field(..., description="类别: speisen/getraenke")
    netto: float = Field(..., ge=0, description="净价")
    brutto: float = Field(..., ge=0, description="含税总价")
    tax_amount: Optional[float] = Field(default=None, ge=0, description="税额 (可选，未提供则自动计算)")
    quantity: int = Field(default=1, ge=1, le=9999, description="数量")

    @model_validator(mode="after")
    def check_brutto_geq_netto(self) -> "VlmReceiptItem":
        if self.brutto < self.netto:
            raise ValueError(f"brutto ({self.brutto}) 不能小于 netto ({self.netto})")
        return self


class VlmPayment(BaseModel):
    """支付方式"""
    method: str = Field(..., min_length=1, description="支付方式")
    amount: float = Field(..., ge=0, description="支付金额")


class VlmReceiptSummary(BaseModel):
    """收银机自带汇总（可选）"""
    netto_total: Optional[float] = Field(default=None, ge=0)
    tax_total: Optional[float] = Field(default=None, ge=0)
    brutto_total: Optional[float] = Field(default=None, ge=0)


class VlmReceiptInput(BaseModel):
    """
    本地 VLM 提取的小票完整输出。

    示例:
        {
            "receipt_date": "2026-06-05",
            "receipt_number": "0234",
            "items": [
                {"name": "Miso Soup", "category": "speisen", "netto": 5.00, "brutto": 5.35}
            ],
            "payments": [
                {"method": "cash", "amount": 20.00}
            ],
            "summary": {"netto_total": 33.00, "brutto_total": 35.35}
        }
    """
    receipt_date: str = Field(
        ..., min_length=8, max_length=10,
        pattern=r"^\d{4}-\d{2}-\d{2}$",
        description="小票日期 (YYYY-MM-DD)",
    )
    receipt_number: Optional[str] = Field(default=None, description="小票编号")
    items: List[VlmReceiptItem] = Field(..., min_length=1, description="条目列表")
    payments: List[VlmPayment] = Field(default_factory=list, description="支付方式列表")
    summary: Optional[VlmReceiptSummary] = Field(default=None)

    @field_validator("receipt_date")
    @classmethod
    def validate_date(cls, v: str) -> str:
        try:
            date.fromisoformat(v)
        except ValueError:
            raise ValueError(f"无效日期格式: {v!r}，应为 YYYY-MM-DD")
        return v

    @model_validator(mode="after")
    def payment_total_rough_check(self) -> "VlmReceiptInput":
        """Warn if payment total is wildly different from item brutto total."""
        if self.items and self.payments:
            items_brutto = sum(item.brutto for item in self.items)
            payments_total = sum(p.amount for p in self.payments)
            if abs(items_brutto - payments_total) > 100.0:
                raise ValueError(
                    f"支付总额 ({payments_total:.2f}) 与条目总额 ({items_brutto:.2f}) "
                    f"偏差过大 (>100€)，可能是数据错误"
                )
        return self


# ╔══════════════════════════════════════════════════════════════╗
# ║                   Utility                                   ║
# ╚══════════════════════════════════════════════════════════════╝

def validate_or_raise(raw_data: dict) -> VlmReceiptInput:
    """
    校验并返回 VlmReceiptInput，如格式错误则抛出 ValidationError。
    这是 VLM 输出进入系统的唯一入口。
    """
    return VlmReceiptInput.model_validate(raw_data)


# ╔══════════════════════════════════════════════════════════════╗
# ║                   Quick Test                                ║
# ╚══════════════════════════════════════════════════════════════╝

if __name__ == "__main__":
    # 正常数据
    good = {
        "receipt_date": "2026-06-05",
        "receipt_number": "TEST",
        "items": [
            {"name": "Ramen", "category": "speisen", "netto": 10.0, "brutto": 10.70},
        ],
        "payments": [{"method": "cash", "amount": 10.70}],
    }
    validated = validate_or_raise(good)
    print(f"✅ Valid: {validated.receipt_date}, {len(validated.items)} items")

    # 错误数据
    bad = {
        "receipt_date": "2026-06-05",
        "items": [
            {"name": "X", "category": "invalid_cat", "netto": -5.0, "brutto": 5.0},
        ],
    }
    try:
        validate_or_raise(bad)
    except Exception as e:
        print(f"✅ Correctly rejected: {e}")
