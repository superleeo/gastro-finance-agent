<p align="center">
  <img src="https://img.shields.io/badge/version-1.0.0-003527?style=flat-square" alt="version">
  <img src="https://img.shields.io/badge/python-3.11+-blue?style=flat-square" alt="python">
  <img src="https://img.shields.io/badge/license-MIT-green?style=flat-square" alt="license">
  <img src="https://img.shields.io/badge/tests-39%20passed-brightgreen?style=flat-square" alt="tests">
  <img src="https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey?style=flat-square" alt="platform">
</p>

<h1 align="center">🍽️ Gastro Finance Agent</h1>
<p align="center"><strong>Autonome Finanzautomatisierung & KI-Visualisierung für die deutsche Gastronomie</strong></p>
<p align="center"><strong>Autonomous Financial Automation & AI Visualization for German Restaurants</strong></p>
<p align="center"><strong>德国餐饮业自主财务自动化与 AI 可视化系统</strong></p>

---

## 📖 Inhalt / Table of Contents / 目录

- [🇩🇪 Deutsch](#-deutsch) — Zielgruppe, Funktionen, Installation
- [🇬🇧 English](#-english) — Target Audience, Features, Architecture
- [🇨🇳 中文](#-中文) — 适用人群、功能架构、使用方法

---

# 🇩🇪 Deutsch

## 🎯 Zielgruppe

Gastro Finance Agent wurde **für Restaurantbetreiber in Deutschland** entwickelt — vom kleinen Familienimbiss bis zum mittelständischen Gastronomiebetrieb mit mehreren Filialen.

| Zielgruppe | Warum? |
|------------|--------|
| **Selbstständige Gastronomen** | Automatische Buchhaltung ohne Steuerberater-Wartezeiten |
| **Restaurant-Manager** | Echtzeit-Überblick über Umsatz, Kosten, Gewinn |
| **Steuerberater / Buchhalter** | Strukturierte Daten für UStVA & Jahresabschluss |
| **GmbH-Gesellschafter** | Steueroptimierung: GmbH vs. Einzelunternehmen simulieren |
| **Café- & Bar-Betreiber** | 7% / 19% USt-Trennung nach §12 UStG |

## 🚀 Funktionen

| Kategorie | Funktion |
|-----------|----------|
| **📸 Z-Bon Parser** | Lokales VLM (Vision Language Model) extrahiert Kassenzettel → autom. Finanzvalidierung |
| **🏦 Bankabgleich** | Automatischer CSV-Import (Deutsche Bank, Sparkasse, Commerzbank) → Fuzzy-Matching mit Lieferantenrechnungen |
| **📧 Mahnwesen** | Fehlende Rechnungen automatisch erkennen → deutsche Mahn-E-Mails generieren |
| **📊 Finanz-Dashboard** | 5-seitiges Streamlit-Dashboard: Übersicht, Abgleich, Lieferanten, Aufgaben, Steuern |
| **📈 Finanzanalyse** | Tages-/Wochen-/Monats-/Jahres-Visualisierung mit Altair-Charts: Umsatz, Kosten, EBITDA, Marge |
| **🧾 Steuerrechner** | GmbH vs. Einzelunternehmen Vergleich: KSt, GewSt, ESt, Soli |
| **🤖 KI-Empfehlungen** | Automatische Analyse: Margen-Warnungen, Kostenoptimierung, Steuertipps |
| **🇩🇪 GoBD-konform** | Log-Rotation, Prüfpfade, unveränderbare Archivierung |

## 🏗 Architektur

```
Gastro_Finance_Agent/
├── config.py              ← Restaurant-Profil (Name, Email, Tel) via ENV
├── zbon_parser.py         ← VLM Z-Bon Parser + finanzmathematische Validierung
├── reconciliation.py      ← Bankabgleich + Fuzzy-Matching + E-Mail-Generator
├── dashboard.py           ← Streamlit 6-Seiten MD3 Dashboard
├── finanz_dashboard.py    ← Finanzvisualisierung & KI-Analyse
├── financial_analytics.py ← Steuerrechner (GmbH/Einzel), Zeitreihen
├── vlm_schema.py          ← Pydantic V2 Schema für VLM-Input
├── services.py            ← Business-Logik Service-Schicht + DI
├── tax_report.py          ← UStVA-Export (ELSTER KZ 81/86/35/36)
├── tests/                 ← 39 Unit-Tests (pytest)
├── input_raw/             ← Kassenbon-Fotos
├── input_bank/            ← Bank CSV-Dateien
├── output/                ← Excel/PDF Berichte
├── email_drafts/          ← Mahn-E-Mails (.txt)
└── logs/                  ← Rotierende Logs (10MB × 30)
```

## 📦 Installation

```bash
# 1. Repository klonen
git clone https://github.com/dein-username/gastro-finance-agent.git
cd gastro-finance-agent

# 2. Abhängigkeiten installieren
pip install -r requirements.txt

# 3. Restaurant konfigurieren
cp .env.example .env
# .env bearbeiten: Name, E-Mail, Telefon eintragen

# 4. Demo-Modus starten
GASTRO_DEMO_MODE=1 streamlit run dashboard.py

# 5. Tests ausführen
python3 -m pytest tests/ -v
```

## ⚙️ Konfiguration

```bash
# .env Datei
GASTRO_RESTAURANT_NAME="Zum Goldenen Hirsch"
GASTRO_RESTAURANT_EMAIL="steuer@hirsch-gastro.de"
GASTRO_RESTAURANT_PHONE="+49 (0)30 1234567"
GASTRO_RESTAURANT_ADDRESS="Musterstraße 1, 10115 Berlin"
GASTRO_DEMO_MODE=1   # 1 = Demo-Daten, 0 = Produktion
```

## 🇩🇪 Steuersätze (Deutschland 2026)

| Kategorie | Steuersatz | § UStG |
|-----------|-----------|--------|
| Speisen / Lebensmittel | **7%** | §12 Abs. 2 Nr. 1 |
| Getränke / Alkohol | **19%** | §12 Abs. 1 |
| Körperschaftsteuer (GmbH) | 15% | KStG |
| Solidaritätszuschlag | 5.5% × KSt | SolZG |
| Gewerbesteuer | 3.5% × Hebesatz (~400%) | GewStG |
| Einkommensteuer (Einzel) | 14%–45% progressiv | EStG |

---

# 🇬🇧 English

## 🎯 Target Audience

Gastro Finance Agent is built **for restaurant operators in Germany** — from small family-run bistros to mid-sized hospitality businesses with multiple locations.

| Audience | Value Proposition |
|----------|-------------------|
| **Independent Restaurateurs** | Automated bookkeeping without waiting for tax advisors |
| **Restaurant Managers** | Real-time revenue, cost, and profit visibility |
| **Tax Advisors / Accountants** | Structured data for VAT returns & annual statements |
| **GmbH Shareholders** | Tax optimization: simulate GmbH vs. sole proprietorship |
| **Café & Bar Operators** | 7% / 19% VAT separation per German tax law |

## 🚀 Key Features

| Category | Feature |
|----------|---------|
| **📸 Z-Bon Parser** | Local VLM extracts receipt items → automated financial math validation (net + tax = gross ± €0.02) |
| **🏦 Bank Reconciliation** | CSV import (Deutsche Bank, Sparkasse, Commerzbank) → fuzzy matching against supplier invoices |
| **📧 Automated Reminders** | Missing invoices auto-detected → German-language reminder emails generated |
| **📊 Finance Dashboard** | 6-page Material Design 3 Streamlit app: Overview, Reconciliation, Suppliers, Tasks, Tax Reports, Financial Analytics |
| **📈 Analytics** | Day/Week/Month/Year visualization with Altair charts: revenue composition, cost breakdown, EBITDA trends |
| **🧾 Tax Calculator** | GmbH vs. Sole Proprietorship comparison: corporate tax, trade tax, income tax, solidarity surcharge |
| **🤖 AI Recommendations** | Automated insights: margin alerts, cost optimization suggestions, tax planning |
| **🇩🇪 GoBD Compliant** | Log rotation, audit trails, immutable archiving |

## 📦 Quick Start

```bash
git clone https://github.com/dein-username/gastro-finance-agent.git
cd gastro-finance-agent
pip install -r requirements.txt
cp .env.example .env
GASTRO_DEMO_MODE=1 streamlit run dashboard.py
```

## 🧪 Testing

```bash
python3 -m pytest tests/ -v    # 39 tests in 0.09s
python3 -m zbon_parser          # Z-Bon parser demo
python3 -m reconciliation       # Bank reconciliation demo
python3 -m financial_analytics  # Tax & analytics demo
```

## 🔧 Tech Stack

`Python 3.11+` · `Streamlit` · `Altair` · `Pandas` · `Pydantic V2` · `OpenPyXL` · `Decimal` (exact financial math) · `pytest`

---

# 🇨🇳 中文

## 🎯 适用人群

Gastro Finance Agent 专为**德国餐饮业经营者**打造——从家庭式小餐馆到多分店的中型餐饮企业。

| 用户类型 | 核心价值 |
|----------|----------|
| **独立餐厅老板** | 自动化记账，无需等待税务顾问 |
| **餐厅经理** | 实时掌握营业额、成本、利润 |
| **税务顾问/会计师** | 结构化数据直接用于增值税预申报和年报 |
| **GmbH 股东** | 税务优化：模拟 GmbH vs 个体经营对比 |
| **咖啡馆/酒吧经营者** | 精准分离 7% 食品税和 19% 饮品税 |

## 🚀 核心功能

| 模块 | 功能说明 |
|------|----------|
| **📸 小票解析** | 本地 VLM 视觉模型提取收据 → 自动财务校验（净值+税额=总额，误差<€0.02） |
| **🏦 银行对账** | 导入德国银行 CSV（德意志银行/Sparkasse/Commerzbank）→ 与供应商发票模糊匹配 |
| **📧 自动催收** | 自动检测缺失发票 → 生成标准德语催收邮件 |
| **📊 财务看板** | 6 页 Material Design 3 Streamlit 界面：概览、对账、供应商、任务、税务、财务分析 |
| **📈 可视化分析** | 日/周/月/年可视化：营业额构成饼图、成本结构柱状图、EBITDA 趋势折线图 |
| **🧾 税务计算器** | GmbH vs 个体经营双模式对比：公司税、营业税、个人所得税、团结附加税 |
| **🤖 AI 智能建议** | 自动分析：利润率预警、成本优化建议、税务规划 |
| **🇩🇪 GoBD 合规** | 日志轮转、审计追踪、不可篡改归档 |

## 📦 安装使用

```bash
# 1. 克隆仓库
git clone https://github.com/dein-username/gastro-finance-agent.git
cd gastro-finance-agent

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置餐厅信息
cp .env.example .env
# 编辑 .env：填写餐厅名称、邮箱、电话

# 4. 演示模式启动（含 365 天模拟数据）
GASTRO_DEMO_MODE=1 streamlit run dashboard.py

# 5. 运行测试
python3 -m pytest tests/ -v   # 39 个测试，0.09 秒通过
```

## 🏗 系统架构

```
数据输入层          业务逻辑层                展示层
┌──────────┐      ┌──────────────┐      ┌──────────────┐
│ 小票照片  │  →   │ zbon_parser  │  →   │              │
│ 银行 CSV  │  →   │reconciliation│  →   │  Streamlit   │
│ 发票 CSV  │  →   │  services    │  →   │  Dashboard   │
│ 环境变量  │  →   │   config     │  →   │  6 页交互    │
└──────────┘      │  tax_report   │      │  Altair 图表  │
                  │finanz_analytics│     └──────────────┘
                  │  vlm_schema   │
                  └──────────────┘
```

## 🇩🇪 德国餐饮税务速查 (2026)

| 税种 | 税率 | 法律依据 |
|------|------|----------|
| 食品增值税 | **7%** | §12 Abs. 2 Nr. 1 UStG |
| 饮品增值税 | **19%** | §12 Abs. 1 UStG |
| 公司所得税 (GmbH) | 15% | KStG |
| 团结附加税 | 5.5% × 公司税 | SolZG |
| 营业税 | 3.5% × 稽征率 (~400%) | GewStG |
| 个人所得税 (个体) | 14%–45% 累进 | EStG |

---

## 📄 Lizenz / License / 许可

MIT License — frei für kommerzielle und private Nutzung.

---

<p align="center">
  <sub>Built with ❤️ for the German gastronomy industry · 2026</sub>
</p>
