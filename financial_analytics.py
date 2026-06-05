"""
financial_analytics.py — 德国餐饮财务分析引擎
==============================================
跨时间维度（日/周/月/年）的 GAAP 兼容财务计算。
支持 GmbH 和 Einzelunternehmen 两种企业形式。

税种覆盖:
  - Umsatzsteuer (USt): 食品 7% / 饮品 19%
  - Gewerbesteuer (GewSt): 3.5% × Hebesatz (默认 400%)
  - Körperschaftsteuer (KSt): 15% (仅 GmbH)
  - Solidaritätszuschlag (Soli): 5.5% × KSt (仅 GmbH)
  - Einkommensteuer (ESt): 累进税率 14-45% (仅 Einzelunternehmen)
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from config import (
    DIR_OUTPUT,
    TAX_RATE_SPEISEN,
    TAX_RATE_GETRAENKE,
    logger,
)


# ╔══════════════════════════════════════════════════════════╗
# ║                   Enums & Constants                     ║
# ╚══════════════════════════════════════════════════════════╝

class BusinessType(str, Enum):
    """企业形式"""
    GMBH = "gmbh"
    EINZELUNTERNEHMEN = "einzelunternehmen"

class TimePeriod(str, Enum):
    """时间维度"""
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    YEAR = "year"

# ── 税率常量 ─────────────────────────────────────────────
KST_RATE = Decimal("0.15")         # Körperschaftsteuer
SOLI_RATE = Decimal("0.055")       # Solidaritätszuschlag (auf KSt)
GEWST_MESSZAHL = Decimal("0.035")  # Gewerbesteuer-Messzahl
DEFAULT_HEBESATZ = Decimal("400")  # 默认 Hebesatz (400%)

# Einkommensteuer 累进税率 (2026 年德国)
EST_BRACKETS = [
    (Decimal("0"),       Decimal("11604"),  Decimal("0.00")),
    (Decimal("11605"),   Decimal("17005"),  Decimal("0.14")),
    (Decimal("17006"),   Decimal("66760"),  Decimal("0.24")),
    (Decimal("66761"),   Decimal("277825"), Decimal("0.42")),
    (Decimal("277826"),  None,             Decimal("0.45")),
]

# ── 典型成本结构（占营业额百分比，用于 demo 生成）─────────
TYPICAL_COST_STRUCTURE = {
    "wareneinsatz":   Decimal("0.28"),   # 食材成本
    "personal":       Decimal("0.32"),   # 人工成本
    "miete":          Decimal("0.08"),   # 租金
    "energie":        Decimal("0.04"),   # 能源
    "versicherung":   Decimal("0.02"),   # 保险
    "marketing":      Decimal("0.03"),   # 营销
    "sonstiges":      Decimal("0.05"),   # 其他
    # 合计 ~82% → 利润率 ~18%
}


# ╔══════════════════════════════════════════════════════════╗
# ║                   Data Models                            ║
# ╚══════════════════════════════════════════════════════════╝

@dataclass
class DailyFinancials:
    """单日财务数据"""
    datum: date
    brutto_7: Decimal = Decimal("0")      # 食品含税收入
    brutto_19: Decimal = Decimal("0")     # 饮品含税收入
    wareneinsatz: Decimal = Decimal("0")  # 食材成本
    personal: Decimal = Decimal("0")      # 人工
    miete: Decimal = Decimal("0")         # 租金
    energie: Decimal = Decimal("0")       # 能源
    versicherung: Decimal = Decimal("0")  # 保险
    marketing: Decimal = Decimal("0")     # 营销
    sonstiges: Decimal = Decimal("0")     # 其他成本

    @property
    def netto_7(self) -> Decimal:
        return (self.brutto_7 / (Decimal("1") + TAX_RATE_SPEISEN)).quantize(Decimal("0.01"))

    @property
    def netto_19(self) -> Decimal:
        return (self.brutto_19 / (Decimal("1") + TAX_RATE_GETRAENKE)).quantize(Decimal("0.01"))

    @property
    def ust_7(self) -> Decimal:
        return (self.brutto_7 - self.netto_7).quantize(Decimal("0.01"))

    @property
    def ust_19(self) -> Decimal:
        return (self.brutto_19 - self.netto_19).quantize(Decimal("0.01"))

    @property
    def brutto_total(self) -> Decimal:
        return self.brutto_7 + self.brutto_19

    @property
    def total_costs(self) -> Decimal:
        return (self.wareneinsatz + self.personal + self.miete
                + self.energie + self.versicherung + self.marketing + self.sonstiges)

    @property
    def ebitda(self) -> Decimal:
        """Earnings Before Interest, Taxes, Depreciation & Amortization"""
        return self.brutto_total - self.ust_7 - self.ust_19 - self.total_costs

    def to_dict(self) -> Dict[str, Any]:
        return {
            "datum": self.datum.isoformat(),
            "brutto_7": float(self.brutto_7), "brutto_19": float(self.brutto_19),
            "wareneinsatz": float(self.wareneinsatz), "personal": float(self.personal),
            "miete": float(self.miete), "energie": float(self.energie),
            "versicherung": float(self.versicherung), "marketing": float(self.marketing),
            "sonstiges": float(self.sonstiges),
            "netto_7": float(self.netto_7), "netto_19": float(self.netto_19),
            "ust_7": float(self.ust_7), "ust_19": float(self.ust_19),
            "brutto_total": float(self.brutto_total), "total_costs": float(self.total_costs),
            "ebitda": float(self.ebitda),
        }


@dataclass
class PeriodSummary:
    """某时间段的汇总数据"""
    period_label: str                           # "2026-06-05" / "KW23" / "2026-06" / "2026"
    days: int = 0
    brutto_7: Decimal = Decimal("0")
    brutto_19: Decimal = Decimal("0")
    netto_7: Decimal = Decimal("0")
    netto_19: Decimal = Decimal("0")
    ust_7: Decimal = Decimal("0")
    ust_19: Decimal = Decimal("0")
    wareneinsatz: Decimal = Decimal("0")
    personal: Decimal = Decimal("0")
    miete: Decimal = Decimal("0")
    energie: Decimal = Decimal("0")
    versicherung: Decimal = Decimal("0")
    marketing: Decimal = Decimal("0")
    sonstiges: Decimal = Decimal("0")

    @property
    def brutto_total(self) -> Decimal: return self.brutto_7 + self.brutto_19
    @property
    def total_costs(self) -> Decimal:
        return (self.wareneinsatz + self.personal + self.miete
                + self.energie + self.versicherung + self.marketing + self.sonstiges)
    @property
    def ebitda(self) -> Decimal: return self.brutto_total - self.ust_7 - self.ust_19 - self.total_costs
    @property
    def avg_daily_revenue(self) -> Decimal:
        return (self.brutto_total / self.days).quantize(Decimal("0.01")) if self.days > 0 else Decimal("0")
    @property
    def cost_ratio(self) -> float:
        return float(self.total_costs / self.brutto_total * 100) if self.brutto_total > 0 else 0.0
    @property
    def profit_margin(self) -> float:
        return float(self.ebitda / self.brutto_total * 100) if self.brutto_total > 0 else 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "period": self.period_label, "days": self.days,
            "brutto_total": float(self.brutto_total), "ebitda": float(self.ebitda),
            "total_costs": float(self.total_costs),
            "netto_7": float(self.netto_7), "netto_19": float(self.netto_19),
            "ust_7": float(self.ust_7), "ust_19": float(self.ust_19),
            "wareneinsatz": float(self.wareneinsatz), "personal": float(self.personal),
            "miete": float(self.miete), "energie": float(self.energie),
            "avg_daily": float(self.avg_daily_revenue),
            "cost_ratio": self.cost_ratio, "profit_margin": self.profit_margin,
        }


@dataclass
class TaxBreakdown:
    """税务明细"""
    business_type: BusinessType
    ebitda: Decimal
    # 共同税种
    gewerbesteuer: Decimal = Decimal("0")
    # GmbH 专属
    koerperschaftsteuer: Decimal = Decimal("0")
    soli: Decimal = Decimal("0")
    # Einzelunternehmen 专属
    einkommensteuer: Decimal = Decimal("0")
    # 汇总
    total_tax: Decimal = Decimal("0")
    net_profit: Decimal = Decimal("0")

    @property
    def tax_rate_effective(self) -> float:
        return float(self.total_tax / self.ebitda * 100) if self.ebitda > 0 else 0.0


@dataclass
class AIRecommendation:
    """AI 分析建议"""
    category: str          # "warning" | "positive" | "neutral" | "opportunity"
    title: str
    detail: str
    impact_eur: Optional[float] = None
    metric_change: Optional[str] = None


# ╔══════════════════════════════════════════════════════════╗
# ║                   Tax Calculators                        ║
# ╚══════════════════════════════════════════════════════════╝

def calc_gewerbesteuer(ebitda: Decimal, hebesatz: Decimal = DEFAULT_HEBESATZ) -> Decimal:
    """Gewerbesteuer = 3.5% × Hebesatz% × Gewerbeertrag"""
    messbetrag = (ebitda * GEWST_MESSZAHL).quantize(Decimal("0.01"))
    return (messbetrag * hebesatz / Decimal("100")).quantize(Decimal("0.01"))


def calc_einkommensteuer(zve: Decimal) -> Decimal:
    """德国累进 Einkommensteuer (2026)"""
    est = Decimal("0")
    remaining = zve
    for lower, upper, rate in EST_BRACKETS:
        if remaining <= Decimal("0"):
            break
        if upper is None:
            bracket_income = remaining
        else:
            bracket_income = min(remaining, upper - lower + Decimal("1"))
        est += (bracket_income * rate).quantize(Decimal("0.01"))
        remaining -= bracket_income
    return est.quantize(Decimal("0.01"))


def compute_taxes(ebitda: Decimal, business_type: BusinessType,
                  hebesatz: Decimal = DEFAULT_HEBESATZ) -> TaxBreakdown:
    """根据企业形式计算完整税务"""
    tb = TaxBreakdown(business_type=business_type, ebitda=ebitda)

    if ebitda <= Decimal("0"):
        return tb

    # 共同：Gewerbesteuer
    tb.gewerbesteuer = calc_gewerbesteuer(ebitda, hebesatz)

    if business_type == BusinessType.GMBH:
        # GmbH: KSt + Soli + GewSt
        gewinn_nach_gewst = ebitda - tb.gewerbesteuer
        tb.koerperschaftsteuer = (gewinn_nach_gewst * KST_RATE).quantize(Decimal("0.01"))
        tb.soli = (tb.koerperschaftsteuer * SOLI_RATE).quantize(Decimal("0.01"))
        tb.total_tax = tb.gewerbesteuer + tb.koerperschaftsteuer + tb.soli
    else:
        # Einzelunternehmen: ESt + GewSt (mit Anrechnung)
        tb.einkommensteuer = calc_einkommensteuer(ebitda)
        # 简单模型：GewSt 全额计入
        tb.total_tax = tb.einkommensteuer + tb.gewerbesteuer

    tb.net_profit = ebitda - tb.total_tax
    return tb


# ╔══════════════════════════════════════════════════════════╗
# ║                   Aggregation                           ║
# ╚══════════════════════════════════════════════════════════╝

def aggregate_by_period(daily_data: List[DailyFinancials],
                        period: TimePeriod) -> List[PeriodSummary]:
    """按时间维度聚合日数据"""
    if not daily_data:
        return []

    df = pd.DataFrame([d.to_dict() for d in daily_data])
    df["datum"] = pd.to_datetime(df["datum"])

    if period == TimePeriod.DAY:
        groups = df.groupby(df["datum"].dt.strftime("%Y-%m-%d"))
    elif period == TimePeriod.WEEK:
        groups = df.groupby(df["datum"].dt.strftime("%G-W%V"))
    elif period == TimePeriod.MONTH:
        groups = df.groupby(df["datum"].dt.strftime("%Y-%m"))
    else:
        groups = df.groupby(df["datum"].dt.strftime("%Y"))

    summaries = []
    for label, gdf in groups:
        s = PeriodSummary(period_label=label, days=len(gdf))
        for col in ["brutto_7", "brutto_19", "ust_7", "ust_19",
                     "wareneinsatz", "personal", "miete", "energie",
                     "versicherung", "marketing", "sonstiges"]:
            setattr(s, col, Decimal(str(round(gdf[col].sum(), 2))))
        s.netto_7 = Decimal(str(round(gdf["netto_7"].sum(), 2)))
        s.netto_19 = Decimal(str(round(gdf["netto_19"].sum(), 2)))
        summaries.append(s)

    return sorted(summaries, key=lambda x: x.period_label)


# ╔══════════════════════════════════════════════════════════╗
# ║                   AI Recommendation Engine              ║
# ╚══════════════════════════════════════════════════════════╝

def generate_recommendations(
    current: PeriodSummary,
    previous: Optional[PeriodSummary],
    business_type: BusinessType,
) -> List[AIRecommendation]:
    """基于财务数据生成 AI 建议"""
    recs: List[AIRecommendation] = []

    profit = current.profit_margin

    # ── 利润率分析 ──
    if profit < 5:
        recs.append(AIRecommendation(
            category="warning", title="⚠️ Kritische Gewinnmarge",
            detail=f"Die Nettomarge liegt bei nur {profit:.1f}%. "
                   f"Branchenstandard für Gastronomie ist 10-18%. "
                   f"Empfehlung: Speisekarte optimieren, Lieferantenpreise prüfen.",
            impact_eur=float(current.ebitda),
            metric_change=f"{profit:.1f}%"
        ))
    elif profit < 12:
        recs.append(AIRecommendation(
            category="neutral", title="📊 Durchschnittliche Marge",
            detail=f"Die Marge von {profit:.1f}% liegt im unteren Mittelfeld. "
                   f"Potenzial durch Reduktion der Wareneinsatzkosten oder Erhöhung "
                   f"der Getränkequote.",
        ))
    else:
        recs.append(AIRecommendation(
            category="positive", title="✅ Starke Gewinnmarge",
            detail=f"{profit:.1f}% Marge — über dem Branchenschnitt. "
                   f"Gut positioniert für Reinvestition oder Expansion."
        ))

    # ── 成本分析 ──
    if current.total_costs > 0:
        personal_pct = float(current.personal / current.brutto_total * 100)
        waren_pct = float(current.wareneinsatz / current.brutto_total * 100)

        if personal_pct > 35:
            recs.append(AIRecommendation(
                category="warning", title="👥 Hohe Personalkosten",
                detail=f"Personalkosten bei {personal_pct:.1f}% (Branchenziel: 28-32%). "
                       f"Optimierung von Schichtplänen oder Automatisierung prüfen.",
                impact_eur=float(current.personal),
            ))
        if waren_pct > 30:
            recs.append(AIRecommendation(
                category="warning", title="🥩 Hoher Wareneinsatz",
                detail=f"Wareneinsatz bei {waren_pct:.1f}%. Zielwert: 25-28%. "
                       f"Lieferanten vergleichen, Portionsgrößen standardisieren.",
                metric_change=f"{waren_pct:.1f}%"
            ))

    # ── 趋势分析 ──
    if previous and previous.brutto_total > 0:
        revenue_change = float((current.brutto_total - previous.brutto_total)
                               / previous.brutto_total * 100)
        if revenue_change > 10:
            recs.append(AIRecommendation(
                category="positive", title="📈 Starkes Umsatzwachstum",
                detail=f"Umsatz +{revenue_change:.1f}% gegenüber Vorperiode. "
                       f"Personal-RoI prüfen, ggf. Kapazitäten erweitern.",
                metric_change=f"+{revenue_change:.1f}%"
            ))
        elif revenue_change < -5:
            recs.append(AIRecommendation(
                category="warning", title="📉 Umsatzrückgang",
                detail=f"Umsatz {revenue_change:.1f}% unter Vorperiode. "
                       f"Aktionen/Marketing für Frequenzsteigerung prüfen.",
                metric_change=f"{revenue_change:.1f}%"
            ))

    # ── 税务建议 ──
    if business_type == BusinessType.EINZELUNTERNEHMEN:
        if current.ebitda > Decimal("60000"):
            recs.append(AIRecommendation(
                category="opportunity", title="🏢 GmbH-Gründung prüfen",
                detail=f"Bei diesem Gewinnniveau (€{float(current.ebitda):,.0f}) "
                       f"kann eine GmbH steuerliche Vorteile bieten. "
                       f"Effektive Steuerlast vergleichen lassen.",
                impact_eur=float(current.ebitda),
            ))

    # ── 现金流 ──
    ust_total = current.ust_7 + current.ust_19
    recs.append(AIRecommendation(
        category="neutral",
        title="🧾 Umsatzsteuer-Voranmeldung fällig",
        detail=f"Für den Zeitraum {current.period_label}: "
               f"€{float(ust_total):,.2f} USt an das Finanzamt abzuführen. "
               f"Frist: 10. des Folgemonats.",
        impact_eur=float(ust_total),
    ))

    return recs


# ╔══════════════════════════════════════════════════════════╗
# ║                   Demo Data Generator                   ║
# ╚══════════════════════════════════════════════════════════╝

def generate_demo_data(days: int = 365) -> List[DailyFinancials]:
    """
    生成逼真的德国餐厅全年日度财务数据。
    包含季节波动（夏季↑冬季↓）、周末效应、随机噪声。
    """
    random.seed(42)
    data: List[DailyFinancials] = []
    today = date.today()
    start = today - timedelta(days=days)

    for i in range(days):
        d = start + timedelta(days=i)
        month = d.month

        # 季节因子：5-9 月旺季，1-2 月淡季
        if 5 <= month <= 9:
            season = Decimal(str(random.uniform(1.1, 1.4)))
        elif month in (3, 4, 10):
            season = Decimal(str(random.uniform(0.9, 1.15)))
        elif month in (11, 12):
            season = Decimal(str(random.uniform(0.9, 1.25)))  # 圣诞季
        else:
            season = Decimal(str(random.uniform(0.7, 0.95)))

        # 周末效应
        is_weekend = d.weekday() >= 5
        weekend_factor = Decimal(str(random.uniform(1.3, 1.6))) if is_weekend else Decimal("1.0")

        base_daily = Decimal("2500")
        brutto_7 = (base_daily * Decimal("0.75") * season * weekend_factor
                    * Decimal(str(random.uniform(0.85, 1.15)))).quantize(Decimal("0.01"))
        brutto_19 = (base_daily * Decimal("0.25") * season * weekend_factor
                     * Decimal(str(random.uniform(0.85, 1.15)))).quantize(Decimal("0.01"))

        bt = brutto_7 + brutto_19
        df_day = DailyFinancials(
            datum=d,
            brutto_7=brutto_7,
            brutto_19=brutto_19,
            wareneinsatz=(bt * TYPICAL_COST_STRUCTURE["wareneinsatz"]
                          * Decimal(str(random.uniform(0.85, 1.15)))).quantize(Decimal("0.01")),
            personal=(bt * TYPICAL_COST_STRUCTURE["personal"]
                      * Decimal(str(random.uniform(0.9, 1.1)))).quantize(Decimal("0.01")),
            miete=(bt * TYPICAL_COST_STRUCTURE["miete"]).quantize(Decimal("0.01")),
            energie=(bt * TYPICAL_COST_STRUCTURE["energie"]
                     * Decimal(str(random.uniform(0.8, 1.2)))).quantize(Decimal("0.01")),
            versicherung=(bt * TYPICAL_COST_STRUCTURE["versicherung"]).quantize(Decimal("0.01")),
            marketing=(bt * TYPICAL_COST_STRUCTURE["marketing"]
                       * Decimal(str(random.uniform(0.5, 1.5)))).quantize(Decimal("0.01")),
            sonstiges=(bt * TYPICAL_COST_STRUCTURE["sonstiges"]
                       * Decimal(str(random.uniform(0.7, 1.3)))).quantize(Decimal("0.01")),
        )
        data.append(df_day)

    return data


def get_current_year_data(data: List[DailyFinancials],
                          year: Optional[int] = None) -> List[DailyFinancials]:
    """筛选指定年份数据"""
    y = year or date.today().year
    return [d for d in data if d.datum.year == y]


# ╔══════════════════════════════════════════════════════════╗
# ║                   Quick Test                             ║
# ╚══════════════════════════════════════════════════════════╝

if __name__ == "__main__":
    from pprint import pprint

    demo = generate_demo_data(365)
    print(f"Generated {len(demo)} daily records")
    print(f"First: {demo[0].to_dict()['datum']} brutto=€{demo[0].brutto_total:.2f}")
    print(f"Last:  {demo[-1].to_dict()['datum']} brutto=€{demo[-1].brutto_total:.2f}")

    # 月汇总
    monthly = aggregate_by_period(demo, TimePeriod.MONTH)
    latest = monthly[-1]
    print(f"\nLatest month: {latest.period_label}")
    print(f"  Revenue: €{latest.brutto_total:,.2f}")
    print(f"  Costs:   €{latest.total_costs:,.2f}")
    print(f"  EBITDA:  €{latest.ebitda:,.2f}")
    print(f"  Margin:  {latest.profit_margin:.1f}%")
    print(f"  Avg/day: €{latest.avg_daily_revenue:,.2f}")

    # 税务
    taxes_gmbh = compute_taxes(latest.ebitda, BusinessType.GMBH)
    taxes_einzel = compute_taxes(latest.ebitda, BusinessType.EINZELUNTERNEHMEN)
    print(f"\nTax comparison on €{latest.ebitda:,.2f} EBITDA:")
    print(f"  GmbH:    total tax €{taxes_gmbh.total_tax:,.2f} ({taxes_gmbh.tax_rate_effective:.1f}%)")
    print(f"  Einzel:  total tax €{taxes_einzel.total_tax:,.2f} ({taxes_einzel.tax_rate_effective:.1f}%)")

    # AI 建议
    prev = monthly[-2] if len(monthly) > 1 else None
    recs = generate_recommendations(latest, prev, BusinessType.GMBH)
    print(f"\nAI Recommendations ({len(recs)}):")
    for r in recs:
        print(f"  [{r.category}] {r.title}: {r.detail[:80]}...")
