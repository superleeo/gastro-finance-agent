"""
reconciliation.py — 银行流水对账与缺失发票检测模块
====================================================
读取 input_bank/ 下的 CSV 文件（德语分号格式），识别支出项，
与系统已有发票记录进行模糊比对，生成缺失发票的德语催收邮件草稿。

邮件模板和签名从 config.RestaurantConfig 动态读取，
支持德国任意餐厅品牌。

功能:
  1. parse_bank_csv()        — 解析德语银行 CSV
  2. filter_expenses()       — 过滤支出项
  3. fuzzy_match_invoices()  — 跨发票记录模糊比对
  4. generate_reminder_emails() — 生成德语邮件草稿
  5. run_reconciliation()    — 一键执行全流程
"""

import csv
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

import pandas as pd

from config import (
    DIR_INPUT_BANK,
    DIR_EMAIL_DRAFTS,
    CSV_DELIMITER,
    CSV_DECIMAL,
    CSV_ENCODING,
    BANK_COLUMN_MAP,
    build_email_template,
    build_email_signature,
    restaurant,
    logger,
)


# ============================================================
# 数据结构
# ============================================================

@dataclass
class BankTransaction:
    """单笔银行交易"""
    buchungstag: date
    empfaenger: str
    verwendungszweck: str
    betrag: Decimal       # 正数=收入，负数=支出（按解析逻辑统一）
    waehrung: str = "EUR"
    rohdaten: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_expense(self) -> bool:
        """是否为支出（负数金额即为支出）"""
        return self.betrag < 0

    @property
    def abs_betrag(self) -> Decimal:
        """支出绝对值"""
        return abs(self.betrag)


@dataclass
class InvoiceRecord:
    """系统已有发票记录"""
    invoice_id: str
    lieferant: str           # 供应商名称
    betrag: Decimal
    datum: date
    beschreibung: str = ""
    kategorie: str = ""      # "lieferant" | "dienstleister" | "miete" | ...
    pdf_path: Optional[Path] = None


@dataclass
class MissingInvoice:
    """缺失发票条目"""
    transaction: BankTransaction
    best_match: Optional[InvoiceRecord] = None
    match_score: float = 0.0
    email_sent: bool = False
    email_path: Optional[Path] = None


@dataclass
class ReconciliationReport:
    """对账报告"""
    report_date: date
    total_expenses: int
    matched_count: int
    missing_count: int
    missing_invoices: List[MissingInvoice] = field(default_factory=list)
    summary_text: str = ""


# ============================================================
# 银行 CSV 解析
# ============================================================

def _detect_encoding(file_path: Path) -> str:
    """检测 CSV 文件编码"""
    try:
        import chardet
        raw = file_path.read_bytes()
        result = chardet.detect(raw)
        logger.info(f"编码检测: {result['encoding']} (置信度 {result['confidence']:.0%})")
        return result["encoding"] or CSV_ENCODING
    except ImportError:
        return CSV_ENCODING


def _normalize_column_name(col: str) -> str:
    """规范化列名（小写、去重音、去空格）"""
    col = col.strip().lower()
    col = unicodedata.normalize("NFKD", col).encode("ascii", "ignore").decode("ascii")
    return col


def _find_column(df_columns: List[str], candidates: List[str]) -> Optional[str]:
    """在 DataFrame 列中匹配候选列名"""
    norm_map = {_normalize_column_name(c): c for c in df_columns}
    for cand in candidates:
        norm_cand = _normalize_column_name(cand)
        if norm_cand in norm_map:
            return norm_map[norm_cand]
    # 模糊匹配
    for cand in candidates:
        norm_cand = _normalize_column_name(cand)
        for norm_col, orig_col in norm_map.items():
            if norm_cand in norm_col or norm_col in norm_cand:
                return orig_col
    return None


def _parse_german_number(raw: str) -> Decimal | None:
    """
    解析德语数字格式，支持多种银行格式。
    - 1.234,56 → Decimal("1234.56")
    - -1.234,56 → Decimal("-1234.56")
    - 1.234,56- → Decimal("-1234.56")  (DTAUS 尾置负号)
    返回 None 表示无法解析（调用方应跳过该交易）。
    """
    if not isinstance(raw, str):
        raw = str(raw)
    raw = raw.strip().replace("€", "").replace("EUR", "").strip()
    if not raw:
        return None
    # 检测符号：支持前置 "-" 和 DTAUS 尾置 "-" 两种格式
    is_negative = raw.startswith("-") or raw.endswith("-")
    raw = raw.strip("-").strip()
    # 去掉千位分隔符（德语是点）
    raw = raw.replace(".", "")
    # 逗号 → 小数点
    raw = raw.replace(",", ".")
    try:
        value = Decimal(raw)
    except Exception:
        logger.warning(f"无法解析数字: {raw!r}")
        return None
    return -value if is_negative else value


def parse_bank_csv(file_path: Path) -> List[BankTransaction]:
    """
    解析德语银行 CSV 文件。

    支持的格式:
    - 分号分隔 (;)
    - 包含 Buchungstag, Empfänger/Zahlungspflichtiger, Verwendungszweck, Betrag 等列
    - 金额可能为德语格式 1.234,56 或 -1.234,56
    """
    encoding = _detect_encoding(file_path)
    transactions: List[BankTransaction] = []

    try:
        df = pd.read_csv(
            file_path,
            sep=CSV_DELIMITER,
            encoding=encoding,
            dtype=str,
            skip_blank_lines=True,
        )
    except Exception:
        # 回退：尝试逗号分隔
        try:
            df = pd.read_csv(file_path, sep=",", encoding=encoding, dtype=str)
        except Exception as exc:
            logger.error(f"无法解析 CSV 文件 {file_path.name}: {exc}")
            return []

    df = df.dropna(how="all")  # 去掉全空行
    columns = list(df.columns)

    # 列映射
    col_buchungstag = _find_column(columns, BANK_COLUMN_MAP["buchungstag"])
    col_empfaenger = _find_column(columns, BANK_COLUMN_MAP["empfaenger"])
    col_verwendungszweck = _find_column(columns, BANK_COLUMN_MAP["verwendungszweck"])
    col_betrag = _find_column(columns, BANK_COLUMN_MAP["betrag"])
    col_waehrung = _find_column(columns, BANK_COLUMN_MAP["waehrung"])

    if not col_betrag:
        logger.error(f"找不到金额列，可用列: {columns}")
        return []

    logger.info(f"列映射: Datum={col_buchungstag}, Empfänger={col_empfaenger}, "
                f"Betrag={col_betrag}, VWZ={col_verwendungszweck}")

    for idx, row in df.iterrows():
        try:
            # 解析日期
            if col_buchungstag:
                raw_date = str(row.get(col_buchungstag, ""))
                try:
                    buchungstag = pd.to_datetime(raw_date, dayfirst=True).date()
                except Exception:
                    logger.debug(f"跳过行 {idx}: 无法解析日期 {raw_date}")
                    continue
            else:
                buchungstag = date.today()

            # 解析金额
            raw_betrag = row.get(col_betrag, "")
            betrag = _parse_german_number(str(raw_betrag))

            # 跳过无法解析或金额为 0 的行
            if betrag is None:
                logger.debug(f"跳过行 {idx}: 无法解析金额 {raw_betrag!r}")
                continue
            if betrag == 0:
                continue

            # 收款人
            empfaenger = (
                str(row.get(col_empfaenger, "")).strip()
                if col_empfaenger
                else ""
            )

            # 用途
            verwendungszweck = (
                str(row.get(col_verwendungszweck, "")).strip()
                if col_verwendungszweck
                else ""
            )

            # 币种
            waehrung = (
                str(row.get(col_waehrung, "EUR")).strip()
                if col_waehrung
                else "EUR"
            )

            txn = BankTransaction(
                buchungstag=buchungstag,
                empfaenger=empfaenger,
                verwendungszweck=verwendungszweck,
                betrag=betrag,
                waehrung=waehrung,
                rohdaten=row.to_dict(),
            )
            transactions.append(txn)

        except Exception as exc:
            logger.warning(f"跳过行 {idx}: {exc}")
            continue

    logger.info(f"解析完成: {len(transactions)} 笔交易")
    return transactions


def filter_expenses(transactions: List[BankTransaction],
                    min_amount: Decimal = Decimal("0")) -> List[BankTransaction]:
    """过滤出支出项"""
    expenses = [t for t in transactions if t.is_expense and t.abs_betrag > min_amount]
    logger.info(f"支出项: {len(expenses)} / {len(transactions)}")
    return expenses


# ============================================================
# 模糊比对引擎
# ============================================================

def _normalize_text(text: str) -> str:
    """文本规范化：小写、去重音、去特殊字符、去多余空格"""
    text = text.lower().strip()
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _tokenize(text: str) -> Set[str]:
    """分词"""
    return set(_normalize_text(text).split())


def _fuzzy_score(text_a: str, text_b: str) -> float:
    """
    计算两个文本的模糊匹配分 (0.0 ~ 1.0)。
    结合 Jaccard 相似度 + 子串包含加分。
    """
    if not text_a or not text_b:
        return 0.0

    tokens_a = _tokenize(text_a)
    tokens_b = _tokenize(text_b)

    if not tokens_a or not tokens_b:
        return 0.0

    # Jaccard 相似度
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    jaccard = len(intersection) / len(union) if union else 0.0

    # 子串加分
    norm_a = _normalize_text(text_a)
    norm_b = _normalize_text(text_b)
    substring_bonus = 0.0
    if len(norm_a) >= 4 and norm_a in norm_b:
        substring_bonus = 0.3
    elif len(norm_b) >= 4 and norm_b in norm_a:
        substring_bonus = 0.3

    # 金额匹配加分（如果有）
    amount_bonus = 0.0
    # 在文本中查找金额模式 xx,xx 或 xx.xx
    amounts_a = set(re.findall(r"(\d+[.,]\d{2})", text_a))
    amounts_b = set(re.findall(r"(\d+[.,]\d{2})", text_b))
    if amounts_a and amounts_b and amounts_a & amounts_b:
        amount_bonus = 0.4

    score = jaccard * 0.6 + substring_bonus + amount_bonus
    return min(score, 1.0)


def fuzzy_match_invoices(
    expenses: List[BankTransaction],
    invoices: List[InvoiceRecord],
    min_score: float = 0.4,
) -> Tuple[List[MissingInvoice], int]:
    """
    对支出项与发票记录进行模糊比对。

    对每笔支出，计算与所有发票的匹配分，取最高分。
    低于 min_score 的视为缺失发票。

    返回: (缺失发票列表, 已匹配数量)
    """
    missing: List[MissingInvoice] = []
    matched_count = 0

    for txn in expenses:
        best_score = 0.0
        best_match: Optional[InvoiceRecord] = None

        # 组合交易的可搜索文本
        txn_text = f"{txn.empfaenger} {txn.verwendungszweck} {txn.abs_betrag}"

        for inv in invoices:
            inv_text = f"{inv.lieferant} {inv.beschreibung} {inv.betrag} {inv.invoice_id}"
            score = _fuzzy_score(txn_text, inv_text)
            if score > best_score:
                best_score = score
                best_match = inv

        if best_score >= min_score:
            matched_count += 1
            logger.debug(
                f"✓ 匹配: {txn.empfaenger} [{txn.abs_betrag}€] "
                f"↔ {best_match.lieferant} [{best_match.betrag}€] "
                f"(得分 {best_score:.2f})"
            )
        else:
            missing.append(MissingInvoice(
                transaction=txn,
                best_match=best_match,
                match_score=best_score,
            ))
            logger.info(
                f"✗ 缺失发票: *** [{txn.abs_betrag}€] "
                f"(最高匹配得分 {best_score:.2f})"
            )
            logger.debug(
                f"  详情: {txn.empfaenger} | "
                f"{best_match.lieferant if best_match else '无匹配'}"
            )

    logger.info(f"匹配结果: {matched_count} 已匹配, {len(missing)} 缺失")
    return missing, matched_count


# ============================================================
# 邮件草稿生成
# ============================================================

def generate_reminder_emails(
    missing_invoices: List[MissingInvoice],
    output_dir: Optional[Path] = None,
) -> List[MissingInvoice]:
    """
    为每条缺失发票生成德语催收邮件 .txt 草稿。

    文件命名: {日期}_{收款人}_reminder.txt
    """
    if output_dir is None:
        output_dir = DIR_EMAIL_DRAFTS

    output_dir.mkdir(parents=True, exist_ok=True)

    for mi in missing_invoices:
        txn = mi.transaction
        # 安全文件名
        safe_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", txn.empfaenger)[:50]
        filename = f"{txn.buchungstag.isoformat()}_{safe_name}_reminder.txt"
        file_path = output_dir / filename

        body = build_email_template().format(
            empfaenger=txn.empfaenger,
            buchungstag=txn.buchungstag.isoformat(),
            betrag=float(txn.abs_betrag),
            verwendungszweck=txn.verwendungszweck or "(nicht angegeben)",
            restaurant_email=restaurant.email,
            signature=build_email_signature(),
        )

        file_path.write_text(body, encoding="utf-8")
        mi.email_sent = True
        mi.email_path = file_path
        logger.info(f"邮件草稿已生成: {file_path}")

    return missing_invoices


# ============================================================
# 一键对账
# ============================================================

def run_reconciliation(
    invoices: Optional[List[InvoiceRecord]] = None,
    bank_dir: Optional[Path] = None,
    generate_emails: bool = True,
) -> ReconciliationReport:
    """
    一键执行完整对账流程:
      1. 扫描 input_bank/ 下所有 CSV
      2. 解析并过滤支出项
      3. 与发票记录模糊比对
      4. 生成催收邮件草稿

    参数
    ----
    invoices : 发票记录列表（若为 None 则使用 Mock 数据）
    bank_dir : 银行 CSV 目录
    generate_emails : 是否生成邮件

    返回
    ----
    ReconciliationReport
    """
    if bank_dir is None:
        bank_dir = DIR_INPUT_BANK

    if invoices is None:
        invoices = _get_mock_invoices()

    all_expenses: List[BankTransaction] = []
    all_missing: List[MissingInvoice] = []
    matched_total = 0

    # 扫描银行目录
    csv_files = sorted(bank_dir.glob("*.csv"))
    if not csv_files:
        logger.warning(f"在 {bank_dir} 中未找到 CSV 文件")

    for csv_file in csv_files:
        logger.info(f"处理银行文件: {csv_file.name}")
        transactions = parse_bank_csv(csv_file)
        expenses = filter_expenses(transactions)
        all_expenses.extend(expenses)

    # 模糊比对
    if all_expenses:
        missing, matched = fuzzy_match_invoices(all_expenses, invoices)
        all_missing.extend(missing)
        matched_total += matched

    # 生成邮件
    if generate_emails and all_missing:
        generate_reminder_emails(all_missing)

    # 生成摘要
    report = ReconciliationReport(
        report_date=date.today(),
        total_expenses=len(all_expenses),
        matched_count=matched_total,
        missing_count=len(all_missing),
        missing_invoices=all_missing,
    )

    report.summary_text = (
        f"===== 对账报告 {report.report_date} =====\n"
        f"  支出总笔数: {report.total_expenses}\n"
        f"  已匹配:     {report.matched_count}\n"
        f"  缺失发票:   {report.missing_count}\n"
        f"{'=' * 40}\n"
    )
    for mi in all_missing:
        txn = mi.transaction
        report.summary_text += (
            f"  • {txn.buchungstag} | {txn.empfaenger} | {txn.abs_betrag:.2f} EUR" +
            (f"  → 邮件已生成" if mi.email_sent else "") + "\n"
        )

    # 仅输出不含敏感数据的摘要日志
    logger.info(
        "对账完成: %d 笔支出, %d 已匹配, %d 缺失发票",
        report.total_expenses, report.matched_count, report.missing_count,
    )
    logger.debug(report.summary_text)
    return report


# ============================================================
# Mock 发票数据（用于测试）
# ============================================================

def _get_mock_invoices() -> List[InvoiceRecord]:
    """Mock 发票记录 — 模拟系统已有发票"""
    return [
        InvoiceRecord(
            invoice_id="INV-2026-001",
            lieferant="Deutsche Getränke GmbH",
            betrag=Decimal("345.00"),
            datum=date(2026, 6, 1),
            beschreibung="Getränkelieferung Juni Woche 1",
            kategorie="getraenke",
            pdf_path=None,
        ),
        InvoiceRecord(
            invoice_id="INV-2026-002",
            lieferant="Metro C&C Düsseldorf",
            betrag=Decimal("1240.00"),
            datum=date(2026, 6, 2),
            beschreibung="Lebensmittel Großhandel",
            kategorie="speisen",
            pdf_path=None,
        ),
        InvoiceRecord(
            invoice_id="INV-2026-003",
            lieferant="Fischhandel Nordsee GmbH",
            betrag=Decimal("580.00"),
            datum=date(2026, 6, 3),
            beschreibung="Frischfisch Lieferung Sashimi",
            kategorie="speisen",
            pdf_path=None,
        ),
        InvoiceRecord(
            invoice_id="INV-2026-004",
            lieferant="Energie AG",
            betrag=Decimal("450.00"),
            datum=date(2026, 6, 1),
            beschreibung="Strom Abschlag Juni 2026",
            kategorie="versorgung",
            pdf_path=None,
        ),
        InvoiceRecord(
            invoice_id="INV-2026-005",
            lieferant="Brauerei Himmel",
            betrag=Decimal("210.00"),
            datum=date(2026, 6, 4),
            beschreibung="Fassbier Lieferung",
            kategorie="getraenke",
            pdf_path=None,
        ),
        InvoiceRecord(
            invoice_id="INV-2026-006",
            lieferant="Gemüsehof Niederrhein",
            betrag=Decimal("320.00"),
            datum=date(2026, 6, 5),
            beschreibung="Gemüse und Obst Lieferung",
            kategorie="speisen",
            pdf_path=None,
        ),
    ]


# ============================================================
# Quick-test / Demo
# ============================================================

def demo():
    """
    用 Mock 银行 CSV 模拟对账全流程。
    使用临时目录，不污染真实 input_bank/ 目录。
    """
    import tempfile
    from config import restaurant as cfg

    with tempfile.TemporaryDirectory() as tmpdir:
        demo_csv = Path(tmpdir) / "_demo_bank.csv"
        demo_csv.write_text(
            "Buchungstag;Empfänger/Zahlungspflichtiger;Verwendungszweck;Betrag;Währung\r\n"
            "01.06.2026;Deutsche Getränke GmbH;Rechnung 2026-0451 Getränke;-345,00;EUR\r\n"
            "02.06.2026;Metro C&C Düsseldorf;Einkauf Lebensmittel;-1.240,00;EUR\r\n"
            "03.06.2026;Fischhandel Nordsee GmbH;Rechnung 8842 Sashimi Fisch;-580,00;EUR\r\n"
            "04.06.2026;Unbekannter Lieferant XYZ;Keine Rechnung erhalten;-156,80;EUR\r\n"
            "05.06.2026;Energie AG;Strom Abschlag Juni;-450,00;EUR\r\n"
            "06.06.2026;IT Systemhaus Berlin;Wartung Kassensystem MR-003;-299,00;EUR\r\n"
            "07.06.2026;GastroClean Service;Küchenreinigung 06/2026;-180,00;EUR\r\n",
            encoding="utf-8",
        )

        print("=" * 60)
        print(f"Gastro Finance Agent — Reconciliation Demo")
        print(f"Restaurant: {cfg.name}  |  Email: {cfg.email}")
        print("=" * 60)

        # 用临时目录执行对账
        report = run_reconciliation(bank_dir=Path(tmpdir))

        print(report.summary_text)
        print(f"\n邮件草稿目录: {DIR_EMAIL_DRAFTS}")
        for f in sorted(DIR_EMAIL_DRAFTS.glob("*.txt")):
            print(f"  📧 {f.name}")

        print("\n✓ Demo 完成")
        return report


if __name__ == "__main__":
    demo()
