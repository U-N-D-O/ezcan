"""Plain-text product copy for Sugimori Gem Archive descriptions.

These are intentionally plain text.  The HTML renderer is responsible for
escaping and laying out the selected text safely for eBay.  The seller can
later expand each template without changing the listing workflow.
"""

from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class ProductTemplate:
    key: str
    label: str
    text: str


PRODUCT_TEMPLATES: tuple[ProductTemplate, ...] = (
    ProductTemplate(
        "japanese_tcg_old_back",
        "Japanese TCG old back",
        """This is a vintage Japanese Pokémon Trading Card Game card with the original classic Pokémon card back.

Card name: {card_name}
Product line: Japanese Pokémon TCG
Year: {year}
Artist: {artist}
Set or release: {set_name}
Card number: {card_number}

This early-era Japanese release is presented as part of the Sugimori Gem Archive collection of vintage Pokémon cards and related artwork.""",
    ),
    ProductTemplate(
        "japanese_tcg_new_back",
        "Japanese TCG new back",
        """This is a vintage Japanese Pokémon Trading Card Game card with the later Japanese Pokémon card back.

Card name: {card_name}
Product line: Japanese Pokémon TCG
Year: {year}
Artist: {artist}
Set or release: {set_name}
Card number: {card_number}

This Japanese release is presented as part of the Sugimori Gem Archive collection of vintage Pokémon cards and related artwork.""",
    ),
    ProductTemplate(
        "topsun",
        "Topsun",
        """This is a vintage Japanese Pokémon Topsun card from the early Pokémon era.

Card name: {card_name}
Product line: Topsun
Year: {year}
Artist: {artist}
Release or variation: {set_name}
Card number or identifier: {card_number}

Topsun cards are early Japanese Pokémon collectibles and are presented here as part of the Sugimori Gem Archive collection.""",
    ),
    ProductTemplate(
        "bandai_carddass_1996",
        "Bandai Carddass 1996",
        """This is a vintage Japanese Bandai Pokémon Carddass card from 1996.

Card name: {card_name}
Product line: Bandai Carddass
Year: 1996
Artist: {artist}
Series or part: {set_name}
Card number or identifier: {card_number}

This early Carddass release is presented as part of the Sugimori Gem Archive collection of vintage Japanese Pokémon material.""",
    ),
    ProductTemplate(
        "bandai_carddass_1997",
        "Bandai Carddass 1997",
        """This is a vintage Japanese Bandai Pokémon Carddass card from 1997, from the Carddass Part 3 or Part 4 era.

Card name: {card_name}
Product line: Bandai Carddass
Year: 1997
Artist: Ken Sugimori
Series or part: {set_name}
Card number or identifier: {card_number}

The artwork in this 1997 Carddass Part 3 and Part 4 release is Ken Sugimori artwork in the manga-style visual approach requested for these series. This artwork is also represented in the official Pokémon 25 Years art book. It is included in the Sugimori Gem Archive as an early example of Sugimori's range beyond the familiar standard game-card presentation.""",
    ),
    ProductTemplate(
        "amada_stickers_1996",
        "Amada stickers 1996",
        """This is a vintage Japanese Amada Pokémon sticker from 1996.

Character: {card_name}
Product line: Amada Pokémon stickers
Year: 1996
Artist: {artist}
Series or release: {set_name}
Sticker number or identifier: {card_number}

This early Japanese sticker release is presented as part of the Sugimori Gem Archive collection of vintage Pokémon ephemera and artwork.""",
    ),
    ProductTemplate(
        "amada_stickers_1997",
        "Amada stickers 1997",
        """This is a vintage Japanese Amada Pokémon sticker from 1997.

Character: {card_name}
Product line: Amada Pokémon stickers
Year: 1997
Artist: {artist}
Series or release: {set_name}
Sticker number or identifier: {card_number}

This early Japanese sticker release is presented as part of the Sugimori Gem Archive collection of vintage Pokémon ephemera and artwork.""",
    ),
)


PRODUCT_TEMPLATE_BY_KEY = {template.key: template for template in PRODUCT_TEMPLATES}
DEFAULT_PRODUCT_TEMPLATE = "japanese_tcg_old_back"


def infer_product_template(listing_name: str | None) -> str | None:
    """Identify an internal product line from an eBay/listing name.

    These labels never become eBay marketplace categories.  They only choose
    the seller's description copy and internal archive presentation.
    """
    name = re.sub(r"[^a-z0-9]+", " ", str(listing_name or "").lower()).strip()
    if "topsun" in name:
        return "topsun"
    if "amada" in name and "sticker" in name:
        if re.search(r"(?:19)?96", name):
            return "amada_stickers_1996"
        if re.search(r"(?:19)?97", name):
            return "amada_stickers_1997"
    if "carddass" in name or "card dass" in name:
        if re.search(r"(?:19)?96", name):
            return "bandai_carddass_1996"
        if re.search(r"(?:19)?97", name):
            return "bandai_carddass_1997"
    if "new back" in name or "newback" in name:
        return "japanese_tcg_new_back"
    if "old back" in name or "oldback" in name:
        return "japanese_tcg_old_back"
    return None


def product_template_choices() -> tuple[str, ...]:
    """Return the short labels shown in the computer UI."""
    return tuple(template.label for template in PRODUCT_TEMPLATES)


def product_template_key(label_or_key: str | None) -> str:
    value = str(label_or_key or "").strip()
    if value in PRODUCT_TEMPLATE_BY_KEY:
        return value
    for template in PRODUCT_TEMPLATES:
        if template.label == value:
            return template.key
    return DEFAULT_PRODUCT_TEMPLATE


def render_product_template(
    product_type: str | None,
    *,
    card_name: str = "",
    year: str = "",
    artist: str = "Ken Sugimori",
    set_name: str = "",
    card_number: str = "",
) -> str:
    """Fill one product template with listing metadata as plain text."""
    template = PRODUCT_TEMPLATE_BY_KEY[product_template_key(product_type)]
    values = {
        "card_name": card_name.strip(),
        "year": year.strip() or "Early Pokémon era",
        "artist": artist.strip() or "Ken Sugimori",
        "set_name": set_name.strip() or "To be documented",
        "card_number": card_number.strip() or "To be documented",
    }
    return template.text.format(**values).strip()
