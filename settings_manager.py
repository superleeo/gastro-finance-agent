"""
settings_manager.py — Gastro Finance Agent 完整设置管理
=========================================================
持久化存储所有餐厅配置，支持 Dashboard 可视化编辑。

数据存储: JSON 文件 ~/.gastro_finance/settings.json
环境变量优先级: GASTRO_* 覆盖 JSON (用于 Docker/CI)
"""

from __future__ import annotations

import json
import os
from copy import deepcopy
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config import logger


# ╔══════════════════════════════════════════════════════════╗
# ║                   Enums                                  ║
# ╚══════════════════════════════════════════════════════════╝

class Language(str, Enum):
    DE = "de"
    EN = "en"
    ZH = "zh"

class BusinessType(str, Enum):
    GMBH = "gmbh"                      # 有限责任公司
    EINZELUNTERNEHMEN = "einzel"       # 个体经营
    KG = "kg"                          # 两合公司
    OHG = "ohg"                        # 无限公司
    GBR = "gbr"                        # 民事合伙
    UG = "ug"                          # 迷你有限责任公司
    FREIBERUFLER = "freiberufler"      # 自由职业者

class TaxClass(str, Enum):
    """德国工资税级"""
    I   = "I"     # 单身/离异/丧偶
    II  = "II"    # 单亲
    III = "III"   # 已婚 (高收入方)
    IV  = "IV"    # 已婚 (双收入)
    V   = "V"     # 已婚 (低收入方)
    VI  = "VI"    # 第二份工作

class MaritalStatus(str, Enum):
    SINGLE = "ledig"
    MARRIED = "verheiratet"
    DIVORCED = "geschieden"
    WIDOWED = "verwitwet"

class EmploymentStatus(str, Enum):
    FULL_TIME = "Vollzeit"
    PART_TIME = "Teilzeit"
    MINI_JOB = "Minijob"
    MIDI_JOB = "Midijob"
    SHORT_TERM = "Kurzfristig"


# ╔══════════════════════════════════════════════════════════╗
# ║                   Data Models                             ║
# ╚══════════════════════════════════════════════════════════╝

@dataclass
class EmployeeRecord:
    """员工信息"""
    name: str = ""
    position: str = ""
    tax_class: TaxClass = TaxClass.I
    marital_status: MaritalStatus = MaritalStatus.SINGLE
    hourly_wage: float = 12.82     # 2026 年德国最低工资
    hours_per_week: float = 40.0
    employment_status: EmploymentStatus = EmploymentStatus.FULL_TIME
    start_date: str = ""            # YYYY-MM-DD
    has_children: bool = False
    church_tax: bool = False        # 教会税
    health_insurance_pct: float = 7.3   # 医保 (雇主承担一半)
    pension_insurance_pct: float = 9.3  # 养老保险
    unemployment_insurance_pct: float = 1.3  # 失业保险
    care_insurance_pct: float = 1.7      # 护理保险

    @property
    def monthly_gross(self) -> float:
        """月薪（假设 4.33 周/月）"""
        return round(self.hourly_wage * self.hours_per_week * 4.33, 2)

    @property
    def monthly_employer_cost(self) -> float:
        """雇主总成本（含社保雇主部分）"""
        social_pct = (self.health_insurance_pct + self.pension_insurance_pct +
                      self.unemployment_insurance_pct + self.care_insurance_pct) / 100
        return round(self.monthly_gross * (1 + social_pct / 2), 2)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["tax_class"] = self.tax_class.value
        d["marital_status"] = self.marital_status.value
        d["employment_status"] = self.employment_status.value
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "EmployeeRecord":
        return cls(
            name=d.get("name", ""),
            position=d.get("position", ""),
            tax_class=TaxClass(d.get("tax_class", "I")),
            marital_status=MaritalStatus(d.get("marital_status", "ledig")),
            hourly_wage=float(d.get("hourly_wage", 12.82)),
            hours_per_week=float(d.get("hours_per_week", 40.0)),
            employment_status=EmploymentStatus(d.get("employment_status", "Vollzeit")),
            start_date=d.get("start_date", ""),
            has_children=bool(d.get("has_children", False)),
            church_tax=bool(d.get("church_tax", False)),
            health_insurance_pct=float(d.get("health_insurance_pct", 7.3)),
            pension_insurance_pct=float(d.get("pension_insurance_pct", 9.3)),
            unemployment_insurance_pct=float(d.get("unemployment_insurance_pct", 1.3)),
            care_insurance_pct=float(d.get("care_insurance_pct", 1.7)),
        )


@dataclass
class RestaurantSettings:
    """完整的餐厅配置"""
    # ── 基本信息 ──
    language: Language = Language.DE
    restaurant_name: str = ""
    email: str = ""
    phone: str = ""
    address: str = ""
    steuernummer: str = ""          # 税号
    ust_id: str = ""                # 增值税号
    business_type: BusinessType = BusinessType.EINZELUNTERNEHMEN

    # ── 税务设置 ──
    tax_rate_speisen: float = 7.0
    tax_rate_getraenke: float = 19.0
    hebesatz: int = 400             # 地方稽征率

    # ── 银行 ──
    bank_name: str = ""
    iban: str = ""
    bic: str = ""

    # ── 税务顾问 ──
    tax_advisor_name: str = ""
    tax_advisor_email: str = ""
    tax_advisor_phone: str = ""
    tax_start_date: str = ""        # 何时开始营业 (YYYY-MM-DD)
    tax_registration_date: str = "" # 税务登记日期
    last_tax_filing: str = ""       # 上次报税日期

    # ── 员工 ──
    employees: List[EmployeeRecord] = field(default_factory=list)

    # ── 演示模式 ──
    demo_mode: bool = False

    @property
    def total_employees(self) -> int:
        return len(self.employees)

    @property
    def total_monthly_payroll(self) -> float:
        return sum(e.monthly_gross for e in self.employees)

    @property
    def total_monthly_employer_cost(self) -> float:
        return sum(e.monthly_employer_cost for e in self.employees)

    # ── 企业形式中文名 ──
    def get_business_type_display(self, lang: str = "de") -> str:
        """根据语言返回企业形式显示名"""
        maps = {
            "de": {"gmbh": "GmbH", "einzel": "Einzelunternehmen", "kg": "KG",
                   "ohg": "OHG", "gbr": "GbR", "ug": "UG (haftungsbeschränkt)",
                   "freiberufler": "Freiberufler"},
            "en": {"gmbh": "GmbH (LLC)", "einzel": "Sole Proprietorship", "kg": "KG (LP)",
                   "ohg": "OHG (GP)", "gbr": "GbR (Partnership)", "ug": "UG (Mini LLC)",
                   "freiberufler": "Freelancer"},
            "zh": {"gmbh": "有限责任公司 (GmbH)", "einzel": "个体经营", "kg": "两合公司 (KG)",
                   "ohg": "无限公司 (OHG)", "gbr": "民事合伙 (GbR)", "ug": "迷你有限责任公司 (UG)",
                   "freiberufler": "自由职业者"},
        }
        return maps.get(lang, maps["de"]).get(self.business_type.value, self.business_type.value)


# ╔══════════════════════════════════════════════════════════╗
# ║                   Persistence                             ║
# ╚══════════════════════════════════════════════════════════╝

SETTINGS_DIR  = Path.home() / ".gastro_finance"
SETTINGS_FILE = SETTINGS_DIR / "settings.json"


def _env_override(settings: RestaurantSettings) -> RestaurantSettings:
    """环境变量覆盖 JSON 配置"""
    env_map = {
        "GASTRO_RESTAURANT_NAME": "restaurant_name",
        "GASTRO_RESTAURANT_EMAIL": "email",
        "GASTRO_RESTAURANT_PHONE": "phone",
        "GASTRO_RESTAURANT_ADDRESS": "address",
        "GASTRO_DEMO_MODE": "demo_mode",
        "GASTRO_STEUERNUMMER": "steuernummer",
        "GASTRO_TAX_ADVISOR_EMAIL": "tax_advisor_email",
    }
    for env_key, attr in env_map.items():
        val = os.getenv(env_key)
        if val is not None:
            if attr == "demo_mode":
                setattr(settings, attr, val == "1")
            else:
                setattr(settings, attr, val)
    return settings


def load_settings() -> RestaurantSettings:
    """从 JSON 文件加载设置，环境变量覆盖"""
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)

    if SETTINGS_FILE.exists():
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            settings = _dict_to_settings(data)
            logger.info(f"设置已加载: {SETTINGS_FILE}")
            return _env_override(settings)
        except Exception as exc:
            logger.warning(f"设置文件损坏，使用默认值: {exc}")

    # 从环境变量创建初始设置
    settings = RestaurantSettings(
        restaurant_name=os.getenv("GASTRO_RESTAURANT_NAME", ""),
        email=os.getenv("GASTRO_RESTAURANT_EMAIL", ""),
        phone=os.getenv("GASTRO_RESTAURANT_PHONE", ""),
        address=os.getenv("GASTRO_RESTAURANT_ADDRESS", ""),
        demo_mode=os.getenv("GASTRO_DEMO_MODE", "0") == "1",
    )
    logger.info("使用默认设置（未找到设置文件）")
    return settings


def save_settings(settings: RestaurantSettings) -> bool:
    """保存设置到 JSON 文件"""
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        data = _settings_to_dict(settings)
        SETTINGS_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        logger.info(f"设置已保存: {SETTINGS_FILE}")
        return True
    except Exception as exc:
        logger.error(f"保存设置失败: {exc}")
        return False


def _settings_to_dict(settings: RestaurantSettings) -> Dict[str, Any]:
    """Settings → JSON-safe dict"""
    d = asdict(settings)
    d["language"] = settings.language.value
    d["business_type"] = settings.business_type.value
    d["employees"] = [e.to_dict() for e in settings.employees]
    return d


def _dict_to_settings(data: Dict[str, Any]) -> RestaurantSettings:
    """JSON dict → Settings"""
    employees = []
    for e in data.pop("employees", []):
        employees.append(EmployeeRecord.from_dict(e))

    lang = data.pop("language", "de")
    biz = data.pop("business_type", "einzel")

    settings = RestaurantSettings(
        language=Language(lang) if lang in [e.value for e in Language] else Language.DE,
        business_type=BusinessType(biz) if biz in [e.value for e in BusinessType] else BusinessType.EINZELUNTERNEHMEN,
        restaurant_name=data.get("restaurant_name", ""),
        email=data.get("email", ""),
        phone=data.get("phone", ""),
        address=data.get("address", ""),
        steuernummer=data.get("steuernummer", ""),
        ust_id=data.get("ust_id", ""),
        tax_rate_speisen=float(data.get("tax_rate_speisen", 7.0)),
        tax_rate_getraenke=float(data.get("tax_rate_getraenke", 19.0)),
        hebesatz=int(data.get("hebesatz", 400)),
        bank_name=data.get("bank_name", ""),
        iban=data.get("iban", ""),
        bic=data.get("bic", ""),
        tax_advisor_name=data.get("tax_advisor_name", ""),
        tax_advisor_email=data.get("tax_advisor_email", ""),
        tax_advisor_phone=data.get("tax_advisor_phone", ""),
        tax_start_date=data.get("tax_start_date", ""),
        tax_registration_date=data.get("tax_registration_date", ""),
        last_tax_filing=data.get("last_tax_filing", ""),
        employees=employees,
        demo_mode=bool(data.get("demo_mode", False)),
    )
    return settings


# ╔══════════════════════════════════════════════════════════╗
# ║                   Tax Advisor Notification               ║
# ╚══════════════════════════════════════════════════════════╝

def generate_tax_advisor_email(settings: RestaurantSettings) -> str:
    """
    生成通知税务顾问的邮件草稿（德语）。
    内容包括：餐厅信息、开始营业日期、员工人数、工资总额。
    """
    emp_count = settings.total_employees
    payroll = settings.total_monthly_payroll

    # 员工列表
    emp_lines = ""
    for e in settings.employees:
        emp_lines += (
            f"  • {e.name} — {e.position} — "
            f"StKl {e.tax_class.value} ({e.marital_status.value}) — "
            f"{e.hours_per_week:.0f} Std/Woche × €{e.hourly_wage:.2f}/Std "
            f"= €{e.monthly_gross:,.2f}/Monat"
        )
        if e.start_date:
            emp_lines += f" (seit {e.start_date})"
        emp_lines += "\n"

    body = f"""Betreff: Anmeldung zur Steuerberatung — {settings.restaurant_name}

Sehr geehrte(r) {settings.tax_advisor_name or 'Damen und Herren'},

hiermit möchten wir Ihnen mitteilen, dass unser Gastronomiebetrieb
«{settings.restaurant_name}» seine steuerliche Betreuung bei Ihnen
aufnehmen möchte.

── Geschäftsdaten ──────────────────────────────────
  • Rechtsform:          {settings.get_business_type_display('de')}
  • Adresse:             {settings.address}
  • Steuernummer:        {settings.steuernummer or '(noch nicht erteilt)'}
  • USt-IdNr.:           {settings.ust_id or '(noch nicht erteilt)'}
  • Betriebsaufnahme:    {settings.tax_start_date or '(bitte eintragen)'}
  • Bankverbindung:      {settings.bank_name} / IBAN {settings.iban}

── Umsatzsteuer ─────────────────────────────────────
  • Speisen:             {settings.tax_rate_speisen:.0f}% (§12 Abs. 2 Nr. 1 UStG)
  • Getränke:            {settings.tax_rate_getraenke:.0f}% (§12 Abs. 1 UStG)
  • Hebesatz:            {settings.hebesatz}%

── Mitarbeiter ({emp_count}) ────────────────────────
{emp_lines}
  • Monatliche Lohnsumme (brutto): €{payroll:,.2f}
  • Arbeitgeber-Gesamtkosten:       €{settings.total_monthly_employer_cost:,.2f}

── Erforderlich ────────────────────────────────────
  □ Anmeldung beim Finanzamt (Fragebogen zur steuerlichen Erfassung)
  □ Beantragung Steuernummer + USt-IdNr.
  □ Anmeldung zur Umsatzsteuer-Voranmeldung (monatlich/vierteljährlich)
  □ Anmeldung der Mitarbeiter bei der Sozialversicherung
  □ Einrichtung Lohnbuchhaltung ({emp_count} Mitarbeiter, StKl I-VI)
  □ Gewerbeanmeldung prüfen

Bitte teilen Sie uns mit, welche weiteren Unterlagen Sie benötigen.

Mit freundlichen Grüßen,
{settings.restaurant_name}
Tel: {settings.phone}
E-Mail: {settings.email}
"""
    return body


def save_tax_advisor_draft(settings: RestaurantSettings,
                           output_dir: Optional[Path] = None) -> Path:
    """保存税务顾问通知邮件草稿"""
    from config import DIR_EMAIL_DRAFTS
    out = output_dir or DIR_EMAIL_DRAFTS
    out.mkdir(parents=True, exist_ok=True)

    body = generate_tax_advisor_email(settings)
    filename = f"Steuerberater_Anmeldung_{settings.restaurant_name.replace(' ', '_')}.txt"
    filepath = out / filename
    filepath.write_text(body, encoding="utf-8")
    logger.info(f"税务顾问通知已生成: {filepath}")
    return filepath


# ╔══════════════════════════════════════════════════════════╗
# ║                   Quick Test                             ║
# ╚══════════════════════════════════════════════════════════╝

if __name__ == "__main__":
    # 创建示例设置
    settings = RestaurantSettings(
        language=Language.ZH,
        restaurant_name="金龍大酒樓",
        email="steuer@jinlong.de",
        phone="+49 621 123456",
        address="Kaiserring 12, 68161 Mannheim",
        steuernummer="123/456/78901",
        business_type=BusinessType.GMBH,
        tax_advisor_name="Herr Dr. Müller",
        tax_advisor_email="mueller@steuerkanzlei.de",
        tax_start_date="2026-01-15",
        tax_rate_speisen=7.0,
        tax_rate_getraenke=19.0,
        hebesatz=420,
        employees=[
            EmployeeRecord(name="张三", position="Chefkoch", tax_class=TaxClass.III,
                          marital_status=MaritalStatus.MARRIED, hourly_wage=22.0,
                          hours_per_week=40, start_date="2026-01-15"),
            EmployeeRecord(name="李四", position="Serviceleitung", tax_class=TaxClass.I,
                          marital_status=MaritalStatus.SINGLE, hourly_wage=14.0,
                          hours_per_week=35, start_date="2026-02-01"),
            EmployeeRecord(name="王五", position="Spüler", tax_class=TaxClass.V,
                          marital_status=MaritalStatus.MARRIED, hourly_wage=13.50,
                          hours_per_week=20, start_date="2026-03-01",
                          employment_status=EmploymentStatus.PART_TIME),
        ],
    )

    # 保存
    save_settings(settings)

    # 重新加载验证
    loaded = load_settings()
    print(f"✅ 设置已持久化: {SETTINGS_FILE}")
    print(f"   餐厅: {loaded.restaurant_name}")
    print(f"   语言: {loaded.language.value}")
    print(f"   企业形式: {loaded.get_business_type_display('zh')}")
    print(f"   员工: {loaded.total_employees} 人, 月薪 €{loaded.total_monthly_payroll:,.2f}")
    print(f"   雇主总成本: €{loaded.total_monthly_employer_cost:,.2f}")

    # 生成税务顾问邮件
    draft_path = save_tax_advisor_draft(settings)
    print(f"\n📧 税务顾问通知草稿: {draft_path}")
    print(f"   内容预览:\n{generate_tax_advisor_email(settings)[:500]}...")
