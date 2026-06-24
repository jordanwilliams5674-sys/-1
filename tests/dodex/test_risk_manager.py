from __future__ import annotations

import unittest

from dodex.config.types import RiskConfig
from dodex.trading.broker.types import OrderRequest
from dodex.trading.risk.risk_manager import RiskManager


class RiskManagerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = RiskManager(RiskConfig(max_order_notional=1000.0, allowed_symbols=("AAPL",)))

    def test_rejects_zero_quantity(self) -> None:
        decision = self.manager.evaluate(
            OrderRequest("AAPL", "buy", "market", 0, 100.0, "bad", "sample"),
            broker_mode="paper",
        )
        self.assertFalse(decision.allowed)

    def test_rejects_unknown_symbol(self) -> None:
        decision = self.manager.evaluate(
            OrderRequest("TSLA", "buy", "market", 1, 100.0, "bad", "sample"),
            broker_mode="paper",
        )
        self.assertFalse(decision.allowed)

    def test_rejects_live_mode(self) -> None:
        decision = self.manager.evaluate(
            OrderRequest("AAPL", "buy", "market", 1, 100.0, "bad", "sample"),
            broker_mode="live",
        )
        self.assertFalse(decision.allowed)


if __name__ == "__main__":
    unittest.main()
