# Beidou investment research website

This repository is the deployment package for the Beidou investment research dashboard.

## Safety boundary

- Research and risk-warning dashboard only.
- No automatic trading.
- No broker, bank, payment, password, verification-code, or 2FA handling.
- No live broker connection.
- No order placement.
- No buy/sell instruction generation.
- Social-media or low-confidence signals must remain research leads until verified by official sources or high-confidence media.

## Current deployment

- Primary deployment path: Cloudflare Pages.
- Static output directory: `docs`.
- Static page source: `beidou_monitor_site/preview_dashboard.html`.
- Generated static page: `docs/index.html`.
- Generated static data: `docs/api/webdata.json`.

## Data boundary

- Public site data must not include real account balances, broker names, cost basis, position size, passwords, tokens, screenshots, or verification codes.
- `data/holdings_accounts/accounts.json` is intentionally sanitized.
- Watchlist data is research-only and does not imply a position or a trade.

## Removed trading code

Dodex `live`, `paper`, and `backtest` entrypoints are not part of this website deployment repository. See `docs/dodex-removed.md`.
