"""
tax_report.py — 德国餐饮月度增值税预申报 (UStVA) 模块
======================================================
根据 Z-Bon 采集的数据，按月度汇总 7% 和 19% 税率分项，
输出符合德国 ELSTER 税表格式的 CSV 文件。

§12 Abs. 2 Nr. 1 UStG — 食品类 7%
§12 Abs. 1 UStG       — 饮品类 19%

ELSTER 字段映射:
  KZ 81: 税基 (Bemessungsgrundlage) — 7% 食品
  KZ 86: 税基 (Bemessungsgrundlage) — 19% 饮品
  KZ 35: 可抵扣进项税 (Vorsteuer) — 总计
  KZ 36: 应付增值税 — 总计
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from config import (
    DIR_OUTPUT,
    TAX_RATE_SPEISEN,
    TAX_RATE_GETRAENKE,
    logger,
)


# ╔══════════════════════════════════════════════════════════════╗
# ║                   Data Structures                           ║
# ╚══════════════════════════════════════════════════════════════╝

@dataclass
class MonthlyTaxRecord:
    """单月税务汇总"""
    month: str              # "2026-06"
    netto_7: Decimal = Decimal("0")
    tax_7: Decimal = Decimal("0")
    brutto_7: Decimal = Decimal("0")
    netto_19: Decimal = Decimal("0")
    tax_19: Decimal = Decimal("0")
    brutto_19: Decimal = Decimal("0")

    @property
    def netto_total(self) -> Decimal:
        return self.netto_7 + self.netto_19

    @property
    def tax_total(self) -> Decimal:
        return self.tax_7 + self.tax_19

    @property
    def brutto_total(self) -> Decimal:
        return self.brutto_7 + self.brutto_19


@dataclass
class UStVARecord:
    """单笔日结 Z-Bon 记录（持久化后的）"""
    date: date
    netto_7: Decimal
    tax_7: Decimal
    brutto_7: Decimal
    netto_19: Decimal
    tax_19: Decimal
    brutto_19: Decimal
    receipt_number: str = ""


@dataclass
class UStVAReport:
    """完整 UStVA 报告"""
    year: int
    records: List[UStVARecord] = field(default_factory=list)
    input_tax_deductible: Decimal = Decimal("0")  # 可抵扣进项税 (Vorsteuer)

    @property
    def monthly_records(self) -> Dict[str, MonthlyTaxRecord]:
        """按月聚合"""
        months: Dict[str, MonthlyTaxRecord] = {}
        for rec in self.records:
            m = rec.date.strftime("%Y-%m")
            if m not in months:
                months[m] = MonthlyTaxRecord(month=m)
            mr = months[m]
            mr.netto_7 += rec.netto_7
            mr.tax_7 += rec.tax_7
            mr.brutto_7 += rec.brutto_7
            mr.netto_19 += rec.netto_19
            mr.tax_19 += rec.tax_19
            mr.brutto_19 += rec.brutto_19
        return months


# ╔══════════════════════════════════════════════════════════════╗
# ║                   CSV Export                                ║
# ╚══════════════════════════════════════════════════════════════╝

def export_ustva_csv(
    report: UStVAReport,
    month: Optional[str] = None,
    output_dir: Optional[Path] = None,
) -> Path:
    """
    导出符合德国 ELSTER 格式的月度 UStVA CSV。

    输出列:
      Kennziffer, Bezeichnung, Bemessungsgrundlage, Steuerbetrag
    """
    if output_dir is None:
        output_dir = DIR_OUTPUT
    output_dir.mkdir(parents=True, exist_ok=True)

    # 确定要导出的月份
    monthly = report.monthly_records
    if month:
        target = monthly.get(month)
        if target is None:
            raise ValueError(f"月份 {month} 没有数据")
        records_to_export = {month: target}
    else:
        records_to_export = monthly

    for m, mr in records_to_export.items():
        filename = f"UStVA_{m}.csv"
        filepath = output_dir / filename

        rows = [
            {
                "Kennziffer": "81",
                "Bezeichnung": "Steuerpflichtige Umsätze (7% USt — Lebensmittel)",
                "Bemessungsgrundlage_EUR": f"{float(mr.netto_7):.2f}",
                "Steuerbetrag_EUR": f"{float(mr.tax_7):.2f}",
            },
            {
                "Kennziffer": "86",
                "Bezeichnung": "Steuerpflichtige Umsätze (19% USt — Getränke/sonstige)",
                "Bemessungsgrundlage_EUR": f"{float(mr.netto_19):.2f}",
                "Steuerbetrag_EUR": f"{float(mr.tax_19):.2f}",
            },
            {
                "Kennziffer": "—",
                "Bezeichnung": "Summe steuerpflichtige Umsätze",
                "Bemessungsgrundlage_EUR": f"{float(mr.netto_total):.2f}",
                "Steuerbetrag_EUR": f"{float(mr.tax_total):.2f}",
            },
            {
                "Kennziffer": "66",
                "Bezeichnung": "Abziehbare Vorsteuer (geschätzt/aus Bank CSV)",
                "Bemessungsgrundlage_EUR": "0.00",
                "Steuerbetrag_EUR": f"{float(report.input_tax_deductible):.2f}",
            },
            {
                "Kennziffer": "83",
                "Bezeichnung": "Umsatzsteuer-Vorauszahlung (berechnet)",
                "Bemessungsgrundlage_EUR": "0.00",
                "Steuerbetrag_EUR": f"{float(mr.tax_total - report.input_tax_deductible):.2f}",
            },
        ]

        pd.DataFrame(rows).to_csv(filepath, index=False, encoding="utf-8-sig")
        logger.info("UStVA 报告已导出: %s (应付增值税 €%.2f)", filepath, float(mr.tax_total - report.input_tax_deductible))

    return filepath


def export_monthly_summary_excel(
    report: UStVAReport,
    output_dir: Optional[Path] = None,
) -> Path:
    """
    导出多月份汇总 Excel（用于税务顾问）。
    """
    if output_dir is None:
        output_dir = DIR_OUTPUT

    monthly = report.monthly_records
    rows = []
    for m, mr in sorted(monthly.items()):
        rows.append({
            "Monat": m,
            "Netto_7%_EUR": float(mr.netto_7),
            "Steuer_7%_EUR": float(mr.tax_7),
            "Brutto_7%_EUR": float(mr.brutto_7),
            "Netto_19%_EUR": float(mr.netto_19),
            "Steuer_19%_EUR": float(mr.tax_19),
            "Brutto_19%_EUR": float(mr.brutto_19),
            "Netto_Gesamt_EUR": float(mr.netto_total),
            "Steuer_Gesamt_EUR": float(mr.tax_total),
            "Brutto_Gesamt_EUR": float(mr.brutto_total),
            "Vorsteuer_Abziehbar_EUR": float(report.input_tax_deductible),
            "USt_Zahllast_EUR": float(mr.tax_total - report.input_tax_deductible),
        })

    filepath = output_dir / f"UStVA_Jahresubersicht_{report.year}.xlsx"
    pd.DataFrame(rows).to_excel(filepath, index=False, engine="openpyxl")
    logger.info("年度税务汇总已导出: %s", filepath)
    return filepath


# ╔══════════════════════════════════════════════════════════════╗
# ║                   Builder                                   ║
# ╚══════════════════════════════════════════════════════════════╝

def build_report_from_zbons(
    zbon_results: List[Dict[str, Any]],
    year: int,
    input_tax_deductible: Decimal = Decimal("0"),
) -> UStVAReport:
    """
    从 Z-Bon 校验结果列表构建 UStVA 报告。

    参数
    ----
    zbon_results : list of dict
        每个 dict 来自 ZbonValidationResult 的序列化输出，
        需包含: receipt_date, netto_7, tax_7, brutto_7,
               netto_19, tax_19, brutto_19, receipt_number
    """
    report = UStVAReport(year=year, input_tax_deductible=input_tax_deductible)

    for zr in zbon_results:
        rec_date = zr.get("receipt_date")
        if isinstance(rec_date, str):
            rec_date = date.fromisoformat(rec_date)
        elif rec_date is None:
            rec_date = date.today()

        report.records.append(UStVARecord(
            date=rec_date,
            netto_7=Decimal(str(zr.get("netto_7", 0))),
            tax_7=Decimal(str(zr.get("tax_7", 0))),
            brutto_7=Decimal(str(zr.get("brutto_7", 0))),
            netto_19=Decimal(str(zr.get("netto_19", 0))),
            tax_19=Decimal(str(zr.get("tax_19", 0))),
            brutto_19=Decimal(str(zr.get("brutto_19", 0))),
            receipt_number=str(zr.get("receipt_number", "")),
        ))

    return report


# ╔══════════════════════════════════════════════════════════════╗
# ║                   Quick Test                                ║
# ╚══════════════════════════════════════════════════════════════╝

if __name__ == "__main__":
    # 模拟 2026 年 6 月 3 天 Z-Bon 数据
    demo_data = [
        {
            "receipt_date": "2026-06-01",
            "receipt_number": "ZB-001",
            "netto_7": "2800.00", "tax_7": "196.00", "brutto_7": "2996.00",
            "netto_19": "420.00", "tax_19": "79.80", "brutto_19": "499.80",
        },
        {
            "receipt_date": "2026-06-02",
            "receipt_number": "ZB-002",
            "netto_7": "3100.00", "tax_7": "217.00", "brutto_7": "3317.00",
            "netto_19": "380.00", "tax_19": "72.20", "brutto_19": "452.20",
        },
        {
            "receipt_date": "2026-06-03",
            "receipt_number": "ZB-003",
            "netto_7": "2900.00", "tax_7": "203.00", "brutto_7": "3103.00",
            "netto_19": "500.00", "tax_19": "95.00", "brutto_19": "595.00",
        },
    ]

    # 模拟从银行 CSV 中提取的可抵扣进项税
    input_tax = Decimal("420.00")

    report = build_report_from_zbons(demo_data, year=2026, input_tax_deductible=input_tax)

    print("=" * 60)
    print("Gastro Finance Agent — UStVA 报告 (Demo)")
    print("=" * 60)
    for m, mr in sorted(report.monthly_records.items()):
        print(f"\n📅 {m}")
        print(f"  食品 7% : Netto €{mr.netto_7:,.2f}  Steuer €{mr.tax_7:,.2f}  Brutto €{mr.brutto_7:,.2f}")
        print(f"  饮品 19%: Netto €{mr.netto_19:,.2f}  Steuer €{mr.tax_19:,.2f}  Brutto €{mr.brutto_19:,.2f}")
        print(f"  ─────────────────────────────────────")
        print(f"  合计    : Netto €{mr.netto_total:,.2f}  Steuer €{mr.tax_total:,.2f}  Brutto €{mr.brutto_total:,.2f}")
        print(f"  可抵扣进项税: €{input_tax:,.2f}")
        print(f"  应付增值税  : €{mr.tax_total - input_tax:,.2f}")

    export_ustva_csv(report)
    print(f"\n✅ CSV 已导出到 {DIR_OUTPUT}")
