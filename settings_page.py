"""
settings_page.py — Dashboard 设置中心页面
==========================================
可视化编辑所有餐厅配置：语言、税率、经营模式、员工、税号等。
数据持久化到 ~/.gastro_finance/settings.json
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Optional

import streamlit as st

from config import DIR_EMAIL_DRAFTS, restaurant as cfg, logger
from settings_manager import (
    BusinessType,
    EmployeeRecord,
    EmploymentStatus,
    Language,
    MaritalStatus,
    RestaurantSettings,
    TaxClass,
    generate_tax_advisor_email,
    load_settings,
    save_settings,
    save_tax_advisor_draft,
    SETTINGS_FILE,
)

# 语言翻译字典
L10N = {
    "zh": {
        "title": "⚙️ 系统设置",
        "restaurant": "🏪 餐厅信息",
        "tax": "🧾 税务设置",
        "bank": "🏦 银行信息",
        "employees": "👥 员工管理",
        "advisor": "📧 税务顾问",
        "save": "💾 保存设置",
        "saved": "✅ 设置已保存",
        "draft_advisor": "📨 生成税务顾问通知邮件",
        "draft_saved": "✅ 邮件草稿已生成",
        "add_employee": "➕ 添加员工",
        "remove_employee": "🗑 移除",
    },
    "de": {
        "title": "⚙️ Einstellungen",
        "restaurant": "🏪 Restaurant",
        "tax": "🧾 Steuern",
        "bank": "🏦 Bank",
        "employees": "👥 Personal",
        "advisor": "📧 Steuerberater",
        "save": "💾 Speichern",
        "saved": "✅ Gespeichert",
        "draft_advisor": "📨 Steuerberater-Benachrichtigung",
        "draft_saved": "✅ E-Mail-Entwurf erstellt",
        "add_employee": "➕ Mitarbeiter",
        "remove_employee": "🗑 Entfernen",
    },
    "en": {
        "title": "⚙️ Settings",
        "restaurant": "🏪 Restaurant",
        "tax": "🧾 Tax",
        "bank": "🏦 Bank",
        "employees": "👥 Staff",
        "advisor": "📧 Tax Advisor",
        "save": "💾 Save",
        "saved": "✅ Settings Saved",
        "draft_advisor": "📨 Generate Tax Advisor Notice",
        "draft_saved": "✅ Draft Email Created",
        "add_employee": "➕ Add Employee",
        "remove_employee": "🗑 Remove",
    },
}


def _t(key: str, lang: str = "zh") -> str:
    return L10N.get(lang, L10N["zh"]).get(key, key)


def page_settings() -> None:
    """设置主页面"""
    lang = cfg.demo_mode and "zh" or "de"
    t = lambda k: _t(k, lang)  # noqa: E731

    # 页头
    st.markdown(f"""
    <div style="display:flex;align-items:center;justify-content:space-between;
                padding:8px 0 16px 0;border-bottom:1px solid #bfc9c3;margin-bottom:20px;">
        <div style="font-size:24px;font-weight:700;color:#003527;">{t('title')}</div>
        <span style="font-size:11px;color:#707974;">📁 {SETTINGS_FILE}</span>
    </div>
    """, unsafe_allow_html=True)

    # 加载当前设置
    settings = load_settings()

    # ── Tab 布局 ────────────────────────────────────────────
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        t("restaurant"), t("tax"), t("bank"), t("employees"), t("advisor")
    ])

    # ═══ Tab 1: 餐厅信息 ═══
    with tab1:
        st.subheader(t("restaurant"))
        c1, c2 = st.columns(2)
        with c1:
            lang_choice = st.selectbox("语言 / Sprache / Language",
                                       [("zh", "中文"), ("de", "Deutsch"), ("en", "English")],
                                       index=0 if settings.language == Language.ZH else (1 if settings.language == Language.DE else 2),
                                       format_func=lambda x: x[1])
            settings.language = Language(lang_choice[0])
            settings.restaurant_name = st.text_input("餐厅名称", value=settings.restaurant_name)
            settings.business_type = BusinessType(st.selectbox(
                "经营模式 / Rechtsform",
                [("einzel", "个体经营"), ("gmbh", "GmbH 有限责任公司"), ("kg", "KG 两合公司"),
                 ("ohg", "OHG 无限公司"), ("gbr", "GbR 民事合伙"), ("ug", "UG 迷你有限责任公司"),
                 ("freiberufler", "自由职业者")],
                index=["einzel","gmbh","kg","ohg","gbr","ug","freiberufler"].index(settings.business_type.value)
                if settings.business_type.value in ["einzel","gmbh","kg","ohg","gbr","ug","freiberufler"]
                else 0,
                format_func=lambda x: x[1],
            ))
        with c2:
            settings.email = st.text_input("邮箱 / E-Mail", value=settings.email)
            settings.phone = st.text_input("电话 / Telefon", value=settings.phone)
            settings.address = st.text_area("地址 / Adresse", value=settings.address)
            settings.steuernummer = st.text_input("税号 / Steuernummer", value=settings.steuernummer)
            settings.ust_id = st.text_input("增值税号 / USt-IdNr.", value=settings.ust_id)

    # ═══ Tab 2: 税务设置 ═══
    with tab2:
        st.subheader(t("tax"))
        c1, c2 = st.columns(2)
        with c1:
            settings.tax_rate_speisen = st.number_input(
                "食品税率 / Speisen USt (%)", min_value=0.0, max_value=25.0,
                value=float(settings.tax_rate_speisen), step=0.5,
                help="德国 2026: 7% (§12 Abs. 2 Nr. 1 UStG)")
            settings.hebesatz = st.number_input(
                "地方稽征率 / Hebesatz (%)", min_value=200, max_value=900,
                value=int(settings.hebesatz), step=10,
                help="Gewerbesteuer-Hebesatz (默认 400%)")
        with c2:
            settings.tax_rate_getraenke = st.number_input(
                "饮品税率 / Getränke USt (%)", min_value=0.0, max_value=25.0,
                value=float(settings.tax_rate_getraenke), step=0.5,
                help="德国 2026: 19% (§12 Abs. 1 UStG)")
            st.caption(f"💡 当前配置: 食品 {settings.tax_rate_speisen:.0f}% / 饮品 {settings.tax_rate_getraenke:.0f}%")

    # ═══ Tab 3: 银行 ═══
    with tab3:
        st.subheader(t("bank"))
        settings.bank_name = st.text_input("银行名称 / Bank", value=settings.bank_name)
        c1, c2 = st.columns(2)
        with c1:
            settings.iban = st.text_input("IBAN", value=settings.iban)
        with c2:
            settings.bic = st.text_input("BIC", value=settings.bic)

    # ═══ Tab 4: 员工管理 ═══
    with tab4:
        st.subheader(t("employees"))

        if not settings.employees:
            settings.employees = []

        # 显示现有员工
        for i, emp in enumerate(settings.employees):
            with st.expander(f"👤 {emp.name or f'Mitarbeiter {i+1}'} — €{emp.monthly_gross:,.2f}/Monat", expanded=i == 0):
                ce1, ce2, ce3 = st.columns(3)
                with ce1:
                    emp.name = st.text_input("姓名 / Name", value=emp.name, key=f"ename_{i}")
                    emp.position = st.text_input("职位 / Position", value=emp.position, key=f"epos_{i}")
                    emp.start_date = st.text_input("入职日期 / Start (YYYY-MM-DD)", value=emp.start_date, key=f"estart_{i}")
                with ce2:
                    emp.hourly_wage = st.number_input("时薪 €/Std", min_value=12.0, max_value=100.0,
                                                      value=float(emp.hourly_wage), step=0.5, key=f"ewage_{i}")
                    emp.hours_per_week = st.number_input("周工时 / Std/Woche", min_value=1.0, max_value=60.0,
                                                         value=float(emp.hours_per_week), step=1.0, key=f"ehours_{i}")
                    emp.employment_status = EmploymentStatus(st.selectbox(
                        "雇佣类型", ["Vollzeit", "Teilzeit", "Minijob", "Midijob", "Kurzfristig"],
                        index=["Vollzeit","Teilzeit","Minijob","Midijob","Kurzfristig"].index(emp.employment_status.value),
                        key=f"estatus_{i}"))
                with ce3:
                    emp.tax_class = TaxClass(st.selectbox(
                        "税级 / StKl", ["I","II","III","IV","V","VI"],
                        index=["I","II","III","IV","V","VI"].index(emp.tax_class.value), key=f"etax_{i}"))
                    emp.marital_status = MaritalStatus(st.selectbox(
                        "婚姻状态", ["ledig","verheiratet","geschieden","verwitwet"],
                        index=["ledig","verheiratet","geschieden","verwitwet"].index(emp.marital_status.value),
                        format_func=lambda x: {"ledig":"未婚","verheiratet":"已婚","geschieden":"离异","verwitwet":"丧偶"}[x],
                        key=f"emar_{i}"))
                    emp.has_children = st.checkbox("有子女 / Kinder", value=emp.has_children, key=f"echild_{i}")
                    emp.church_tax = st.checkbox("教会税 / Kirchensteuer", value=emp.church_tax, key=f"echurch_{i}")

                st.caption(f"💶 月薪 Brutto: €{emp.monthly_gross:,.2f} | "
                          f"雇主成本: €{emp.monthly_employer_cost:,.2f}")

                if st.button(t("remove_employee"), key=f"rem_{i}"):
                    settings.employees.pop(i)
                    st.rerun()

        # 添加新员工
        if st.button(t("add_employee"), type="primary"):
            settings.employees.append(EmployeeRecord())
            st.rerun()

        if settings.employees:
            st.markdown("---")
            st.metric("员工总数", f"{settings.total_employees} 人")
            st.metric("月度工资总额 (Brutto)", f"€{settings.total_monthly_payroll:,.2f}")
            st.metric("雇主总成本 (含社保)", f"€{settings.total_monthly_employer_cost:,.2f}")

    # ═══ Tab 5: 税务顾问 ═══
    with tab5:
        st.subheader(t("advisor"))
        c1, c2 = st.columns(2)
        with c1:
            settings.tax_advisor_name = st.text_input("顾问姓名 / Name", value=settings.tax_advisor_name)
            settings.tax_advisor_email = st.text_input("顾问邮箱 / E-Mail", value=settings.tax_advisor_email)
            settings.tax_advisor_phone = st.text_input("顾问电话 / Telefon", value=settings.tax_advisor_phone)
        with c2:
            settings.tax_start_date = st.text_input(
                "开始营业日期 / Betriebsaufnahme", value=settings.tax_start_date,
                help="格式: YYYY-MM-DD，例如 2026-01-15")
            settings.tax_registration_date = st.text_input(
                "税务登记日期 / Steuerliche Erfassung", value=settings.tax_registration_date)
            settings.last_tax_filing = st.text_input(
                "上次报税日期 / Letzte Abgabe", value=settings.last_tax_filing)

        st.markdown("---")
        if st.button(t("draft_advisor"), type="primary"):
            save_tax_advisor_draft(settings)
            st.success(t("draft_saved"))
            with st.expander("📧 邮件预览"):
                st.code(generate_tax_advisor_email(settings), language="text")

    # ── 保存按钮 ────────────────────────────────────────────
    st.markdown("---")
    col_save, col_status = st.columns([1, 3])
    with col_save:
        if st.button(t("save"), type="primary", use_container_width=True):
            if save_settings(settings):
                st.success(t("saved"))
                st.rerun()


if __name__ == "__main__":
    print("设置页面 — 从 dashboard.py 中作为 '设置' 页面调用")
    print("page_settings() 函数已就绪")
