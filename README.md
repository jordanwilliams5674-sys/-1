# Beidou Investment Site

This repository publishes the Beidou investment research dashboard as a static website.

The site is research-only. It does not connect to brokers, place orders, run live trading, or provide buy/sell instructions.

## Current Deployment

- Platform: Cloudflare Pages
- Repository: `jordanwilliams5674-sys/-`
- Branch: `main`
- Build command: leave blank
- Build output directory: `docs`
- Environment variables: leave blank

See `CLOUDFLARE_PAGES_DEPLOY.md` for step-by-step setup.

## Important Files

- `beidou_monitor_site/preview_dashboard.html`: single dashboard HTML source.
- `docs/index.html`: generated static page for Cloudflare Pages. Do not edit directly.
- `docs/api/webdata.json`: generated static data snapshot.
- `scripts/export_static_site.py`: exports the static site from the source dashboard and local Beidou data.
- `CLOUDFLARE_PAGES_DEPLOY.md`: Cloudflare Pages setup guide.
- `docs/dodex-removed.md`: explains why trading execution entrypoints are not part of this site repo.

## Refreshing Site Data

After the local Beidou radar data is refreshed, regenerate the static site:

```powershell
python scripts\export_static_site.py
```

Then commit and push the changed `docs/index.html` and `docs/api/webdata.json`.

## Safety Boundary

- No live broker connection.
- No broker login.
- No bank, payment, password, verification-code, or 2FA handling.
- No order placement.
- No real account balances, broker names, cost basis, or position sizes in the public site data.
- Watchlist and event data are research signals only, not trading instructions.
