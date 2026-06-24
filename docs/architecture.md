# Dodex Architecture

Dodex 是一个面向 Codex 的 AI 交易系统开发与执行平台。第一阶段只搭工程骨架、安全边界和本地可运行的 paper trading 流程，不接真钱、不接真实交易所、不读取真实密钥。

## 1. Project Intelligence Layer

- 扫描 repo 结构、语言、测试与配置文件。
- 识别项目技术栈并沿用既有实现方式。
- 生成 Codex 项目规则、开发提示和模块状态。
- 推荐 Skills、MCP、Subagents 的后续接入点。

## 2. Market Data Layer

- 统一行情数据接口。
- Phase 1 仅提供 `MockMarketDataProvider`，不联网。
- 后续可扩展 Binance、OKX、Bybit、美股、加密货币数据源。

## 3. Strategy Layer

- 统一策略接口和输入输出类型。
- 提供 `SampleMovingAverageStrategy` 作为最小策略示例。
- 后续支持 AI 生成、修复和优化策略。

## 4. Backtest Layer

- 历史数据回测入口。
- 当前实现使用 mock 行情逐根 K 线回放样例策略。
- 支持手续费、滑点参数和基础指标：总收益、最大回撤、胜率、profit factor、交易次数。
- 回测订单仍走 `RiskManager`，并写入 `AuditLog`，避免和真实交易路径形成两套安全口径。

## 5. Broker Layer

- `PaperBroker` 负责模拟下单。
- `LiveBroker` 只保留适配器接口与 stub。
- Phase 1 明确禁止真实下单。

## 6. Risk Layer

- 单笔最大风险。
- 每日最大亏损。
- 最大仓位。
- 最大杠杆。
- 黑名单交易品种。
- kill switch。
- 实盘交易必须显式开启。

## 7. Audit Layer

- 所有交易决策写入日志。
- 所有订单请求写入日志。
- 所有风控拒绝写入日志。
- 所有配置变化写入日志。
- 如果审计日志失败，交易流程必须中止。

## 8. Codex Integration Layer

- 维护 `AGENTS.md`。
- 维护 Skills 生成器。
- 维护 MCP 配置生成器。
- 后续支持 Codex 直接调用 Dodex 工具。

## 当前实现边界

- Dodex 作为独立 Python 子系统落在仓库内，不改现有北斗雷达主流程。
- 当前 CLI 提供 `doctor`、`backtest`、`trade:paper`、`trade:live` 四个入口。
- `trade:live` 在当前阶段必须固定拒绝执行。
