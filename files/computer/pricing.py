from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Iterable, Mapping


CENT = Decimal("0.01")


@dataclass(frozen=True)
class PricingRecommendation:
    sold_count: int
    active_count: int
    lowest_sold_total: Decimal
    median_sold_total: Decimal
    highest_sold_total: Decimal
    suggested_total_low: Decimal
    suggested_total_high: Decimal
    owner_shipping_charge: Decimal
    suggested_item_low: Decimal
    suggested_item_high: Decimal
    estimated_fee_low: Decimal
    estimated_fee_high: Decimal
    estimated_profit_before_costs_low: Decimal
    estimated_profit_before_costs_high: Decimal


def _money(value: object) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ValueError("Comparable prices must be valid numbers") from error
    if not amount.is_finite() or amount < 0:
        raise ValueError("Comparable prices cannot be negative")
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def _rounded(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def recommend_price(
    candidates: Iterable[Mapping[str, object]],
    owner_first_item_shipping: object = "34.00",
    fee_rate: object = "0.1325",
) -> PricingRecommendation:
    sold_totals: list[Decimal] = []
    active_count = 0
    for candidate in candidates:
        status = str(candidate.get("market_status", "")).strip().lower()
        total = _money(candidate.get("total_buyer_cost", 0))
        if status == "sold":
            sold_totals.append(total)
        elif status == "active":
            active_count += 1
    if not sold_totals:
        raise ValueError("At least one sold comparable is required")

    sold_totals.sort()
    middle = len(sold_totals) // 2
    if len(sold_totals) % 2:
        median = sold_totals[middle]
    else:
        median = _rounded((sold_totals[middle - 1] + sold_totals[middle]) / 2)
    shipping = _money(owner_first_item_shipping)
    rate = Decimal(str(fee_rate))
    if not rate.is_finite() or rate < 0 or rate >= 1:
        raise ValueError("The fee rate must be between zero and one")

    suggested_low = _rounded(median * Decimal("0.90"))
    suggested_high = _rounded(median * Decimal("1.10"))
    item_low = max(Decimal("0.00"), _rounded(suggested_low - shipping))
    item_high = max(Decimal("0.00"), _rounded(suggested_high - shipping))
    fee_low = _rounded(suggested_low * rate)
    fee_high = _rounded(suggested_high * rate)

    return PricingRecommendation(
        sold_count=len(sold_totals),
        active_count=active_count,
        lowest_sold_total=sold_totals[0],
        median_sold_total=median,
        highest_sold_total=sold_totals[-1],
        suggested_total_low=suggested_low,
        suggested_total_high=suggested_high,
        owner_shipping_charge=shipping,
        suggested_item_low=item_low,
        suggested_item_high=item_high,
        estimated_fee_low=fee_low,
        estimated_fee_high=fee_high,
        estimated_profit_before_costs_low=_rounded(item_low - fee_low),
        estimated_profit_before_costs_high=_rounded(item_high - fee_high),
    )
