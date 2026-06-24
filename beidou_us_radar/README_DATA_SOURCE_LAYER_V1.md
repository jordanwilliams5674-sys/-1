# 北斗美股全时段雷达 Data Source Layer V1

## 架构原则

本层只吸收“多源分层、主备互补、字段校验、降级备用、去重过滤”的架构思想，不接入 A 股主源。美股雷达按用途分为六层：

1. 行情层：TradingView/Yahoo/可选商业 API/akshare_us 辅助，用于价格、涨跌幅、成交量、盘前盘后状态。
2. 财报/公告层：SEC EDGAR 和公司 IR/Newsroom，用于 10-K、10-Q、8-K、S-1、S-3、424B、Form 4、earnings release、guidance、conference call。
3. 新闻层：Reuters、Bloomberg、WSJ、CNBC、FT、AP、MarketWatch，用于事件入口和发酵跟踪。
4. 宏观层：FRED、BLS、BEA、U.S. Treasury、Federal Reserve，用于 CPI、PCE、非农、收益率、美元流动性、真实利率。
5. 信号层：X/Reddit/YouTube/Stocktwits/Serenity 等，只作为“社媒早期线索/未确认”。
6. 估值层：akshare_us 估值接口或后续商业源，只作辅助；重大判断必须回到 SEC/IR。

所有事件统一进入 `core/event_schema.py`，必须带 `source`、`timestamp`、`credibility`、`staleness_flag`。

## 禁用的 A 股源

- `mootdx`：A 股通达信 TCP 源，只适合 A 股 K 线、盘口、F10。
- `同花顺热点`：A 股题材热度和强势股接口。
- `百度股市通 PAE`：主要用于 A 股概念、资金流和 K 线。
- `iwencai`：A 股自然语言选股且需要鉴权。
- `Ashare`：教学项目，停更风险高。
- `tushare`：不作为核心源；如后续需要，只能低优先级备选并做鉴权、字段和延迟检查。

## 接入的美股源

- `SEC EDGAR`：最高优先级官方源，验证财报、8-K、增发、ATM、S-3、424B、Form 4、13F 和风险披露。
- `Company IR / Newsroom`：最高优先级公司源，验证 earnings release、guidance、investor presentation、conference call、订单、合作、回购、分红。
- `Official Macro`：FRED、BLS、BEA、U.S. Treasury、Federal Reserve，用于宏观事件。
- `Exchange / Index Official`：Nasdaq、NYSE、CBOE、S&P Dow Jones Indices，用于上市状态、指数变更、波动率和市场结构。
- `akshare_us`：免费辅助行情/财务源，必须做字段、时间戳、缓存和限流检查，不能作为最终事实源。
- `Trusted News`：高可信新闻入口，必须判断是否已计价。
- `Social Radar`：早期线索，不能直接触发交易提醒。

## Mock Event 流程

1. SEC EDGAR 抓到 `MRVL 8-K`：
   - `providers/sec_edgar.py` 生成 `event_type=SEC filing`，`source_tier=official`，`credibility=1.0`。
2. 公司 IR 抓到同一事项 earnings release：
   - `providers/company_ir.py` 生成 `event_type=earnings/guidance`，并打 `new_guidance` 或 `new_official_file` 标签。
3. CNBC/Yahoo 新闻跟进：
   - `providers/news_rss.py` 只作为发酵入口，不能替代 SEC/IR。
4. 行情层出现放量/大跌：
   - `providers/market_data.py` 只提供价格和成交量确认，打 `new_price_confirmation` 或 `new_volume_confirmation`。
5. `core/event_dedupe.py` 生成签名并过滤 48 小时重复事件。
6. `core/alert_classifier.py` 先判定 `watchlist / excluded`：
   - 实仓内容已删除，原实仓标的已转入观察池。
   - 观察池：只进入研究提醒。
   - 排除：默认不提醒。
7. `core/beidou_formatter.py` 输出北斗手机短版，只使用北京时间和美东时间。

## 测试覆盖

使用标准库 `unittest`：

- `test_event_dedupe.py`：48 小时重复事件会被过滤；新官方文件/新指引可突破重复。
- `test_source_health.py`：字段缺失、时间戳过期会标记 stale。
- `test_holdings_watchlist_separation.py`：空实仓时按观察池处理；社媒-only 不触发交易提醒。
- `test_akshare_us_fields.py`：akshare 字段缺失或过期会标记 stale。
- `test_beidou_formatter.py`：提醒格式符合北京时间 + 美东时间，不出现东京时间。
