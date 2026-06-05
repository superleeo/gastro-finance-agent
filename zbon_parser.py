"""
zbon_parser.py — 小票(Z-Bon)解析与财务校验模块
================================================
本模块是本地视觉大模型(VLM)的下游接口。
VLM 提取小票照片中的结构化 JSON 后，由本模块执行严格的财务数学校验。

数据流：
  小票照片 → 本地 VLM → JSON → validate_and_calculate_zbon() → 财务报告
"""

import json
import math
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import date, datetime

from config import (
    TAX_RATE_SPEISEN,
    TAX_RATE_GETRAENKE,
    TAX_CATEGORY_MAP,
    FINANCE_TOLERANCE,
    logger,
)


# ============================================================
# 数据结构
# ============================================================

@dataclass
class ZbonLineItem:
    """单行菜品/饮品条目"""
    name: str
    category: str          # "speisen" | "getraenke"
    netto: Decimal
    brutto: Decimal
    tax_rate: Decimal
    tax_amount: Decimal
    quantity: int = 1
    unit_price_netto: Optional[Decimal] = None

    def __post_init__(self):
        if self.unit_price_netto is None and self.quantity > 0:
            self.unit_price_netto = self.netto / self.quantity


@dataclass
class ZbonPayment:
    """支付方式"""
    method: str            # "cash" | "card" | "ec" | "visa" | "mastercard" | ...
    amount: Decimal


@dataclass
class ZbonValidationResult:
    """校验结果"""
    is_valid: bool = False
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    # 汇总
    netto_total: Decimal = Decimal("0")
    tax_total: Decimal = Decimal("0")
    brutto_total: Decimal = Decimal("0")

    # 按税率分项
    netto_7: Decimal = Decimal("0")
    tax_7: Decimal = Decimal("0")
    brutto_7: Decimal = Decimal("0")
    netto_19: Decimal = Decimal("0")
    tax_19: Decimal = Decimal("0")
    brutto_19: Decimal = Decimal("0")

    # 支付
    cash_total: Decimal = Decimal("0")
    card_total: Decimal = Decimal("0")

    # 原始数据
    items: List[ZbonLineItem] = field(default_factory=list)
    payments: List[ZbonPayment] = field(default_factory=list)
    raw_summary: Dict[str, Any] = field(default_factory=dict)


# ============================================================
# 核心校验函数
# ============================================================

def validate_and_calculate_zbon(raw_data: Dict[str, Any]) -> ZbonValidationResult:
    """
    接收 VLM 提取的 JSON 数据，执行严格的财务数学校验。

    参数
    ----
    raw_data : dict
        VLM 输出，预期结构：
        {
            "receipt_date": "2026-06-05",
            "receipt_number": "0234",
            "items": [
                {
                    "name": "Miso Soup",
                    "category": "speisen",       # "speisen" 或 "getraenke"
                    "netto": 5.00,
                    "brutto": 5.35,
                    "quantity": 1
                },
                ...
            ],
            "payments": [
                {"method": "cash", "amount": 20.00},
                {"method": "card", "amount": 15.35}
            ],
            "summary": {                          # 可选：收银机汇总
                "netto_total": 33.00,
                "tax_total": 2.35,
                "brutto_total": 35.35
            }
        }

    返回
    ----
    ZbonValidationResult — 包含校验结果与财务汇总
    """
    result = ZbonValidationResult()
    result.raw_summary = raw_data.get("summary", {})

    # ---- Step 1: 解析条目 ----
    raw_items = raw_data.get("items", [])
    if not raw_items:
        result.is_valid = False
        result.errors.append("小票中没有找到任何条目 (items 为空)")
        return result

    for i, ri in enumerate(raw_items):
        try:
            item = _parse_line_item(ri, i)
            result.items.append(item)

            # 按税率累加
            if item.tax_rate == Decimal(str(TAX_RATE_SPEISEN)):
                result.netto_7 += item.netto
                result.tax_7 += item.tax_amount
                result.brutto_7 += item.brutto
            elif item.tax_rate == Decimal(str(TAX_RATE_GETRAENKE)):
                result.netto_19 += item.netto
                result.tax_19 += item.tax_amount
                result.brutto_19 += item.brutto
            else:
                result.warnings.append(
                    f"条目 #{i} ({item.name}) 税率 {item.tax_rate} 不是 7% 或 19%"
                )

        except (ValueError, TypeError, KeyError) as exc:
            result.errors.append(f"解析条目 #{i} 失败 (数据格式错误): {exc}")
            continue

    # ---- Step 2: 单行校验 ----
    for i, item in enumerate(result.items):
        expected_brutto = item.netto + item.tax_amount
        diff = abs(item.brutto - expected_brutto)
        if diff > Decimal(str(FINANCE_TOLERANCE)):
            result.errors.append(
                f"条目 #{i} ({item.name}): "
                f"净额 {item.netto} + 税额 {item.tax_amount} = {expected_brutto} "
                f"≠ 总额 {item.brutto} (差值 {diff})"
            )

        # 单独校验税率
        expected_tax = _calc_tax(item.netto, item.tax_rate)
        tax_diff = abs(item.tax_amount - expected_tax)
        if tax_diff > Decimal(str(FINANCE_TOLERANCE)):
            result.warnings.append(
                f"条目 #{i} ({item.name}): "
                f"税额 {item.tax_amount} 与按税率计算值 {expected_tax} 有偏差 ({tax_diff})"
            )

    # ---- Step 3: 汇总校验 ----
    for item in result.items:
        result.netto_total += item.netto
        result.tax_total += item.tax_amount
        result.brutto_total += item.brutto

    # 净值 + 税额 = 总额
    computed_brutto = result.netto_total + result.tax_total
    brutto_diff = abs(result.brutto_total - computed_brutto)
    if brutto_diff > Decimal(str(FINANCE_TOLERANCE)):
        result.errors.append(
            f"汇总校验失败: 净额 {result.netto_total} + 税额 {result.tax_total} "
            f"= {computed_brutto} ≠ 总额 {result.brutto_total}"
        )

    # ---- Step 4: 支付校验 ----
    raw_payments = raw_data.get("payments", [])
    for rp in raw_payments:
        try:
            method = str(rp.get("method", "")).lower().strip()
            amount = Decimal(str(rp.get("amount", 0)))
            pmt = ZbonPayment(method=method, amount=amount)
            result.payments.append(pmt)

            if method in ("cash", "bar"):
                result.cash_total += amount
            elif method in ("card", "ec", "visa", "mastercard", "american_express",
                            "maestro", "girocard", "debit", "credit"):
                result.card_total += amount
            else:
                result.warnings.append(f"未知支付方式 '{method}'，金额 {amount}")
        except (ValueError, TypeError, KeyError, decimal.InvalidOperation) as exc:
            result.errors.append(f"解析支付记录失败 (数据格式错误): {exc}")

    # 现金 + 刷卡 = 总额
    payment_total = result.cash_total + result.card_total
    payment_diff = abs(result.brutto_total - payment_total)
    if result.payments:
        if payment_diff > Decimal(str(FINANCE_TOLERANCE)):
            result.errors.append(
                f"支付校验失败: 现金 {result.cash_total} + 刷卡 {result.card_total} "
                f"= {payment_total} ≠ 总额 {result.brutto_total}"
            )

    # ---- Step 5: 与小票自带汇总比对（如果提供）----
    if result.raw_summary:
        sm = result.raw_summary
        for field_name, computed_val in [
            ("netto_total", result.netto_total),
            ("tax_total", result.tax_total),
            ("brutto_total", result.brutto_total),
        ]:
            raw_val = sm.get(field_name)
            if raw_val is not None:
                raw_d = Decimal(str(raw_val))
                if abs(raw_d - computed_val) > Decimal(str(FINANCE_TOLERANCE)):
                    result.warnings.append(
                        f"小票汇总 {field_name}: 原始值 {raw_d} ≠ 计算值 {computed_val}"
                    )

    # ---- 最终判定 ----
    result.is_valid = len(result.errors) == 0

    if result.is_valid:
        logger.info("小票校验通过 ✓")
    else:
        logger.warning(f"小票校验未通过: {len(result.errors)} 个错误")

    return result


# ============================================================
# 辅助函数
# ============================================================

def _parse_line_item(ri: Dict[str, Any], index: int) -> ZbonLineItem:
    """解析单行条目，统一转换为 Decimal"""
    name = str(ri.get("name", f"Item_{index}"))
    category = str(ri.get("category", "speisen")).lower().strip()

    # 安全取值：防止 VLM 返回 null 导致 Decimal(str(None)) 崩溃
    _raw_netto = ri.get("netto")
    _raw_brutto = ri.get("brutto")
    _raw_qty = ri.get("quantity", 1)
    netto = Decimal(str(_raw_netto)) if _raw_netto is not None else Decimal("0")
    brutto = Decimal(str(_raw_brutto)) if _raw_brutto is not None else Decimal("0")
    quantity = int(_raw_qty) if _raw_qty is not None else 1
    unit_price_netto = (
        Decimal(str(ri["unit_price_netto"]))
        if ri.get("unit_price_netto") is not None
        else None
    )

    # 根据类别确定税率
    if category in ("speisen", "food", "essen"):
        tax_rate = Decimal(str(TAX_RATE_SPEISEN))
    elif category in ("getraenke", "drink", "getränke"):
        tax_rate = Decimal(str(TAX_RATE_GETRAENKE))
    else:
        # 尝试匹配映射
        matched_rate = TAX_CATEGORY_MAP.get(category)
        if matched_rate is not None:
            tax_rate = Decimal(str(matched_rate))
        else:
            # 回退：从 brutto/netto 反推税率
            if netto > 0:
                tax_rate = (brutto / netto - Decimal("1")).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
            else:
                tax_rate = Decimal(str(TAX_RATE_SPEISEN))  # 默认 7%

    # 税额 (若 JSON 中未给，则自动计算)
    _raw_tax = ri.get("tax_amount")
    if _raw_tax is not None:
        tax_amount = Decimal(str(_raw_tax))
    else:
        tax_amount = _calc_tax(netto, tax_rate)

    return ZbonLineItem(
        name=name,
        category=category,
        netto=netto,
        brutto=brutto,
        tax_rate=tax_rate,
        tax_amount=tax_amount,
        quantity=quantity,
        unit_price_netto=unit_price_netto,
    )


def _calc_tax(netto: Decimal, rate: Decimal) -> Decimal:
    """计算税额，四舍五入到分（使用 Decimal 避免浮点精度损失）"""
    tax = netto * rate
    return tax.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ============================================================
# Quick-test / Demo
# ============================================================

def demo() -> ZbonValidationResult:
    """
    用模拟数据运行一次完整校验，方便调试。
    模拟场景：
      - 1× Miso Soup (7%)  €5.00 netto → €5.35 brutto
      - 1× Ramen (7%)      €10.00 netto → €10.70 brutto
      - 1× Asahi Beer (19%) €4.00 netto → €4.76 brutto
      - 现金 €15.00, 刷卡 €5.81
    """
    mock_data = {
        "receipt_date": "2026-06-05",
        "receipt_number": "DEMO-001",
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

    return validate_and_calculate_zbon(mock_data)


if __name__ == "__main__":
    result = demo()

    print("=" * 60)
    print("Gastro Finance Agent — Z-Bon Parser Demo")
    print("=" * 60)
    print(f"  Valid: {result.is_valid}")
    print(f"  Errors: {result.errors}")
    print(f"  Warnings: {result.warnings}")
    print()
    print(f"  ── 财务汇总 ──")
    print(f"  Netto (7%):   {result.netto_7}")
    print(f"  Tax (7%):     {result.tax_7}")
    print(f"  Brutto (7%):  {result.brutto_7}")
    print(f"  Netto (19%):  {result.netto_19}")
    print(f"  Tax (19%):    {result.tax_19}")
    print(f"  Brutto (19%): {result.brutto_19}")
    print(f"  ── 总计 ──")
    print(f"  Netto Total:  {result.netto_total}")
    print(f"  Tax Total:    {result.tax_total}")
    print(f"  Brutto Total: {result.brutto_total}")
    print(f"  Cash:         {result.cash_total}")
    print(f"  Card:         {result.card_total}")
    print("=" * 60)
