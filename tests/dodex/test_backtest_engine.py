from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dodex.config.default_config import build_default_config
from dodex.trading.audit.audit_log import AuditLog
from dodex.trading.backtest.backtest_engine import BacktestEngine
from dodex.trading.market_data.mock_market_data_provider import MockMarketDataProvider
from dodex.trading.risk.risk_manager import RiskManager
from dodex.trading.strategy.sample_moving_average_strategy import SampleMovingAverageStrategy


class BacktestEngineTest(unittest.TestCase):
    def test_mock_backtest_executes_buy_signal_through_risk_manager(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = build_default_config(Path(temp_dir))
            engine = BacktestEngine(
                market_data_provider=MockMarketDataProvider(),
                strategy=SampleMovingAverageStrategy(),
                risk_manager=RiskManager(config.risk),
                audit_log=AuditLog(config.audit_log_path),
                config=config,
            )

            result = engine.run("AAPL")

            self.assertEqual(result.symbol, "AAPL")
            self.assertEqual(result.metrics.trade_count, 1)
            self.assertEqual(result.trades[0].side, "buy")
            self.assertEqual(result.rejected_signals, [])
            self.assertTrue(config.audit_log_path.exists())


if __name__ == "__main__":
    unittest.main()
