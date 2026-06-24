# Dodex Trading Roadmap

## Phase 1: 工程骨架

- 项目结构
- 类型定义
- mock market data
- paper broker
- risk manager
- audit log
- sample strategy

## Phase 2: 回测系统

- backtest engine：已接入 mock 行情与样例策略，逐根 K 线回放。
- fee/slippage：已预留 `fee_rate` 和 `slippage_bps` 参数。
- metrics：已输出 initial cash、final equity、total return、max drawdown、win rate、profit factor、trade count。
- report output：CLI 先输出 JSON；后续可落地 HTML/Markdown 报告。

## Phase 3: Codex 集成

- AGENTS.md generator
- Skill generator
- MCP config generator
- Codex trading skill

## Phase 4: 模拟盘

- paper trading loop
- portfolio tracking
- order lifecycle
- trade journal

## Phase 5: 实盘准备

- exchange adapter interface
- credentials loading policy
- live broker implementation
- emergency stop
- readonly/account check mode

## Phase 6: 实盘交易

- 小资金模式
- 仓位限制
- 每日亏损限制
- 人工确认模式
- 全量 audit
