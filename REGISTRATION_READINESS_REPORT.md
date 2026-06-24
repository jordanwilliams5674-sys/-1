# 北斗网站注册前准备报告

生成时间：2026-06-24 19:53:13 +08:00

## 结论

- 已生成注册前干净包；未上传、未注册、未打开券商或密钥页面。
- 包内排除了真实密钥、截图/媒体、日志、历史报告、缓存和 pycache。
- 网站源码已完成两个最小修正：默认券商名不再返回；首页观察池优先从 config/watchlist.yaml 读取。
- 真实持仓 CSV 不进入本网站注册包。

## 已排除

- config/secrets.env
- .env、	oken.json、credentials.json
- logs/
- __pycache__/、.pytest_cache/
- data/member_sources/window_captures/
- data/social_signals/media/
- eports/premarket/important/
- 除 latest.html、latest.json、latest_zh.json 外的历史报告
- 图片、截图、媒体文件

## 保留

- eidou_monitor_site/preview_dashboard.html
- eidou_monitor_site/preview_server.py
- scripts/radar_dashboard.py
- scripts/premarket_mover_scan.py
- config/watchlist.yaml
- config/secrets.env.example
- data/holdings_accounts/accounts.json
- eports/premarket/latest.html
- eports/premarket/latest.json
- eports/premarket/latest_zh.json
- eidou_us_radar/ 核心包与测试

## 验证

- adar_dashboard.py 与 preview_server.py 内存语法编译通过。
- 北斗核心单元测试：12 个通过。
- Dodex 非回测权限相关测试：5 个通过。
- Dodex 回测测试仍因 Windows 目录权限导致日志目录创建失败；不是实盘交易问题。
- uild_webdata() 不启动服务时可组装 eidou_monitor_site_v1 payload。
- payload 当前 watchlist_count=26，且 holdings 为空。

## 注册前提醒

- 注册/部署时不要上传 C:\premarket_mover_radar\config\secrets.env。
- 不要上传桌面截图、窗口截图、社媒图片缓存、日志、历史 reports。
- 如果部署平台需要环境变量，只填行情/通知所需 key，不填券商交易权限。
- 本系统是投研与风险提醒网站，不是自动交易系统。
