from __future__ import annotations

from pathlib import Path
from typing import Mapping

from description_html import render_description_template
from description_templates import infer_product_template, render_product_template
from pricing import PricingRecommendation
from listing_rules import (
    FIXED_CONDITION,
    FIXED_GRADING,
    FIXED_VINTAGE,
    HANDLING_TIME_DAYS,
    ITEM_LOCATION_CITY,
    ITEM_LOCATION_COUNTRY,
    COMBINED_SHIPPING_ENABLED,
    CONDITION_DISCLAIMER,
    REQUIRE_IMMEDIATE_PAYMENT,
    SHIPPING_FLAT_RATE,
    SHIPPING_SERVICE,
    SHIPPING_TRANSIT_TIME,
    STORE_CATEGORIES,
    UNPAID_PAYMENT_WINDOW_DAYS,
)


# Store navigation uses the short category labels chosen for Sugimori Gem
# Archive. The eBay marketplace category is selected separately through the
# Taxonomy API and is not hard-coded here.
CATEGORY = "Non-TCG"
VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".avi", ".webm"}
def _text(value: object) -> str:
    return str(value or "").strip()


def enforce_condition_disclaimer(description: str) -> str:
    clean = description.strip()
    if CONDITION_DISCLAIMER.lower() in clean.lower():
        return clean
    return f"{clean}\n\n{CONDITION_DISCLAIMER}" if clean else CONDITION_DISCLAIMER


def build_listing_draft(
    card: Mapping[str, object],
    recommendation: PricingRecommendation,
    image_paths: list[str],
) -> dict[str, object]:
    language = _text(card.get("language"))
    card_name = _text(card.get("card_name"))
    set_name = _text(card.get("set_name"))
    card_number = _text(card.get("card_number"))
    product_type = _text(card.get("product_type")) or infer_product_template(
        " ".join((card_name, set_name, card_number))
    ) or ""
    title_parts = [part for part in (language.title(), card_name, set_name, card_number) if part]
    title = " | ".join(title_parts)
    product_text = render_product_template(
        product_type,
        card_name=card_name,
        set_name=set_name,
        card_number=card_number,
    ) if product_type else f"{card_name} from {set_name}."
    description = enforce_condition_disclaimer("\n\n".join(
        [product_text]
        + [
        part
        for part in (
            f"Language: {language}.",
            f"Condition: {FIXED_CONDITION}.",
            f"Grading: {FIXED_GRADING}.",
            f"Archive code: {_text(card.get('archive_code'))}.",
        )
        if part
        ]
    ))
    folder_path = _text(card.get("folder_path"))
    original_folder = Path(folder_path) / "original" if folder_path else None
    video_paths = []
    if original_folder is not None and original_folder.is_dir():
        video_paths = [
            str(path)
            for path in sorted(original_folder.iterdir())
            if path.is_file() and path.suffix.lower() in VIDEO_SUFFIXES
        ]
    store_category = _text(card.get("store_category")) or CATEGORY
    return {
        "status": "draft",
        "title": title,
        "category": CATEGORY,
        "storeCategory": store_category,
        "productType": product_type,
        "vintage": FIXED_VINTAGE,
        "description": description,
        "descriptionHtml": render_description_template(
            archive_code=_text(card.get("archive_code")),
            title=title,
            body=description,
            card_name=card_name,
            store_category=store_category,
        ),
        "itemSpecifics": {
            "language": language,
            "cardName": card_name,
            "set": set_name,
            "cardNumber": card_number,
            "edition": _text(card.get("edition")),
            "printing": _text(card.get("printing")),
            "finish": _text(card.get("finish")),
            "condition": FIXED_CONDITION,
            "gradeCompany": "none",
            "grade": FIXED_GRADING,
            "vintage": "Yes",
        },
        "suggestedPrice": {
            "low": str(recommendation.suggested_item_low),
            "high": str(recommendation.suggested_item_high),
            "buyerTotalLow": str(recommendation.suggested_total_low),
            "buyerTotalHigh": str(recommendation.suggested_total_high),
        },
        "listingPrice": str(recommendation.suggested_item_high),
        "priceConfirmed": False,
        "shipping": {
            "service": SHIPPING_SERVICE,
            "transitTime": SHIPPING_TRANSIT_TIME,
            "firstItemCharge": str(SHIPPING_FLAT_RATE),
            "additionalItemsCharge": "0.00",
            "domestic": True,
            "international": True,
            "handlingTimeBusinessDays": HANDLING_TIME_DAYS,
            "combinedShipping": COMBINED_SHIPPING_ENABLED,
        },
        "itemLocation": {"countryOrRegion": ITEM_LOCATION_COUNTRY, "city": ITEM_LOCATION_CITY},
        "payment": {
            "requireImmediatePayment": REQUIRE_IMMEDIATE_PAYMENT,
            "unpaidOrderWindowDays": UNPAID_PAYMENT_WINDOW_DAYS,
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
        "researchStatus": "current",
        "archiveCode": _text(card.get("archive_code")),
        "internalId": _text(card.get("internal_id")),
        "imagePaths": image_paths,
        "videoPaths": video_paths,
        "publishing": {"published": False, "sellerCredentialsUsed": False},
    }
