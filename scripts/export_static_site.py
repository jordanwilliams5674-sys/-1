from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = ROOT / "beidou_monitor_site"
OUT_ROOT = ROOT / "docs"
sys.path.insert(0, str(ROOT))

from beidou_monitor_site import preview_server  # noqa: E402


def main() -> None:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(OUT_ROOT / "api", ignore_errors=True)
    for generated in [OUT_ROOT / "index.html", OUT_ROOT / ".nojekyll", OUT_ROOT / "health.txt"]:
        if generated.exists():
            generated.unlink()
    (OUT_ROOT / "api").mkdir(parents=True)

    html = (WEB_ROOT / "preview_dashboard.html").read_text(encoding="utf-8")
    html = html.replace("fetch('/api/webdata?ts='+Date.now())", "fetch('api/webdata.json?ts='+Date.now())")
    html = html.replace("await fetch('/api/scan',{method:'POST'});", "throw new Error('静态网站不支持在线刷新，请更新数据后重新导出。');")
    html = html.replace('onclick="refreshNow()">', 'onclick="refreshNow()" title="静态网站不支持在线刷新">')
    (OUT_ROOT / "index.html").write_text(html, encoding="utf-8")

    data = preview_server.build_webdata()
    data.setdefault("status", {})
    data["status"]["staticExport"] = {
        "enabled": True,
        "note": "GitHub Pages static snapshot. Update source data and rerun scripts/export_static_site.py to refresh.",
    }
    (OUT_ROOT / "api" / "webdata.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    (OUT_ROOT / ".nojekyll").write_text("", encoding="utf-8")
    (OUT_ROOT / "health.txt").write_text("ok\n", encoding="utf-8")


if __name__ == "__main__":
    main()
