# 北斗全时段异动雷达 / premarket_mover_radar

本模块用于每天美股盘前、盘中、盘后自动筛选“今天可能短线发酵、有异动、可能值得手动判断是否小仓参与”的股票。

当前覆盖的美股时段：

- 盘前：美东 04:00-09:30。
- 盘中：美东 09:30-16:00。
- 盘后：美东 16:00-20:00。
- 非交易时段：继续记录新闻、SEC 和催化线索，但不把它当成实时量价确认。

它不是自动交易系统，不自动下单，不承诺盈利。任何输出都只是人工判断前的线索。

## 扫描范围

默认扫描范围不是只看你的持仓：

- Nasdaq 100 成分股。
- 你确认过的跟踪标的。
- 已卖出但仍观察。
- 观察池/待确认。
- 全市场异动候选，包括 Polygon/Massive API、Yahoo screener、TradingView scanner 等能自动返回的 movers。

你的持仓和观察池只用于优先标记和加分，不是扫描边界。

## 文件结构

- `AGENTS.md`：项目执行原则和安全边界。
- `config/watchlist.yaml`：扫描时间、股票池、重点主题、通知开关。
- `config/data_sources.yaml`：价格、新闻、SEC、特殊事件数据源登记。
- `scripts/premarket_mover_scan.py`：主扫描脚本，生成全时段异动报告。
- `scripts/news_catalyst_scan.py`：新闻和 SEC 催化扫描脚本。
- `scripts/send_alert.py`：桌面、邮件、Telegram、PushPlus、Server酱通知脚本。
- `scripts/nasdaq100_universe.py`：自动抓取并缓存 Nasdaq 100 成分股。
- `scripts/radar_dashboard.py`：本地自动刷新看板和 API 服务。
- `reports/premarket/`：每次扫描生成的 Markdown 报告。
- `reports/premarket/important/`：重要消息置顶状态、JSONL 历史和当天 Markdown 回看记录。
- `logs/`：运行日志。

## 北斗软件接入方式

推荐直接读取中文 JSON：

```text
C:\premarket_mover_radar\reports\premarket\latest_zh.json
```

字段都是中文，例如：`候选股票`、`五站交叉验证`、`信息处理标签`、`短线发酵分数`。

重要消息会额外写入：

```text
C:\premarket_mover_radar\reports\premarket\important\important_records.json
C:\premarket_mover_radar\reports\premarket\important\important_records.jsonl
C:\premarket_mover_radar\reports\premarket\important\YYYY-MM-DD_important.md
```

规则：重要消息约置顶 15 分钟，可以超过 3 条；普通候选仍然随最新扫描实时更新。如果你没看到实时看板，可以打开当天 `_important.md` 回看。

也可以启动本地看板/API：

```powershell
& "C:\Users\Dell\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" C:\premarket_mover_radar\scripts\radar_dashboard.py --scan-now
```

然后北斗软件读取后端接口：

```text
http://127.0.0.1:8766/api/latest
http://127.0.0.1:8766/api/important
```

浏览器前端看板入口：

```text
http://127.0.0.1:8786/dashboard
```

## 手动运行一次扫描

Codex runtime Python：

```powershell
& "C:\Users\Dell\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" C:\premarket_mover_radar\scripts\premarket_mover_scan.py --notify
```

如果你本机以后装好了 Python，也可以：

```powershell
python C:\premarket_mover_radar\scripts\premarket_mover_scan.py --notify
```

只扫新闻和 SEC 催化：

```powershell
& "C:\Users\Dell\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" C:\premarket_mover_radar\scripts\news_catalyst_scan.py
```

刷新 Nasdaq 100 成分股缓存：

```powershell
& "C:\Users\Dell\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" C:\premarket_mover_radar\scripts\nasdaq100_universe.py --refresh
```

## Windows 11 计划任务

用管理员 PowerShell 执行以下命令，按北京时间创建 4 个每日任务：

```powershell
$py = "C:\Users\Dell\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$script = "C:\premarket_mover_radar\scripts\premarket_mover_scan.py"
$times = @("15:30","16:05","20:30","21:20")
foreach ($t in $times) {
  $safeTime = $t -replace ":", ""
  $name = "Beidou Premarket Radar $safeTime"
  $action = New-ScheduledTaskAction -Execute $py -Argument "$script --notify"
  $trigger = New-ScheduledTaskTrigger -Daily -At $t
  Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Description "北斗盘前异动雷达 $t" -Force
}
```

## 修改股票池

编辑：

```text
C:\premarket_mover_radar\config\watchlist.yaml
```

把股票加到对应层级：

- `current_actual_holdings`：旧字段名；新网站前台不展示实仓明细，只作为后台兼容字段。
- `sold_but_still_watching`：已卖出但仍观察。
- `watch_pool_pending_confirmation`：观察池/待确认。

`QCOM` 已设置为低优先级，只记录重大变化，不主动反复提醒。

## 添加 API Key 和手机提醒

推荐把密钥写入本机文件：

```text
C:\premarket_mover_radar\config\secrets.env
```

模板文件：

```text
C:\premarket_mover_radar\config\secrets.env.example
```

脚本启动时会自动读取 `config/secrets.env`。Telegram、PushPlus、Server酱、邮件只要密钥完整，就会自动尝试发送，不需要再改系统环境变量。

行情 API 可填写：

```text
FINNHUB_API_KEY=
POLYGON_API_KEY=
MASSIVE_API_KEY=
ALPACA_KEY_ID=
ALPACA_SECRET_KEY=
QUIVER_API_KEY=
```

手机通知可填写：

```text
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
PUSHPLUS_TOKEN=
SERVERCHAN_SENDKEY=
```

邮件通知可填写：

```text
PREMARKET_EMAIL_TO=295765031@qq.com
PREMARKET_EMAIL_FROM=295765031@qq.com
PREMARKET_SMTP_HOST=smtp.qq.com
PREMARKET_SMTP_PORT=465
PREMARKET_SMTP_USER=295765031@qq.com
PREMARKET_SMTP_PASSWORD=
```

## 添加邮箱提醒

QQ 邮箱通常需要开启 SMTP，并使用授权码，不是 QQ 登录密码。

设置环境变量示例：

```powershell
setx PREMARKET_SMTP_HOST "smtp.qq.com"
setx PREMARKET_SMTP_PORT "465"
setx PREMARKET_SMTP_USER "295765031@qq.com"
setx PREMARKET_SMTP_PASSWORD "你的QQ邮箱SMTP授权码"
setx PREMARKET_EMAIL_FROM "295765031@qq.com"
setx PREMARKET_EMAIL_TO "295765031@qq.com"
```

也可以继续使用 `setx`。如果写入 `config/secrets.env`，无需再把 `config/watchlist.yaml` 里的 `email_enabled` 改成 `true`。

## 添加 Telegram 提醒

```powershell
setx TELEGRAM_BOT_TOKEN "你的BotToken"
setx TELEGRAM_CHAT_ID "你的ChatId"
```

也可以继续使用 `setx`。如果写入 `config/secrets.env`，无需再把 `config/watchlist.yaml` 里的 `telegram_enabled` 改成 `true`。

## 添加 PushPlus / Server酱

PushPlus：

```powershell
setx PUSHPLUS_TOKEN "你的PushPlusToken"
```

Server酱：

```powershell
setx SERVERCHAN_SENDKEY "你的SendKey"
```

也可以继续使用 `setx`。如果写入 `config/secrets.env`，无需再在 `config/watchlist.yaml` 打开对应开关。

## 数据源说明

当前脚本默认使用无需额外依赖的自动化源：

- Yahoo Finance quote API：watchlist 盘前行情。
- Yahoo Finance RSS：个股新闻标题。
- SEC data API：8-K、S-3、424B、Form 4、10-Q、10-K 等最新披露。

如设置 API key，脚本会尝试使用：

- `FINNHUB_API_KEY`
- `POLYGON_API_KEY` 或 `MASSIVE_API_KEY`
- `ALPACA_KEY_ID` / `ALPACA_SECRET_KEY`

MarketWatch、Nasdaq、TradingView 记录为备用来源；网页可能动态渲染或需要登录，自动抓取失败时不编造结果。

## 当前通知环境

当前脚本支持桌面通知、邮件、Telegram、PushPlus、Server酱。若本机未安装 BurntToast 且 `msg.exe` 不可用，桌面通知会自动失败并保留报告文件。

如需增强 Windows 桌面通知，建议在 PowerShell 中安装 BurntToast：

```powershell
Install-Module BurntToast -Scope CurrentUser
```

## 分数解释

- 80 分以上：强提醒，但仍需人工判断，不自动买入。
- 65-79 分：值得观察，开盘等 30-60 分钟确认。
- 50-64 分：只看，除非后续继续放量。
- 50 分以下：过滤。
