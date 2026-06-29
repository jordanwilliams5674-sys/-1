from __future__ import annotations

import re
import unittest
from pathlib import Path

from beidou_us_radar.core.dashboard_bridge import load_actual_holdings


ROOT = Path(__file__).resolve().parents[2]
HOLDINGS_CONFIG = ROOT / "config" / "holdings.yaml"
WATCHLIST_CONFIG = ROOT / "config" / "watchlist.yaml"
RULES_CONFIG = ROOT / "config" / "beidou_investment_rules.yaml"
TEMPLATE = ROOT / "templates" / "beidou_daily_email.md"


def section_text(text: str, section: str) -> str:
    match = re.search(rf"^\s{{2}}{section}:\s*$", text, flags=re.M)
    if not match:
        return ""
    tail = text[match.end() :]
    stop = re.search(r"^\s{2}[a-z_]+:\s*$", tail, flags=re.M)
    return tail[: stop.start()] if stop else tail


class InvestmentSystemConfigTest(unittest.TestCase):
    def test_confirmed_us_holdings_are_actual_and_old_names_are_not(self) -> None:
        actual = load_actual_holdings()
        self.assertTrue({"NVDA", "SOXS", "CRCL", "AEP", "AMKR", "KO"}.issubset(actual))
        self.assertFalse({"INTC", "MRVL", "RGTI", "SQQQ"} & actual)

    def test_holding_config_contains_nine_confirmed_research_labels(self) -> None:
        text = HOLDINGS_CONFIG.read_text(encoding="utf-8")
        for symbol in ["NVDA", "SOXS", "CRCL", "AEP", "AMKR", "KO", "HK_DAJIN_HEAVY", "HK_LENS_TECH", "HK_CHAOQI_TECH"]:
            self.assertIn(f"ticker: {symbol}", text)
        self.assertEqual(text.count("holding_status: actual_holding"), 9)
        for protected in ["INTC", "MRVL", "RGTI", "SQQQ"]:
            self.assertRegex(text, rf"ticker: {protected}[\s\S]*?allowed_status: watchlist_or_historical")

    def test_watchlist_keeps_protected_symbols_out_of_actual_holding_section(self) -> None:
        text = WATCHLIST_CONFIG.read_text(encoding="utf-8")
        actual_section = section_text(text, "current_actual_holdings")
        watch_section = section_text(text, "watch_pool_pending_confirmation")
        for protected in ["INTC", "MRVL", "RGTI", "SQQQ"]:
            self.assertNotIn(f"ticker: {protected}", actual_section)
            self.assertIn(f"ticker: {protected}", watch_section)

    def test_rules_and_template_preserve_research_only_boundary(self) -> None:
        rules = RULES_CONFIG.read_text(encoding="utf-8")
        template = TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("券商交易接口调用", rules)
        self.assertIn("只读行情源", rules)
        self.assertIn("SOXS 是三倍做空半导体ETF", template)
        self.assertIn("不自动执行买卖", template)
        self.assertIn("INTC：观察池/历史，不是实际持仓", template)
        self.assertIn("MRVL：观察池，不是实际持仓", template)
        self.assertIn("RGTI：观察池/历史，不是实际持仓", template)
        self.assertIn("SQQQ：观察池/历史，不是实际持仓", template)


if __name__ == "__main__":
    unittest.main()
