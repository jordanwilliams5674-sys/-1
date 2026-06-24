from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from ..core.source_health import SourceHealthResult, check_payload_health

AKSHARE_ROLE = "美股行情/财务辅助源，不作为最终事实源。"
SPOT_REQUIRED_FIELDS = ["symbol", "price", "change_percent", "timestamp"]
DAILY_REQUIRED_FIELDS = ["symbol", "date", "open", "high", "low", "close", "volume", "timestamp"]
FINANCIAL_REQUIRED_FIELDS = ["symbol", "period", "revenue", "net_income", "timestamp"]


def import_akshare() -> Any:
    try:
        import akshare as ak  # type: ignore
    except Exception as exc:
        raise RuntimeError(f"akshare unavailable: {exc}") from exc
    return ak


def validate_akshare_payload(
    payload: dict[str, Any] | None,
    *,
    source: str = "akshare_us",
    required_fields: list[str] | None = None,
    now: datetime | None = None,
    max_age: timedelta = timedelta(minutes=20),
) -> SourceHealthResult:
    return check_payload_health(
        source,
        payload,
        required_fields=required_fields or SPOT_REQUIRED_FIELDS,
        timestamp_field="timestamp",
        max_age=max_age,
        now=now or datetime.now(timezone.utc),
    )


def fetch_stock_us_spot_safe() -> tuple[Any | None, SourceHealthResult]:
    try:
        ak = import_akshare()
        data = ak.stock_us_spot()
        health = SourceHealthResult("akshare.stock_us_spot", True, False, "ok")
        return data, health
    except Exception as exc:
        return None, SourceHealthResult("akshare.stock_us_spot", False, True, "unavailable", error=str(exc))


def normalize_quote(row: dict[str, Any], timestamp: datetime | None = None) -> dict[str, Any]:
    timestamp = timestamp or datetime.now(timezone.utc)
    return {
        "symbol": str(row.get("symbol") or row.get("代码") or row.get("ticker") or "").upper(),
        "price": row.get("price") or row.get("最新价") or row.get("close"),
        "change_percent": row.get("change_percent") or row.get("涨跌幅"),
        "volume": row.get("volume") or row.get("成交量"),
        "timestamp": timestamp.isoformat(),
        "source": "akshare_us",
    }
