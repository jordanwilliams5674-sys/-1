# Dodex trading modules removed

This repository is the Beidou investment research website deployment package.

Dodex `live`, `paper`, and `backtest` execution entrypoints were removed from this repository because the corresponding `dodex` Python package is not present here and live/paper trading commands are outside the scope of the public website deployment.

Current boundary:

- No live broker connection.
- No broker login.
- No order placement.
- No paper-trading loop in this deployment package.
- No backtest execution entrypoint in this deployment package.

The Beidou site remains a research, event review, watchlist, and risk-warning dashboard only. It does not provide buy/sell instructions or automated trading.
