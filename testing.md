# Beidou checks

Use the standard-library check runner:

```powershell
python run_beidou_checks.py
```

The runner checks:

- Python syntax for the website and export scripts.
- `beidou_us_radar/tests` with `unittest`.
- Static export through `scripts/export_static_site.py`.
- `docs/api/webdata.json` structure.
- `docs/index.html` static-mode wiring.

No `pytest` dependency is required.

Dodex trading tests were removed from this website deployment repository because the trading execution package is not present here. See `docs/dodex-removed.md`.
