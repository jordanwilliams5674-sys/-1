# 北斗盘前异动雷达数据源表

Last updated: 2026-06-03

所有数据源只用于信息收集、交叉验证和人工判断前的线索整理。系统不自动下单，不承诺盈利，不把单一来源升级为买卖建议。

| source_name | url | category | use_case | beidou_role | automation_level | requires_login | lag_risk | best_for | not_suitable_for | weight_in_scoring | notes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| TradingView | https://www.tradingview.com | 价格/异动/技术图表 | 自动查询盘前涨跌幅、盘前量、常规涨跌幅和成交量 | 量价确认 / 技术状态 | 已自动接入：TradingView scanner | false | 低，受行情权限影响 | 盘前量价确认 | 解释真正催化原因 | 高 | 不再标记为手动查看；字段为空则写自动源无盘前字段 |
| StockAnalysis | https://stockanalysis.com | 基本面/财务/估值 | 自动探测个股页和财务入口 | 基本面 / 财报 / 估值锚 | 已自动接入：公开页探测 | false | 中 | 快速核对基本面入口 | 单独判断短线方向 | 高 | 关键数据仍需 IR/SEC 核验 |
| WhaleWisdom | https://whalewisdom.com | 机构13F/基金持仓 | 自动探测机构持仓背景页 | 机构资金线索工具 | 已自动接入：公开页探测 | false | 高，13F滞后 | 背景加分 | 当天短线买入依据 | 中低 | 不能单独触发正式提醒 |
| Quiver Quant | https://www.quiverquant.com | 国会交易/政府合同/另类数据 | 自动探测公开页；结构化数据需 API Key | 政策资金流 / 政府合同雷达 | 部分自动接入：公开页探测；结构化需 QUIVER_API_KEY | true | 中高 | 政策、政府合同、国会线索 | 直接跟单 | 中 | 没有 API Key 不编造国会/合同结果 |
| ITC Markets Hawk/Dove Cheat Sheet | https://www.itcmarkets.com/cheat-sheet/ | 宏观/Fed/利率 | 自动探测宏观鹰鸽派页 | 宏观利率过滤器 | 已自动接入：公开页探测 | false | 中 | 宏观事件日风险偏好过滤 | 单独判断个股催化 | 中 | 需结合 Fed 原文、CME、DXY、美债 |
| Yahoo Finance chart/RSS | https://finance.yahoo.com | 行情/新闻 | 行情 fallback 和新闻 RSS | 备用价格源 / 新闻标题源 | 已自动接入 | false | 中 | 备用行情和新闻标题 | 单独确认重大事实 | 中 | quote API 401 时自动切 chart fallback |
| SEC EDGAR data API | https://data.sec.gov | SEC文件 | 自动查 8-K、S-3、424B、Form 4、10-Q、10-K | 官方披露验证源 | 已自动接入 | false | 低到中 | 重大披露核验 | 解释市场情绪 | 高 | 缓存 company_tickers.json |
| Finnhub quote API | https://finnhub.io/api/v1/quote | 行情API | 可选行情备用源 | 备用价格源 | 需 FINNHUB_API_KEY | true | 取决于套餐 | 稳定行情 fallback | 无 API Key 环境 | 中 | 设置环境变量后启用 |
| Polygon / Massive top market movers API | https://polygon.io/docs/rest/stocks/snapshots/top-market-movers | 全市场异动API | 可选全市场 movers | 全市场热门异动扫描 | 需 POLYGON_API_KEY 或 MASSIVE_API_KEY | true | 取决于套餐 | 全市场异动发现 | 无 API Key 环境 | 高 | 有 Key 后增强全市场扫描 |
| Alpaca market data API | https://alpaca.markets/data | 行情API | 可选美股行情源 | 备用行情源 | 需 ALPACA_KEY_ID / ALPACA_SECRET_KEY | true | 取决于套餐 | 稳定行情数据 | 交易下单接口 | 中 | 本项目禁止调用交易接口 |

## 当前五站自动化状态

- TradingView：已自动接入 scanner，可自动返回部分股票的盘前涨跌幅和盘前量。
- StockAnalysis：已自动接入公开页探测。
- WhaleWisdom：已自动接入公开页探测，13F 只做背景分。
- Quiver Quant：公开页可自动探测；结构化国会交易/政府合同数据需要 `QUIVER_API_KEY`。
- ITC Markets：已自动接入公开页探测，作为宏观过滤器。

