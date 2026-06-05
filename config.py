"""
Gastro_Finance_Agent — 配置中心
================================
2026 年德国餐饮税务配置 + 可配置餐厅信息。
适用于德国的任何餐厅（Restaurant / Café / Imbiss / Bistro）。

使用方式:
  1. 复制 .env.example 为 .env 并填写你的餐厅信息
  2. 或直接设置环境变量
  3. 未设置的字段使用默认值
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path


# ╔══════════════════════════════════════════════════════════╗
# ║                   项目根目录                             ║
# ╚══════════════════════════════════════════════════════════╝

PROJECT_ROOT = Path(__file__).resolve().parent

# ╔══════════════════════════════════════════════════════════╗
# ║                   目录路径                               ║
# ╚══════════════════════════════════════════════════════════╝

DIR_INPUT_RAW      = PROJECT_ROOT / "input_raw"        # 小票照片
DIR_INPUT_BANK     = PROJECT_ROOT / "input_bank"       # 银行 CSV
DIR_ORGANIZED      = PROJECT_ROOT / "organized_data"   # 归档
DIR_OUTPUT         = PROJECT_ROOT / "output"           # 生成的 Excel/PDF
DIR_EMAIL_DRAFTS   = PROJECT_ROOT / "email_drafts"     # 催收邮件草稿
DIR_LOGS           = PROJECT_ROOT / "logs"             # 日志文件

for _d in (DIR_INPUT_RAW, DIR_INPUT_BANK, DIR_ORGANIZED,
           DIR_OUTPUT, DIR_EMAIL_DRAFTS, DIR_LOGS):
    _d.mkdir(parents=True, exist_ok=True)


# ╔══════════════════════════════════════════════════════════╗
# ║              餐厅信息（可配置）                           ║
# ╚══════════════════════════════════════════════════════════╝

@dataclass
class RestaurantConfig:
    """
    餐厅配置 — 通过环境变量或 .env 文件设置。

    环境变量:
      GASTRO_RESTAURANT_NAME    餐厅名称（默认 "Mein Restaurant"）
      GASTRO_RESTAURANT_EMAIL   财务邮箱（默认 "buchhaltung@mein-restaurant.de"）
      GASTRO_RESTAURANT_PHONE   电话（默认 "+49 (0)XXX XXXXXXX"）
      GASTRO_RESTAURANT_ADDRESS 地址（默认 ""）
      GASTRO_DEMO_MODE          演示模式 1/0（默认 0）
    """
    name: str = field(default_factory=lambda: os.getenv("GASTRO_RESTAURANT_NAME", "Mein Restaurant"))
    email: str = field(default_factory=lambda: os.getenv("GASTRO_RESTAURANT_EMAIL", "buchhaltung@mein-restaurant.de"))
    phone: str = field(default_factory=lambda: os.getenv("GASTRO_RESTAURANT_PHONE", "+49 (0)XXX XXXXXXX"))
    address: str = field(default_factory=lambda: os.getenv("GASTRO_RESTAURANT_ADDRESS", ""))
    demo_mode: bool = field(default_factory=lambda: os.getenv("GASTRO_DEMO_MODE", "0") == "1")


# 全局单例
restaurant = RestaurantConfig()

# 向后兼容别名
RESTAURANT_EMAIL = restaurant.email


# ╔══════════════════════════════════════════════════════════╗
# ║             2026 年德国餐饮税务常量                       ║
# ╚══════════════════════════════════════════════════════════╝

# §12 Abs. 2 Nr. 1 UStG — 食品类统一下调至 7%
TAX_RATE_SPEISEN = Decimal("0.07")
# §12 Abs. 1 UStG — 饮品类保持 19%
TAX_RATE_GETRAENKE = Decimal("0.19")

TAX_CATEGORY_MAP: dict[str, Decimal] = {
    "speisen":   TAX_RATE_SPEISEN,
    "getraenke": TAX_RATE_GETRAENKE,
    "food":      TAX_RATE_SPEISEN,
    "drink":     TAX_RATE_GETRAENKE,
    "essen":     TAX_RATE_SPEISEN,
    "getränke":  TAX_RATE_GETRAENKE,
}

# 财务校验容差（欧元）
FINANCE_TOLERANCE = Decimal("0.02")


# ╔══════════════════════════════════════════════════════════╗
# ║              银行 CSV 解析配置                           ║
# ╚══════════════════════════════════════════════════════════╝

CSV_DELIMITER = ";"
CSV_DECIMAL   = ","
CSV_ENCODING  = "utf-8"

BANK_COLUMN_MAP = {
    "buchungstag":   ["Buchungstag", "Buchungsdatum", "Valutadatum", "Datum"],
    "empfaenger":    ["Empfänger/Zahlungspflichtiger", "Empfänger", "Auftraggeber",
                      "Begünstigter", "Name"],
    "verwendungszweck": ["Verwendungszweck", "Buchungstext", "Transaktionstext"],
    "betrag":        ["Betrag", "Umsatz", "Wert", "Amount"],
    "waehrung":      ["Währung", "Currency"],
}


# ╔══════════════════════════════════════════════════════════╗
# ║              邮件模板                                     ║
# ╚══════════════════════════════════════════════════════════╝

def build_email_signature() -> str:
    """根据餐厅配置动态生成邮件签名"""
    parts = [
        "Mit freundlichen Grüßen,",
        f"{restaurant.name} — Finanzabteilung",
    ]
    if restaurant.address:
        parts.append(restaurant.address)
    parts.append(f"Tel: {restaurant.phone}")
    parts.append(f"E-Mail: {restaurant.email}")
    return "\n".join(parts)


def build_email_template() -> str:
    """根据餐厅配置动态生成德语催收邮件模板"""
    return (
        "Betreff: Bitte um Rechnungszusendung — {empfaenger} / Buchung vom {buchungstag}\n"
        "\n"
        "Sehr geehrte Damen und Herren,\n"
        "\n"
        "bei der Durchsicht unserer Bankkontobewegungen ist uns aufgefallen,\n"
        "dass wir für die folgende Abbuchung bislang noch keine Rechnung erhalten haben:\n"
        "\n"
        "  • Buchungstag:   {buchungstag}\n"
        "  • Empfänger:     {empfaenger}\n"
        "  • Betrag:        {betrag:.2f} EUR\n"
        "  • Verwendungszweck: {verwendungszweck}\n"
        "\n"
        "Wir bitten Sie, uns die zugehörige Rechnung schnellstmöglich zukommen\n"
        "zu lassen — bevorzugt per E-Mail an {restaurant_email} oder per Post\n"
        "an die Ihnen bekannte Adresse.\n"
        "\n"
        "Vielen Dank für Ihre Mühe.\n"
        "\n"
        "{signature}"
    )


# 向后兼容（静态版本，dashboard 也可直接调用 build_* 函数）
EMAIL_SIGNATURE = build_email_signature()
EMAIL_TEMPLATE_DE = build_email_template()


# ╔══════════════════════════════════════════════════════════╗
# ║              日志配置                                     ║
# ╚══════════════════════════════════════════════════════════╝

from logging.handlers import RotatingFileHandler

logger = logging.getLogger("Gastro_Finance")
logger.setLevel(logging.DEBUG if restaurant.demo_mode else logging.WARNING)

# 控制台 handler（仅 WARNING+ 在生产环境）
_console = logging.StreamHandler(sys.stderr)
_console.setLevel(logging.DEBUG if restaurant.demo_mode else logging.WARNING)
_console.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
))
logger.addHandler(_console)

# 文件 handler（WARNING+，自动轮转）
_file_handler = RotatingFileHandler(
    DIR_LOGS / "gastro_finance.log",
    maxBytes=10 * 1024 * 1024,  # 10MB
    backupCount=30,
    encoding="utf-8",
)
_file_handler.setLevel(logging.WARNING)
_file_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
))
logger.addHandler(_file_handler)
