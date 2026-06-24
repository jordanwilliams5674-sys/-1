from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class LowBuyInputs:
    company_logic_intact: bool
    financials_or_orders_not_worse: bool
    valuation_margin_of_safety: bool
    chart_has_shore: bool
    no_one_way_outflow: bool


def passes_low_buy_filter(inputs: LowBuyInputs) -> bool:
    return all(
        [
            inputs.company_logic_intact,
            inputs.financials_or_orders_not_worse,
            inputs.valuation_margin_of_safety,
            inputs.chart_has_shore,
            inputs.no_one_way_outflow,
        ]
    )


def low_buy_reason(inputs: LowBuyInputs) -> str:
    failures = []
    if not inputs.company_logic_intact:
        failures.append("公司逻辑未确认")
    if not inputs.financials_or_orders_not_worse:
        failures.append("财报或订单可能恶化")
    if not inputs.valuation_margin_of_safety:
        failures.append("估值安全边际不足")
    if not inputs.chart_has_shore:
        failures.append("图形没有止跌/横盘/承接")
    if not inputs.no_one_way_outflow:
        failures.append("资金仍可能单边外流")
    return "通过低吸过滤" if not failures else "低吸未通过：" + "；".join(failures)
