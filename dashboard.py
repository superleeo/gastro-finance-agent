"""
dashboard.py — Gastro Finance Agent · 德国餐饮财务看板
========================================================
Material Design 3 风格，6 页导航，全中文界面。
通过环境变量配置餐厅品牌，适用于德国任意餐厅。

启动: streamlit run dashboard.py
配置: GASTRO_RESTAURANT_NAME="我的餐厅" GASTRO_DEMO_MODE=1 streamlit run dashboard.py
"""

from __future__ import annotations

import io
import os
import sys
import tempfile
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import (
    DIR_INPUT_BANK, DIR_EMAIL_DRAFTS, DIR_OUTPUT,
    TAX_RATE_SPEISEN, TAX_RATE_GETRAENKE,
    restaurant as cfg, logger,
)
from finanz_dashboard import page_finanzanalyse
from reconciliation import (
    BankTransaction, InvoiceRecord, MissingInvoice, ReconciliationReport,
    parse_bank_csv, filter_expenses, fuzzy_match_invoices,
    generate_reminder_emails, run_reconciliation, _get_mock_invoices,
)

# ══════════════════════════════════════════ 主题 ══════════════════════════════════════════

PRIMARY         = "#003527"
PRIMARY_CONTAINER = "#064e3b"
PRIMARY_FIXED   = "#b0f0d6"
ON_PRIMARY      = "#ffffff"
ON_PRIMARY_CONTAINER = "#80bea6"
SURFACE         = "#f8f9ff"
SURFACE_BRIGHT  = "#f8f9ff"
SURFACE_CONTAINER_LOWEST = "#ffffff"
SURFACE_CONTAINER_LOW = "#eff4ff"
SURFACE_CONTAINER = "#e5eeff"
SURFACE_CONTAINER_HIGH = "#dce9ff"
ON_SURFACE       = "#0b1c30"
ON_SURFACE_VARIANT = "#404944"
OUTLINE_VARIANT  = "#bfc9c3"
OUTLINE          = "#707974"
ERROR            = "#ba1a1a"
ERROR_CONTAINER  = "#ffdad6"
ON_ERROR_CONTAINER = "#93000a"
TERTIARY         = "#00352f"
TERTIARY_CONTAINER = "#004e45"
ON_TERTIARY_CONTAINER = "#0cc8b3"
TERTIARY_FIXED   = "#62fae3"
SECONDARY_CONTAINER = "#dae2fd"
ON_SECONDARY_CONTAINER = "#5c647a"
FONT_FAMILY  = '"Inter", "SF Pro Display", system-ui, -apple-system, sans-serif'
FONT_MONO    = '"JetBrains Mono", "SF Mono", "Cascadia Code", monospace'


def inject_m3_theme() -> None:
    st.markdown(f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&family=JetBrains+Mono:wght@500&display=swap');
    html, body, [class*="css"] {{ font-family: {FONT_FAMILY} !important; }}
    .stApp {{ background-color: {SURFACE}; }}
    .stApp > header {{ background-color: transparent !important; }}
    section[data-testid="stSidebar"] {{ background-color: {SURFACE} !important; border-right: 1px solid {OUTLINE_VARIANT} !important; }}
    section[data-testid="stSidebar"] * {{ font-family: {FONT_FAMILY} !important; }}
    .main .block-container {{ padding-top: 1.5rem; padding-left: 2rem; padding-right: 2rem; max-width: 1400px; }}
    .brand-title {{ font-family: {FONT_FAMILY}; font-size: 18px; font-weight: 800; color: {PRIMARY}; letter-spacing: -0.01em; line-height: 1.1; }}
    .brand-subtitle {{ font-family: {FONT_FAMILY}; font-size: 10px; font-weight: 600; color: {ON_SURFACE_VARIANT}; text-transform: uppercase; letter-spacing: 0.08em; }}
    .page-headline {{ font-family: {FONT_FAMILY}; font-size: 24px; font-weight: 700; color: {PRIMARY}; letter-spacing: -0.01em; }}
    .glass-card {{ background: rgba(255,255,255,0.8); backdrop-filter: blur(8px); -webkit-backdrop-filter: blur(8px); border: 1px solid rgba(191,201,195,0.6); border-radius: 12px; padding: 20px; }}
    .metric-card {{ background: {SURFACE_CONTAINER_LOWEST}; border: 1px solid {OUTLINE_VARIANT}; border-radius: 12px; padding: 20px 24px; transition: box-shadow 0.2s; }}
    .metric-card:hover {{ box-shadow: 0 2px 12px rgba(0,0,0,0.06); }}
    .metric-card .metric-label {{ font-family: {FONT_FAMILY}; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em; color: {ON_SURFACE_VARIANT}; }}
    .metric-card .metric-value {{ font-family: {FONT_FAMILY}; font-size: 28px; font-weight: 800; letter-spacing: -0.02em; color: {ON_SURFACE}; margin-top: 2px; }}
    .metric-card .metric-delta {{ font-size: 10px; font-weight: 700; padding: 2px 8px; border-radius: 9999px; display: inline-block; }}
    .icon-primary {{ background: {PRIMARY_FIXED}; color: {PRIMARY}; }}
    .icon-tertiary {{ background: #c8f5ed; color: {TERTIARY}; }}
    .icon-error {{ background: {ERROR_CONTAINER}; color: {ERROR}; }}
    .chip-primary {{ background: {PRIMARY_FIXED}; color: {PRIMARY}; }}
    .chip-tertiary {{ background: {TERTIARY_CONTAINER}; color: {ON_TERTIARY_CONTAINER}; }}
    .chip-error {{ background: {ERROR_CONTAINER}; color: {ON_ERROR_CONTAINER}; }}
    .ai-status-bar {{ background: {PRIMARY}; color: {ON_PRIMARY}; border-radius: 12px; padding: 16px 24px; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 16px; position: relative; overflow: hidden; margin: 0 0 24px 0; }}
    .ai-status-bar::after {{ content: ""; position: absolute; inset: 0; opacity: 0.08; background-image: radial-gradient(circle at 2px 2px, white 1px, transparent 0); background-size: 22px 22px; pointer-events: none; }}
    .ai-status-bar .ai-label {{ font-size: 10px; font-weight: 700; color: {ON_PRIMARY_CONTAINER}; text-transform: uppercase; letter-spacing: 0.05em; }}
    .ai-status-bar .ai-task {{ font-family: {FONT_MONO}; font-size: 14px; color: {ON_PRIMARY}; }}
    .ai-status-bar .ai-highlight {{ color: {ON_TERTIARY_CONTAINER}; font-weight: 600; }}
    .progress-track {{ width: 120px; height: 6px; background: rgba(255,255,255,0.2); border-radius: 9999px; overflow: hidden; }}
    .progress-fill {{ height: 100%; background: {ON_TERTIARY_CONTAINER}; border-radius: 9999px; transition: width 0.6s ease; }}
    .badge {{ display: inline-flex; align-items: center; gap: 4px; padding: 3px 10px; border-radius: 9999px; font-size: 10px; font-weight: 700; }}
    .badge-auto     {{ background: {PRIMARY_FIXED}22; color: {PRIMARY}; border: 1px solid {PRIMARY_FIXED}; }}
    .badge-warn     {{ background: #fff3cd; color: #856404; border: 1px solid #ffc107; }}
    .badge-flagged  {{ background: {ERROR_CONTAINER}; color: {ON_ERROR_CONTAINER}; border: 1px solid {ERROR}33; }}
    .stDataFrame {{ font-family: {FONT_MONO} !important; font-size: 13px; }}
    div[data-testid="stDataFrame"] th {{ background: {SURFACE_CONTAINER_LOW} !important; color: {OUTLINE} !important; font-size: 10px !important; font-weight: 700 !important; text-transform: uppercase !important; letter-spacing: 0.06em !important; padding: 12px 16px !important; border-bottom: 1px solid {OUTLINE_VARIANT} !important; }}
    div[data-testid="stDataFrame"] td {{ padding: 10px 16px !important; border-bottom: 1px solid rgba(191,201,195,0.3) !important; }}
    .quick-btn {{ width: 100%; padding: 12px 16px; border: 1px solid {OUTLINE_VARIANT}; border-radius: 8px; background: {SURFACE_CONTAINER_LOWEST}; font-family: {FONT_FAMILY}; font-size: 13px; font-weight: 600; color: {ON_SURFACE}; cursor: pointer; display: flex; align-items: center; justify-content: space-between; transition: background 0.15s; }}
    .quick-btn:hover {{ background: {SURFACE_CONTAINER_LOW}; }}
    .ai-insight {{ background: {PRIMARY}; color: {ON_PRIMARY}; border-radius: 12px; padding: 20px; position: relative; overflow: hidden; }}
    .ai-insight::after {{ content: ""; position: absolute; inset: 0; opacity: 0.1; background-image: radial-gradient(circle at 2px 2px, white 1px, transparent 0); background-size: 16px 16px; pointer-events: none; }}
    .filter-bar {{ background: {SURFACE_CONTAINER_LOWEST}; border: 1px solid {OUTLINE_VARIANT}; border-radius: 12px; padding: 16px 20px; display: flex; flex-wrap: wrap; align-items: center; gap: 16px; }}
    .filter-label {{ font-size: 10px; font-weight: 700; color: {OUTLINE}; text-transform: uppercase; letter-spacing: 0.06em; }}
    .table-footer-stats {{ display: flex; align-items: center; gap: 24px; padding: 12px 20px; background: {SURFACE_CONTAINER}; border-top: 2px solid {PRIMARY}; }}
    .footer-stat-label {{ font-size: 10px; font-weight: 700; color: {ON_SURFACE_VARIANT}; text-transform: uppercase; letter-spacing: 0.04em; }}
    .footer-stat-value {{ font-family: {FONT_MONO}; font-size: 14px; font-weight: 700; color: {ON_SURFACE}; }}
    @keyframes osaka-pulse {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: 0.5; }} }}
    .ai-pulse {{ animation: osaka-pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite; }}
    </style>
    """, unsafe_allow_html=True)


# ══════════════════════════════════════════ Session ═══════════════════════════════════════

def init_session() -> None:
    demo = cfg.demo_mode
    defaults: Dict[str, Any] = {
        "page": "概览",
        "bank_transactions": [],
        "invoices": _get_mock_invoices() if demo else [],
        "missing_invoices": [],
        "report": None,
        "emails_generated": False,
        "demo_mode": demo,
        "pipeline_progress": 72 if demo else 0,
        "pipeline_task": "正在解析银行对账单: Demo_2026_06.csv" if demo else "空闲",
        "pos_total": 0.0, "bank_total": 0.0, "diff_total": 0.0,
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


# ══════════════════════════════════════════ 工具函数 ═══════════════════════════════════════

_DANGEROUS_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n")

def _sanitize_excel_value(val: Any) -> Any:
    if isinstance(val, str) and val.startswith(_DANGEROUS_PREFIXES):
        return "'" + val
    return val

def fmt_eur(val: float) -> str:
    return f"€{val:,.2f}"

def metric_card(value: str, label: str, icon: str = "📊",
                icon_class: str = "icon-primary", delta_text: Optional[str] = None,
                delta_class: str = "chip-primary", accent_bottom: bool = False) -> None:
    accent = ""
    if accent_bottom:
        accent = f'<div style="position:absolute;bottom:0;left:0;width:100%;height:3px;background:{PRIMARY};border-radius:0 0 12px 12px;"></div>'
    delta = f'<span class="metric-delta {delta_class}">{delta_text}</span>' if delta_text else ""
    st.markdown(f"""
    <div class="metric-card" style="position:relative;overflow:hidden;">
        <div class="icon-box {icon_class}" style="width:40px;height:40px;border-radius:8px;display:flex;align-items:center;justify-content:center;margin-bottom:12px;">{icon}</div>
        <div class="metric-label">{label}</div>
        <div class="metric-value">{value}</div>
        {delta}{accent}
    </div>
    """, unsafe_allow_html=True)


# ══════════════════════════════════════════ 侧边栏 ═════════════════════════════════════════

def render_sidebar() -> None:
    pages = [
        ("概览", "📊"), ("财务分析", "📈"),
        ("智能对账", "💳"), ("供应商", "🏪"),
        ("任务日志", "🖥"), ("报表", "📑"),
    ]
    active_page = st.session_state.get("page", "概览")

    st.markdown(
        f'<div style="display:flex;align-items:center;gap:12px;margin-bottom:28px;padding:0 8px;">'
        f'<span style="font-size:36px;">🍽️</span>'
        f'<div>'
        f'<div class="brand-title">{cfg.name}</div>'
        f'<div class="brand-subtitle">AI 智能财务管家</div>'
        f'</div></div>',
        unsafe_allow_html=True,
    )
    st.markdown("---")

    for label, icon in pages:
        is_active = label == active_page
        if is_active:
            st.button(f"{icon}  {label}", key=f"nav_{label}", use_container_width=True, type="primary")
        else:
            if st.button(f"{icon}  {label}", key=f"nav_{label}", use_container_width=True):
                st.session_state.page = label
                st.rerun()

    st.markdown("---")
    st.button("⚡ 执行自动平账", type="primary", use_container_width=True)
    st.button("⚙ 设置", use_container_width=True)
    st.button("❓ 帮助中心", use_container_width=True)

    st.markdown(
        f'<div style="margin-top:16px;font-size:10px;color:{OUTLINE};text-align:center;">'
        f'© 2026 Gastro Finance Agent<br>'
        f'<a href="mailto:{cfg.email}" style="color:{OUTLINE};">{cfg.email}</a>'
        f'</div>',
        unsafe_allow_html=True,
    )


# ══════════════════════════════════════════ 页头 ═══════════════════════════════════════════

def render_header() -> None:
    active_page = st.session_state.get("page", "概览")
    titles = {
        "概览": "📊 财务总览", "财务分析": "📈 财务分析与预测",
        "智能对账": "💳 智能对账中心", "供应商": "🏪 供应商管理",
        "任务日志": "🖥 AI 任务日志", "报表": "📑 报表与导出",
    }
    title = titles.get(active_page, active_page)
    st.markdown(
        f'<div style="display:flex;align-items:center;justify-content:space-between;'
        f'padding:8px 0 16px 0;border-bottom:1px solid {OUTLINE_VARIANT};margin-bottom:20px;">'
        f'<div class="page-headline">{title}</div>'
        f'<div style="display:flex;align-items:center;gap:12px;">'
        f'<span style="display:flex;align-items:center;gap:6px;'
        f'background:{SURFACE_CONTAINER_HIGH};padding:4px 12px;border-radius:9999px;font-size:11px;font-weight:700;">'
        f'<span class="ai-pulse" style="width:8px;height:8px;border-radius:50%;background:{ON_TERTIARY_CONTAINER};"></span>'
        f'<span style="color:{TERTIARY};letter-spacing:0.05em;">AI 在线</span></span>'
        f'</div></div>',
        unsafe_allow_html=True,
    )


def render_ai_banner() -> None:
    task = st.session_state.get("pipeline_task", "空闲")
    progress = st.session_state.get("pipeline_progress", 0)
    if progress == 0:
        return
    st.markdown(f"""
    <div class="ai-status-bar">
        <div style="display:flex;align-items:center;gap:16px;z-index:1;">
            <div style="width:44px;height:44px;background:rgba(255,255,255,0.08);border-radius:10px;display:flex;align-items:center;justify-content:center;">
                <span class="ai-pulse" style="font-size:22px;color:{ON_TERTIARY_CONTAINER};">🖥</span>
            </div>
            <div><p class="ai-label">当前自动化任务</p><p class="ai-task">{task}</p></div>
        </div>
        <div style="display:flex;align-items:center;gap:20px;z-index:1;">
            <div style="text-align:right;">
                <p style="font-size:10px;font-weight:700;opacity:0.6;text-transform:uppercase;letter-spacing:0.04em;margin:0;">处理进度</p>
                <div class="progress-track" style="margin-top:4px;"><div class="progress-fill" style="width:{progress}%;"></div></div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)


# ══════════════════════════════════════════ 页面：概览 ═════════════════════════════════════

def page_overview() -> None:
    render_header()
    render_ai_banner()

    c1, c2, c3, c4 = st.columns(4)
    missing_count = len(st.session_state.missing_invoices)
    if st.session_state.report:
        missing_count = st.session_state.report.missing_count

    with c1:
        metric_card(value="12,482" if st.session_state.demo_mode else "—",
                    label="累计自动对账", icon="🔄", icon_class="icon-primary",
                    delta_text="较上周 +12%" if st.session_state.demo_mode else None, delta_class="chip-primary")
    with c2:
        metric_card(value="99.8%" if st.session_state.demo_mode else "—",
                    label="AI 准确率", icon="✅", icon_class="icon-tertiary",
                    delta_text="运行稳定" if st.session_state.demo_mode else None, delta_class="chip-tertiary")
    with c3:
        metric_card(value=f"{missing_count:02d}", label="待处理异常", icon="⚠", icon_class="icon-error",
                    delta_text="需要处理" if missing_count > 0 else "一切正常", delta_class="chip-error")
    with c4:
        metric_card(value="€412.5k" if st.session_state.demo_mode else "—",
                    label="预计月现金流", icon="📈", icon_class="icon-primary",
                    delta_text="预估值" if st.session_state.demo_mode else None,
                    delta_class="chip-primary", accent_bottom=True)

    st.markdown("<br>", unsafe_allow_html=True)
    col_left, col_right = st.columns([2, 1])

    with col_left:
        st.markdown(f"""
        <div class="glass-card" style="height:100%;">
            <div style="display:flex;justify-content:space-between;align-items:start;margin-bottom:20px;">
                <div>
                    <h2 style="font-size:18px;font-weight:700;color:{PRIMARY};margin:0;">📊 财务健康度</h2>
                    <p style="font-size:12px;color:{ON_SURFACE_VARIANT};margin:4px 0 0 0;">AI 验证 vs 手动 POS 数据（最近 30 天）</p>
                </div>
                <div style="display:flex;gap:8px;">
                    <span style="font-size:11px;font-weight:600;padding:6px 12px;border:1px solid {OUTLINE_VARIANT};border-radius:8px;cursor:pointer;">导出 CSV</span>
                    <span style="font-size:11px;font-weight:600;padding:6px 12px;background:{PRIMARY};color:{ON_PRIMARY};border-radius:8px;cursor:pointer;">执行预测</span>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        weekdays = ["一", "二", "三", "四", "五", "六", "日"]
        pos_vals = [60, 75, 65, 85, 90, 70, 95]
        ai_vals = [40, 55, 45, 65, 70, 50, 75]
        chart = f'<div style="display:flex;align-items:end;justify-content:space-between;height:180px;padding:0 8px;gap:6px;">'
        for i in range(7):
            chart += f'<div style="flex:1;display:flex;flex-direction:column;gap:3px;">'
            chart += f'<div style="width:100%;background:rgba(0,53,39,0.2);border-radius:4px 4px 0 0;height:{pos_vals[i]}%;"></div>'
            chart += f'<div style="width:100%;background:{PRIMARY};border-radius:4px 4px 0 0;height:{ai_vals[i]}%;"></div></div>'
        chart += '</div>'
        chart += f'<div style="display:flex;justify-content:space-between;padding:8px 8px 0 8px;font-size:10px;font-weight:700;color:{ON_SURFACE_VARIANT};text-transform:uppercase;letter-spacing:0.04em;border-top:1px solid {OUTLINE_VARIANT};margin-top:12px;">'
        chart += "".join(f"<span>周{d}</span>" for d in weekdays) + "</div>"
        chart += f'<div style="display:flex;gap:24px;margin-top:8px;font-size:11px;"><span style="display:flex;align-items:center;gap:6px;"><span style="width:12px;height:12px;background:{PRIMARY};border-radius:2px;"></span> AI 验证</span><span style="display:flex;align-items:center;gap:6px;"><span style="width:12px;height:12px;background:rgba(0,53,39,0.2);border-radius:2px;"></span> POS 原始</span></div>'
        st.markdown(chart, unsafe_allow_html=True)

    with col_right:
        anomalies = [
            ("GFS 食品批发", "INV-99021", "€1,240.00", "error", "发票缺失"),
            ("UberEats 结算", "STRIPE_882", "€892.15", "warn", "商户ID不匹配"),
            ("Sysco Metro", "CREDIT_MEMO", "€45.00", "error", "发票缺失"),
            ("收银终端", "SHIFT_END_B", "€12.50", "warn", "四舍五入误差"),
        ]
        rows_html = ""
        for name, ref, amt, kind, reason in anomalies:
            cls = "badge-error" if kind == "error" else "badge-warn"
            rows_html += f'<tr style="border-bottom:1px solid rgba(191,201,195,0.3);"><td style="padding:10px 12px;"><span style="font-weight:600;font-size:13px;">{name}</span><br><span style="font-size:10px;color:{ON_SURFACE_VARIANT};">{ref}</span></td><td style="padding:10px 12px;font-family:{FONT_MONO};font-size:13px;">{amt}</td><td style="padding:10px 12px;"><span class="badge {cls}">{reason}</span></td></tr>'
        st.markdown(f"""
        <div class="glass-card" style="height:100%;display:flex;flex-direction:column;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
                <div><h2 style="font-size:18px;font-weight:700;color:{PRIMARY};margin:0;">🚨 高优先级</h2><p style="font-size:12px;color:{ON_SURFACE_VARIANT};margin:2px 0 0 0;">待处理 (04)</p></div>
            </div>
            <table style="width:100%;border-collapse:collapse;font-size:12px;">
                <thead><tr style="background:{SURFACE_CONTAINER_LOW};font-size:10px;font-weight:700;text-transform:uppercase;color:{OUTLINE};"><th style="padding:10px 12px;text-align:left;">实体</th><th style="padding:10px 12px;text-align:left;">金额</th><th style="padding:10px 12px;text-align:left;">原因</th></tr></thead>
                <tbody>{rows_html}</tbody>
            </table>
            <div style="margin-top:auto;padding-top:12px;border-top:1px solid {OUTLINE_VARIANT};"><span style="font-size:12px;font-weight:600;color:{PRIMARY};cursor:pointer;">查看所有处理操作 →</span></div>
        </div>
        """, unsafe_allow_html=True)


# ══════════════════════════════════════════ 页面：智能对账 ═════════════════════════════════

def page_reconciliation() -> None:
    render_header()

    with st.container():
        st.markdown(f'<div class="filter-bar">', unsafe_allow_html=True)
        fc1, fc2, fc3, fc4 = st.columns([2, 1.5, 2, 1.5])
        with fc1:
            st.markdown('<span class="filter-label">📅 日期范围</span>', unsafe_allow_html=True)
            ca, cb = st.columns(2)
            with ca: start_date = st.date_input("开始", date.today() - timedelta(days=30), label_visibility="collapsed")
            with cb: end_date = st.date_input("结束", date.today(), label_visibility="collapsed")
        with fc2:
            st.markdown('<span class="filter-label">🏪 数据源</span>', unsafe_allow_html=True)
            st.selectbox("来源", ["全部来源", "银行 CSV", "POS 终端", "手动录入"], label_visibility="collapsed")
        with fc3:
            st.markdown('<span class="filter-label">💳 支付渠道</span>', unsafe_allow_html=True)
            st.multiselect("渠道", ["全部", "现金", "EC卡", "信用卡", "银行转账", "PayPal"], default=["全部"], label_visibility="collapsed")
        with fc4:
            st.markdown("<br>", unsafe_allow_html=True)
            st.button("🔍 高级筛选", use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    main_col, side_col = st.columns([3, 1])

    with main_col:
        st.markdown(f"""
        <div style="border:1px solid {OUTLINE_VARIANT};border-radius:12px;overflow:hidden;background:{SURFACE_CONTAINER_LOWEST};">
            <div style="padding:14px 20px;background:{SURFACE_CONTAINER_LOW};border-bottom:1px solid {OUTLINE_VARIANT};display:flex;align-items:center;justify-content:space-between;">
                <div style="display:flex;align-items:center;gap:12px;">
                    <h3 style="font-size:16px;font-weight:700;color:{PRIMARY};margin:0;">交易对比明细</h3>
                    <span class="ai-pulse" style="background:{TERTIARY_CONTAINER};color:{ON_TERTIARY_CONTAINER};padding:2px 10px;border-radius:9999px;font-size:10px;font-weight:700;display:flex;align-items:center;gap:4px;"><span style="width:6px;height:6px;background:{ON_TERTIARY_CONTAINER};border-radius:50%;"></span> AI 实时监控中</span>
                </div>
                <span style="font-size:11px;color:{ON_SURFACE_VARIANT};">显示 142 笔交易中的 1-5 笔</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

        tx_data = pd.DataFrame({
            "交易时间": ["2026-06-05 18:42", "2026-06-05 17:15", "2026-06-05 14:02", "2026-06-05 13:55", "2026-06-05 12:20"],
            "支付方式": ["微信支付", "美团外卖", "支付宝", "饿了么", "EC卡"],
            "POS 金额": ["€452.00", "€1,280.50", "€89.00", "€342.20", "€10,400.00"],
            "银行金额": ["€452.00", "€1,265.50", "€0.00", "€342.20", "€10,400.00"],
            "AI 状态": ["✓ 自动平账", "⚠ 账目不符", "⚑ 已标记", "✓ 自动平账", "✓ 自动平账"],
        })
        st.dataframe(tx_data, use_container_width=True, hide_index=True)

        pos_t, bank_t = 12563.70, 12458.70
        diff_t = pos_t - bank_t
        st.markdown(f"""
        <div class="table-footer-stats">
            <div><span class="footer-stat-label">POS 总额</span><span class="footer-stat-value">€{pos_t:,.2f}</span></div>
            <div style="width:1px;height:28px;background:{OUTLINE_VARIANT};"></div>
            <div><span class="footer-stat-label">银行总额</span><span class="footer-stat-value">€{bank_t:,.2f}</span></div>
            <div style="width:1px;height:28px;background:{OUTLINE_VARIANT};"></div>
            <div><span class="footer-stat-label" style="color:{ERROR};">净差异</span><span class="footer-stat-value" style="color:{ERROR};">-€{diff_t:,.2f}</span></div>
            <div style="flex:1;"></div>
            <span style="font-size:11px;color:{ON_SURFACE_VARIANT};font-style:italic;">下次扫描在 4:22 分后</span>
            <span class="ai-pulse" style="width:6px;height:6px;background:{PRIMARY};border-radius:50%;"></span>
        </div>
        """, unsafe_allow_html=True)

    with side_col:
        missing_count = len(st.session_state.missing_invoices)
        if st.session_state.report:
            missing_count = st.session_state.report.missing_count

        st.markdown(f"""
        <div class="ai-insight">
            <h4>🤖 AI 智能分析</h4>
            <p style="font-size:12px;line-height:1.6;color:{ON_PRIMARY_CONTAINER};">
                检测到银行数据中有 <b>{missing_count} 处异常</b> — 可能存在缺失发票。
                建议对未匹配的支出项发起自动催收。
            </p>
        </div>
        """, unsafe_allow_html=True)

        if st.button("🤖 修复异常", type="primary", use_container_width=True, key="fix_recon"):
            if missing_count > 0:
                try:
                    report = run_reconciliation()
                    st.session_state.report = report
                    st.session_state.missing_invoices = report.missing_invoices
                    st.success(f"✓ 已识别 {report.missing_count} 处异常，已生成催收邮件")
                    st.rerun()
                except Exception as exc:
                    st.error(f"对账出错: {exc}")
            else:
                st.info("没有发现异常。")

        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown(f"""
        <div style="border:1px solid {OUTLINE_VARIANT};border-radius:12px;padding:16px;background:{SURFACE_CONTAINER_LOWEST};">
            <h4 style="font-size:12px;font-weight:700;color:{ON_SURFACE};text-transform:uppercase;letter-spacing:0.06em;margin:0 0 12px 0;">⚡ 快捷操作</h4>
        </div>
        """, unsafe_allow_html=True)

        bc1, bc2 = st.columns(2)
        with bc1: st.button("✅ 批量审批", use_container_width=True)
        with bc2:
            if st.button("📧 补全发票申请", use_container_width=True):
                try:
                    report = run_reconciliation()
                    st.session_state.report = report
                    st.session_state.missing_invoices = report.missing_invoices
                    st.success(f"✓ 已生成 {report.missing_count} 封催收邮件")
                    st.rerun()
                except Exception as exc:
                    st.error(f"出错: {exc}")
        if st.button("📄 导出审计报告", use_container_width=True):
            now = date.today().isoformat()
            rows = []
            for mi in st.session_state.missing_invoices:
                rows.append({
                    "日期": mi.transaction.buchungstag.isoformat(),
                    "收款方": _sanitize_excel_value(mi.transaction.empfaenger),
                    "金额_EUR": float(mi.transaction.abs_betrag),
                    "用途": _sanitize_excel_value(mi.transaction.verwendungszweck),
                    "匹配度": mi.match_score,
                })
            if rows:
                xlsx_path = DIR_OUTPUT / f"audit_report_{now}.xlsx"
                pd.DataFrame(rows).to_excel(xlsx_path, index=False, engine="openpyxl")
                st.success(f"✓ 已导出至 {xlsx_path}")
            else:
                st.warning("暂无数据可导出。")

        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown(f"""
        <div style="border:1px solid {OUTLINE_VARIANT};border-radius:12px;padding:16px;background:{SURFACE_CONTAINER_LOWEST};">
            <h4 style="font-size:12px;font-weight:700;color:{ON_SURFACE};text-transform:uppercase;letter-spacing:0.06em;margin:0 0 12px 0;">📡 系统健康度</h4>
            <div style="display:flex;flex-direction:column;gap:14px;">
                <div><div style="display:flex;justify-content:space-between;font-size:11px;margin-bottom:4px;"><span style="color:{ON_SURFACE_VARIANT};">POS 连接器</span><span style="color:{PRIMARY};font-weight:700;">运行稳定</span></div><div style="width:100%;height:5px;background:{SURFACE_CONTAINER};border-radius:9999px;"><div style="width:100%;height:100%;background:{PRIMARY};border-radius:9999px;"></div></div></div>
                <div><div style="display:flex;justify-content:space-between;font-size:11px;margin-bottom:4px;"><span style="color:{ON_SURFACE_VARIANT};">银行数据流 (3)</span><span style="color:{PRIMARY};font-weight:700;">2分钟前同步</span></div><div style="width:100%;height:5px;background:{SURFACE_CONTAINER};border-radius:9999px;"><div style="width:85%;height:100%;background:{PRIMARY};border-radius:9999px;"></div></div></div>
                <div><div style="display:flex;justify-content:space-between;font-size:11px;margin-bottom:4px;"><span style="color:{ON_SURFACE_VARIANT};">AI 对账引擎</span><span style="color:{ON_TERTIARY_CONTAINER};font-weight:700;">持续监控</span></div><div style="width:100%;height:5px;background:{SURFACE_CONTAINER};border-radius:9999px;"><div class="ai-pulse" style="width:98%;height:100%;background:{ON_TERTIARY_CONTAINER};border-radius:9999px;"></div></div></div>
            </div>
        </div>
        """, unsafe_allow_html=True)


# ══════════════════════════════════════════ 页面：任务日志 ═════════════════════════════════

def page_tasks() -> None:
    render_header()
    tasks = [
        ("2026-06-05 09:15", "银行对账扫描", "✅ 完成", "发现 3 处差异，已生成催收邮件"),
        ("2026-06-05 08:00", "POS 数据同步", "✅ 完成", "同步 142 笔交易"),
        ("2026-06-04 22:30", "异常检测扫描", "⚠ 警告", "UberEats 结算差异 €15.00"),
        ("2026-06-04 18:00", "供应商发票审核", "✅ 完成", "12 家供应商，2 家缺失发票"),
        ("2026-06-04 14:20", "月度报表生成", "✅ 完成", "6 月 UStVA 已生成"),
        ("2026-06-04 09:00", "自动平账运行", "✅ 完成", "零差异"),
    ]
    colors = {"✅ 完成": PRIMARY, "⚠ 警告": "#856404", "❌ 失败": ERROR}
    rows = ""
    for ts, name, status, detail in tasks:
        c = colors.get(status, ON_SURFACE)
        rows += f'<tr style="border-bottom:1px solid rgba(191,201,195,0.3);"><td style="padding:12px 16px;font-family:{FONT_MONO};font-size:12px;color:{ON_SURFACE_VARIANT};">{ts}</td><td style="padding:12px 16px;font-weight:600;">{name}</td><td style="padding:12px 16px;color:{c};font-weight:700;">{status}</td><td style="padding:12px 16px;font-size:12px;color:{ON_SURFACE_VARIANT};">{detail}</td></tr>'
    st.markdown(f"""
    <div style="border:1px solid {OUTLINE_VARIANT};border-radius:12px;overflow:hidden;background:{SURFACE_CONTAINER_LOWEST};">
        <div style="padding:14px 20px;border-bottom:1px solid {OUTLINE_VARIANT};background:{SURFACE_CONTAINER_LOW};"><h3 style="font-size:16px;font-weight:700;color:{PRIMARY};margin:0;">📋 最近任务执行记录</h3></div>
        <table style="width:100%;border-collapse:collapse;"><thead><tr style="background:{SURFACE_CONTAINER_LOW};font-size:10px;font-weight:700;text-transform:uppercase;color:{OUTLINE};"><th style="padding:10px 16px;text-align:left;">时间</th><th style="padding:10px 16px;text-align:left;">任务</th><th style="padding:10px 16px;text-align:left;">状态</th><th style="padding:10px 16px;text-align:left;">详情</th></tr></thead><tbody>{rows}</tbody></table>
    </div>
    """, unsafe_allow_html=True)


# ══════════════════════════════════════════ 页面：供应商 ═══════════════════════════════════

def page_vendors() -> None:
    render_header()
    st.markdown(f"""
    <div style="border:1px solid {OUTLINE_VARIANT};border-radius:12px;overflow:hidden;background:{SURFACE_CONTAINER_LOWEST};margin-bottom:16px;">
        <div style="padding:14px 20px;background:{SURFACE_CONTAINER_LOW};border-bottom:1px solid {OUTLINE_VARIANT};"><h3 style="font-size:16px;font-weight:700;color:{PRIMARY};margin:0;">🏪 已登记供应商发票</h3></div>
    </div>
    """, unsafe_allow_html=True)

    invoices = st.session_state.invoices
    if invoices:
        inv_data = [{"发票号": i.invoice_id, "供应商": i.lieferant, "金额": f"€{float(i.betrag):,.2f}", "日期": i.datum.isoformat(), "类别": i.kategorie or "—", "描述": i.beschreibung[:40] if i.beschreibung else "—"} for i in invoices]
        st.dataframe(pd.DataFrame(inv_data), use_container_width=True, hide_index=True)
    else:
        st.info("暂无已登记供应商。请上传发票 CSV。")

    st.markdown("---")
    cu1, cu2 = st.columns(2)
    with cu1:
        st.subheader("📂 上传银行 CSV")
        uploaded = st.file_uploader("选择 CSV 文件", type=["csv"], key="v_csv", help="最大 10MB")
        if uploaded:
            if uploaded.size > 10 * 1024 * 1024:
                st.error("文件过大（最大 10MB）。")
            elif uploaded.size == 0:
                st.error("文件为空。")
            else:
                tmp_path = None
                try:
                    header = uploaded.getvalue()[:512]
                    if b"\x00" in header:
                        st.error("检测到二进制文件 — 不是有效的 CSV。")
                    else:
                        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="wb") as tmp:
                            tmp.write(uploaded.getvalue())
                            tmp_path = Path(tmp.name)
                        txns = parse_bank_csv(tmp_path)
                        expenses = filter_expenses(txns)
                        st.session_state.bank_transactions = expenses
                        st.success(f"✓ 已解析 {len(txns)} 笔交易（{len(expenses)} 笔支出）")
                        missing, matched = fuzzy_match_invoices(expenses, invoices)
                        st.session_state.missing_invoices = missing
                        st.info(f"已匹配 {matched} 笔，缺失 {len(missing)} 笔")
                except Exception as exc:
                    st.error(f"解析失败: {exc}")
                finally:
                    if tmp_path is not None:
                        try: tmp_path.unlink(missing_ok=True)
                        except Exception: pass
    with cu2:
        st.subheader("📋 上传发票 CSV")
        inv_csv = st.file_uploader("选择发票 CSV", type=["csv"], key="i_csv", help="需包含列: invoice_id, lieferant, betrag, datum")
        if inv_csv:
            try:
                from services import ReconciliationService
                df_inv = pd.read_csv(io.BytesIO(inv_csv.getvalue()))
                new_inv = ReconciliationService.load_invoices_from_df(df_inv)
                if not new_inv:
                    st.error("未找到有效发票记录。请检查列名和金额格式。")
                else:
                    st.session_state.invoices = new_inv
                    st.success(f"✓ 已加载 {len(new_inv)} 条发票记录")
            except Exception as exc:
                st.error(f"解析失败: {exc}")

    missing = st.session_state.missing_invoices
    if missing:
        st.markdown("---")
        st.subheader(f"🚨 缺失发票（{len(missing)} 笔）")
        miss_data = [{"日期": mi.transaction.buchungstag.isoformat(), "收款方": mi.transaction.empfaenger, "金额 EUR": f"{float(mi.transaction.abs_betrag):,.2f}", "用途": mi.transaction.verwendungszweck[:60]} for mi in missing]
        st.dataframe(pd.DataFrame(miss_data), use_container_width=True, hide_index=True)
        cb1, cb2 = st.columns(2)
        with cb1:
            if st.button("📧 一键生成催收邮件", type="primary", key="gv"):
                generate_reminder_emails(missing)
                st.session_state.emails_generated = True
                st.success(f"✓ 已生成 {len(missing)} 封催收邮件")
        with cb2:
            if st.button("📥 导出 Excel", key="ev"):
                now = date.today().isoformat()
                ed = [{"日期": m_.transaction.buchungstag.isoformat(), "收款方": _sanitize_excel_value(m_.transaction.empfaenger), "金额 EUR": f"{float(m_.transaction.abs_betrag):,.2f}", "用途": _sanitize_excel_value(m_.transaction.verwendungszweck[:120])} for m_ in missing]
                pd.DataFrame(ed).to_excel(DIR_OUTPUT / f"缺失发票_{now}.xlsx", index=False, engine="openpyxl")
                st.success(f"✓ 已导出")


# ══════════════════════════════════════════ 页面：报表 ═════════════════════════════════════

def page_reports() -> None:
    render_header()
    cr1, cr2 = st.columns(2)
    with cr1:
        st.markdown(f"""
        <div style="border:1px solid {OUTLINE_VARIANT};border-radius:12px;padding:20px;background:{SURFACE_CONTAINER_LOWEST};">
            <h3 style="font-size:16px;font-weight:700;color:{PRIMARY};margin:0 0 16px 0;">🧾 德国增值税预申报 (UStVA)</h3>
            <p style="font-size:13px;color:{ON_SURFACE_VARIANT};">税率：食品 <b>{float(TAX_RATE_SPEISEN)*100:.0f}%</b> / 饮品 <b>{float(TAX_RATE_GETRAENKE)*100:.0f}%</b></p>
            <p style="font-size:13px;color:{ON_SURFACE_VARIANT};">§12 Abs. 2 Nr. 1 UStG（食品）/ §12 Abs. 1 UStG（饮品）</p>
            <p style="font-size:11px;color:{OUTLINE};margin-top:8px;">餐厅：{cfg.name} | 税号可配置</p>
        </div>
        """, unsafe_allow_html=True)
    with cr2:
        email_files = sorted(DIR_EMAIL_DRAFTS.glob("*.txt"))
        st.markdown(f"""
        <div style="border:1px solid {OUTLINE_VARIANT};border-radius:12px;padding:20px;background:{SURFACE_CONTAINER_LOWEST};">
            <h3 style="font-size:16px;font-weight:700;color:{PRIMARY};margin:0 0 12px 0;">📧 邮件草稿（{len(email_files)} 封）</h3>
        </div>
        """, unsafe_allow_html=True)
        if email_files:
            for ef in email_files[-5:]:
                with st.expander(f"📧 {ef.name}"):
                    st.code(ef.read_text(encoding="utf-8"), language="text")
        else:
            st.caption("暂无邮件草稿。请先执行对账并生成邮件。")


# ══════════════════════════════════════════ 主入口 ═════════════════════════════════════════

def main() -> None:
    st.set_page_config(
        page_title=f"{cfg.name} · 餐饮财务管家",
        page_icon="🍽️",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    init_session()
    inject_m3_theme()

    anomaly_count = len(st.session_state.missing_invoices)
    st.markdown(f"""
    <div style="position:fixed;bottom:24px;right:24px;z-index:9999;width:56px;height:56px;background:{PRIMARY};color:{ON_PRIMARY};border-radius:50%;box-shadow:0 8px 32px rgba(0,53,39,0.35);display:flex;align-items:center;justify-content:center;cursor:pointer;border:none;font-size:24px;transition:transform 0.15s;">
        <span>🤖</span>
        <span style="position:absolute;top:-2px;right:-2px;width:18px;height:18px;background:{ERROR};color:white;border-radius:50%;font-size:10px;font-weight:900;display:flex;align-items:center;justify-content:center;border:2px solid {SURFACE};">{anomaly_count}</span>
    </div>
    """, unsafe_allow_html=True)

    with st.sidebar:
        render_sidebar()

    page = st.session_state.get("page", "概览")
    if page == "概览": page_overview()
    elif page == "财务分析": page_finanzanalyse()
    elif page == "智能对账": page_reconciliation()
    elif page == "任务日志": page_tasks()
    elif page == "供应商": page_vendors()
    elif page == "报表": page_reports()
    else: page_overview()


if __name__ == "__main__":
    main()
