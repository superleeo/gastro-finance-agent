"""
finanz_dashboard.py — 餐饮财务可视化与 AI 分析看板
==================================================
跨时间维度（日/周/月/年）的全面财务可视化。
支持 GmbH vs Einzelunternehmen 双模式对比。

集成到主 Dashboard 中作为 'Finanzanalyse' 页面。
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

import altair as alt
import pandas as pd
import streamlit as st

from config import (
    TAX_RATE_SPEISEN,
    TAX_RATE_GETRAENKE,
    restaurant as cfg,
    logger,
)
from financial_analytics import (
    AIRecommendation,
    BusinessType,
    DailyFinancials,
    PeriodSummary,
    TaxBreakdown,
    TimePeriod,
    aggregate_by_period,
    compute_taxes,
    generate_demo_data,
    generate_recommendations,
    get_current_year_data,
    DEFAULT_HEBESATZ,
)


# ╔══════════════════════════════════════════════════════════╗
# ║                   Session / Cache                        ║
# ╚══════════════════════════════════════════════════════════╝

@st.cache_data(ttl=3600)
def load_finance_data() -> List[DailyFinancials]:
    """加载财务数据（demo 模式）或返回空列表（生产模式）"""
    if cfg.demo_mode:
        return generate_demo_data(365)
    return []


# ╔══════════════════════════════════════════════════════════╗
# ║                   UI Components                          ║
# ╚══════════════════════════════════════════════════════════╝

# ── 颜色常量 ──────────────────────────────────────────────
C_GREEN  = "#003527"
C_BLUE   = "#1a73e8"
C_RED    = "#ba1a1a"
C_ORANGE = "#e8710a"
C_TEAL   = "#0cc8b3"
C_GRAY   = "#707974"
C_GOLD   = "#d4a853"
CHART_BG = "#f8f9ff"

FONT_SM = "11px"
FONT_MD = "14px"


def metric_card_html(value: str, label: str, delta: str = "",
                     color: str = C_GREEN, icon: str = "📊") -> str:
    """生成 KPI 卡片 HTML"""
    d_color = C_RED if delta.startswith("-") else C_GREEN if delta.startswith("+") else C_GRAY
    delta_html = f'<span style="color:{d_color};font-size:{FONT_SM};font-weight:700;">{delta}</span>' if delta else ""
    return f"""
    <div style="background:white;border:1px solid #bfc9c3;border-radius:12px;padding:16px 20px;text-align:center;">
        <div style="font-size:24px;margin-bottom:6px;">{icon}</div>
        <div style="font-size:{FONT_SM};color:{C_GRAY};text-transform:uppercase;font-weight:600;letter-spacing:0.03em;">{label}</div>
        <div style="font-size:22px;font-weight:800;color:{color};margin:4px 0;font-family:'JetBrains Mono',monospace;">{value}</div>
        {delta_html}
    </div>"""


def color_scale() -> alt.Scale:
    return alt.Scale(domain=["Umsatz", "Kosten", "EBITDA"],
                     range=[C_GREEN, C_RED, C_BLUE])


# ╔══════════════════════════════════════════════════════════╗
# ║                   Chart Builders                         ║
# ╚══════════════════════════════════════════════════════════╝

def build_revenue_composition_chart(summary: PeriodSummary) -> alt.Chart:
    """营业额构成：食品 7% vs 饮品 19%"""
    df = pd.DataFrame([
        {"Kategorie": f"Speisen (7% USt)", "Betrag": float(summary.brutto_7)},
        {"Kategorie": f"Getränke (19% USt)", "Betrag": float(summary.brutto_19)},
    ])
    base = alt.Chart(df).encode(
        theta=alt.Theta("Betrag:Q", stack=True),
        color=alt.Color("Kategorie:N", scale=alt.Scale(range=[C_GREEN, C_TEAL])),
        tooltip=["Kategorie:N", alt.Tooltip("Betrag:Q", format=",.2f")],
    )
    pie = base.mark_arc(outerRadius=90, innerRadius=50)
    text = base.mark_text(radius=115, size=11, fontWeight="bold").encode(text=alt.Text("Betrag:Q", format="€,.0f"))
    return (pie + text).properties(
        title=alt.TitleParams("Umsatz Zusammensetzung", fontSize=14, fontWeight="bold", color=C_GREEN),
        height=280, width=280,
    ).configure_view(strokeWidth=0)


def build_cost_breakdown_chart(summary: PeriodSummary) -> alt.Chart:
    """成本构成横向柱状图"""
    cats = [
        ("Wareneinsatz", float(summary.wareneinsatz)),
        ("Personal", float(summary.personal)),
        ("Miete", float(summary.miete)),
        ("Energie", float(summary.energie)),
        ("Versicherung", float(summary.versicherung)),
        ("Marketing", float(summary.marketing)),
        ("Sonstiges", float(summary.sonstiges)),
    ]
    df = pd.DataFrame(cats, columns=["Kategorie", "Betrag"])
    df["Prozent"] = (df["Betrag"] / float(summary.brutto_total) * 100).round(1)
    df = df.sort_values("Betrag")

    return alt.Chart(df).mark_bar(cornerRadius=4).encode(
        y=alt.Y("Kategorie:N", sort="-x", title=None, axis=alt.Axis(labelFontSize=11)),
        x=alt.X("Betrag:Q", title=None, axis=alt.Axis(format="€,.0f", labelFontSize=10)),
        color=alt.Color("Betrag:Q", scale=alt.Scale(scheme="greens"), legend=None),
        tooltip=[alt.Tooltip("Kategorie:N"), alt.Tooltip("Betrag:Q", format="€,.0f"),
                 alt.Tooltip("Prozent:Q", format=".1f", title="Anteil %")],
    ).properties(
        title=alt.TitleParams("Kostenstruktur", fontSize=14, fontWeight="bold", color=C_GREEN),
        height=260, width=350,
    ).configure_view(strokeWidth=0)


def build_trend_chart(summaries: List[PeriodSummary], metric: str = "brutto_total") -> alt.Chart:
    """趋势折线图"""
    df = pd.DataFrame([{
        "Periode": s.period_label,
        "Umsatz (€)": float(s.brutto_total),
        "Kosten (€)": float(s.total_costs),
        "EBITDA (€)": float(s.ebitda),
        "Personal (€)": float(s.personal),
        "Wareneinsatz (€)": float(s.wareneinsatz),
    } for s in summaries])

    base = alt.Chart(df).mark_line(point=alt.OverlayMarkDef(size=50, filled=True), strokeWidth=2.5).encode(
        x=alt.X("Periode:N", title=None, sort=None, axis=alt.Axes(labelAngle=-45, labelFontSize=10)),
        tooltip=[alt.Tooltip("Periode:N"), alt.Tooltip("Umsatz (€):Q", format="€,.0f"),
                 alt.Tooltip("Kosten (€):Q", format="€,.0f"), alt.Tooltip("EBITDA (€):Q", format="€,.0f")],
    )

    rev_line = base.encode(y=alt.Y("Umsatz (€):Q", title="EUR", axis=alt.Axes(format="€,.0f")),
                           color=alt.value(C_GREEN)).properties(height=280, width=650)

    cost_line = base.encode(y=alt.Y("Kosten (€):Q"), color=alt.value(C_RED))
    ebitda_line = base.encode(y=alt.Y("EBITDA (€):Q"), color=alt.value(C_BLUE))

    return (rev_line + cost_line + ebitda_line).properties(
        title=alt.TitleParams("Finanz-Trend", fontSize=14, fontWeight="bold", color=C_GREEN),
    ).configure_view(strokeWidth=0)


def build_tax_comparison_chart(ebitda: Decimal) -> alt.Chart:
    """GmbH vs Einzelunternehmen 税务对比"""
    tax_g = compute_taxes(ebitda, BusinessType.GMBH)
    tax_e = compute_taxes(ebitda, BusinessType.EINZELUNTERNEHMEN)

    rows = []
    for label, g_val, e_val in [
        ("Gewerbesteuer", float(tax_g.gewerbesteuer), float(tax_e.gewerbesteuer)),
        ("Körperschaftsteuer", float(tax_g.koerperschaftsteuer), 0),
        ("Soli", float(tax_g.soli), 0),
        ("Einkommensteuer", 0, float(tax_e.einkommensteuer)),
        ("Netto Gewinn", float(tax_g.net_profit), float(tax_e.net_profit)),
    ]:
        rows.append({"Steuerart": label, "GmbH (€)": g_val, "Einzelunternehmen (€)": e_val})

    df = pd.DataFrame(rows)
    df_melt = df.melt(id_vars=["Steuerart"], var_name="Rechtsform", value_name="Betrag")

    return alt.Chart(df_melt).mark_bar(cornerRadius=4).encode(
        x=alt.X("Betrag:Q", title="EUR", axis=alt.Axes(format="€,.0f")),
        y=alt.Y("Steuerart:N", title=None, sort=df["Steuerart"].tolist()),
        color=alt.Color("Rechtsform:N", scale=alt.Scale(range=[C_GREEN, C_GOLD])),
        row=alt.Row("Rechtsform:N", title=None, header=alt.Header(labelFontSize=12, labelFontWeight="bold")),
        tooltip=["Steuerart:N", alt.Tooltip("Betrag:Q", format="€,.2f")],
    ).properties(
        title=alt.TitleParams("Steuervergleich GmbH vs Einzelunternehmen", fontSize=14, fontWeight="bold"),
        height=200, width=500,
    ).configure_view(strokeWidth=0)


# ╔══════════════════════════════════════════════════════════╗
# ║                   Main Page                              ║
# ╚══════════════════════════════════════════════════════════╝

STYLE_COLORS = {
    "warning":     ("⚠️ ", C_RED, "#ffdad6"),
    "positive":    ("✅ ", C_GREEN, "#b0f0d6"),
    "neutral":     ("📊 ", C_GRAY, "#e5eeff"),
    "opportunity": ("💡 ", C_BLUE, "#d3e4fe"),
}


def page_finanzanalyse() -> None:
    """财务分析主页面"""
    data = load_finance_data()

    # ── 顶部控制栏 ──────────────────────────────────────────
    st.markdown("""
    <div style="display:flex;align-items:center;justify-content:space-between;
                padding:8px 0 16px 0;border-bottom:1px solid #bfc9c3;margin-bottom:20px;">
        <div style="font-size:24px;font-weight:700;color:#003527;">📊 Finanzanalyse</div>
    </div>
    """, unsafe_allow_html=True)

    ctrl1, ctrl2, ctrl3, ctrl4 = st.columns([2, 2, 2, 1])
    with ctrl1:
        period = st.selectbox("Zeitraum", ["Tag", "Woche", "Monat", "Jahr"],
                              index=2, key="fa_period",
                              format_func=lambda x: {"Tag": "📅 Heute",
                                                      "Woche": "📆 Diese Woche",
                                                      "Monat": "🗓 Dieser Monat",
                                                      "Jahr": "📅 Dieses Jahr"}[x])
    with ctrl2:
        year_choice = st.selectbox("Jahr", ["2026", "2025"],
                                   index=0, key="fa_year")
    with ctrl3:
        biz_type = st.radio("Rechtsform",
                            ["GmbH", "Einzelunternehmen"],
                            horizontal=True, key="fa_biz",
                            format_func=lambda x: f"🏢 {x}" if x == "GmbH" else f"👤 {x}")
    with ctrl4:
        st.markdown("<br>", unsafe_allow_html=True)
        use_demo = st.checkbox("Demo Daten", value=cfg.demo_mode, key="fa_demo",
                               help="Demo-Daten mit realistischen Werten")

    bt = BusinessType.GMBH if biz_type == "GmbH" else BusinessType.EINZELUNTERNEHMEN
    tp = {"Tag": TimePeriod.DAY, "Woche": TimePeriod.WEEK,
          "Monat": TimePeriod.MONTH, "Jahr": TimePeriod.YEAR}[period]

    if not data and not use_demo:
        st.warning("Keine Daten vorhanden. Bitte zuerst Z-Bons erfassen oder Demo-Modus aktivieren.")
        return

    if use_demo and not data:
        data = generate_demo_data(365)
    current_year = get_current_year_data(data, int(year_choice))
    summaries = aggregate_by_period(current_year, tp)

    if not summaries:
        st.error(f"Keine Daten für {year_choice}")
        return

    latest = summaries[-1]
    prev = summaries[-2] if len(summaries) > 1 else None

    # ── KPI 卡片行 ──────────────────────────────────────────
    ue7 = float(latest.brutto_7)
    ue19 = float(latest.brutto_19)
    ue_total = float(latest.brutto_total)
    costs = float(latest.total_costs)
    ebitda_val = float(latest.ebitda)
    margin = latest.profit_margin
    taxes = compute_taxes(latest.ebitda, bt)

    rev_delta = ""
    cost_delta = ""
    margin_delta = ""
    if prev:
        rev_chg = (ue_total - float(prev.brutto_total)) / float(prev.brutto_total) * 100 if prev.brutto_total > 0 else 0
        cost_chg = (costs - float(prev.total_costs)) / float(prev.total_costs) * 100 if prev.total_costs > 0 else 0
        margin_chg = margin - prev.profit_margin
        rev_delta = f"{'+' if rev_chg >= 0 else ''}{rev_chg:.1f}%"
        cost_delta = f"{'+' if cost_chg >= 0 else ''}{cost_chg:.1f}%"
        margin_delta = f"{'+' if margin_chg >= 0 else ''}{margin_chg:.1f}pp"

    mc1, mc2, mc3, mc4, mc5 = st.columns(5)
    with mc1:
        st.markdown(metric_card_html(f"€{ue_total:,.0f}", "Umsatz (brutto)", rev_delta, C_GREEN, "💰"), unsafe_allow_html=True)
    with mc2:
        st.markdown(metric_card_html(f"€{costs:,.0f}", "Gesamtkosten", cost_delta, C_RED if cost_delta.startswith("+") else C_GRAY, "📉"), unsafe_allow_html=True)
    with mc3:
        st.markdown(metric_card_html(f"€{ebitda_val:,.0f}", "EBITDA", margin_delta, C_BLUE, "📈"), unsafe_allow_html=True)
    with mc4:
        st.markdown(metric_card_html(f"{margin:.1f}%", "Gewinnmarge", margin_delta, C_GREEN if margin > 10 else C_ORANGE, "🎯"), unsafe_allow_html=True)
    with mc5:
        tax_eff = taxes.tax_rate_effective
        st.markdown(metric_card_html(f"€{float(taxes.total_tax):,.0f}", f"Steuer ({tax_eff:.0f}%)",
                                     "", C_RED if tax_eff > 30 else C_GRAY, "🧾"), unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── 图表区域 ────────────────────────────────────────────
    chart_col1, chart_col2 = st.columns([1, 1])
    with chart_col1:
        rev_chart = build_revenue_composition_chart(latest)
        st.altair_chart(rev_chart, use_container_width=True)
    with chart_col2:
        cost_chart = build_cost_breakdown_chart(latest)
        st.altair_chart(cost_chart, use_container_width=True)

    # ── 趋势图 ──────────────────────────────────────────────
    st.markdown("<br>", unsafe_allow_html=True)
    if len(summaries) > 1:
        trend_chart = build_trend_chart(summaries)
        st.altair_chart(trend_chart, use_container_width=True)

    # ── 详细数据表 ──────────────────────────────────────────
    st.markdown("<br>", unsafe_allow_html=True)
    with st.expander("📋 Detaildaten (Tabelle)", expanded=False):
        df_table = pd.DataFrame([{
            "Periode": s.period_label, "Tage": s.days,
            "Umsatz €": f"{float(s.brutto_total):,.0f}",
            "Kosten €": f"{float(s.total_costs):,.0f}",
            "EBITDA €": f"{float(s.ebitda):,.0f}",
            "Marge %": f"{s.profit_margin:.1f}",
            "∅/Tag €": f"{float(s.avg_daily_revenue):,.0f}",
            "Personal %": f"{float(s.personal/s.brutto_total*100):.0f}" if s.brutto_total > 0 else "0",
            "Ware %": f"{float(s.wareneinsatz/s.brutto_total*100):.0f}" if s.brutto_total > 0 else "0",
        } for s in summaries])
        st.dataframe(df_table, use_container_width=True, hide_index=True)

    # ── 税务面板 ────────────────────────────────────────────
    st.markdown("<br>", unsafe_allow_html=True)
    tax_col1, tax_col2 = st.columns([3, 2])
    with tax_col1:
        tax_chart = build_tax_comparison_chart(latest.ebitda)
        st.altair_chart(tax_chart, use_container_width=True)
    with tax_col2:
        st.markdown(f"""
        <div style="border:1px solid #bfc9c3;border-radius:12px;padding:20px;background:white;">
            <h4 style="font-size:14px;font-weight:700;color:{C_GREEN};margin:0 0 12px 0;">🧾 Steuerdetails — {biz_type}</h4>
            <table style="width:100%;font-size:13px;border-collapse:collapse;">
                <tr><td style="padding:6px 0;color:{C_GRAY};">Gewerbesteuer</td><td style="text-align:right;font-family:monospace;">€{float(taxes.gewerbesteuer):,.2f}</td></tr>
                {f'<tr><td style="padding:6px 0;color:{C_GRAY};">Körperschaftsteuer (15%)</td><td style="text-align:right;font-family:monospace;">€{float(taxes.koerperschaftsteuer):,.2f}</td></tr><tr><td style="padding:6px 0;color:{C_GRAY};">Soli (5.5%)</td><td style="text-align:right;font-family:monospace;">€{float(taxes.soli):,.2f}</td></tr>' if bt == BusinessType.GMBH else f'<tr><td style="padding:6px 0;color:{C_GRAY};">Einkommensteuer (prog.)</td><td style="text-align:right;font-family:monospace;">€{float(taxes.einkommensteuer):,.2f}</td></tr>'}
                <tr style="border-top:2px solid #bfc9c3;"><td style="padding:8px 0;font-weight:700;">Gesamtsteuer</td><td style="text-align:right;font-family:monospace;font-weight:700;color:{C_RED};">€{float(taxes.total_tax):,.2f}</td></tr>
                <tr><td style="padding:4px 0;font-weight:700;color:{C_GREEN};">Netto Gewinn</td><td style="text-align:right;font-family:monospace;font-weight:700;color:{C_GREEN};">€{float(taxes.net_profit):,.2f}</td></tr>
            </table>
            <p style="font-size:10px;color:{C_GRAY};margin-top:8px;">Effektive Steuerlast: {tax_eff:.1f}% | Hebesatz: {float(DEFAULT_HEBESATZ):.0f}%</p>
        </div>
        """, unsafe_allow_html=True)

    # ── AI 建议面板 ─────────────────────────────────────────
    st.markdown("<br>", unsafe_allow_html=True)
    st.subheader("🤖 KI-Empfehlungen")

    recs = generate_recommendations(latest, prev, bt)
    for r in recs:
        icon, color, bg = STYLE_COLORS.get(r.category, ("📊", C_GRAY, "#e5eeff"))
        impact_str = f" — €{r.impact_eur:,.0f}" if r.impact_eur else ""
        metric_str = f" ({r.metric_change})" if r.metric_change else ""

        st.markdown(f"""
        <div style="border-left:4px solid {color};background:{bg};padding:12px 16px;
                    border-radius:0 8px 8px 0;margin-bottom:8px;">
            <div style="display:flex;align-items:center;gap:8px;">
                <span style="font-size:16px;">{icon}</span>
                <span style="font-weight:700;font-size:14px;color:{color};">{r.title}{metric_str}</span>
            </div>
            <p style="margin:4px 0 0 28px;font-size:12px;color:#404944;">{r.detail}{impact_str}</p>
        </div>
        """, unsafe_allow_html=True)


# ╔══════════════════════════════════════════════════════════╗
# ║                   Quick Test                             ║
# ╚══════════════════════════════════════════════════════════╝

if __name__ == "__main__":
    print("Finanzanalyse page — import this from dashboard.py")
    print("Run: streamlit run dashboard.py → select 'Finanzanalyse' in sidebar")
