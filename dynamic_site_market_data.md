# Dynamic Site And Read-Only Market Data Plan

## Conclusion

Beidou Investment Site can become dynamic on a free tier, but the broker boundary must stay strict:

- Use Cloudflare Pages + Functions/Workers for lightweight dynamic reads.
- Keep GitHub Pages as the static backup.
- Only connect read-only market data endpoints.
- Do not connect broker trading, order placement, account transfer, password, verification-code, or 2FA flows.

## Free Dynamic Hosting Direction

GitHub Pages is suitable for static backup only. A dynamic free path should use:

1. Cloudflare Pages for the frontend.
2. Cloudflare Functions or Workers for API endpoints.
3. Public or API-key-based read-only market data providers.
4. No persistent storage of secrets in the public repo.

## Read-Only Connector Candidates

| Connector | Status | Allowed Use | Forbidden Use |
| --- | --- | --- | --- |
| Alpaca Market Data | Candidate, disabled by default | US market data reads | Trading API, order placement |
| Tiger OpenAPI | Candidate, disabled by default | Possible quote reads after user confirms permissions | Login handling, order placement, account operations |
| Yahoo Finance public endpoints | Existing auxiliary style | Quote and chart hints | Sole source for high-stakes decisions |

## Current Read-Only Adapter

The repository now includes a read-only market data adapter:

- Module: `beidou_us_radar/providers/readonly_market_data.py`
- Enabled provider: Alpaca Market Data latest quotes, only when `ALPACA_KEY_ID` and `ALPACA_SECRET_KEY` are present.
- HTTP method: `GET` only.
- Guardrail: endpoint paths containing account, position, order, trade, transfer, withdraw, or deposit words are refused.
- Scan integration: `scripts/premarket_mover_scan.py` uses the adapter as an optional fallback after TradingView/Yahoo and before Finnhub.

Tiger OpenAPI remains a documented candidate only. It is not called by this repository because the current boundary forbids broker login, account access, and trading operations.

## Implementation Gate

Before enabling any dynamic connector:

1. User confirms the provider and permission scope.
2. API keys are stored only in the hosting provider's secret manager.
3. The code path is read-only and has no order/trade/account-transfer methods.
4. Public responses exclude account, broker, balance, cost, quantity, screenshots, passwords, tokens, verification codes, and 2FA data.
5. Reports label market data as quotes, not verified investment conclusions.

## Not In Scope

- Automatic trading.
- Automatic buy/sell decisions.
- Broker login automation.
- Broker account scraping.
- Live account balance, position size, cost basis, or P/L display.
