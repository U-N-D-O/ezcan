"""Sugimori Gem Archive store graphics, links, and description blocks."""

from __future__ import annotations

import html
import os
from pathlib import Path
from typing import Mapping
from urllib.parse import quote

from listing_rules import STORE_CATEGORIES


STORE_BRANDING_MARKER = "<!-- SGA_STORE_BRANDING -->"

STORE_DESCRIPTION = (
    "Welcome to Sugimori Gem Archive. This is a new store specializing specifically in vintage Japanese "
    "Pokémon artwork by Ken Sugimori, with a focus on early Pokémon releases from the 1996–1998 era. "
    "The collection includes official Japanese TCG cards, Topsun, Bandai Carddass, Amada stickers, "
    "PSA-graded items, and other early Pokémon collectibles. Every item is individually archived and "
    "photographed. Please review the photos and video carefully, and feel free to message me with any "
    "questions. I am very happy to help fellow collectors."
)

_STORE_FRONT = Path("Store") / "Sugimori Gem Archive" / "Store front"
_DESCRIPTION_NAMES = {
    "TCG": "categories/cat 1 TCG.png",
    "Non-TCG": "categories/cat 2 Other.png",
    "PSA": "categories/Cat 3 PSA.png",
    "Bulk": "categories/cat 4 Bulk.png",
}
_STOREFRONT_NAMES = {
    "TCG": "categories/1 TCG.png",
    "Non-TCG": "categories/2 Bandai Topsun Amada.png",
    "PSA": "categories/3 PSA.png",
    "Bulk": "categories/4 Bulk.png",
}


def _esc(value: object) -> str:
    return html.escape(str(value or "").strip(), quote=True)


def store_base_url() -> str:
    configured = os.getenv("EBAY_STORE_URL", "").strip().rstrip("/")
    return configured or "https://www.ebay.com/str/SugimoriGemArchive"


def store_links() -> dict[str, str]:
    base = store_base_url()
    return {
        "store": base,
        "about": f"{base}?_tab=about",
        **{category: f"{base}/{quote(category)}/" for category in STORE_CATEGORIES},
    }


def branding_asset_paths(root: Path | None = None) -> dict[str, Path]:
    """Find the supplied square, wide, CTA, and thank-you artwork."""
    if root is not None:
        asset_root = Path(root)
    elif os.getenv("EZCAN_BRANDING_DIR", "").strip():
        asset_root = Path(os.environ["EZCAN_BRANDING_DIR"].strip()).expanduser()
    else:
        # Source checkout: workspace/Store/Sugimori Gem Archive/Store front.
        asset_root = Path(__file__).resolve().parents[3] / _STORE_FRONT
        if not asset_root.is_dir():
            asset_root = Path.cwd() / _STORE_FRONT
    paths: dict[str, Path] = {}
    for category, name in _DESCRIPTION_NAMES.items():
        paths[f"description_{category}"] = asset_root / name
    for category, name in _STOREFRONT_NAMES.items():
        paths[f"storefront_{category}"] = asset_root / name
    paths["logo"] = asset_root / "Store logo.png"
    paths["checkout"] = asset_root / "Check out the store.png"
    paths["thank_you_background"] = asset_root / "Thank you letter background.jpg"
    return paths


def required_description_assets() -> tuple[str, ...]:
    return tuple([f"description_{category}" for category in STORE_CATEGORIES] + ["checkout", "thank_you_background"])


def render_store_front_assets(urls: Mapping[str, str]) -> str:
    """Create the wide four-panel store-front block for later store setup."""
    links = store_links()
    cells: list[str] = []
    for category in STORE_CATEGORIES:
        image_url = str(urls.get(f"storefront_{category}", "")).strip()
        if not image_url.lower().startswith("https://"):
            continue
        safe_image = _esc(image_url)
        cells.append(
            f'<td style="width:50%;padding:6px;vertical-align:top;">'
            f'<a href="{_esc(links[category])}" target="_blank">'
            f'<img src="{safe_image}" alt="Sugimori Gem Archive { _esc(category) }" '
            'style="display:block;width:100%;height:auto;max-width:700px;border:0;">'
            "</a></td>"
        )
    rows = []
    for index in range(0, len(cells), 2):
        row = cells[index:index + 2]
        if len(row) == 1:
            row.append('<td style="width:50%;padding:6px;"></td>')
        rows.append(f'<tr>{"".join(row)}</tr>')
    return '<table role="presentation" style="width:100%;max-width:700px;border-collapse:collapse;">' + "".join(rows) + "</table>"


def render_description_branding(urls: Mapping[str, str]) -> str:
    """Create the square category navigation and thank-you closing block."""
    links = store_links()
    cells: list[str] = []
    for category in STORE_CATEGORIES:
        image_url = str(urls.get(f"description_{category}", "")).strip()
        if not image_url.lower().startswith("https://"):
            continue
        safe_image = _esc(image_url)
        cells.append(
            f'<td style="width:50%;padding:6px;vertical-align:top;">'
            f'<a href="{_esc(links[category])}" target="_blank">'
            f'<img src="{safe_image}" alt="Browse { _esc(category) }" '
            'style="display:block;width:100%;height:auto;max-width:700px;border:0;">'
            "</a></td>"
        )
    rows = []
    for index in range(0, len(cells), 2):
        row = cells[index:index + 2]
        if len(row) == 1:
            row.append('<td style="width:50%;padding:6px;"></td>')
        rows.append(f'<tr>{"".join(row)}</tr>')
    category_grid = '<table role="presentation" style="width:100%;max-width:700px;border-collapse:collapse;">' + "".join(rows) + "</table>"
    checkout = str(urls.get("checkout", "")).strip()
    thank_you = str(urls.get("thank_you_background", "")).strip()
    checkout_block = ""
    if checkout.lower().startswith("https://"):
        checkout_block = (
            f'<a href="{_esc(links["store"])}" target="_blank">'
            f'<img src="{_esc(checkout)}" alt="Check out the Sugimori Gem Archive store" '
            'style="display:block;width:100%;height:auto;max-width:700px;border:0;">'
            "</a>"
        )
    background_style = (
        f'background-image:url("{_esc(thank_you)}");background-size:cover;background-position:center;'
        if thank_you.lower().startswith("https://")
        else "background:#f8f1e5;"
    )
    return f'''<div style="margin-top:18px;padding-top:14px;border-top:1px solid #d7e1e7;">
  <div style="font-size:13px;line-height:1.4;font-weight:bold;color:#147f8a;margin-bottom:6px;">BROWSE THE ARCHIVE</div>
  {category_grid}
  <div style="margin-top:12px;text-align:center;">{checkout_block}
    <a href="{_esc(links["about"])}" target="_blank" style="display:inline-block;margin-top:10px;padding:9px 16px;border:1px solid #147f8a;color:#147f8a;text-decoration:none;font-size:13px;font-weight:bold;">ABOUT THE STORE</a>
  </div>
  <div style="{background_style}margin-top:18px;padding:42px 24px;text-align:center;color:#24313b;">
    <div style="font-size:18px;font-weight:bold;">Thank you for visiting Sugimori Gem Archive</div>
    <div style="margin-top:9px;font-size:13px;line-height:1.55;">This is a new store, and I am very happy to help. If you have a question about an item, the archive, or Japanese Pokémon collectibles, please send me a message.</div>
  </div>
</div>'''
