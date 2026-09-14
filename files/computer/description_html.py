"""eBay-safe, responsive description HTML for Sugimori Gem Archive listings.

The renderer deliberately uses ordinary markup only.  It contains no script,
form, iframe, animation, or fixed-width object, so it can be sent through the
eBay listing APIs and rendered on both desktop and mobile.
"""

from __future__ import annotations

import html
import re
from collections.abc import Iterable

from listing_rules import (
    COMBINED_SHIPPING_ENABLED,
    CONDITION_DISCLAIMER,
    FIXED_CONDITION,
    FIXED_GRADING,
    HANDLING_TIME_DAYS,
    ITEM_LOCATION_CITY,
    ITEM_LOCATION_COUNTRY,
    REQUIRE_IMMEDIATE_PAYMENT,
    SHIPPING_FLAT_RATE,
    SHIPPING_SERVICE,
    SHIPPING_TRANSIT_TIME,
)
from store_branding import STORE_BRANDING_MARKER, render_description_branding, required_description_assets


IMAGE_GALLERY_MARKER = "<!-- SGA_IMAGE_GALLERY -->"


def _escape(value: object) -> str:
    return html.escape(str(value or "").strip(), quote=True)


def _paragraphs(value: str) -> str:
    """Turn seller-entered plain text into safe HTML paragraphs."""
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", value.strip()) if part.strip()]
    if not paragraphs:
        return ""
    return "".join(
        f'<p style="margin:0 0 12px;line-height:1.55;">{_escape(paragraph).replace(chr(10), "<br>")}</p>'
        for paragraph in paragraphs
    )


def _gallery(image_urls: Iterable[str]) -> str:
    cards: list[str] = []
    for raw_url in image_urls:
        url = str(raw_url or "").strip()
        if not url or not url.lower().startswith("https://"):
            continue
        safe_url = _escape(url)
        cards.append(
            '<td style="width:50%;padding:6px;vertical-align:top;">'
            f'<a href="{safe_url}" target="_blank">'
            f'<img src="{safe_url}" alt="Sugimori Gem Archive card photo" '
            'style="display:block;width:100%;height:auto;max-width:700px;border:0;">'
            "</a></td>"
        )
    if not cards:
        return ""
    rows = []
    for index in range(0, len(cards), 2):
        row = cards[index:index + 2]
        if len(row) == 1:
            row.append('<td style="width:50%;padding:6px;vertical-align:top;"></td>')
        rows.append(f'<tr>{"".join(row)}</tr>')
    return (
        '<table role="presentation" style="width:100%;max-width:700px;border-collapse:collapse;">'
        + "".join(rows)
        + "</table>"
    )


def render_listing_description(
    *,
    archive_code: str,
    title: str,
    body: str,
    card_name: str = "",
    store_category: str = "Non-TCG",
    image_urls: Iterable[str] = (),
) -> str:
    """Render a complete description, optionally filling the image gallery.

    ``body`` is treated as seller-entered plain text.  Category-specific HTML
    templates can later provide their own body renderer while retaining the
    same fixed facts and image-gallery marker.
    """
    gallery = _gallery(image_urls)
    if not gallery:
        gallery = (
            IMAGE_GALLERY_MARKER
            if IMAGE_GALLERY_MARKER in body
            else '<p style="margin:0;color:#5d6872;">Card photos are shown in the eBay photo gallery above.</p>'
        )
    safe_category = _escape(store_category or "Non-TCG")
    safe_card_name = _escape(card_name)
    safe_title = _escape(title)
    safe_archive = _escape(archive_code)
    condition_note = CONDITION_DISCLAIMER
    payment_note = (
        "Immediate payment is not required so buyers can purchase additional items and request combined shipping."
        if not REQUIRE_IMMEDIATE_PAYMENT
        else "Immediate payment is required for this Buy It Now listing."
    )
    combined_note = "Combined shipping is available for multiple purchases." if COMBINED_SHIPPING_ENABLED else ""
    body_without_marker = body.replace(IMAGE_GALLERY_MARKER, "").strip()
    body_html = _paragraphs(body_without_marker)
    if IMAGE_GALLERY_MARKER in body:
        body_html = gallery + body_html
    else:
        body_html = gallery + body_html
    return f'''<div style="width:100%;max-width:700px;margin:0 auto;font-family:Arial,Helvetica,sans-serif;color:#20252b;background:#ffffff;">
  <div style="border:1px solid #d7e1e7;border-radius:10px;overflow:hidden;">
    <div style="padding:18px 20px;background:#edf7f8;border-bottom:1px solid #d7e1e7;">
      <div style="font-size:12px;letter-spacing:1.5px;color:#147f8a;font-weight:bold;">SUGIMORI GEM ARCHIVE</div>
      <div style="margin-top:7px;font-size:20px;line-height:1.25;font-weight:bold;">{safe_title}</div>
      <div style="margin-top:8px;font-size:13px;color:#5d6872;">Archive ID: <strong>{safe_archive}</strong> &nbsp;|&nbsp; Category: {safe_category}</div>
    </div>
    <div style="padding:16px 20px;">
      {body_html}
      {STORE_BRANDING_MARKER}
    </div>
    <div style="margin:0 20px 16px;padding:14px;background:#fff7e6;border-left:4px solid #e1a12b;font-size:13px;line-height:1.5;">
      <strong>Condition notice</strong><br>{_escape(condition_note)}
    </div>
    <table role="presentation" style="width:100%;max-width:700px;border-collapse:collapse;border-top:1px solid #d7e1e7;font-size:13px;">
      <tr><td style="padding:8px 20px;color:#5d6872;">Condition</td><td style="padding:8px 20px;text-align:right;font-weight:bold;">{_escape(FIXED_CONDITION)}</td></tr>
      <tr><td style="padding:8px 20px;color:#5d6872;">Grading</td><td style="padding:8px 20px;text-align:right;font-weight:bold;">{_escape(FIXED_GRADING)}</td></tr>
      <tr><td style="padding:8px 20px;color:#5d6872;">Shipping</td><td style="padding:8px 20px;text-align:right;font-weight:bold;">{_escape(SHIPPING_SERVICE)} — ${SHIPPING_FLAT_RATE:.2f}</td></tr>
      <tr><td style="padding:8px 20px;color:#5d6872;">Delivery estimate</td><td style="padding:8px 20px;text-align:right;font-weight:bold;">{_escape(SHIPPING_TRANSIT_TIME)}</td></tr>
      <tr><td style="padding:8px 20px;color:#5d6872;">Handling</td><td style="padding:8px 20px;text-align:right;font-weight:bold;">{HANDLING_TIME_DAYS} business days</td></tr>
      <tr><td style="padding:8px 20px;color:#5d6872;">Item location</td><td style="padding:8px 20px;text-align:right;font-weight:bold;">{_escape(ITEM_LOCATION_CITY)}, {_escape(ITEM_LOCATION_COUNTRY)}</td></tr>
    </table>
    <div style="padding:14px 20px 18px;font-size:12px;color:#5d6872;line-height:1.5;">{_escape(payment_note)} { _escape(combined_note) }</div>
  </div>
</div>'''


def render_description_template(
    *,
    archive_code: str,
    title: str,
    body: str,
    card_name: str = "",
    store_category: str = "Non-TCG",
) -> str:
    """Create a draft-safe description with a gallery marker."""
    return render_listing_description(
        archive_code=archive_code,
        title=title,
        body=body + "\n\n" + IMAGE_GALLERY_MARKER,
        card_name=card_name,
        store_category=store_category,
    )


def fill_image_gallery(description_html: str, image_urls: Iterable[str]) -> str:
    """Replace the draft marker after eBay has hosted the card images."""
    gallery = _gallery(image_urls)
    if not gallery:
        gallery = '<p style="margin:0;color:#5d6872;">Card photos are shown in the eBay photo gallery above.</p>'
    return description_html.replace(IMAGE_GALLERY_MARKER, gallery)


def fill_store_branding(description_html: str, branding_urls: dict[str, str] | None = None) -> str:
    """Replace the store-navigation marker with hosted branding graphics."""
    urls = branding_urls or {}
    complete = all(str(urls.get(key, "")).lower().startswith("https://") for key in required_description_assets())
    branding = render_description_branding(urls) if complete else ""
    if not branding:
        branding = '<p style="margin-top:18px;color:#5d6872;">Visit the Sugimori Gem Archive store for more vintage Japanese Pokémon collectibles.</p>'
    return description_html.replace(STORE_BRANDING_MARKER, branding)
