from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = ROOT / "beidou_monitor_site"
OUT_ROOT = ROOT / "docs"
DEFAULT_SOURCE_ROOT = Path(r"C:\premarket_mover_radar")
sys.path.insert(0, str(ROOT))

from beidou_monitor_site import preview_server  # noqa: E402


def resolve_source_root() -> Path:
    configured = os.environ.get("BEIDOU_STATIC_SOURCE_ROOT")
    candidates = [Path(configured)] if configured else []
    candidates.extend([DEFAULT_SOURCE_ROOT, ROOT])
    for candidate in candidates:
        if candidate and (candidate / "reports" / "premarket" / "latest_zh.json").exists():
            return candidate
    return ROOT


def configure_preview_source(source_root: Path) -> None:
    preview_server.ROOT = source_root
    preview_server.MARKET_STRUCTURE_FILE = source_root / "data" / "market_structure" / "latest.json"
    preview_server.RESEARCH_LOCAL_ROOT = source_root / "data" / "research_pool"


def snapshot_age_hours(data: dict) -> float | None:
    raw = data.get("market", {}).get("generatedAtUtc")
    if not raw:
        return None
    try:
        generated = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if generated.tzinfo is None:
            generated = generated.replace(tzinfo=timezone.utc)
        return round((datetime.now(timezone.utc) - generated.astimezone(timezone.utc)).total_seconds() / 3600, 2)
    except Exception:
        return None


def main() -> None:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(OUT_ROOT / "api", ignore_errors=True)
    for generated in [OUT_ROOT / "index.html", OUT_ROOT / ".nojekyll", OUT_ROOT / "health.txt"]:
        if generated.exists():
            generated.unlink()
    (OUT_ROOT / "api").mkdir(parents=True)

    html = (WEB_ROOT / "preview_dashboard.html").read_text(encoding="utf-8")
    html = html.replace("fetch('/api/webdata?ts='+Date.now())", "fetch('api/webdata.json?ts='+Date.now())")
    html = html.replace(
        "await fetch('/api/scan',{method:'POST'});",
        "throw new Error('静态网站不支持在线刷新，请更新数据后重新导出。');",
    )
    html = html.replace('onclick="refreshNow()">', 'onclick="refreshNow()" title="静态网站不支持在线刷新">')
    (OUT_ROOT / "index.html").write_text(html, encoding="utf-8")

    source_root = resolve_source_root()
    configure_preview_source(source_root)
    data = preview_server.build_webdata()
    data.setdefault("status", {})
    age_hours = snapshot_age_hours(data)
    data["status"]["staticExport"] = {
        "enabled": True,
        "sourceRoot": str(source_root),
        "eventCount": len(data.get("events", [])),
        "topEventCount": len(data.get("homeV1", {}).get("topEvents", [])),
        "snapshotAgeHours": age_hours,
        "isStale": age_hours is None or age_hours > 24,
        "note": "Static snapshot for Pages deployment. Refresh the source radar data, then rerun scripts/export_static_site.py.",
    }
    (OUT_ROOT / "api" / "webdata.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    (OUT_ROOT / ".nojekyll").write_text("", encoding="utf-8")
    (OUT_ROOT / "health.txt").write_text("ok\n", encoding="utf-8")


if __name__ == "__main__":
    main()
