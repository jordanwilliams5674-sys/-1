# Dodex Safety Model

1. 默认只允许 mock 数据和 paper trading。
2. 默认禁止 live trading。
3. 默认禁止读取 `.env`、真实 API key、交易所密钥。
4. 默认禁止自动下真实订单。
5. live trading 必须同时满足：
   - 配置文件显式开启 `liveTrading: true`
   - 用户显式选择 live broker
   - 风控模块允许
   - audit log 正常工作
   - kill switch 未触发
6. 所有交易动作必须经过 `RiskManager`。
7. 所有订单请求必须写入 `AuditLog`。
8. 任何绕过 `RiskManager` 或 `AuditLog` 的交易实现都视为严重 bug。
9. 不承诺盈利，不生成投资建议，只实现工具和执行系统。
10. 后续接入真实交易所时，必须先有 paper trading 和 backtest 测试通过。

## Phase 1 Enforcement

- `MockMarketDataProvider` 不联网。
- `PaperBroker` 仅内存记录模拟订单。
- `RiskManager` 默认拒绝 live broker。
- `AuditLog` 写入失败时直接抛错，中断交易流程。

## Phase 2 Backtest Enforcement

- `backtest` 入口只使用 mock 行情和样例策略。
- 回测订单必须经过 `RiskManager`，broker mode 固定为 `paper`。
- 回测信号、风控结果和模拟成交必须写入 `AuditLog`。
- 回测输出是工程验证结果，不是投资建议，也不触发真实订单。
