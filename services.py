"""
services.py — 业务服务层
=========================
封装跨模块的业务流程，提供统一的服务接口给 Dashboard 调用。
消除重复的 run_reconciliation() + session-state 更新逻辑。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol, Tuple

import pandas as pd

from config import (
    DIR_INPUT_BANK,
    DIR_EMAIL_DRAFTS,
    DIR_OUTPUT,
    TAX_RATE_SPEISEN,
    TAX_RATE_GETRAENKE,
    restaurant as _restaurant_cfg,
    logger,
)
from reconciliation import (
    BankTransaction,
    InvoiceRecord,
    MissingInvoice,
    ReconciliationReport,
    parse_bank_csv,
    filter_expenses,
    fuzzy_match_invoices,
    generate_reminder_emails,
    run_reconciliation,
    _get_mock_invoices,
)


# ╔══════════════════════════════════════════════════════════════╗
# ║                   AppConfig (DI)                           ║
# ╚══════════════════════════════════════════════════════════════╝

@dataclass
class AppConfig:
    """可注入的应用配置，替代模块级全局变量。"""
    tax_rate_speisen: Decimal = Decimal(str(TAX_RATE_SPEISEN))
    tax_rate_getraenke: Decimal = Decimal(str(TAX_RATE_GETRAENKE))
    finance_tolerance: Decimal = Decimal("0.02")
    restaurant_email: str = _restaurant_cfg.email
    dir_input_bank: Path = DIR_INPUT_BANK
    dir_email_drafts: Path = DIR_EMAIL_DRAFTS
    dir_output: Path = DIR_OUTPUT
    demo_mode: bool = False


# ╔══════════════════════════════════════════════════════════════╗
# ║                   ReconciliationService                    ║
# ╚══════════════════════════════════════════════════════════════╝

@dataclass
class ReconciliationResult:
    """对账操作统一返回类型"""
    success: bool
    report: Optional[ReconciliationReport] = None
    missing_invoices: List[MissingInvoice] = field(default_factory=list)
    total_transactions: int = 0
    matched_count: int = 0
    error_message: str = ""


class ReconciliationService:
    """
    银行对账服务 — 所有 Dashboard 页面对账操作的统一入口。

    使用方式:
        svc = ReconciliationService(progress_callback=st.info)
        result = svc.run_full_reconciliation()
        result = svc.reconcile_uploaded_csv(uploaded_bytes, filename)
    """

    def __init__(
        self,
        config: Optional[AppConfig] = None,
        progress_callback: Optional[Callable[[str], None]] = None,
    ):
        self.config = config or AppConfig()
        self._progress = progress_callback or (lambda msg: logger.info(msg))

    # ── 完整对账（使用 input_bank/ 目录下已有文件）──

    def run_full_reconciliation(
        self,
        invoices: Optional[List[InvoiceRecord]] = None,
        generate_emails: bool = True,
    ) -> ReconciliationResult:
        """
        一键执行完整对账流程：扫描目录 → 解析 → 比对 → 生成邮件。

        返回统一的 ReconciliationResult，调用方无需手动管理 session state。
        """
        try:
            if invoices is None:
                invoices = _get_mock_invoices() if self.config.demo_mode else []

            self._progress("正在扫描银行 CSV 文件…")
            report = run_reconciliation(
                invoices=invoices,
                bank_dir=self.config.dir_input_bank,
                generate_emails=generate_emails,
            )

            return ReconciliationResult(
                success=True,
                report=report,
                missing_invoices=report.missing_invoices,
                total_transactions=report.total_expenses,
                matched_count=report.matched_count,
            )
        except Exception as exc:
            logger.exception("对账流程异常")
            return ReconciliationResult(
                success=False,
                error_message=str(exc),
            )

    # ── 上传 CSV 对账 ──

    def reconcile_uploaded_csv(
        self,
        uploaded_bytes: bytes,
        filename: str,
        invoices: Optional[List[InvoiceRecord]] = None,
    ) -> ReconciliationResult:
        """
        解析用户上传的银行 CSV，执行对账。

        uploaded_bytes: 文件原始字节
        filename: 原始文件名（用于日志）
        """
        import tempfile
        tmp_path: Optional[Path] = None

        try:
            if invoices is None:
                invoices = _get_mock_invoices() if self.config.demo_mode else []

            # 安全校验
            if len(uploaded_bytes) == 0:
                return ReconciliationResult(success=False, error_message="上传文件为空")
            if len(uploaded_bytes) > 10 * 1024 * 1024:
                return ReconciliationResult(success=False, error_message="文件超过 10MB 限制")
            if b"\x00" in uploaded_bytes[:512]:
                return ReconciliationResult(success=False, error_message="文件不是有效文本格式")

            # 写入临时文件
            with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="wb") as tmp:
                tmp.write(uploaded_bytes)
                tmp_path = Path(tmp.name)

            self._progress(f"正在解析 {filename}…")
            transactions = parse_bank_csv(tmp_path)
            expenses = filter_expenses(transactions)
            self._progress(f"解析完成: {len(transactions)} 笔交易 ({len(expenses)} 笔支出)")

            # 执行模糊匹配
            missing, matched = fuzzy_match_invoices(expenses, invoices)
            self._progress(f"匹配结果: {matched} 已匹配, {len(missing)} 缺失")

            # 生成邮件
            if missing:
                generate_reminder_emails(missing, output_dir=self.config.dir_email_drafts)
                self._progress(f"已生成 {len(missing)} 封催收邮件")

            report = ReconciliationReport(
                report_date=date.today(),
                total_expenses=len(expenses),
                matched_count=matched,
                missing_count=len(missing),
                missing_invoices=missing,
            )

            return ReconciliationResult(
                success=True,
                report=report,
                missing_invoices=missing,
                total_transactions=len(transactions),
                matched_count=matched,
            )

        except Exception as exc:
            logger.exception("上传 CSV 对账异常")
            return ReconciliationResult(success=False, error_message=str(exc))
        finally:
            if tmp_path is not None:
                try:
                    tmp_path.unlink(missing_ok=True)
                except Exception:
                    pass

    # ── 生成催收邮件 ──

    def generate_emails(
        self, missing_invoices: List[MissingInvoice]
    ) -> int:
        """为缺失发票生成催收邮件，返回生成数量。"""
        if not missing_invoices:
            return 0
        result = generate_reminder_emails(missing_invoices, output_dir=self.config.dir_email_drafts)
        return len(result)

    # ── 导入发票 CSV ──

    @staticmethod
    def load_invoices_from_df(df: pd.DataFrame) -> List[InvoiceRecord]:
        """将 DataFrame 转换为 InvoiceRecord 列表，含安全校验。"""
        records = []
        for idx, row in df.iterrows():
            try:
                inv_date_val = pd.to_datetime(row.get("datum", date.today())).date()
            except Exception:
                inv_date_val = date.today()
            try:
                betrag_raw = str(row.get("betrag", 0)).replace("€", "").replace(",", ".").strip()
                betrag_val = Decimal(betrag_raw)
            except Exception:
                logger.warning(f"跳过发票 #{idx}: 无法解析金额")
                continue

            records.append(InvoiceRecord(
                invoice_id=str(row.get("invoice_id", f"AUTO-{idx}")),
                lieferant=str(row.get("lieferant", row.get("empfaenger", ""))),
                betrag=betrag_val,
                datum=inv_date_val,
                beschreibung=str(row.get("beschreibung", row.get("verwendungszweck", ""))),
                kategorie=str(row.get("kategorie", "")),
            ))
        return records


# ╔══════════════════════════════════════════════════════════════╗
# ║                   Quick Test                                ║
# ╚══════════════════════════════════════════════════════════════╝

if __name__ == "__main__":
    svc = ReconciliationService(config=AppConfig(demo_mode=True))
    result = svc.run_full_reconciliation()
    print(f"Success: {result.success}")
    print(f"Transactions: {result.total_transactions}")
    print(f"Matched: {result.matched_count}")
    print(f"Missing: {len(result.missing_invoices)}")
    for mi in result.missing_invoices:
        txn = mi.transaction
        print(f"  ✗ {txn.buchungstag} | *** | €{txn.abs_betrag:.2f}")
