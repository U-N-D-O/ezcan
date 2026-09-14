"""Store-wide listing rules that must be identical for every item."""

from __future__ import annotations

from decimal import Decimal


STORE_CATEGORIES = ("TCG", "Non-TCG", "PSA", "Bulk")
SHIPPING_SERVICE = "Expedited International Shipping"
SHIPPING_TRANSIT_TIME = "7 - 15 business days"
SHIPPING_FLAT_RATE = Decimal("35.00")
HANDLING_TIME_DAYS = 2
ITEM_LOCATION_COUNTRY = "Greenland"
ITEM_LOCATION_CITY = "Nuuk"
FIXED_CONDITION = "Poor"
FIXED_GRADING = "Ungraded"
FIXED_VINTAGE = True
REQUIRE_IMMEDIATE_PAYMENT = False
UNPAID_PAYMENT_WINDOW_DAYS = 4
COMBINED_SHIPPING_ENABLED = True
CONDITION_DISCLAIMER = (
    "This card is sold as being in Poor condition. I am not a trained professional card appraiser. "
    "Please refer to the supplied photos and video for visible flaws and condition before purchasing."
)
