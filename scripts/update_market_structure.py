from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "market_structure" / "latest.json"
LIVE_URL = "http://127.0.0.1:8766/api/live"


def fetch_live() -> dict:
    try:
        with urllib.request.urlopen(LIVE_URL, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        return {"状态": "failed", "错误": str(exc)}


def number(value):
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None


def find_symbol(live: dict, symbol: str) -> dict:
    rows = []
    for key in ("美国指数", "实时快照"):
        value = live.get(key)
        if isinstance(value, list):
            rows.extend(item for item in value if isinstance(item, dict))
    for row in rows:
        row_symbol = str(row.get("标的") or row.get("股票代码") or row.get("symbol") or "").upper()
        if row_symbol == symbol.upper():
            return row
    return {}


def snapshot(symbol: str, label: str, live: dict) -> dict:
    row = find_symbol(live, symbol)
    now = datetime.now(timezone.utc).isoformat()
    return {
        "symbol": symbol,
        "label": label,
        "spotPrice": number(row.get("当前价格")),
        "changePct": number(row.get("当前涨跌幅")),
        "volume": number(row.get("当前成交量")),
        "timestamp": live.get("北京时间") or now,
        "source": row.get("数据源") or live.get("来源说明") or "本地北斗行情API",
        "session": row.get("时段") or (live.get("当前美股时段") or {}).get("label") or "待确认",
        "freshnessSeconds": 0 if row else None,
        "gammaRegime": "待接入供应商/CSV",
        "netGex": None,
        "putWall": None,
        "callWall": None,
        "gammaFlip": None,
        "darkPoolMainLevel": None,
        "expectedMovePct": None,
        "intradayMoveUsedPct": None,
        "zeroDteSensitivity": "待接入供应商/CSV",
        "open15mStatus": "待开盘后回填",
        "open30mStatus": "待开盘后回填",
        "open60mStatus": "待开盘后回填",
        "confirmationStatus": "公开行情已录入；结构字段等待 Cheddar/OCC/FINRA/CSV",
        "structureReading": "当前只确认公开行情和涨跌幅，不推断 Gamma、期权墙或暗池方向。",
        "beidouConclusion": "观察，不输出独立买卖指令。",
        "riskLevel": "pending",
        "shouldArchiveToQixing": True,
    }


def main() -> None:
    live = fetch_live()
    payload = {
        "moduleName": "市场结构雷达",
        "asOf": live.get("北京时间") or datetime.now(timezone.utc).isoformat(),
        "sourceMode": "local_live_quote_plus_manual_structure_fields",
        "autoUpdate": {
            "quote": True,
            "structureFields": False,
            "note": "QQQ/SPY公开行情可由本地北斗API刷新；Gamma、Put Wall、Call Wall、Dark Pool、Expected Move 需要供应商CSV、截图或手动录入。",
        },
        "snapshots": [
            snapshot("QQQ", "纳斯达克100风险偏好", live),
            snapshot("SPY", "标普500市场宽度", live),
        ],
        "dataSources": [
            {"name": "本地北斗行情API", "type": "quote", "url": LIVE_URL, "auto": True},
            {"name": "Cheddar Flow截图或CSV", "type": "gamma/options/dark_pool", "url": "manual_csv_or_screenshot", "auto": False},
            {"name": "OCC每日OI", "type": "open_interest", "url": "https://www.theocc.com/market-data/market-data-reports/series-and-trading-data/series-search", "auto": False},
            {"name": "FINRA ATS/OTC延迟数据", "type": "dark_pool_reference", "url": "https://www.finra.org/finra-data/browse-catalog/weekly-summary", "auto": False},
        ],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()
