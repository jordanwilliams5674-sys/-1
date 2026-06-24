from __future__ import annotations

import unittest

from dodex.trading.market_data.mock_market_data_provider import MockMarketDataProvider
from dodex.trading.strategy.sample_moving_average_strategy import SampleMovingAverageStrategy
from dodex.trading.strategy.types import StrategyContext


class SampleMovingAverageStrategyTest(unittest.TestCase):
    def test_mock_data_produces_buy_signal(self) -> None:
        provider = MockMarketDataProvider()
        strategy = SampleMovingAverageStrategy()
        signal = strategy.on_candle(StrategyContext(candles=provider.get_candles("AAPL")))
        self.assertEqual(signal.symbol, "AAPL")
        self.assertEqual(signal.action, "buy")


if __name__ == "__main__":
    unittest.main()
