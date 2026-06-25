from __future__ import annotations

import json
import os
import shutil
import re
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse
try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None

ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = Path(__file__).resolve().parent
API_ROOT = os.environ.get("BEIDOU_API_ROOT", "http://127.0.0.1:8766")
SITE_NAME = "北斗投研雷达"
BUILTIN_ROOT = WEB_ROOT / "builtin_files"
HIDDEN_TICKERS = set()
PRIVATE_BUILTIN_FILES = {"holdings.csv", "holdings.yaml"}
MARKET_STRUCTURE_DOC = "qixing_project/market_structure_radar.md"
MARKET_STRUCTURE_FILE = ROOT / "data" / "market_structure" / "latest.json"
RESEARCH_LOCAL_ROOT = ROOT / "data" / "research_pool"
RESEARCH_OVERFLOW_ROOT = Path("D:/BeidouResearchLibrary/research_pool")
RESEARCH_RETENTION_DAYS = 183
RESEARCH_ROLLOVER_BYTES = 300 * 1024 * 1024
RESEARCH_MIN_FREE_BYTES = 5 * 1024 * 1024 * 1024


def read_json(path: Path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def fetch_json(url: str, fallback):
    try:
        with urllib.request.urlopen(url, timeout=8) as res:
            return json.loads(res.read().decode("utf-8"))
    except Exception:
        return fallback


def parse_yaml_list(text: str, section: str) -> list[dict]:
    out: list[dict] = []
    in_section = False
    current: dict | None = None
    for raw in text.splitlines():
        sec = re.match(r"^([A-Za-z0-9_]+):\s*$", raw)
        if sec:
            if in_section and sec.group(1) != section:
                break
            in_section = sec.group(1) == section
            continue
        if not in_section:
            continue
        start = re.match(r"^\s{2}-\s+([A-Za-z0-9_]+):\s*(.*)$", raw)
        if start:
            current = {start.group(1): start.group(2).strip().strip('"').strip("'")}
            out.append(current)
            continue
        prop = re.match(r"^\s{4}([A-Za-z0-9_]+):\s*(.*)$", raw)
        if prop and current is not None:
            current[prop.group(1)] = prop.group(2).strip().strip('"').strip("'")
    return out


def parse_watch_config(text: str) -> list[dict]:
    flat = parse_yaml_list(text, "watchlist")
    if flat:
        return flat
    out: list[dict] = []
    in_watchlists = False
    group = ""
    current: dict | None = None
    for raw in text.splitlines():
        if re.match(r"^watchlists:\s*$", raw):
            in_watchlists = True
            continue
        if in_watchlists and re.match(r"^[A-Za-z0-9_]+:\s*$", raw):
            break
        if not in_watchlists:
            continue
        group_match = re.match(r"^\s{2}([A-Za-z0-9_]+):\s*$", raw)
        if group_match:
            group = group_match.group(1)
            continue
        ticker_match = re.match(r"^\s{4}-\s+ticker:\s*(.+?)\s*$", raw)
        if ticker_match:
            current = {"ticker": ticker_match.group(1).strip().strip('"').strip("'"), "group": group}
            out.append(current)
            continue
        prop = re.match(r"^\s{6}([A-Za-z0-9_]+):\s*(.*)$", raw)
        if prop and current is not None:
            current[prop.group(1)] = prop.group(2).strip().strip('"').strip("'")
    return out


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def number(value, fallback=None):
    try:
        if value in (None, ""):
            return fallback
        return float(value)
    except Exception:
        return fallback


def text(value, fallback=""):
    if value is None:
        return fallback
    value = str(value).strip()
    return value or fallback


def relation(value) -> str:
    value = text(value).lower()
    if "actual" in value or "实际" in value:
        return "actual_holding"
    if "watch" in value or "观察" in value:
        return "watchlist"
    return "excluded"


def slug(value) -> str:
    value = text(value, "event").lower()
    value = re.sub(r"[^\w\u4e00-\u9fff]+", "-", value, flags=re.UNICODE).strip("-")
    return (value or "event")[:80]


def date_part(value) -> str:
    match = re.search(r"\d{4}-\d{2}-\d{2}", text(value))
    return match.group(0) if match else "date-pending"


def domain_from_url(value) -> str:
    value = text(value)
    match = re.match(r"https?://([^/]+)", value)
    return match.group(1).replace("www.", "") if match else ""


def source_tier(source, label="") -> str:
    low = f"{text(source)} {text(label)}".lower()
    if re.search(r"sec|edgar|company ir|newsroom|nasdaq|nyse|cboe|s&p|spglobal|bls|bea|treasury|federal reserve|fred|官方|ir", low):
        return "official"
    if re.search(r"reuters|bloomberg|wsj|wall street journal|cnbc|financial times|ft\.com|marketwatch|ap news|associated press", low):
        return "major_media"
    if re.search(r"polygon|finnhub|alpha vantage|benzinga|financialmodelingprep|fmp|market chameleon|quartr|koyfin|quiver|tradingview|stockanalysis|whalewisdom", low):
        return "commercial_api"
    if re.search(r"x\.com|twitter|reddit|youtube|stocktwits|discord|serenity|社媒|social", low):
        return "social"
    return "free_aux"


def verification_status(tier: str, social_only: bool) -> str:
    if social_only or tier == "social":
        return "social_only_unconfirmed"
    if tier == "official":
        return "official_confirmed"
    if tier == "major_media":
        return "major_media_confirmed"
    if tier == "commercial_api":
        return "commercial_confirmed"
    return "free_aux_only"


def suggested_action(value) -> str:
    value = text(value)
    if "减风险" in value:
        return "减风险"
    if "分批" in value or "研究" in value:
        return "分批研究"
    if "等" in value or "30" in value or "强关注" in value:
        return "等30–60分钟"
    if "追" in value:
        return "追"
    return "只看不动"


def severity(event: dict) -> int:
    score = 4 if event["impact_strength"] == "high" else 3 if event["impact_strength"] == "medium" else 2
    if event["relation_type"] == "actual_holding":
        score += 1
    if event["impact_direction"] == "bearish" and event["relation_type"] == "actual_holding":
        score += 1
    if event.get("is_social_only") or event.get("stale_flag") or event.get("is_duplicate"):
        score -= 1
    return max(1, min(5, score))


def signature_for(row: dict) -> str:
    scope_key = text(row.get("ticker") or row.get("sector"), "USMARKET").upper()
    actor = slug(row.get("company") or row.get("ticker") or row.get("sector") or "market")
    event_type = slug(row.get("event_type"))
    src = slug(row.get("source") or "source-pending")
    doc_or_title = slug(row.get("official_doc_id") or row.get("title"))
    return f"{scope_key}|{actor}|{event_type}|{src}|{doc_or_title}|{date_part(row.get('published_time'))}"


def source_ref(source, tier, credibility, url="", published="", form="") -> dict:
    url = text(url)
    return {
        "name": text(source, "source pending"),
        "domain": domain_from_url(url) or slug(source),
        "url": url or None,
        "source_tier": tier,
        "credibility": credibility,
        "published_at_et": text(published) or None,
        "form_type": text(form) or None,
    }


def impact_direction(row: dict) -> str:
    explicit = text(row.get("impact_direction") or row.get("影响方向")).lower()
    if "bull" in explicit or "利好" in explicit:
        return "bullish"
    if "bear" in explicit or "利空" in explicit:
        return "bearish"
    pct = number(row.get("price_move_pct") or row.get("当前行情", {}).get("当前涨跌幅"))
    if pct is not None and pct >= 1:
        return "bullish"
    if pct is not None and pct <= -1:
        return "bearish"
    return "neutral"


def impact_strength(row: dict) -> str:
    explicit = text(row.get("impact_strength") or row.get("影响强度")).lower()
    if "high" in explicit or "高" in explicit:
        return "high"
    if "medium" in explicit or "中" in explicit:
        return "medium"
    score = number(row.get("短线发酵分数"))
    event_type = text(row.get("event_type") or row.get("事件类型"))
    if event_type in {"SEC filing", "guidance", "dilution/ATM/S-3", "macro data"} or (score is not None and score >= 75):
        return "high"
    if score is not None and score >= 65:
        return "medium"
    return "low"


def event_type_from(value: str) -> str:
    low = value.lower()
    if any(x in low for x in ["10-k", "10-q", "8-k", "sec", "filing"]):
        return "SEC filing"
    if any(x in low for x in ["财报", "earnings"]):
        return "earnings"
    if any(x in low for x in ["guidance", "指引"]):
        return "guidance"
    if any(x in low for x in ["fed", "fomc", "cpi", "pce", "美联储", "非农"]):
        return "macro data"
    if any(x in low for x in ["twitter", "youtube", "社媒", "x/"]):
        return "social signal"
    return "unusual price/volume/options"


def normalize_event(row: dict, index: int) -> dict:
    if "ticker" in row or "event_type" in row:
        rel = relation(row.get("position_scope") or row.get("relation_type"))
        social_only = bool(row.get("only_social") or row.get("is_social_only"))
        stale = bool(row.get("staleness_flag") or row.get("stale_flag"))
        duplicate = bool(row.get("is_duplicate") or row.get("duplicate"))
        tier = source_tier(row.get("source"), row.get("source_label"))
        credibility = number(row.get("credibility") or row.get("source_credibility"))
        event = {
            "id": f"{text(row.get('ticker') or row.get('sector') or 'USMARKET')}-{index}",
            "ticker": text(row.get("ticker")),
            "tickers": [text(item) for item in row.get("tickers", []) if text(item)] if isinstance(row.get("tickers"), list) else None,
            "sector": text(row.get("sector")),
            "relation_type": rel,
            "event_type": text(row.get("event_type"), "unusual price/volume/options"),
            "source": text(row.get("source"), "source pending"),
            "source_tier": tier,
            "verification_status": verification_status(tier, social_only),
            "source_credibility": credibility,
            "source_label": text(row.get("source_label"), "未确认"),
            "primary_source": source_ref(row.get("source"), tier, credibility, row.get("url") or row.get("source_url"), row.get("timestamp") or row.get("published_time"), row.get("official_form")),
            "official_form": text(row.get("official_form") or row.get("form_type")) or None,
            "official_doc_id": text(row.get("official_doc_id") or row.get("doc_id") or row.get("accession_number")) or None,
            "published_time": text(row.get("timestamp") or row.get("published_time")),
            "detected_time": text(row.get("detected_time") or row.get("timestamp")),
            "title": text(row.get("title"), "事件待确认"),
            "summary": text(row.get("summary") or row.get("description") or row.get("reason"), "北斗事件流已接入。"),
            "impact_direction": impact_direction(row),
            "impact_strength": impact_strength(row),
            "is_duplicate": duplicate,
            "is_repeat_48h": bool(row.get("is_repeat_48h") or duplicate),
            "is_second_catalyst": bool(row.get("is_second_catalyst")),
            "is_old_event": bool(row.get("is_old_event")),
            "is_priced_in": row.get("is_priced_in") if isinstance(row.get("is_priced_in"), bool) else None,
            "is_social_only": social_only,
            "stale_flag": stale,
            "stale_reason": text(row.get("stale_reason")),
            "suggested_action": suggested_action(row.get("action") or row.get("suggested_action")),
            "beidou_reason": text(row.get("reason") or row.get("beidou_reason"), "仅作投研线索。"),
            "price_context": {"last": number(row.get("price") or row.get("current_price")), "change_pct": number(row.get("price_move_pct")), "vol_vs_20d": number(row.get("relative_volume")), "session_phase": row.get("session_phase")},
            "signal_score": number(row.get("signal_score") or row.get("短线发酵分数")),
            "suppression_reason": "social_only_unconfirmed" if social_only else "stale_data" if stale else "duplicate_48h" if duplicate else None,
        }
        event["event_signature"] = text(row.get("event_signature")) or signature_for(event)
        event["severity"] = severity(event)
        return event

    catalyst = row.get("催化来源", [{}])[0] if isinstance(row.get("催化来源"), list) and row.get("催化来源") else {}
    title = text(catalyst.get("中文标题") or catalyst.get("标题") or row.get("事件标注"), "事件待确认")
    rel = relation(row.get("所属类型") or row.get("事件标注"))
    src = text(catalyst.get("来源"), "source pending")
    tier = source_tier(src, catalyst.get("可信度"))
    credibility = 0.9 if catalyst.get("可信度") == "high" else 0.72 if catalyst.get("可信度") == "medium" else None
    duplicate = "重复" in text(row.get("是否重复"))
    old = "旧消息" in text(row.get("时间标注"))
    event = {
        "id": f"{text(row.get('股票代码'), 'USMARKET')}-{index}",
        "ticker": text(row.get("股票代码")),
        "sector": "",
        "relation_type": rel,
        "event_type": event_type_from(f"{title} {row.get('事件标注', '')}"),
        "source": src,
        "source_tier": tier,
        "verification_status": verification_status(tier, False),
        "source_credibility": credibility,
        "source_label": "免费新闻辅助源" if "Yahoo" in src else "官方事实源" if tier == "official" else "未确认",
        "primary_source": source_ref(src, tier, credibility, catalyst.get("网址"), catalyst.get("发布时间"), catalyst.get("催化类型")),
        "official_form": text(catalyst.get("催化类型"), "SEC") if "SEC" in src else None,
        "official_doc_id": text(catalyst.get("网址")) if "SEC" in src else None,
        "published_time": text(catalyst.get("发布时间")),
        "detected_time": text(row.get("首次记录UTC") or catalyst.get("发布时间")),
        "title": title,
        "summary": text(row.get("事件标注"), "北斗事件摘要待补充。"),
        "impact_direction": impact_direction(row),
        "impact_strength": impact_strength(row),
        "is_duplicate": duplicate,
        "is_repeat_48h": duplicate,
        "is_second_catalyst": "新发酵" in text(row.get("是否重复")) or "新发酵" in text(row.get("时间标注")),
        "is_old_event": old,
        "is_priced_in": False if "未" in text(row.get("是否已计价")) else None,
        "is_social_only": False,
        "stale_flag": False,
        "suggested_action": suggested_action(row.get("信息处理标签")),
        "beidou_reason": text(row.get("理由"), "仅作投研线索。"),
        "price_context": {"last": number(row.get("当前行情", {}).get("当前价格")), "change_pct": number(row.get("当前行情", {}).get("当前涨跌幅")), "vol_vs_20d": number(row.get("当前行情", {}).get("相对成交量"))},
        "signal_score": number(row.get("短线发酵分数")),
        "suppression_reason": "duplicate_48h" if duplicate else "old_event" if old else None,
    }
    event["event_signature"] = signature_for({**event, "company": row.get("公司名称")})
    event["severity"] = severity(event)
    return event


def names_in_yaml_section(yaml_text: str, section: str) -> list[str]:
    names: list[str] = []
    in_section = False
    for raw in yaml_text.splitlines():
      sec = re.match(r"^([A-Za-z0-9_]+):\s*$", raw)
      if sec:
          if in_section and sec.group(1) != section:
              break
          in_section = sec.group(1) == section
          continue
      if not in_section:
          continue
      name = re.match(r"^\s{2}-\s+name:\s*(.*)$", raw)
      if name:
          names.append(name.group(1).strip().strip('"').strip("'"))
    return names


def source_status(names: list[str], health: list[dict]) -> dict:
    lowered = [name.lower() for name in names]
    matched = [src for src in health if any(name in text(src.get("source_name")).lower() or text(src.get("source_name")).lower() in name for name in lowered)]
    active = len([src for src in matched if src.get("status") == "active"])
    stale = sum(int(src.get("stale_count") or 0) for src in matched)
    down = any(src.get("status") == "down" for src in matched)
    return {"active": active, "stale": stale, "status": "down" if down else "degraded" if stale else "active" if active else "pending"}


def build_source_layers(source_yaml: str, health: list[dict]) -> list[dict]:
    p1 = names_in_yaml_section(source_yaml, "priority_1_official")
    p2 = names_in_yaml_section(source_yaml, "priority_2_market_auxiliary")
    p3 = names_in_yaml_section(source_yaml, "priority_3_news_and_signal")
    layers = [
        ("market", "行情层", "P2", "盘前、盘中、盘后价格、成交量、扩展时段状态", ["akshare_us", "Tencent US Finance", "Optional Commercial APIs"], "行情只说明价格变化，不替代 SEC/IR 事实源。"),
        ("research", "研报层", "P2", "评级、目标价、分析师动作、预期变化", ["Optional Commercial APIs", "Trusted News"], "用于解释发酵，不直接生成交易结论。"),
        ("signal", "信号层", "P2", "异常价量、期权、停牌、指数事件、内部人和增发线索", ["Exchange / Index Official", "Optional Commercial APIs", "Social Radar"], "signal_score 只代表研究优先级。"),
        ("news", "新闻层", "P1", "主流新闻与 IR 的同日验证", ["Trusted News", "Company IR / Newsroom"], "新闻是入口，重大事实仍回到官方文件。"),
        ("fundamental", "基础数据层", "P0", "财报六问、估值、股本、现金流、负债和指引", ["SEC EDGAR", "Company IR / Newsroom", "Official Macro"], "基本面锚点优先 SEC/IR。"),
        ("filing", "公告层", "P0", "10-K/10-Q/8-K/S-3/424B/Form 4/13F/ATM/停牌/指数公告", ["SEC EDGAR", "Company IR / Newsroom", "Exchange / Index Official"], "官方事实源最高优先级。"),
    ]
    configured = set(p1 + p2 + p3)
    out = []
    for key, name, priority, purpose, primary_sources, notes in layers:
        status = source_status(primary_sources, health)
        out.append({
            "layer_key": key,
            "layer_name": name,
            "priority": priority,
            "purpose": purpose,
            "source_count": len([src for src in primary_sources if src in configured]) or len(primary_sources),
            "active_count": status["active"],
            "stale_count": status["stale"],
            "status": status["status"],
            "primary_sources": primary_sources,
            "notes": notes,
        })
    return out


def builtin_group(rel_path: str) -> str:
    if rel_path.startswith("qixing_project/"):
        return "北斗/七星项目资料包"
    if rel_path.startswith("radar_config/"):
        return "雷达配置"
    if rel_path.startswith("radar_docs/"):
        return "雷达说明文档"
    return "其他内置资料"


def builtin_note(rel_path: str) -> str:
    name = Path(rel_path).name
    notes = {
        "project_instructions.txt": "ChatGPT Project / 北斗工作说明",
        "watchlist.csv": "项目观察池结构",
        "qixing_database.csv": "七星结构化资料库",
        "beidou_task_status.md": "北斗任务状态",
        "project_operating_rules.md": "旧北斗/七星操作规则，已去除实仓内容",
        "company_research.md": "公司研究模板",
        "import_steps.md": "导入步骤",
        "deep_research_workflow.md": "深度研究流程",
        "gmail_external_inputs.md": "外部输入 / 邮件路由说明",
        "integration_status.md": "Google 集成状态",
        "watchlist.yaml": "雷达观察池配置；当前站点读取此配置",
        "sources.yaml": "雷达数据源分层配置",
        "README_premarket_radar.md": "老北斗雷达说明",
        "data_sources.md": "数据源说明",
        "xueqiu_source_plan.md": "雪球社区线索接入计划，需要用户登录授权后使用",
    }
    return notes.get(name, "内置北斗资料")


def builtin_preview(file_path: Path) -> dict:
    body = read_text(file_path)
    lines = body.splitlines()
    non_empty = [line.strip() for line in lines if line.strip()]
    suffix = file_path.suffix.lower()
    preview = " / ".join(non_empty[:3])[:260]
    if suffix == ".csv":
        preview = f"CSV 表格，约 {max(len(lines) - 1, 0)} 行数据。"
    if suffix in {".yaml", ".yml"}:
        preview = f"YAML 配置，约 {len(non_empty)} 行有效内容。"
    return {
        "line_count": len(lines),
        "preview": preview or "空文件或暂无可预览内容。",
    }


def collect_builtin_files() -> dict:
    groups: dict[str, dict] = {}
    files = []
    if not BUILTIN_ROOT.exists():
        return {"root": str(BUILTIN_ROOT), "groups": [], "files": []}
    for file_path in sorted(BUILTIN_ROOT.rglob("*")):
        if not file_path.is_file():
            continue
        if file_path.name in PRIVATE_BUILTIN_FILES:
            continue
        rel = file_path.relative_to(BUILTIN_ROOT).as_posix()
        stat = file_path.stat()
        group = builtin_group(rel)
        preview = builtin_preview(file_path)
        item = {
            "name": file_path.name,
            "relative_path": rel,
            "group": group,
            "note": builtin_note(rel),
            "size_bytes": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
            "line_count": preview["line_count"],
            "preview": preview["preview"],
            "url": f"/builtin/{rel}",
        }
        files.append(item)
        bucket = groups.setdefault(group, {"name": group, "file_count": 0, "total_bytes": 0})
        bucket["file_count"] += 1
        bucket["total_bytes"] += stat.st_size
    return {"root": str(BUILTIN_ROOT), "groups": list(groups.values()), "files": files}


def find_live_symbol(live: dict, symbol: str) -> dict:
    rows = []
    for key in ("美国指数", "实时快照"):
        value = live.get(key)
        if isinstance(value, list):
            rows.extend(item for item in value if isinstance(item, dict))
    aliases = {
        "SPY": {"SPY"},
        "QQQ": {"QQQ"},
    }
    wanted = aliases.get(symbol.upper(), {symbol.upper()})
    for row in rows:
        row_symbol = text(row.get("标的") or row.get("股票代码") or row.get("symbol")).upper()
        if row_symbol in wanted:
            return row
    return {}


def default_structure_snapshot(symbol: str, label: str) -> dict:
    return {
        "symbol": symbol,
        "label": label,
        "spotPrice": None,
        "changePct": None,
        "volume": None,
        "timestamp": "",
        "source": "本地北斗行情 API",
        "session": "待确认",
        "freshnessSeconds": None,
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
        "confirmationStatus": "公开行情自动刷新；结构字段等待 Cheddar/OCC/FINRA/CSV",
        "structureReading": "当前只确认公开行情和涨跌幅，不推断 Gamma、期权墙或暗池方向。",
        "beidouConclusion": "观察，不输出独立买卖指令。",
        "riskLevel": "pending",
        "shouldArchiveToQixing": True,
    }


def default_market_structure() -> dict:
    return {
        "moduleName": "市场结构雷达",
        "subtitle": "QQQ/SPY 盘中结构：Gamma、期权墙、暗池关键价位、Expected Move。",
        "description": "该模块只做盘中执行辅助，不判断公司长期价值，不输出独立买卖建议。",
        "symbols": ["QQQ", "SPY"],
        "stage": "已接入本地行情；结构字段等待供应商 CSV/手动录入",
        "sourceMode": "local_live_quote_plus_manual_structure_fields",
        "autoUpdate": {
            "quote": True,
            "structureFields": False,
            "note": "网页每5分钟自动刷新。QQQ/SPY公开行情随本地北斗API更新；Gamma、Put Wall、Call Wall、暗池、Expected Move 需要CSV/截图/供应商文件。文件更新后网页会自动读取。",
        },
        "dataSources": [
            {"name": "本地北斗行情API", "type": "quote", "url": f"{API_ROOT}/api/live", "auto": True},
            {"name": "Cheddar Flow截图或CSV", "type": "gamma/options/dark_pool", "url": "manual_csv_or_screenshot", "auto": False},
            {"name": "OCC每日OI", "type": "open_interest", "url": "https://www.theocc.com/market-data/market-data-reports/series-and-trading-data/series-search", "auto": False},
            {"name": "FINRA ATS/OTC延迟数据", "type": "dark_pool_reference", "url": "https://www.finra.org/finra-data/browse-catalog/weekly-summary", "auto": False},
        ],
        "snapshots": [
            default_structure_snapshot("QQQ", "纳斯达克100风险偏好"),
            default_structure_snapshot("SPY", "标普500市场宽度"),
        ],
        "rules": [
            {"name": "负Gamma加速风险", "message": "负Gamma + 接近/跌破Put Wall + 成交量或VIX确认时，提示波动放大风险。"},
            {"name": "Put Wall假跌破", "message": "跌破后15分钟K线收回且VIX不继续上升时，提示禁止追空，等待二次确认。"},
            {"name": "Call Wall反弹受阻", "message": "反弹到Call Wall附近两次失败且量能衰减时，提示反弹受阻。"},
            {"name": "Call Wall有效突破", "message": "突破Call Wall并站稳、指数和板块同步转强时，提示空头回补风险上升。"},
            {"name": "暗池关键位确认", "message": "价格站上主要Dark Pool Level且Put Wall未失守时，降低追空优先级。"},
            {"name": "Expected Move耗尽", "message": "开盘后短时间走完80%以上Expected Move时，提示不追单，等待回抽或二次确认。"},
        ],
        "allowedOutputs": ["观察", "等待确认", "假突破风险", "假跌破风险", "波动放大风险", "追单风险", "趋势延续风险", "空头回补风险", "结构支撑确认", "结构压力确认"],
        "forbiddenOutputs": ["立即买入", "立即卖出", "满仓", "梭哈", "确定见底", "确定见顶", "机构一定买入", "机构一定卖出"],
        "sourceDoc": f"/builtin/{MARKET_STRUCTURE_DOC}",
    }


def merge_non_empty(base: dict, extra: dict) -> dict:
    out = dict(base)
    for key, value in extra.items():
        if value not in (None, "", []):
            out[key] = value
    return out


def build_market_structure(live: dict | None = None) -> dict:
    live = live or {}
    payload = default_market_structure()
    saved = read_json(MARKET_STRUCTURE_FILE, {})
    if isinstance(saved, dict):
        for key, value in saved.items():
            if key != "snapshots" and value not in (None, "", []):
                payload[key] = value

    saved_snapshots = {}
    for item in saved.get("snapshots", []) if isinstance(saved, dict) else []:
        if isinstance(item, dict) and text(item.get("symbol")):
            saved_snapshots[text(item.get("symbol")).upper()] = item

    snapshots = []
    for default in default_market_structure()["snapshots"]:
        symbol = text(default.get("symbol")).upper()
        snap = merge_non_empty(default, saved_snapshots.get(symbol, {}))
        row = find_live_symbol(live, symbol)
        if row:
            snap.update({
                "spotPrice": number(row.get("当前价格"), snap.get("spotPrice")),
                "changePct": number(row.get("当前涨跌幅"), snap.get("changePct")),
                "volume": number(row.get("当前成交量"), snap.get("volume")),
                "timestamp": text(live.get("北京时间") or row.get("更新时间") or snap.get("timestamp")),
                "source": text(row.get("数据源") or live.get("来源说明"), snap.get("source")),
                "session": text(row.get("时段") or (live.get("当前美股时段") or {}).get("label"), snap.get("session")),
                "freshnessSeconds": 0,
            })
        snapshots.append(snap)

    payload["snapshots"] = snapshots
    payload["asOf"] = text(live.get("北京时间") or payload.get("asOf") or datetime.now(timezone.utc).isoformat())
    payload["sourceDoc"] = f"/builtin/{MARKET_STRUCTURE_DOC}"
    return payload


def build_recovered_content(builtin_files: dict, source_layers: list[dict], watchlist: list[dict], events: list[dict]) -> dict:
    important_dir = ROOT / "reports" / "premarket" / "important"
    important_files = sorted(important_dir.glob("*_important.md")) if important_dir.exists() else []
    items = [
        {
            "name": "项目规则与安全边界",
            "status": "已找回",
            "detail": "恢复 Project-only memory、安全边界、北斗/七星分工；不恢复实仓字段。",
            "source": "project_operating_rules.md / project_instructions.txt",
        },
        {
            "name": "观察池与研究池",
            "status": "已合并",
            "detail": f"当前前台观察池 {len(watchlist)} 个标的；旧实仓标的已按研究对象处理，MU 已隐藏。",
            "source": "watchlist.yaml / watchlist.csv",
        },
        {
            "name": "数据源分层",
            "status": "已恢复",
            "detail": f"恢复行情、新闻、公告、基础数据、信号等 {len(source_layers)} 个层级，用于判断来源可靠性。",
            "source": "sources.yaml / data_sources.md",
        },
        {
            "name": "历史重要事件",
            "status": "已保留",
            "detail": f"本地仍保留 {len(important_files)} 份重要事件归档，可继续给事件流和复盘使用。",
            "source": "reports/premarket/important",
        },
        {
            "name": "市场结构规则",
            "status": "已接入",
            "detail": "恢复 Gamma、期权墙、暗池、Expected Move 的判读规则；行情自动刷新，结构字段等CSV/供应商文件。",
            "source": "market_structure_radar.md / latest.json",
        },
    ]
    return {
        "title": "已找回可用北斗内容",
        "note": "只恢复规则、观察池、研究资料、数据源和事件归档；不恢复持仓、账户、成本、市值或盈亏。",
        "fileCount": len(builtin_files.get("files", [])),
        "items": items,
    }


def folder_size(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for item in path.rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:
                pass
    return total


def research_root() -> Path:
    local_size = folder_size(RESEARCH_LOCAL_ROOT)
    try:
        free = shutil.disk_usage(str(ROOT.anchor)).free
    except OSError:
        free = RESEARCH_MIN_FREE_BYTES
    if (local_size >= RESEARCH_ROLLOVER_BYTES or free < RESEARCH_MIN_FREE_BYTES) and Path("D:/").exists():
        return RESEARCH_OVERFLOW_ROOT
    return RESEARCH_LOCAL_ROOT


def research_paths() -> dict:
    root = research_root()
    return {
        "root": root,
        "notes": root / "research_notes.jsonl",
        "candidate": root / "candidate_pool_2026-06-07.json",
    }


def parse_dt(value):
    try:
        return datetime.fromisoformat(text(value).replace("Z", "+00:00"))
    except Exception:
        return None


def read_jsonl(path: Path, limit: int = 5000) -> list[dict]:
    rows = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
            if isinstance(item, dict):
                rows.append(item)
        except json.JSONDecodeError:
            continue
        if len(rows) >= limit:
            break
    return rows


def cleanup_research_notes(path: Path) -> None:
    if not path.exists():
        return
    cutoff = datetime.now(timezone.utc) - timedelta(days=RESEARCH_RETENTION_DAYS)
    rows = read_jsonl(path, 20000)
    kept = []
    changed = False
    for row in rows:
        created = parse_dt(row.get("created_at"))
        if created and created < cutoff:
            changed = True
            continue
        kept.append(row)
    if changed:
        path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in kept) + ("\n" if kept else ""), encoding="utf-8")


def normalize_tags(value) -> list[str]:
    if isinstance(value, list):
        return [text(item) for item in value if text(item)]
    return [part.strip() for part in re.split(r"[,，/、\s]+", text(value)) if part.strip()]


def sanitize_research_text(value) -> str:
    value = text(value)
    replacements = {
        "actual_holding": "watchlist",
        "实际持仓": "观察池",
        "实仓": "观察池",
        "持仓": "观察池",
        "holding": "watchlist",
        "position": "watchlist",
    }
    for old, new in replacements.items():
        value = value.replace(old, new)
    return value


def normalize_research_record(payload: dict) -> dict:
    now = datetime.now(timezone.utc)
    ticker = text(payload.get("ticker")).upper()[:32]
    title = sanitize_research_text(payload.get("title") or payload.get("name") or ticker or "未命名研究")
    body = sanitize_research_text(payload.get("body") or payload.get("note") or payload.get("summary"))
    pool = text(payload.get("pool") or payload.get("pool_name") or "manual_research")
    record = {
        "id": text(payload.get("id")) or f"research-{uuid.uuid4().hex[:12]}",
        "record_type": text(payload.get("record_type"), "manual_note"),
        "ticker": ticker,
        "name": sanitize_research_text(payload.get("name") or ticker),
        "pool": pool,
        "segment": sanitize_research_text(payload.get("segment")),
        "title": title,
        "body": body,
        "tags": normalize_tags(payload.get("tags")),
        "source": sanitize_research_text(payload.get("source") or "website"),
        "created_at": text(payload.get("created_at")) or now.isoformat(),
        "expires_at": (now + timedelta(days=RESEARCH_RETENTION_DAYS)).isoformat(),
    }
    record.update({
        "记录类型": "本地笔记",
        "股票代码": ticker,
        "名称": record["name"],
        "所属池": record["pool"],
        "分类": record["segment"],
        "标题": record["title"],
        "正文": record["body"],
        "标签": record["tags"],
        "来源": record["source"],
        "创建时间": record["created_at"],
        "过期时间": record["expires_at"],
    })
    record["text_index"] = " ".join(text(record.get(key)) for key in ("ticker", "name", "pool", "segment", "title", "body", "source")) + " " + " ".join(record["tags"])
    return record


def append_research_record(payload: dict) -> dict:
    paths = research_paths()
    root = paths["root"]
    root.mkdir(parents=True, exist_ok=True)
    cleanup_research_notes(paths["notes"])
    record = normalize_research_record(payload)
    with paths["notes"].open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def load_candidate_pool_items() -> list[dict]:
    paths = research_paths()
    candidates = []
    for path in [paths["candidate"], RESEARCH_LOCAL_ROOT / "candidate_pool_2026-06-07.json"]:
        data = read_json(path, {})
        if isinstance(data, dict) and isinstance(data.get("items"), list):
            candidates = data["items"]
            break
    out = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        ticker = text(item.get("ticker")).upper()
        if not ticker or ticker in HIDDEN_TICKERS:
            continue
        clean_item = dict(item)
        for key in ("beidou_role", "action", "segment", "name"):
            clean_item[key] = sanitize_research_text(clean_item.get(key))
        clean_item["ticker"] = ticker
        clean_item["record_type"] = "candidate_pool"
        clean_item["text_index"] = " ".join([
            ticker,
            text(clean_item.get("name")),
            text(clean_item.get("pool")),
            text(clean_item.get("segment")),
            text(clean_item.get("beidou_role")),
            text(clean_item.get("action")),
            " ".join(clean_item.get("watch_points") or []),
        ])
        out.append(clean_item)
    return out


def research_storage_status() -> dict:
    paths = research_paths()
    root = paths["root"]
    root.mkdir(parents=True, exist_ok=True)
    notes = read_jsonl(paths["notes"], 20000)
    candidates = load_candidate_pool_items()
    return {
        "root": str(root),
        "retentionDays": RESEARCH_RETENTION_DAYS,
        "notesCount": len(notes),
        "candidateCount": len(candidates),
        "totalBytes": folder_size(root),
        "overflowEnabled": root == RESEARCH_OVERFLOW_ROOT,
    }


def research_search(query: str = "", limit: int = 80) -> dict:
    paths = research_paths()
    cleanup_research_notes(paths["notes"])
    q = text(query).lower()
    notes = list(reversed(read_jsonl(paths["notes"], 20000)))
    candidates = load_candidate_pool_items()
    candidate_records = []
    for item in candidates:
        candidate_records.append({
            "id": f"candidate-{item.get('ticker')}-{item.get('pool')}",
            "record_type": "candidate_pool",
            "ticker": item.get("ticker"),
            "name": item.get("name"),
            "pool": item.get("pool"),
            "segment": item.get("segment"),
            "title": f"{item.get('ticker')} · {item.get('beidou_role') or item.get('segment')}",
            "body": "；".join(item.get("watch_points") or []) or item.get("action"),
            "tags": [item.get("pool"), item.get("segment"), item.get("action")],
            "source": "candidate_pool_2026-06-07",
            "created_at": item.get("created_at", ""),
            "text_index": item.get("text_index", ""),
        })
    rows = notes + candidate_records
    if q:
        rows = [row for row in rows if q in text(row.get("text_index") or row).lower()]
    rows = rows[: max(1, min(limit, 300))]
    return {"storage": research_storage_status(), "query": query, "records": rows}


def live_quote_map(live: dict) -> dict:
    rows = {}
    for key in ("美国指数", "实时快照"):
        value = live.get(key)
        if isinstance(value, list):
            for row in value:
                if isinstance(row, dict):
                    symbol = text(row.get("标的") or row.get("股票代码") or row.get("symbol")).upper()
                    if symbol:
                        rows[symbol] = row
    return rows


def pool_bucket(pool: str) -> str:
    pool = text(pool).lower()
    if "p0" in pool:
        return "P0"
    if "p1" in pool:
        return "P1"
    if "p2" in pool:
        return "P2"
    if "p3" in pool:
        return "P3"
    return "其他"


def build_research_radar(watchlist: list[dict], events: list[dict], live: dict) -> dict:
    candidates = load_candidate_pool_items()
    if not candidates:
        candidates = [
            {
                "ticker": row["ticker"],
                "name": row.get("company") or row["ticker"],
                "pool": "watchlist",
                "segment": row.get("theme"),
                "beidou_role": "观察池研究",
                "action": row.get("low_buy_status"),
                "watch_points": [row.get("latest_research_event")],
            }
            for row in watchlist
        ]
    watch_symbols = {text(row.get("ticker")).upper() for row in watchlist}
    events_by_ticker: dict[str, list[dict]] = {}
    for event in events:
        ticker = text(event.get("ticker")).upper()
        if ticker:
            events_by_ticker.setdefault(ticker, []).append(event)
    quotes = live_quote_map(live)
    base_score = {"P0": 90, "P1": 62, "P2": 38, "P3": 50, "其他": 35}
    scored = []
    counts: dict[str, int] = {}
    for item in candidates:
        ticker = text(item.get("ticker")).upper()
        if not ticker or ticker in HIDDEN_TICKERS:
            continue
        bucket = pool_bucket(item.get("pool"))
        counts[bucket] = counts.get(bucket, 0) + 1
        evs = events_by_ticker.get(ticker, [])
        quote = quotes.get(ticker, {})
        change = number(quote.get("当前涨跌幅"))
        volume = number(quote.get("当前成交量"))
        score = base_score.get(bucket, 35)
        reasons = [f"{bucket} 研究优先级"]
        alert_type = "预判关注"
        if ticker in watch_symbols:
            score += 10
            reasons.append("已在观察池")
        if evs:
            score += 18 + min(20, len(evs) * 4)
            reasons.append(f"本地事件流 {len(evs)} 条")
            alert_type = "新闻/事件触发"
        if change is not None and abs(change) >= 5:
            score += 38
            reasons.append(f"涨跌幅 {change:.2f}%")
            alert_type = "异常波动"
        elif change is not None and abs(change) >= 3:
            score += 20
            reasons.append(f"涨跌幅 {change:.2f}%")
            alert_type = "价格异动"
        action = text(item.get("action"))
        if "deep" in action:
            score += 8
            reasons.append("需要深扫")
        if "high" in action.lower():
            score += 6
            reasons.append("高波动")
        scored.append({
            "ticker": ticker,
            "name": text(item.get("name"), ticker),
            "pool": text(item.get("pool"), "watchlist"),
            "bucket": bucket,
            "segment": text(item.get("segment")),
            "beidouRole": text(item.get("beidou_role")),
            "action": sanitize_research_text(action),
            "watchPoints": [sanitize_research_text(point) for point in item.get("watch_points", []) if text(point)][:5],
            "score": score,
            "reasons": reasons,
            "alertType": alert_type,
            "eventCount": len(evs),
            "latestEvent": evs[0]["title"] if evs else "",
            "changePct": change,
            "volume": volume,
            "price": number(quote.get("当前价格")),
            "source": "candidate_pool + local_events + live_quote",
        })
    scored.sort(key=lambda row: row["score"], reverse=True)
    proportions = {"P0": 0.44, "P1": 0.32, "P2": 0.10, "P3": 0.14, "其他": 0.08}
    display_limit = 18
    selected = []
    selected_keys = set()
    for bucket, ratio in proportions.items():
        bucket_rows = [row for row in scored if row["bucket"] == bucket]
        quota = max(1, round(display_limit * ratio)) if bucket_rows else 0
        for row in bucket_rows[:quota]:
            key = (row["ticker"], row["bucket"])
            selected_keys.add(key)
            selected.append(row)
    for row in scored:
        if len(selected) >= display_limit:
            break
        key = (row["ticker"], row["bucket"])
        if key not in selected_keys:
            selected.append(row)
            selected_keys.add(key)
    selected.sort(key=lambda row: row["score"], reverse=True)
    alerts = [row for row in scored if row["alertType"] in {"异常波动", "价格异动", "新闻/事件触发"}][:8]
    if not alerts:
        alerts = selected[:5]
    return {
        "title": "观察池 / 研究池智能雷达",
        "note": "本地研究库可以保存全部资料；首页只按比例显示重要项，并优先提示新闻、事件和价格异常。",
        "displayLimit": display_limit,
        "countsByPool": counts,
        "displayPolicy": [
            {"bucket": "P0", "ratio": "约44%", "meaning": "主动扫描，可能影响AI链定价"},
            {"bucket": "P1", "ratio": "约32%", "meaning": "研究优先，等财务或订单验证"},
            {"bucket": "P2", "ratio": "约10%", "meaning": "消费/防御验证"},
            {"bucket": "P3", "ratio": "约14%", "meaning": "高波动叙事，只做风险和事件雷达"},
        ],
        "alerts": alerts,
        "items": selected,
    }


def build_research_library() -> dict:
    result = research_search("", 18)
    storage = result["storage"]
    return {
        "storage": storage,
        "recent": result["records"][:8],
        "savePolicy": "网站可录入观察池/研究池笔记并保存到本地 JSONL；默认保留半年，空间不足或文件过大时切到 D 盘。",
    }


def build_refresh_policy() -> dict:
    if ZoneInfo:
        now_et = datetime.now(ZoneInfo("America/New_York"))
    else:
        now_et = datetime.now(timezone.utc)
    minutes = now_et.hour * 60 + now_et.minute
    weekday = now_et.weekday()
    is_weekday = weekday < 5
    if is_weekday and 9 * 60 + 30 <= minutes < 16 * 60:
        return {"mode": "美股开盘", "intervalSeconds": 45, "reason": "开盘时段行情和新闻变化快，前台45秒刷新一次。", "easternTime": now_et.isoformat()}
    if is_weekday and 4 * 60 <= minutes < 9 * 60 + 30:
        return {"mode": "盘前", "intervalSeconds": 90, "reason": "盘前异动较多，前台90秒刷新一次。", "easternTime": now_et.isoformat()}
    if is_weekday and 16 * 60 <= minutes < 20 * 60:
        return {"mode": "盘后", "intervalSeconds": 90, "reason": "盘后财报和公告较多，前台90秒刷新一次。", "easternTime": now_et.isoformat()}
    if is_weekday and 20 * 60 <= minutes < 22 * 60:
        return {"mode": "盘后复盘", "intervalSeconds": 180, "reason": "盘后后段以复盘为主，前台3分钟刷新一次。", "easternTime": now_et.isoformat()}
    return {"mode": "休市/低频监控", "intervalSeconds": 300, "reason": "非交易主时段，前台5分钟刷新一次。", "easternTime": now_et.isoformat()}


CORE_FOCUS_SYMBOLS = ["MU", "MRVL", "INTC", "AMKR", "TSM", "NVDA", "AVGO", "AMD", "CSIQ", "RGTI", "CRCL"]
WATCH_POOL_SYMBOLS = ["ASX", "WDC", "SMR", "CRWD", "CEG", "VST", "NRG", "KO", "PEP", "AEP", "AWK", "ORCL", "NOK", "OUST"]

FOCUS_EXCLUDED_SYMBOLS = {"GOLD_BASKET", "SQQQ", "SOXS"}


def derive_home_symbol_groups(watchlist: list[dict], events_by_symbol: dict[str, list[dict]]) -> tuple[list[str], list[str]]:
    configured: list[str] = []
    for row in watchlist:
        symbol = text(row.get("ticker")).upper()
        if symbol and symbol not in configured:
            configured.append(symbol)
    eventful = [symbol for symbol in configured if symbol not in FOCUS_EXCLUDED_SYMBOLS and events_by_symbol.get(symbol)]
    if eventful:
        focus = eventful[:15]
    else:
        focus = [symbol for symbol in configured if symbol not in FOCUS_EXCLUDED_SYMBOLS][:12]
    focus_set = set(focus)
    watch = [symbol for symbol in configured if symbol not in focus_set]
    return focus, watch

SYMBOL_PROFILES = {
    "MU": ("Micron", "HBM / DRAM / AI内存"),
    "MRVL": ("Marvell", "AI网络 / 数据中心互连"),
    "INTC": ("Intel", "半导体制造 / 先进封装"),
    "AMKR": ("Amkor", "先进封装 / 封测"),
    "TSM": ("TSMC", "先进制程 / AI代工"),
    "NVDA": ("NVIDIA", "AI加速器 / 平台"),
    "AVGO": ("Broadcom", "AI ASIC / 网络"),
    "AMD": ("AMD", "AI GPU / CPU"),
    "CSIQ": ("Canadian Solar", "光伏 / 储能"),
    "RGTI": ("Rigetti", "量子计算"),
    "CRCL": ("Circle", "稳定币 / 金融基础设施"),
    "ASX": ("ASE Technology", "先进封装 / 封测"),
    "WDC": ("Western Digital", "存储 / NAND"),
    "SMR": ("NuScale Power", "AI电力 / 核电小堆"),
    "CRWD": ("CrowdStrike", "网络安全"),
    "CEG": ("Constellation Energy", "AI电力 / 核电"),
    "VST": ("Vistra", "AI电力 / 独立发电"),
    "NRG": ("NRG Energy", "AI电力 / 公用事业"),
    "KO": ("Coca-Cola", "成熟现金流 / 消费"),
    "PEP": ("PepsiCo", "成熟现金流 / 消费"),
    "AEP": ("AEP", "公用事业 / 电网"),
    "AWK": ("American Water", "公用事业 / 水务"),
    "ORCL": ("Oracle", "AI云 / 企业软件"),
    "NOK": ("Nokia", "通信设备 / 光网络"),
    "OUST": ("Ouster", "Physical AI / 激光雷达"),
}


def parse_event_datetime(value):
    raw = text(value)
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        pass
    match = re.search(r"(\d{4}-\d{2}-\d{2})(?:[ T](\d{2}:\d{2}(?::\d{2})?))?", raw)
    if not match:
        return None
    stamp = match.group(1) + (" " + match.group(2) if match.group(2) else "")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(stamp, fmt)
        except Exception:
            continue
    return None


def display_event_time(event: dict) -> str:
    return text(event.get("published_time") or event.get("detected_time"), "时间待确认")


def event_age_hours(event: dict):
    dt = parse_event_datetime(event.get("published_time") or event.get("detected_time"))
    if not dt:
        return None
    now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
    return max(0, (now - dt).total_seconds() / 3600)


def v1_source_status(event: dict) -> str:
    tier = text(event.get("source_tier"))
    if event.get("is_social_only") or tier == "social":
        return "社媒线索"
    if tier == "official":
        return "官方"
    if tier == "major_media":
        return "高可信媒体"
    if tier == "commercial_api":
        return "市场数据"
    return "待核验"


def v1_impact_label(event: dict) -> str:
    direction = text(event.get("impact_direction"))
    if direction == "bullish":
        return "利好"
    if direction == "bearish":
        return "利空"
    if direction == "neutral":
        return "中性"
    return "待确认"


def v1_expiry_status(event: dict) -> str:
    if event.get("is_social_only"):
        return "待核验"
    age = event_age_hours(event)
    if event.get("stale_flag") or event.get("is_old_event"):
        return "历史样本"
    if age is not None and age > 48:
        return "历史样本"
    if text(event.get("verification_status")) in {"official_confirmed", "major_media_confirmed", "commercial_confirmed"}:
        return "已验证"
    return "新事件" if age is not None else "待核验"


def v1_event_title(event: dict | None) -> str:
    if not event:
        return "等待下一条高可信事件确认"
    return text(event.get("title"), "事件待确认")


def v1_beidou_judgement(event: dict) -> str:
    reason = text(event.get("beidou_reason"))
    if reason and "浠" not in reason[:3]:
        return reason[:120]
    direction = v1_impact_label(event)
    if direction == "利好":
        return "提高相关主线研究优先级，但需要等待财报、公告或价格结构验证。"
    if direction == "利空":
        return "优先做风险核验，确认事件是否影响基本面或只是短期情绪。"
    return "作为研究线索记录，等待更高可信来源确认。"


def latest_event_for_symbol(events_by_symbol: dict[str, list[dict]], symbol: str):
    rows = events_by_symbol.get(symbol.upper(), [])
    if not rows:
        return None
    return sorted(rows, key=lambda e: (e.get("severity") or 0, text(e.get("published_time") or e.get("detected_time"))), reverse=True)[0]


def symbol_profile(symbol: str, watch_by_symbol: dict[str, dict]) -> tuple[str, str]:
    symbol = symbol.upper()
    watch = watch_by_symbol.get(symbol, {})
    fallback = SYMBOL_PROFILES.get(symbol, (symbol, "研究主题待归类"))
    return text(watch.get("company"), fallback[0]), text(watch.get("theme"), fallback[1]).replace("_", " ")


def v1_action_bias(event: dict | None) -> str:
    if not event:
        return "等待新事件，不扩大研究动作"
    status = v1_source_status(event)
    direction = v1_impact_label(event)
    if status in {"社媒线索", "待核验"}:
        return "先核验来源，再提高研究优先级"
    if direction == "利好":
        return "确认景气，不追高；等待回调、财报或订单验证"
    if direction == "利空":
        return "先做风险复核，等待官方或财报确认"
    return "只记录线索，等待更强证据"


def v1_risk_note(event: dict | None) -> str:
    if not event:
        return "短期没有新事件，避免占用过高注意力。"
    if event.get("is_social_only"):
        return "社媒线索不能直接当作事实，需要官方或高可信媒体确认。"
    if v1_expiry_status(event) in {"历史样本", "已过期"}:
        return "事件时效已经下降，只保留为背景样本。"
    if v1_impact_label(event) == "利好":
        return "如果市场已经提前交易，短线容易出现利好兑现。"
    if v1_impact_label(event) == "利空":
        return "需要区分一次性扰动和基本面变化。"
    return "影响方向仍需验证。"


def library_title(file_item: dict) -> str:
    note = text(file_item.get("note"))
    if note and "鍐" not in note[:2]:
        return note
    name = text(file_item.get("name"), "北斗资料")
    stem = Path(name).stem.replace("_", " ").replace("-", " ")
    return stem[:1].upper() + stem[1:]


def build_home_v1(latest: dict, live: dict, watchlist: list[dict], events: list[dict], builtin_files: dict, research_library: dict, research_radar: dict) -> dict:
    updated_at = text(latest.get("鍖椾含鏃堕棿") or latest.get("鐢熸垚鏃堕棿UTC"), datetime.now().strftime("%Y-%m-%d %H:%M"))
    watch_by_symbol = {text(row.get("ticker")).upper(): row for row in watchlist}
    events_by_symbol: dict[str, list[dict]] = {}
    for event in events:
        symbols = []
        ticker = text(event.get("ticker")).upper()
        if ticker:
            symbols.append(ticker)
        if isinstance(event.get("tickers"), list):
            symbols.extend(text(item).upper() for item in event.get("tickers") if text(item))
        for symbol in symbols:
            events_by_symbol.setdefault(symbol, []).append(event)

    ranked_events = sorted(
        [event for event in events if display_event_time(event) != "时间待确认"],
        key=lambda e: ((e.get("severity") or 0), text(e.get("published_time") or e.get("detected_time"))),
        reverse=True,
    )
    event_cards = []
    for event in ranked_events[:12]:
        related = []
        if text(event.get("ticker")):
            related.append(text(event.get("ticker")).upper())
        if isinstance(event.get("tickers"), list):
            related.extend(text(item).upper() for item in event.get("tickers") if text(item))
        if not related and text(event.get("sector")):
            related.append(text(event.get("sector")))
        event_cards.append({
            "eventTitle": v1_event_title(event),
            "eventTime": display_event_time(event),
            "source": text(event.get("source"), "来源待确认"),
            "sourceStatus": v1_source_status(event),
            "relatedSymbols": list(dict.fromkeys(related))[:8],
            "impactDirection": v1_impact_label(event),
            "beidouJudgement": v1_beidou_judgement(event),
            "actionMeaning": v1_action_bias(event),
            "expiryStatus": v1_expiry_status(event),
            "updatedAt": updated_at,
        })

    core_focus_symbols, watch_pool_symbols = derive_home_symbol_groups(watchlist, events_by_symbol)
    focus_symbols = []
    for idx, symbol in enumerate(core_focus_symbols):
        event = latest_event_for_symbol(events_by_symbol, symbol)
        name, theme = symbol_profile(symbol, watch_by_symbol)
        base = 90 - min(idx, 8) * 3
        if event:
            base += min(10, (event.get("severity") or 0) * 2)
        focus_symbols.append({
            "symbol": symbol,
            "name": name,
            "theme": theme,
            "beidouStatus": "核心跟踪",
            "focusWeight": max(62, min(98, base)),
            "latestEvent": v1_event_title(event),
            "eventTime": display_event_time(event) if event else "暂无新事件",
            "sourceStatus": v1_source_status(event) if event else "待核验",
            "impactDirection": v1_impact_label(event) if event else "待确认",
            "actionBias": v1_action_bias(event),
            "riskNote": v1_risk_note(event),
            "updatedAt": updated_at,
        })
    focus_symbols = sorted(focus_symbols, key=lambda row: row["focusWeight"], reverse=True)[:15]
    focus_set = {row["symbol"] for row in focus_symbols}

    watch_pool = []
    for symbol in watch_pool_symbols:
        if symbol in focus_set:
            continue
        event = latest_event_for_symbol(events_by_symbol, symbol)
        name, theme = symbol_profile(symbol, watch_by_symbol)
        age = event_age_hours(event) if event else None
        stale = not event or (age is not None and age > 24 * 7)
        watch_pool.append({
            "symbol": symbol,
            "name": name,
            "theme": theme,
            "watchReason": v1_event_title(event) if event else f"{theme} 仍有研究价值，但缺少新的高可信触发。",
            "upgradeTrigger": "出现订单、财报指引、官方公告、行业数据验证或显著风险释放。",
            "currentStatus": "暂停/冷却" if stale else "观察等待",
            "updatedAt": updated_at,
        })

    research_seed = [
        ("HBM / DRAM", ["MU", "NVDA", "WDC"], "AI训练和推理需求牵引高端内存周期。", "财报 / 行业价格 / 产能数据", "方向有效，但需要估值、财报和涨幅共同验证。", "等待 MU 财报和 HBM 订单验证。"),
        ("AI电力", ["CEG", "VST", "NRG", "SMR", "AEP"], "数据中心电力需求是 AI 基础设施的长期约束。", "政策 / 电力合同 / 公司指引", "长期逻辑清楚，短期要防止叙事拥挤。", "跟踪正式合同、监管批准和资本开支。"),
        ("先进封装", ["AMKR", "ASX", "TSM", "INTC"], "AI 芯片扩产会向封装和测试链条传导。", "公司公告 / 产能 / 财报", "属于 AI 主线扩散方向，需要订单和毛利验证。", "跟踪先进封装产能和客户结构。"),
        ("CPO / 硅光", ["AVGO", "MRVL", "CRDO", "CIEN", "NOK"], "数据中心互连瓶颈提升光互连研究价值。", "行业资料 / 财报 / 技术路线", "可作为 AI 后排扩散研究，不直接等同短线动作。", "跟踪商业化时间和客户验证。"),
        ("Physical AI", ["OUST", "NVDA", "AMD"], "机器人和空间智能可能成为 AI 应用扩散方向。", "产品发布 / 客户 / 收入质量", "需要把叙事和实际收入分开。", "等待订单、收入和现金流确认。"),
        ("成熟现金流公司估值", ["KO", "PEP", "AWK"], "用于平衡高波动 AI 主题的估值和现金流研究。", "财报 / 估值模型 / 股息数据", "重点在防守属性和估值安全边际。", "更新估值区间和财报质量。"),
        ("世界杯消费链", ["KO", "PEP"], "大型赛事可能影响广告、饮料和消费链景气。", "赛事日历 / 销售数据 / 财报", "只作为阶段性主题资料沉淀。", "等待公司层面验证。"),
        ("AI数据中心产业链", ["NVDA", "AVGO", "MRVL", "ORCL", "CEG"], "算力、网络、云、电力共同构成 AI 投资主线。", "产业链资料 / 财报 / capex", "主线有效，但需要分层看估值和兑现节奏。", "维护产业链地图和风险清单。"),
    ]
    research_items = [{
        "topic": topic,
        "relatedSymbols": symbols,
        "researchReason": reason,
        "sourceType": source_type,
        "beidouConclusion": conclusion,
        "nextAction": action,
        "updatedAt": updated_at,
    } for topic, symbols, reason, source_type, conclusion, action in research_seed]

    library = []
    for file_item in (builtin_files.get("files") or [])[:12]:
        modified = text(file_item.get("modified"))
        library.append({
            "title": library_title(file_item),
            "category": text(file_item.get("group"), "北斗资料库"),
            "relatedSymbols": [],
            "lastUpdated": modified[:19].replace("T", " ") if modified else updated_at,
            "beidouAbsorbStatus": "已吸收" if file_item.get("line_count", 0) else "待确认",
            "oneLineConclusion": text(file_item.get("preview"), "资料已进入北斗资料库。")[:110],
            "fileName": text(file_item.get("name")),
            "url": text(file_item.get("url")),
        })
    for record in (research_library.get("recent") or [])[:6]:
        library.append({
            "title": text(record.get("title") or record.get("topic") or record.get("name"), "研究资料"),
            "category": text(record.get("pool"), "研究池"),
            "relatedSymbols": [text(record.get("ticker")).upper()] if text(record.get("ticker")) else [],
            "lastUpdated": text(record.get("created_at"), updated_at),
            "beidouAbsorbStatus": "仅七星资料",
            "oneLineConclusion": text(record.get("body") or record.get("summary"), "等待北斗吸收。")[:110],
            "fileName": text(record.get("source"), "local_research"),
            "url": "",
        })

    top_event = event_cards[0] if event_cards else {}
    key_symbols = [row["symbol"] for row in focus_symbols[:8]]
    overview = {
        "marketTemperature": text(latest.get("market_regime"), "中性 / 等待确认"),
        "aiSemiCycle": "偏强但需验证" if any(s in focus_set for s in {"NVDA", "TSM", "MU", "AVGO", "MRVL"}) else "等待新证据",
        "riskAppetite": "谨慎",
        "topEvent": top_event.get("eventTitle", "暂无可进入首页的高可信事件"),
        "keySymbols": key_symbols,
        "beidouConclusion": "先分层研究和风险核验，不把关注权重当作交易指令。",
        "updatedAt": updated_at,
    }
    risks = [
        {"riskTitle": "AI半导体利好兑现风险", "affectedSymbols": [s for s in ["TSM", "NVDA", "AVGO", "MU", "MRVL", "AMKR"] if s in focus_set], "riskLevel": "中高", "riskReason": "如果市场已经提前交易景气改善，短线可能出现利好兑现。", "beidouAction": "确认景气，但等待财报、订单、回调或价格结构验证。", "updatedAt": updated_at},
        {"riskTitle": "来源时效和外部接口风险", "affectedSymbols": overview["keySymbols"], "riskLevel": "中", "riskReason": "后台会定时刷新事件快照，但部分外部来源可能延迟或超时。", "beidouAction": "事件卡必须查看来源状态和时效状态，旧内容只作为背景样本。", "updatedAt": updated_at},
        {"riskTitle": "社媒线索待核验风险", "affectedSymbols": list(dict.fromkeys([s for e in event_cards if e["sourceStatus"] == "社媒线索" for s in e["relatedSymbols"]]))[:8], "riskLevel": "中", "riskReason": "社媒内容不能直接当作事实，需要官方公告或高可信媒体交叉验证。", "beidouAction": "只进入研究雷达，不直接形成行动结论。", "updatedAt": updated_at},
        {"riskTitle": "高波动标的叙事拥挤风险", "affectedSymbols": [s for s in ["RGTI", "CRCL", "OUST", "SMR"] if s in focus_set or s in watch_pool_symbols], "riskLevel": "中高", "riskReason": "高波动主题容易由情绪驱动，基本面兑现节奏可能滞后。", "beidouAction": "降低冲动判断，优先补充财报、订单、监管和现金流证据。", "updatedAt": updated_at},
    ]
    return {
        "overview": overview,
        "topEvents": event_cards[:5],
        "focusSymbols": focus_symbols,
        "watchPool": watch_pool,
        "researchPool": research_items,
        "eventRadar": event_cards,
        "library": library[:18],
        "risks": risks,
        "disclaimer": "北斗系统用于投资研究、事件整理和风险提示，不构成买卖建议。北斗关注权重仅代表研究优先级，不代表仓位比例或交易指令。",
    }


def build_webdata() -> dict:
    latest_local = read_json(ROOT / "reports" / "premarket" / "latest_zh.json", {})
    latest = fetch_json(f"{API_ROOT}/api/latest", latest_local)
    live = fetch_json(f"{API_ROOT}/api/live", {})
    watch_yaml = read_text(ROOT / "config" / "watchlist.yaml") or read_text(ROOT / "beidou_us_radar" / "config" / "watchlist.yaml")
    sources_yaml = read_text(ROOT / "beidou_us_radar" / "config" / "sources.yaml")
    watch_config = parse_watch_config(watch_yaml)

    layer = latest.get("数据源层V1") or {}
    events_raw = latest.get("北斗事件流V1") or latest.get("重要置顶") or latest_local.get("重要置顶") or []
    events = []
    for index, row in enumerate(events_raw):
        event = normalize_event(row, index)
        if text(event.get("ticker")).upper() in HIDDEN_TICKERS:
            continue
        if event.get("relation_type") == "actual_holding":
            event["relation_type"] = "watchlist"
            event["beidou_reason"] = text(event.get("beidou_reason"), "仅作投研线索。").replace("实际持仓", "跟踪标的")
        events.append(event)

    watchlist = []
    seen_watch = set()
    for item in watch_config:
        ticker = text(item.get("ticker")).upper()
        if not ticker or ticker in HIDDEN_TICKERS or ticker in seen_watch:
            continue
        seen_watch.add(ticker)
        evs = [event for event in events if event["ticker"] == ticker and event["relation_type"] == "watchlist"]
        low_buy = "batch_research_allowed" if any("分批研究" in e["suggested_action"] for e in evs) else "fundamental_check_needed" if any(e["event_type"] in {"earnings", "guidance"} for e in evs) else "not_ready"
        watchlist.append({
            "ticker": ticker,
            "company": ticker,
            "theme": text(item.get("theme"), "research"),
            "company_type": text(item.get("theme"), "research").replace("_", " "),
            "catalyst": evs[0]["title"] if evs else "等待高质量新催化",
            "valuation_status": "valuation_watch" if evs else "pending",
            "financial_quality": "fundamental_check_needed",
            "chart_structure": "wait_for_support" if any(e["impact_direction"] == "bearish" for e in evs) else "pending",
            "low_buy_status": low_buy,
            "last_checked_time": text(latest.get("生成时间UTC") or latest.get("北京时间"), "-"),
            "latest_research_event": evs[0]["summary"] if evs else "观察池只进入研究队列，不按实仓防守提醒。",
        })

    def instrument_quote_note(requested_symbol: str, matched_symbol: str) -> dict:
        matched = matched_symbol.upper()
        if requested_symbol == "DXY":
            if matched == "UUP":
                return {
                    "label": "UUP 美元ETF代理",
                    "symbol": "UUP",
                    "verificationStatus": "代理指标，待DXY官方源核验",
                    "sourceNote": "当前免费源返回的是UUP美元ETF价格，不是真正DXY美元指数；DXY需以ICE/MarketWatch等指数源核验。",
                }
            return {
                "label": "DXY 美元指数",
                "symbol": matched or "DXY",
                "verificationStatus": "待DXY官方源核验",
                "sourceNote": "美元指数口径；仍需以ICE/MarketWatch等指数源核验。",
            }
        if requested_symbol == "Gold":
            if matched in {"GLD", "IAU"}:
                return {
                    "label": f"{matched} 黄金ETF代理",
                    "symbol": matched,
                    "verificationStatus": "代理指标，待现货黄金/COMEX核验",
                    "sourceNote": f"当前免费源返回的是{matched}黄金ETF价格，不是现货黄金/COMEX黄金；现货黄金需单独核验。",
                }
            if matched == "GC=F":
                return {
                    "label": "COMEX黄金期货代理",
                    "symbol": "GC=F",
                    "verificationStatus": "期货代理，待现货黄金核验",
                    "sourceNote": "当前免费源返回的是COMEX黄金期货价格，不是现货黄金；现货黄金需单独核验。",
                }
            return {
                "label": "黄金代理指标",
                "symbol": matched or "Gold",
                "verificationStatus": "代理指标，待黄金官方/高可信源核验",
                "sourceNote": "当前免费源返回的是黄金相关代理价格，不保证是现货黄金；现货黄金需单独核验。",
            }
        return {}
    instruments = []
    rows = (live.get("美国指数") or []) + (live.get("实时快照") or [])
    aliases = {
        "SPY": ["SPY"], "QQQ": ["QQQ"], "DIA": ["DIA"], "IWM": ["IWM"], "SOXX": ["SOXX"],
        "VIX": ["VIX", "^VIX"], "DXY": ["DXY", "DX-Y.NYB", "UUP"], "10Y": ["10Y", "^TNX", "TNX"],
        "Gold": ["Gold", "GLD", "IAU", "GC=F"], "BTC": ["BTC", "BTC-USD"],
    }
    for label, symbol in [("SPY", "SPY"), ("QQQ", "QQQ"), ("DIA", "DIA"), ("IWM", "IWM"), ("SOXX", "SOXX"), ("VIX", "VIX"), ("DXY", "DXY"), ("10Y Yield", "10Y"), ("Gold", "Gold"), ("BTC", "BTC")]:
        row = next((r for r in rows if text(r.get("标的") or r.get("股票代码") or r.get("symbol")).upper() in {x.upper() for x in aliases[symbol]}), {})
        matched_symbol = text(row.get("标的") or row.get("股票代码") or row.get("symbol"), symbol)
        price = number(row.get("当前价格"))
        change = number(row.get("当前涨跌幅"))
        item = {
            "label": label,
            "symbol": symbol,
            "sourceSymbol": matched_symbol,
            "price": price,
            "change": change,
            "quoteStatus": "ok" if price is not None else "未取得",
            "displayPrice": price if price is not None else "未取得",
            "displayChange": change if change is not None else "未取得",
            "verificationStatus": "本地行情快照，待外部公开源核验" if price is not None else "未取得，无法核验",
            "sourceNote": "公开免费行情源快照；仅作研究参考，不作为交易依据。",
        }
        item.update(instrument_quote_note(symbol, matched_symbol))
        instruments.append(item)

    health = []
    for row in layer.get("健康检查") or []:
        stale = bool(row.get("staleness_flag"))
        ok = bool(row.get("可用"))
        health.append({
            "source_name": text(row.get("数据源"), "source"),
            "layer": text(row.get("layer"), "Data Source Layer V1"),
            "status": "active" if ok and not stale else "degraded" if ok else "down",
            "last_success_time": text(row.get("检查时间UTC"), "-"),
            "latency_ms": row.get("latency_ms"),
            "error_count": len(row.get("异常字段") or []),
            "stale_count": 1 if stale else 0,
            "rate_limit_status": "not reported",
            "credibility_level": "verified by source health" if ok else "needs attention",
        })
    for row in layer.get("禁用A股源") or []:
        health.append({"source_name": text(row.get("name")), "layer": "disabled A-share source", "status": "disabled", "last_success_time": "-", "latency_ms": None, "error_count": 0, "stale_count": 0, "rate_limit_status": "disabled by rule", "credibility_level": "not part of US radar"})
    source_layers = build_source_layers(sources_yaml, health)
    builtin_files = collect_builtin_files()
    research_radar = build_research_radar(watchlist, events, live)
    research_library = build_research_library()
    home_v1 = build_home_v1(latest, live, watchlist, events, builtin_files, research_library, research_radar)
    service_status = latest.get("服务状态") or {}

    return {
        "schemaVersion": "beidou_monitor_site_v1",
        "site": {
            "name": SITE_NAME,
            "subtitle": "合并北斗雷达、北美监视网页和北斗/七星资料包",
            "canonical": True,
        "dedupe_policy": "前台只保留一套观察池、事件流、数据源健康和人工判断；不展示实仓明细，老雷达作为后台数据源。",
        },
        "market": {
            "easternTime": text(latest.get("美东时间"), "-"),
            "beijingTime": text(latest.get("北京时间"), "-"),
            "sessionLabel": text((latest.get("当前美股时段") or {}).get("label"), "状态待确认"),
            "marketRegime": text(latest.get("market_regime"), "pending / no signal"),
            "generatedAtUtc": text(latest.get("生成时间UTC")),
            "instruments": instruments,
            "refreshPolicy": build_refresh_policy(),
        },
        "holdings": [],
        "watchlist": watchlist,
        "events": events,
        "marketStructure": build_market_structure(live),
        "researchRadar": research_radar,
        "researchLibrary": research_library,
        "homeV1": home_v1,
        "sourceHealth": health,
        "sourceLayers": source_layers,
        "builtinFiles": builtin_files,
        "recoveredContent": build_recovered_content(builtin_files, source_layers, watchlist, events),
        "alertSamples": layer.get("手机短版样例") or [],
        "status": {
            "source": "api + builtin",
            "scan": service_status,
            "note": "自动更新模式：读取北斗事件快照、实时接口和本地资料库；不展示实仓明细，只保留观察池和研究资料。",
        },
    }


class Handler(BaseHTTPRequestHandler):
    def send_bytes(self, status: int, body: bytes, content_type: str):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path in {"/", "/dashboard", "/radar/market-structure"}:
            self.send_bytes(200, (WEB_ROOT / "preview_dashboard.html").read_bytes(), "text/html; charset=utf-8")
            return
        if path == "/api/webdata":
            self.send_bytes(200, json.dumps(build_webdata(), ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
            return
        if path == "/api/research/search":
            query = parse_qs(parsed.query).get("q", [""])[0]
            self.send_bytes(200, json.dumps(research_search(query, 120), ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
            return
        if path.startswith("/builtin/"):
            rel = unquote(path.removeprefix("/builtin/"))
            target = (BUILTIN_ROOT / rel).resolve()
            root = BUILTIN_ROOT.resolve()
            if root == target or root not in target.parents or not target.is_file():
                self.send_bytes(404, b"not found", "text/plain; charset=utf-8")
                return
            self.send_bytes(200, target.read_bytes(), "text/plain; charset=utf-8")
            return
        if path == "/health":
            self.send_bytes(200, b"ok", "text/plain; charset=utf-8")
            return
        self.send_bytes(404, b"not found", "text/plain; charset=utf-8")

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/scan":
            try:
                req = urllib.request.Request(f"{API_ROOT}/api/scan", method="POST")
                with urllib.request.urlopen(req, timeout=10) as res:
                    body = res.read()
                    status = res.status
                self.send_bytes(status, body, "application/json; charset=utf-8")
            except urllib.error.HTTPError as exc:
                self.send_bytes(exc.code, exc.read(), "application/json; charset=utf-8")
            except Exception as exc:
                body = {"ok": False, "message": f"触发扫描失败：{exc}"}
                self.send_bytes(502, json.dumps(body, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
            return
        if path == "/api/research/save":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
                record = append_research_record(payload if isinstance(payload, dict) else {})
                body = {"ok": True, "message": "已保存到本地研究库，默认保留半年。", "record": record, "storage": research_storage_status()}
                self.send_bytes(200, json.dumps(body, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
            except Exception as exc:
                body = {"ok": False, "message": f"保存失败：{exc}"}
                self.send_bytes(500, json.dumps(body, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
            return
        self.send_bytes(404, b"not found", "text/plain; charset=utf-8")

    def log_message(self, fmt, *args):
        print(f"[{datetime.now(timezone.utc).isoformat()}] {fmt % args}")


def main():
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8786"))
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"北斗监视网站已启动：http://{host}:{port}/dashboard")
    server.serve_forever()


if __name__ == "__main__":
    main()
