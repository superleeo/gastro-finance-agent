"""
pdf_parser.py — 德国银行 PDF 对账单解析模块
============================================
支持从 PDF 文件中提取银行交易记录，兼容：
  - 文本型 PDF（Deutsche Bank、Sparkasse、Commerzbank 等主流银行）
  - 可选 OCR 模式（扫描件 → 需要 pytesseract + pdf2image）

数据流：
  PDF 文件 → pdfplumber 提取文本 → 正则匹配交易行 → BankTransaction 列表
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pdfplumber

from config import logger
from reconciliation import BankTransaction, _parse_german_number


# ╔══════════════════════════════════════════════════════════╗
# ║                  德国银行 PDF 格式模式                   ║
# ╚══════════════════════════════════════════════════════════╝

# 德国日期格式: DD.MM.YYYY 或 DD.MM.YY
_DATE_PATTERN = re.compile(r"(\d{2})\.(\d{2})\.(\d{2,4})")

# 金额模式: 1.234,56 或 -1.234,56 或 1.234,56-
_AMOUNT_PATTERN = re.compile(r"(-?\d{1,3}(?:\.\d{3})*,\d{2}-?|-?\d+,\d{2})")

# ── 列头关键词（用于检测表格起始行）──────────────────────
COLUMN_HEADER_KEYWORDS = [
    "buchungstag", "buchungsdatum", "valuta", "empfänger",
    "zahlungspflichtiger", "auftraggeber", "verwendungszweck",
    "buchungstext", "betrag", "umsatz", "wert", "soll", "haben",
    "saldo", "währung",
]

# ── 常见银行 PDF 的列结构模式 ─────────────────────────────
# (date_cols, desc_cols, amount_cols, extra_cols)
BANK_PROFILES = {
    "deutsche_bank": {
        "date_col": 0,
        "desc_cols": [1, 2, 3],   # Empfänger + Verwendungszweck 可能跨多列
        "amount_col": -1,          # 金额在最后一列
        "has_soll_haben": False,
    },
    "sparkasse": {
        "date_col": 0,
        "desc_cols": [1, 2],
        "amount_col": -1,
        "has_soll_haben": True,    # Sparkasse 常用 Soll/Haben 列
    },
    "commerzbank": {
        "date_col": 0,
        "desc_cols": [1, 2],
        "amount_col": 3,
        "has_soll_haben": False,
    },
    "generic": {
        "date_col": 0,
        "desc_cols": [1, 2],
        "amount_col": -1,
        "has_soll_haben": False,
    },
}


# ╔══════════════════════════════════════════════════════════╗
# ║                   Core Parsing                           ║
# ╚══════════════════════════════════════════════════════════╝

def _detect_bank_profile(text: str) -> str:
    """根据 PDF 文本特征自动检测银行类型"""
    text_lower = text.lower()
    if "deutsche bank" in text_lower:
        return "deutsche_bank"
    elif "sparkasse" in text_lower:
        return "sparkasse"
    elif "commerzbank" in text_lower:
        return "commerzbank"
    return "generic"


def _has_column_headers(line: str) -> bool:
    """检查一行是否包含表格列头关键词"""
    line_lower = line.lower().replace(" ", "")
    matches = sum(1 for kw in COLUMN_HEADER_KEYWORDS if kw in line_lower)
    return matches >= 3


def _extract_date(text: str) -> Optional[date]:
    """从文本中提取日期"""
    m = _DATE_PATTERN.search(text)
    if not m:
        return None
    d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if y < 100:
        y += 2000
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def _extract_amounts(text: str) -> List[Decimal]:
    """从文本中提取所有金额"""
    amounts = []
    for match in _AMOUNT_PATTERN.finditer(text):
        raw = match.group(1)
        try:
            val = _parse_german_number(raw)
            if val is not None:
                amounts.append(val)
        except Exception:
            continue
    return amounts


def _parse_transaction_row(row_text: str) -> Optional[BankTransaction]:
    """
    尝试从一行（或几行合并的）文本中解析出一笔交易。
    返回 BankTransaction 或 None。
    """
    # 必须有日期和至少一个金额
    txn_date = _extract_date(row_text)
    if txn_date is None:
        return None

    amounts = _extract_amounts(row_text)
    if not amounts:
        return None

    # 取最大的金额作为交易金额（过滤掉余额等小数字）
    betrag = max(amounts, key=abs)

    # 提取收款人和用途
    # 去掉日期和金额部分后，剩余的就是收款人+用途
    remaining = row_text
    # 去掉第一个日期
    remaining = _DATE_PATTERN.sub("", remaining, count=1)
    # 去掉所有金额
    remaining = _AMOUNT_PATTERN.sub("", remaining)
    remaining = re.sub(r"\s+", " ", remaining).strip()

    # 尝试分割收款人和用途
    parts = [p.strip() for p in remaining.split("  ") if p.strip()]
    if len(parts) >= 2:
        empfaenger = parts[0][:80]
        verwendungszweck = " ".join(parts[1:])[:200]
    else:
        empfaenger = remaining[:80]
        verwendungszweck = ""

    return BankTransaction(
        buchungstag=txn_date,
        empfaenger=empfaenger,
        verwendungszweck=verwendungszweck,
        betrag=betrag,
        waehrung="EUR",
    )


def parse_pdf(file_path: Path, password: Optional[str] = None) -> List[BankTransaction]:
    """
    解析德国银行 PDF 对账单，提取所有交易记录。

    参数
    ----
    file_path : Path
        PDF 文件路径
    password : str or None
        PDF 密码（如果加密）

    返回
    ----
    List[BankTransaction] — 按 Buchungstag 排序的交易列表
    """
    transactions: List[BankTransaction] = []
    seen_dates: set = set()

    try:
        with pdfplumber.open(file_path, password=password) as pdf:
            logger.info(f"PDF 解析: {file_path.name} — {len(pdf.pages)} 页")

            full_text_parts: List[str] = []
            for page_num, page in enumerate(pdf.pages, 1):
                text = page.extract_text()
                if text:
                    full_text_parts.append(text)

            full_text = "\n".join(full_text_parts)
            if not full_text.strip():
                logger.warning(f"PDF 中未提取到文本: {file_path.name}")
                return []

            # 检测银行类型
            bank = _detect_bank_profile(full_text)
            logger.info(f"检测到银行类型: {bank}")

            # 逐行解析
            lines = full_text.split("\n")
            txn_started = False
            current_txn_lines: List[str] = []

            for line in lines:
                line = line.strip()
                if not line:
                    if current_txn_lines:
                        # 空行 = 一笔交易结束
                        combined = " ".join(current_txn_lines)
                        txn = _parse_transaction_row(combined)
                        if txn:
                            key = (txn.buchungstag, txn.empfaenger, txn.betrag)
                            if key not in seen_dates:
                                seen_dates.add(key)
                                transactions.append(txn)
                        current_txn_lines = []
                    continue

                # 检查是否是表格头（跳过）
                if _has_column_headers(line):
                    txn_started = True
                    current_txn_lines = []
                    continue

                if txn_started:
                    # 检查是否是新交易的开始（以日期开头）
                    if _DATE_PATTERN.match(line[:10]):
                        # 保存上一笔
                        if current_txn_lines:
                            combined = " ".join(current_txn_lines)
                            txn = _parse_transaction_row(combined)
                            if txn:
                                key = (txn.buchungstag, txn.empfaenger, txn.betrag)
                                if key not in seen_dates:
                                    seen_dates.add(key)
                                    transactions.append(txn)
                        current_txn_lines = [line]
                    else:
                        # 续行（多行交易描述）
                        current_txn_lines.append(line)

            # 处理最后一笔
            if current_txn_lines:
                combined = " ".join(current_txn_lines)
                txn = _parse_transaction_row(combined)
                if txn:
                    key = (txn.buchungstag, txn.empfaenger, txn.betrag)
                    if key not in seen_dates:
                        transactions.append(txn)

    except Exception as exc:
        logger.error(f"PDF 解析失败: {file_path.name} — {exc}")
        return []

    # 按日期排序
    transactions.sort(key=lambda t: t.buchungstag)
    logger.info(f"PDF 解析完成: {len(transactions)} 笔交易 ({file_path.name})")

    # 输出每笔交易的摘要用于调试
    for t in transactions:
        logger.debug(f"  {t.buchungstag} | {t.empfaenger[:40]} | {t.betrag}€")

    return transactions


# ╔══════════════════════════════════════════════════════════╗
# ║                   OCR Fallback (可选)                    ║
# ╚══════════════════════════════════════════════════════════╝

def parse_scanned_pdf(file_path: Path) -> List[BankTransaction]:
    """
    使用 OCR 解析扫描版 PDF（需要额外安装 pytesseract + pdf2image）。
    如果未安装相关依赖，返回空列表并提示。
    """
    try:
        import pdf2image
        import pytesseract
    except ImportError:
        logger.warning(
            "OCR 依赖未安装。安装命令: pip install pytesseract pdf2image\n"
            "还需要安装系统级 Tesseract: brew install tesseract (macOS)"
        )
        return []

    transactions: List[BankTransaction] = []
    try:
        images = pdf2image.convert_from_path(str(file_path), dpi=300)
        logger.info(f"OCR 模式: {file_path.name} — {len(images)} 页图片")

        for i, img in enumerate(images, 1):
            text = pytesseract.image_to_string(img, lang="deu")
            # 对 OCR 提取的文本逐行做简单解析
            for line in text.split("\n"):
                line = line.strip()
                txn = _parse_transaction_row(line)
                if txn:
                    transactions.append(txn)

        transactions.sort(key=lambda t: t.buchungstag)
        logger.info(f"OCR 解析完成: {len(transactions)} 笔交易")
    except Exception as exc:
        logger.error(f"OCR 解析失败: {exc}")

    return transactions


# ╔══════════════════════════════════════════════════════════╗
# ║                   Unified Entry Point                    ║
# ╚══════════════════════════════════════════════════════════╝

def parse_bank_statement(file_path: Path, use_ocr: bool = False) -> List[BankTransaction]:
    """
    统一的银行对账单解析入口。

    自动检测文件类型:
      - .csv  → 使用 reconciliation.parse_bank_csv()
      - .pdf  → 使用 pdf_parser.parse_pdf()
               → 如无文本则回退到 parse_scanned_pdf() (如果 use_ocr=True)

    参数
    ----
    file_path : Path
        文件路径 (.csv 或 .pdf)
    use_ocr : bool
        是否对扫描件 PDF 启用 OCR

    返回
    ----
    List[BankTransaction]
    """
    suffix = file_path.suffix.lower()

    if suffix == ".csv":
        from reconciliation import parse_bank_csv
        return parse_bank_csv(file_path)

    if suffix == ".pdf":
        result = parse_pdf(file_path)
        if not result and use_ocr:
            logger.info("文本提取为空，尝试 OCR 模式…")
            result = parse_scanned_pdf(file_path)
        return result

    logger.error(f"不支持的文件格式: {suffix}")
    return []


# ╔══════════════════════════════════════════════════════════╗
# ║                   Quick Test                             ║
# ╚══════════════════════════════════════════════════════════╝

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        path = Path(sys.argv[1])
        if path.exists():
            txns = parse_bank_statement(path, use_ocr=True)
            print(f"\n解析结果: {len(txns)} 笔交易\n")
            for t in txns[:10]:
                print(f"  {t.buchungstag} | {t.empfaenger[:50]} | €{t.betrag:,.2f}")
            print(f"\n支出: {sum(1 for t in txns if t.is_expense)} 笔")
            print(f"收入: {sum(1 for t in txns if not t.is_expense)} 笔")
        else:
            print(f"文件不存在: {path}")
    else:
        print("用法: python -m pdf_parser <银行对账单.pdf>")
