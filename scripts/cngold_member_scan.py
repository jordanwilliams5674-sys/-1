#!/usr/bin/env python3
"""Collect Cngold signals for the Beidou local radar.

This reader does not inspect browser cookies or account secrets. It pulls
publicly reachable Cngold pages and writes only investment-relevant snippets
into the local social/member signal feed used by the dashboard.
"""

from __future__ import annotations

import argparse
from email.utils import parsedate_to_datetime
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "member_sources" / "public_news"
SOCIAL_DIR = ROOT / "data" / "social_signals"
USER_AGENT = "beidou-cngold-member-source/1.1"

SOURCE_GROUPS = [
    {
        "label": "金投网财经源",
        "author": "金投网",
        "urls": [
            "https://finance.cngold.org/",
            "https://kuaixun.cngold.org/",
            "https://quote.cngold.org/",
            "https://www.cngold.org/quote/",
            "https://usstock.cngold.org/",
        ],
    },
    {
        "label": "金十数据",
        "author": "金十数据",
        "urls": [
            "https://www.jin10.com/",
            "https://www.jin10.com/in/",
        ],
    },
    {
        "label": "口袋贵金属",
        "author": "口袋贵金属",
        "urls": [
            "https://www.gkoudai.com/",
        ],
    },
]
YOUTUBE_FEEDS = [
    {
        "label": "CNBC Television",
        "url": "https://www.youtube.com/feeds/videos.xml?channel_id=UCrp_UI8XtuYfpiqluWLD7Lw",
    },
    {
        "label": "Yahoo Finance",
        "url": "https://www.youtube.com/feeds/videos.xml?channel_id=UCEAZeUIeJs0IjQiqTCdVSIg",
    },
    {
        "label": "Benzinga",
        "url": "https://www.youtube.com/feeds/videos.xml?channel_id=UCqQs28K2zj2dOsc5NfXUKEg",
    },
    {
        "label": "The Compound",
        "url": "https://www.youtube.com/feeds/videos.xml?channel_id=UCBRpqrzuuqE8TZcWw75JSdw",
    },
]
INFO_FEEDS = [
    {
        "label": "美联储公告",
        "author": "Federal Reserve",
        "url": "https://www.federalreserve.gov/feeds/press_all.xml",
        "category": "宏观/央行",
        "include_all": True,
    },
    {
        "label": "美联储讲话",
        "author": "Federal Reserve",
        "url": "https://www.federalreserve.gov/feeds/speeches.xml",
        "category": "讲话/表态",
        "include_all": True,
    },
    {
        "label": "美联储证词",
        "author": "Federal Reserve",
        "url": "https://www.federalreserve.gov/feeds/testimony.xml",
        "category": "讲话/表态",
        "include_all": True,
    },
    {
        "label": "SEC监管",
        "author": "SEC",
        "url": "https://www.sec.gov/news/pressreleases.rss",
        "category": "监管/政策",
        "include_all": False,
    },
    {
        "label": "CNBC市场资讯",
        "author": "CNBC",
        "url": "https://www.cnbc.com/id/100003114/device/rss/rss.html",
        "category": "全球市场资讯",
        "include_all": False,
    },
    {
        "label": "MarketWatch市场资讯",
        "author": "MarketWatch",
        "url": "https://feeds.marketwatch.com/marketwatch/topstories/",
        "category": "全球市场资讯",
        "include_all": False,
    },
    {
        "label": "Yahoo Finance资讯",
        "author": "Yahoo Finance",
        "url": "https://finance.yahoo.com/news/rssindex",
        "category": "全球市场资讯",
        "include_all": False,
    },
]
BAIDU_MANUAL_PATH = ROOT / "data" / "member_sources" / "baidu_gushitong" / "manual_signals.json"

RELEVANT_TERMS = [
    "美股",
    "纳斯达克",
    "NASDAQ",
    "标普",
    "S&P",
    "道琼斯",
    "美国股市",
    "美国上市",
    "英伟达",
    "黄仁勋",
    "NVIDIA",
    "NVDA",
    "特斯拉",
    "Tesla",
    "TSLA",
    "SpaceX",
    "稳定币",
    "Circle",
    "CRCL",
    "美联储",
    "美国通胀",
    "美国非农",
    "降息",
    "加息",
    "FOMC",
    "鲍威尔",
    "CPI",
    "PCE",
    "PMI",
    "ISM",
    "美债",
    "美元",
    "美元指数",
    "关税",
    "贸易战",
    "制裁",
    "出口管制",
    "中东",
    "俄乌",
    "地缘",
    "重大交易",
    "收购",
    "并购",
    "监管",
    "芯片",
    "半导体",
    "人工智能",
    "AI",
    "数据中心",
    "黄金",
    "金价",
    "贵金属",
    "现货金",
    "COMEX",
    "Marvell",
    "Broadcom",
    "Oracle",
    "Micron",
    "美光",
    "AMD",
    "苹果",
    "Apple",
    "AAPL",
    "微软",
    "Microsoft",
    "MSFT",
    "Meta",
    "META",
    "谷歌",
    "Google",
    "GOOGL",
    "亚马逊",
    "Amazon",
    "AMZN",
    "CrowdStrike",
    "CRWD",
    "Intel",
    "INTC",
    "Rigetti",
    "RGTI",
    "SQQQ",
    "SOXS",
    "QQQ",
    "SPY",
    "stocks",
    "stock market",
    "Wall Street",
    "S&P 500",
    "Nasdaq",
    "Federal Reserve",
    "Fed",
    "Powell",
    "speech",
    "remarks",
    "testimony",
    "Waller",
    "Williams",
    "Bostic",
    "Kashkari",
    "Bowman",
    "Jefferson",
    "Goolsbee",
    "Treasury",
    "SEC",
    "rates",
    "rate cut",
    "rate hike",
    "inflation",
    "jobs report",
    "payrolls",
    "jobless claims",
    "retail sales",
    "consumer sentiment",
    "bond yields",
    "10-year",
    "dollar",
    "tariff",
    "sanctions",
    "geopolitical",
    "Middle East",
    "Russia",
    "Ukraine",
    "China",
    "earnings",
    "guidance",
    "M&A",
    "IPO",
    "AI chips",
    "semiconductor",
    "data center",
    "quantum",
]

SYMBOL_HINTS = {
    "NVDA": ["英伟达", "NVIDIA", "黄仁勋"],
    "TSLA": ["特斯拉", "Tesla"],
    "CRCL": ["Circle", "稳定币"],
    "MRVL": ["Marvell"],
    "AVGO": ["Broadcom", "博通"],
    "ORCL": ["Oracle", "甲骨文"],
    "MU": ["Micron", "美光"],
    "AMD": ["AMD"],
    "INTC": ["Intel", "英特尔", "INTC"],
    "CRWD": ["CrowdStrike", "CRWD"],
    "RGTI": ["Rigetti", "RGTI", "quantum"],
    "SQQQ": ["SQQQ"],
    "SOXS": ["SOXS"],
    "QQQ": ["QQQ", "Nasdaq 100", "纳斯达克100"],
    "SPY": ["SPY", "S&P 500", "标普500"],
    "AAPL": ["苹果", "Apple", "AAPL"],
    "MSFT": ["微软", "Microsoft", "MSFT"],
    "META": ["Meta", "META"],
    "GOOGL": ["谷歌", "Google", "GOOGL"],
    "AMZN": ["亚马逊", "Amazon", "AMZN"],
    "GOLD_BASKET": ["黄金", "金价", "贵金属", "现货金", "COMEX", "美债", "美元指数", "DXY"],
    "USMARKET": [
        "美联储",
        "鲍威尔",
        "讲话",
        "表态",
        "证词",
        "听证",
        "FOMC",
        "降息",
        "加息",
        "CPI",
        "PCE",
        "非农",
        "关税",
        "制裁",
        "出口管制",
        "中东",
        "俄乌",
        "美债",
        "美元",
        "美国财政部",
        "SEC",
        "美国证监会",
        "收益率",
        "十年期",
        "就业",
        "初请",
        "纳斯达克",
        "标普",
    ],
}

US_MARKET_TERMS = [
    "美股",
    "纳斯达克",
    "NASDAQ",
    "标普",
    "S&P",
    "道琼斯",
    "美国股市",
    "美国上市",
    "登陆纳斯达克",
    "美联储",
    "讲话",
    "表态",
    "证词",
    "听证",
    "美国通胀",
    "美国非农",
    "降息",
    "加息",
    "FOMC",
    "鲍威尔",
    "CPI",
    "PCE",
    "PMI",
    "ISM",
    "美债",
    "美元",
    "关税",
    "贸易战",
    "制裁",
    "出口管制",
    "中东",
    "俄乌",
    "地缘",
    "重大交易",
    "收购",
    "并购",
    "美国财政部",
    "SEC",
    "美国证监会",
    "收益率",
    "十年期",
    "就业",
    "初请",
]

YOUTUBE_RELEVANT_TERMS = RELEVANT_TERMS + [
    "markets",
    "market",
    "stocks",
    "stock",
    "Wall Street",
    "Nasdaq",
    "S&P 500",
    "Dow",
    "Federal Reserve",
    "Fed",
    "Powell",
    "speech",
    "remarks",
    "testimony",
    "Treasury",
    "SEC",
    "rate cuts",
    "rates",
    "inflation",
    "CPI",
    "PCE",
    "jobs",
    "payrolls",
    "jobless claims",
    "tariffs",
    "sanctions",
    "geopolitical",
    "earnings",
    "guidance",
    "AI",
    "chips",
    "semiconductor",
    "data center",
    "quantum",
]
YOUTUBE_MAX_AGE = timedelta(hours=72)
INFO_MAX_AGE = timedelta(hours=96)

NON_US_NOISE_TERMS = [
    "A股",
    "港股",
    "沪深",
    "科创",
    "创业板",
    "龙虎榜",
    "澳股",
    "小麦",
    "棉花",
    "原油",
    "布伦特",
    "WTI",
    "比特币",
    "港股通",
    "研报掘金",
    "日本央行",
    "植田和男",
    "上美股份",
]

CHINA_PRODUCT_NOISE_TERMS = [
    "ETF华夏",
    "华夏ETF",
    "A股ETF",
    "场内ETF",
    "联接基金",
    "成份股",
    "中证",
    "沪深",
    "创业板",
    "科创板",
    "净申购",
    "盘中净申购",
    "规模居同标的",
    "相关产品：",
]

LOW_VALUE_INFO_TERMS = [
    "what's worth streaming",
    "what’s worth streaming",
    "worth streaming",
    "streaming in june",
    "streaming in july",
    "netflix, hulu, hbo max",
]

DIRECT_US_ANCHOR_TERMS = [
    "美股",
    "纳斯达克",
    "NASDAQ",
    "标普",
    "S&P",
    "道琼斯",
    "美国股市",
    "美联储",
    "美国通胀",
    "美国非农",
    "NVIDIA",
    "Tesla",
    "Marvell",
    "Circle",
    "Oracle",
    "Micron",
    "Intel",
    "Rigetti",
    "英伟达",
    "特斯拉",
    "迈威尔",
    "美光",
    "英特尔",
]

MAX_SIGNAL_AGE = timedelta(days=14)
LAST_SOURCE_STATUS: list[dict] = []


@dataclass
class CngoldSignal:
    id: str
    symbol: str
    title: str
    url: str
    source_page: str
    source_label: str
    author: str
    published_at: str
    fetched_at: str
    importance: str
    note: str


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._in_a = False
        self._href = ""
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "a":
            self._in_a = True
            self._href = dict(attrs).get("href") or ""
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._in_a:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._in_a:
            text = " ".join("".join(self._text).split())
            self.links.append((text, self._href))
            self._in_a = False
            self._href = ""
            self._text = []


def fetch_text(url: str, timeout: int = 15) -> str:
    req = Request(url, headers={"User-Agent": USER_AGENT})
    raw = urlopen(req, timeout=timeout).read()
    for encoding in ("utf-8", "gb18030", "gbk"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def term_in_text(text: str, term: str) -> bool:
    low = text.lower()
    needle = term.lower().strip()
    if not needle:
        return False
    if re.fullmatch(r"[a-z0-9. ]+", needle):
        return re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", low) is not None
    return needle in low


def relevant(text: str) -> bool:
    low = text.lower()
    return any(term_in_text(low, term) for term in RELEVANT_TERMS)


def infer_symbol(text: str) -> str:
    for symbol, terms in SYMBOL_HINTS.items():
        if any(term_in_text(text, term) for term in terms):
            return symbol
    if any(term_in_text(text, term) for term in US_MARKET_TERMS):
        return "USMARKET"
    return "USSTOCK"


def is_us_stock_signal(text: str, url: str, symbol: str) -> bool:
    if not url.startswith(("http://", "https://")):
        return False
    low = text.lower()
    if symbol == "GOLD_BASKET":
        return any(term_in_text(low, term) for term in SYMBOL_HINTS["GOLD_BASKET"])
    has_symbol = symbol in SYMBOL_HINTS and symbol != "USMARKET"
    has_us_market = any(term_in_text(low, term) for term in US_MARKET_TERMS)
    has_non_us_noise = any(term_in_text(low, term) for term in NON_US_NOISE_TERMS)
    has_china_product_noise = any(term_in_text(low, term) for term in CHINA_PRODUCT_NOISE_TERMS)
    if has_china_product_noise:
        return False
    if has_non_us_noise and not has_symbol:
        return False
    if has_symbol or has_us_market:
        return True
    return False


def low_value_info_signal(text: str) -> bool:
    low = text.lower()
    return any(term in low for term in LOW_VALUE_INFO_TERMS)


def looks_like_quote_entry(title: str, symbol: str) -> bool:
    compact = re.sub(r"\s+", "", title)
    if symbol == "GOLD_BASKET" and len(compact) <= 10 and any(term in compact for term in ["黄金", "白银", "COMEX", "伦敦金"]):
        return True
    if len(compact) <= 12 and any(term in compact for term in ["纸白银", "纸黄金", "现货白银", "现货黄金", "美元指数", "外汇牌价"]):
        return True
    return False


def manual_baidu_signals(fetched: datetime, limit: int) -> list[CngoldSignal]:
    if not BAIDU_MANUAL_PATH.exists():
        return []
    try:
        payload = json.loads(BAIDU_MANUAL_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        return [
            CngoldSignal(
                id=signal_id(f"baidu-manual-error:{exc}", str(BAIDU_MANUAL_PATH)),
                symbol="SOURCE",
                title=f"百度股市通手动源读取失败：{exc}",
                url="",
                source_page=str(BAIDU_MANUAL_PATH),
                source_label="百度股市通",
                author="百度股市通",
                published_at=fetched.isoformat(),
                fetched_at=fetched.isoformat(),
                importance="normal",
                note="来源状态记录，不参与交易判断。",
            )
        ]
    raw = payload.get("社媒信号", payload.get("signals", payload if isinstance(payload, list) else []))
    signals: list[CngoldSignal] = []
    if not isinstance(raw, list):
        return signals
    for item in raw[:limit]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("文字") or item.get("title") or item.get("text") or "").strip()
        if not title:
            continue
        symbol = str(item.get("股票代码") or item.get("symbol") or infer_symbol(title)).upper().strip()
        url = str(item.get("原帖链接") or item.get("url") or "")
        published = str(item.get("发布时间") or item.get("published_at") or fetched.isoformat())
        signals.append(
            CngoldSignal(
                id=str(item.get("id") or signal_id(title, url or published)),
                symbol=symbol,
                title=title,
                url=url,
                source_page=str(BAIDU_MANUAL_PATH),
                source_label="百度股市通",
                author=str(item.get("作者") or item.get("author") or "百度股市通"),
                published_at=published,
                fetched_at=fetched.isoformat(),
                importance=str(item.get("重要级别") or item.get("importance") or "normal"),
                note=str(item.get("备注") or item.get("note") or "百度股市通可见页面/截图导入；需回看原页确认。"),
            )
        )
    return signals


def published_from_url(url: str, fetched: datetime) -> datetime:
    match = re.search(r"/(20\d{2})-(\d{2})-(\d{2})/", url)
    if not match:
        return fetched
    y, m, d = map(int, match.groups())
    return datetime(y, m, d, fetched.hour, fetched.minute, tzinfo=ZoneInfo("Asia/Shanghai"))


def parse_atom_datetime(value: str | None, fetched: datetime) -> datetime:
    if not value:
        return fetched
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return fetched
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(ZoneInfo("Asia/Shanghai"))


def parse_feed_datetime(value: str | None, fetched: datetime) -> datetime:
    if not value:
        return fetched
    text = value.strip()
    if not text:
        return fetched
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        parsed = None
    if parsed is not None:
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(ZoneInfo("Asia/Shanghai"))
    try:
        parsed = parsedate_to_datetime(text)
    except Exception:
        return fetched
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(ZoneInfo("Asia/Shanghai"))


def xml_text(element: ET.Element | None, path: str, namespaces: dict[str, str] | None = None) -> str:
    if element is None:
        return ""
    found = element.find(path, namespaces or {})
    return "".join(found.itertext()).strip() if found is not None else ""


def feed_entries(root: ET.Element) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    for item in root.findall(".//item"):
        link = xml_text(item, "link") or xml_text(item, "guid")
        entries.append(
            {
                "title": xml_text(item, "title"),
                "link": link,
                "published": xml_text(item, "pubDate") or xml_text(item, "published") or xml_text(item, "updated"),
                "summary": xml_text(item, "description"),
            }
        )
    for entry in root.findall("atom:entry", ns):
        link = ""
        for link_el in entry.findall("atom:link", ns):
            href = link_el.attrib.get("href", "")
            if href:
                link = href
                break
        entries.append(
            {
                "title": xml_text(entry, "atom:title", ns),
                "link": link,
                "published": xml_text(entry, "atom:published", ns) or xml_text(entry, "atom:updated", ns),
                "summary": xml_text(entry, "atom:summary", ns),
            }
        )
    return entries


def info_note(text: str, fallback: str) -> str:
    low = text.lower()
    if any(term_in_text(low, term) for term in ["speech", "remarks", "testimony", "讲话", "表态", "证词", "听证", "powell", "waller", "williams", "bostic", "kashkari"]):
        return "讲话/表态"
    if any(term_in_text(low, term) for term in ["federal reserve", "fed", "fomc", "美联储", "cpi", "pce", "payrolls", "非农", "inflation", "通胀", "jobs", "就业", "yield", "美债", "dollar", "美元"]):
        return "宏观/央行"
    if any(term_in_text(low, term) for term in ["sec", "treasury", "监管", "财政部", "tariff", "关税", "sanction", "制裁"]):
        return "监管/政策"
    if any(term_in_text(low, term) for term in ["earnings", "guidance", "财报", "指引"]):
        return "财报/指引"
    return fallback


def info_important(text: str, symbol: str, note: str) -> bool:
    if symbol not in {"USSTOCK"}:
        return True
    low = text.lower()
    return note in {"讲话/表态", "宏观/央行", "监管/政策"} or any(
        term_in_text(low, term)
        for term in ["federal reserve", "fed", "powell", "fomc", "cpi", "pce", "payrolls", "tariff", "sanction", "sec", "treasury", "美联储", "鲍威尔", "非农", "关税", "制裁"]
    )


def collect_info_feed_signals(fetched: datetime, limit: int = 18) -> list[CngoldSignal]:
    signals: list[CngoldSignal] = []
    for feed in INFO_FEEDS:
        feed_url = str(feed["url"])
        label = str(feed["label"])
        author = str(feed["author"])
        category = str(feed["category"])
        include_all = bool(feed.get("include_all"))
        before_count = len(signals)
        try:
            xml_text_raw = fetch_text(feed_url, timeout=12)
            root = ET.fromstring(xml_text_raw)
        except Exception as exc:
            LAST_SOURCE_STATUS.append(
                {
                    "平台": "公开资讯RSS",
                    "来源": label,
                    "状态": "访问受限",
                    "数量": 0,
                    "错误": str(exc),
                    "时间": fetched.isoformat(),
                }
            )
            continue
        for entry in feed_entries(root):
            title = entry.get("title", "").strip()
            if not title:
                continue
            link = entry.get("link", "").strip() or feed_url
            published = parse_feed_datetime(entry.get("published"), fetched)
            if fetched - published > INFO_MAX_AGE:
                continue
            combined = f"{title} {entry.get('summary', '')} {label} {link}"
            if not include_all and not relevant(combined):
                continue
            if not include_all and low_value_info_signal(combined):
                continue
            symbol = infer_symbol(combined)
            if not include_all and not is_us_stock_signal(combined, link, symbol):
                continue
            note = info_note(combined, category)
            key = signal_id(title, link)
            signals.append(
                CngoldSignal(
                    id=key,
                    symbol=symbol if symbol != "USSTOCK" else "USMARKET",
                    title=title,
                    url=link,
                    source_page=feed_url,
                    source_label=label,
                    author=author,
                    published_at=published.isoformat(),
                    fetched_at=fetched.isoformat(),
                    importance="important" if info_important(combined, symbol, note) else "normal",
                    note=note,
                )
            )
            if len(signals) >= limit:
                break
        LAST_SOURCE_STATUS.append(
            {
                "平台": "公开资讯RSS",
                "来源": label,
                "状态": "已读取" if len(signals) > before_count else "无近期匹配",
                "数量": len(signals) - before_count,
                "时间": fetched.isoformat(),
            }
        )
        if len(signals) >= limit:
            break
    return signals[:limit]


def youtube_relevant(text: str) -> bool:
    low = text.lower()
    return any(term_in_text(low, term) for term in YOUTUBE_RELEVANT_TERMS)


def infer_youtube_symbol(text: str) -> str:
    symbol = infer_symbol(text)
    if symbol != "USSTOCK":
        return symbol
    low = text.lower()
    if any(term_in_text(low, term) for term in ["stocks", "stock market", "markets", "wall street", "s&p 500", "nasdaq", "federal reserve", "fed", "powell"]):
        return "USMARKET"
    return symbol


def collect_youtube_signals(fetched: datetime, limit: int = 12) -> list[CngoldSignal]:
    signals: list[CngoldSignal] = []
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    for feed in YOUTUBE_FEEDS:
        feed_url = str(feed["url"])
        label = str(feed["label"])
        before_count = len(signals)
        try:
            xml_text = fetch_text(feed_url, timeout=12)
            root = ET.fromstring(xml_text)
        except Exception as exc:
            LAST_SOURCE_STATUS.append(
                {
                    "平台": "YouTube",
                    "来源": label,
                    "状态": "访问受限",
                    "数量": 0,
                    "错误": str(exc),
                    "时间": fetched.isoformat(),
                }
            )
            continue
        for entry in root.findall("atom:entry", ns):
            title = (entry.findtext("atom:title", default="", namespaces=ns) or "").strip()
            if not title:
                continue
            link = ""
            for link_el in entry.findall("atom:link", ns):
                href = link_el.attrib.get("href", "")
                if href:
                    link = href
                    break
            published = parse_atom_datetime(
                entry.findtext("atom:published", namespaces=ns) or entry.findtext("atom:updated", namespaces=ns),
                fetched,
            )
            if fetched - published > YOUTUBE_MAX_AGE:
                continue
            combined = f"{title} {link} {label}"
            if not youtube_relevant(combined):
                continue
            symbol = infer_youtube_symbol(combined)
            important = symbol not in {"USSTOCK"} or any(
                term_in_text(combined, term)
                for term in ["federal reserve", "fed", "powell", "cpi", "pce", "jobs", "tariff", "nasdaq", "ai", "chips", "semiconductor"]
            )
            signals.append(
                CngoldSignal(
                    id=signal_id(title, link or feed_url),
                    symbol=symbol,
                    title=title,
                    url=link,
                    source_page=feed_url,
                    source_label="YouTube",
                    author=label,
                    published_at=published.isoformat(),
                    fetched_at=fetched.isoformat(),
                    importance="important" if important else "normal",
                    note="YouTube财经频道RSS；视频标题只做线索，需回看原视频确认。",
                )
            )
            if len(signals) >= limit:
                break
        LAST_SOURCE_STATUS.append(
            {
                "平台": "YouTube",
                "来源": label,
                "状态": "已读取" if len(signals) > before_count else "无近期匹配",
                "数量": len(signals) - before_count,
                "时间": fetched.isoformat(),
            }
        )
        if len(signals) >= limit:
            break
    return signals[:limit]


def signal_id(title: str, url: str) -> str:
    return hashlib.sha1(f"{title}|{url}".encode("utf-8", errors="replace")).hexdigest()[:16]


def collect(limit: int = 30) -> list[CngoldSignal]:
    fetched = datetime.now(ZoneInfo("Asia/Shanghai"))
    signals: list[CngoldSignal] = []
    seen: set[str] = set()
    symbol_counts: dict[str, int] = {}
    LAST_SOURCE_STATUS.clear()
    manual_items = manual_baidu_signals(fetched, limit=limit)
    LAST_SOURCE_STATUS.append(
        {
            "平台": "百度股市通",
            "来源": str(BAIDU_MANUAL_PATH),
            "状态": "已导入" if manual_items else "等待截图/可见文字",
            "数量": len([item for item in manual_items if item.symbol != "SOURCE"]),
            "时间": fetched.isoformat(),
        }
    )
    for item in manual_items:
        key = signal_id(item.title, item.url or item.source_page)
        if key in seen:
            continue
        seen.add(key)
        signals.append(item)
        if len(signals) >= limit:
            return signals[:limit]
    info_items = collect_info_feed_signals(fetched, limit=min(22, max(8, limit // 2)))
    for item in info_items:
        key = signal_id(item.title, item.url or item.source_page)
        if key in seen:
            continue
        seen.add(key)
        signals.append(item)
        if len(signals) >= limit:
            return signals[:limit]
    youtube_items = collect_youtube_signals(fetched, limit=min(12, max(4, limit // 3)))
    for item in youtube_items:
        key = signal_id(item.title, item.url or item.source_page)
        if key in seen:
            continue
        seen.add(key)
        signals.append(item)
        if len(signals) >= limit:
            return signals[:limit]
    for group in SOURCE_GROUPS:
        source_label = str(group["label"])
        author = str(group["author"])
        for source_url in group["urls"]:
            before_count = len(signals)
            try:
                html = fetch_text(str(source_url))
            except Exception as exc:
                LAST_SOURCE_STATUS.append(
                    {
                        "平台": source_label,
                        "来源": str(source_url),
                        "状态": "访问受限",
                        "数量": 0,
                        "错误": str(exc),
                        "时间": fetched.isoformat(),
                    }
                )
                signals.append(
                    CngoldSignal(
                        id=signal_id(f"source-error:{source_url}", str(source_url)),
                        symbol="SOURCE",
                        title=f"{source_label}访问受限：{source_url}；{exc}",
                        url=str(source_url),
                        source_page=str(source_url),
                        source_label=source_label,
                        author=author,
                        published_at=fetched.isoformat(),
                        fetched_at=fetched.isoformat(),
                        importance="normal",
                        note="来源状态记录，不参与交易判断。",
                    )
                )
                continue
            parser = LinkParser()
            parser.feed(html)
            for title, href in parser.links:
                if not title or len(title) < 6:
                    continue
                url = urljoin(str(source_url), href)
                combined = f"{title} {url}"
                if not relevant(combined):
                    continue
                key = signal_id(title, url)
                if key in seen:
                    continue
                seen.add(key)
                published = published_from_url(url, fetched)
                if fetched - published > MAX_SIGNAL_AGE:
                    continue
                symbol = infer_symbol(combined)
                if not is_us_stock_signal(combined, url, symbol):
                    continue
                if looks_like_quote_entry(title, symbol):
                    continue
                max_per_symbol = 3 if symbol == "GOLD_BASKET" else 10
                if symbol_counts.get(symbol, 0) >= max_per_symbol:
                    continue
                important = symbol not in {"USSTOCK"}
                signals.append(
                    CngoldSignal(
                        id=key,
                        symbol=symbol,
                        title=title,
                        url=url,
                        source_page=str(source_url),
                        source_label=source_label,
                        author=author,
                        published_at=published.isoformat(),
                        fetched_at=fetched.isoformat(),
                        importance="important" if important else "normal",
                        note=f"{source_label}辅助信号；需结合美股量价、黄金/利率背景和原始公告确认。",
                    )
                )
                symbol_counts[symbol] = symbol_counts.get(symbol, 0) + 1
                if len(signals) >= limit:
                    return signals
            added = len(signals) - before_count
            LAST_SOURCE_STATUS.append(
                {
                    "平台": source_label,
                    "来源": str(source_url),
                    "状态": "已读取" if added else "无匹配/动态页",
                    "数量": added,
                    "时间": fetched.isoformat(),
                }
            )
    return signals[:limit]


def write_outputs(signals: list[CngoldSignal]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    SOCIAL_DIR.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(timezone.utc).isoformat()
    payload = {
        "source": "public_news_sources",
        "source_label": "公开财经新闻源",
        "generated_at_utc": generated_at,
        "count": len(signals),
        "source_status": LAST_SOURCE_STATUS,
        "signals": [asdict(item) for item in signals],
    }
    (OUT_DIR / "latest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    social_payload = {
        "社媒信号": [
            {
                "股票代码": item.symbol,
                "平台": item.source_label,
                "作者": item.author,
                "文字": item.title,
                "发布时间": item.published_at,
                "原帖链接": item.url,
                "重要级别": item.importance,
                "备注": item.note,
            }
            for item in signals
            if item.symbol not in {"SOURCE"}
        ]
    }
    (SOCIAL_DIR / "signals.json").write_text(json.dumps(social_payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect Cngold member/public signals for Beidou.")
    parser.add_argument("--limit", type=int, default=60)
    args = parser.parse_args(argv)
    signals = collect(limit=max(5, args.limit))
    write_outputs(signals)
    print(json.dumps({"count": len(signals), "out": str(OUT_DIR / "latest.json")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
