from __future__ import annotations

import unittest

from dodex.trading.broker.paper_broker import PaperBroker
from dodex.trading.broker.types import OrderRequest


class PaperBrokerTest(unittest.TestCase):
    def test_submit_order_returns_filled_result(self) -> None:
        broker = PaperBroker()
        result = broker.submit_order(
            OrderRequest(
                symbol="AAPL",
                side="buy",
                type="market",
                quantity=10,
                price=100.0,
                reason="test",
                strategy_id="sample",
            )
        )
        self.assertEqual(result.status, "filled")
        self.assertEqual(result.filled_quantity, 10)
        self.assertEqual(len(broker.orders), 1)


if __name__ == "__main__":
    unittest.main()
