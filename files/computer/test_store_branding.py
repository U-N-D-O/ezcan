from pathlib import Path

from description_html import fill_store_branding, render_description_template
from store_branding import branding_asset_paths, render_description_branding, render_store_front_assets, store_links


def test_store_links_use_normalized_https_urls() -> None:
    links = store_links()

    assert links["store"] == "https://www.ebay.com/str/SugimoriGemArchive"
    assert links["about"] == "https://www.ebay.com/str/SugimoriGemArchive?_tab=about"
    assert links["TCG"] == "https://www.ebay.com/str/SugimoriGemArchive/TCG/"
    assert links["Non-TCG"] == "https://www.ebay.com/str/SugimoriGemArchive/Non-TCG/"


def test_supplied_branding_asset_manifest_contains_both_sets() -> None:
    asset_root = Path(__file__).resolve().parents[3] / "Store" / "Sugimori Gem Archive" / "Store front"
    paths = branding_asset_paths(asset_root)

    assert all(paths[f"description_{category}"].is_file() for category in ("TCG", "Non-TCG", "PSA", "Bulk"))
    assert all(paths[f"storefront_{category}"].is_file() for category in ("TCG", "Non-TCG", "PSA", "Bulk"))
    assert paths["logo"].is_file()
    assert paths["checkout"].is_file()
    assert paths["thank_you_background"].is_file()


def test_square_branding_is_linked_from_listing_descriptions_and_wide_set_is_store_front_copy() -> None:
    urls = {
        "description_TCG": "https://i.ebayimg.com/description-tcg.jpg",
        "description_Non-TCG": "https://i.ebayimg.com/description-other.jpg",
        "description_PSA": "https://i.ebayimg.com/description-psa.jpg",
        "description_Bulk": "https://i.ebayimg.com/description-bulk.jpg",
        "storefront_TCG": "https://i.ebayimg.com/storefront-tcg.jpg",
        "storefront_Non-TCG": "https://i.ebayimg.com/storefront-other.jpg",
        "storefront_PSA": "https://i.ebayimg.com/storefront-psa.jpg",
        "storefront_Bulk": "https://i.ebayimg.com/storefront-bulk.jpg",
        "checkout": "https://i.ebayimg.com/checkout.jpg",
        "thank_you_background": "https://i.ebayimg.com/thank-you.jpg",
    }
    description = render_description_template(archive_code="SGA-A0C4", title="Pikachu", body="Description")
    filled = fill_store_branding(description, urls)
    store_front = render_store_front_assets(urls)

    assert "description-tcg.jpg" in filled
    assert "https://www.ebay.com/str/SugimoriGemArchive/TCG/" in filled
    assert "ABOUT THE STORE" in filled
    assert "This is a new store" in filled
    assert "storefront-tcg.jpg" in store_front
    assert "storefront-other.jpg" in store_front
    assert "target=\"_blank\"" in filled
    assert "javascript:" not in filled.lower()
