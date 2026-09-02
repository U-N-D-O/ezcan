from __future__ import annotations

from typing import Mapping

from pricing import PricingRecommendation


CATEGORY = "Collectibles > Trading Cards > Pokemon TCG"


def _text(value: object) -> str:
    return str(value or "").strip()


def build_listing_draft(
    card: Mapping[str, object],
    recommendation: PricingRecommendation,
    image_paths: list[str],
) -> dict[str, object]:
    language = _text(card.get("language"))
    card_name = _text(card.get("card_name"))
    set_name = _text(card.get("set_name"))
    card_number = _text(card.get("card_number"))
    title_parts = [part for part in (language.title(), card_name, set_name, card_number) if part]
    title = " | ".join(title_parts)
    condition = _text(card.get("condition"))
    grade_company = _text(card.get("grade_company"))
    grade = _text(card.get("grade"))
    grade_text = f"{grade_company.upper()} {grade}".strip() if grade_company and grade_company != "none" else "Raw"
    description = "\n".join(
        part
        for part in (
            f"{card_name} from {set_name}.",
            f"Language: {language}.",
            f"Condition: {condition}.",
            f"Grade: {grade_text}.",
            "Please review the supplied photos for the card's exact condition and finish.",
            f"Archive code: {_text(card.get('archive_code'))}.",
        )
        if part
    )
    return {
        "status": "draft",
        "title": title,
        "category": CATEGORY,
        "description": description,
        "itemSpecifics": {
            "language": language,
            "cardName": card_name,
            "set": set_name,
            "cardNumber": card_number,
            "edition": _text(card.get("edition")),
            "printing": _text(card.get("printing")),
            "finish": _text(card.get("finish")),
            "condition": condition,
            "gradeCompany": grade_company,
            "grade": grade,
        },
        "suggestedPrice": {
            "low": str(recommendation.suggested_item_low),
            "high": str(recommendation.suggested_item_high),
            "buyerTotalLow": str(recommendation.suggested_total_low),
            "buyerTotalHigh": str(recommendation.suggested_total_high),
        },
        "shipping": {
            "firstItemCharge": str(recommendation.owner_shipping_charge),
            "additionalItemsCharge": "0.00",
        },
        "research": {
            "soldComparables": recommendation.sold_count,
            "activeComparables": recommendation.active_count,
            "medianSoldBuyerTotal": str(recommendation.median_sold_total),
            "estimatedFeeLow": str(recommendation.estimated_fee_low),
            "estimatedFeeHigh": str(recommendation.estimated_fee_high),
            "estimatedProfitBeforeCostsLow": str(recommendation.estimated_profit_before_costs_low),
            "estimatedProfitBeforeCostsHigh": str(recommendation.estimated_profit_before_costs_high),
        },
        "archiveCode": _text(card.get("archive_code")),
        "internalId": _text(card.get("internal_id")),
        "imagePaths": image_paths,
        "publishing": {"published": False, "sellerCredentialsUsed": False},
    }
