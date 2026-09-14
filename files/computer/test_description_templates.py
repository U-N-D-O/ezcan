from description_templates import (
    PRODUCT_TEMPLATES,
    infer_product_template,
    product_template_choices,
    render_product_template,
)


def test_all_requested_product_templates_exist() -> None:
    assert [template.label for template in PRODUCT_TEMPLATES] == [
        "Japanese TCG old back",
        "Japanese TCG new back",
        "Topsun",
        "Bandai Carddass 1996",
        "Bandai Carddass 1997",
        "Amada stickers 1996",
        "Amada stickers 1997",
    ]
    assert product_template_choices() == tuple(template.label for template in PRODUCT_TEMPLATES)


def test_carddass_1997_template_uses_the_seller_provenance_text() -> None:
    text = render_product_template(
        "bandai_carddass_1997",
        card_name="Pikachu",
        set_name="Part 3",
        card_number="15",
    )

    assert "Bandai Pokémon Carddass card from 1997" in text
    assert "Carddass Part 3 and Part 4" in text
    assert "Ken Sugimori artwork" in text
    assert "manga-style" in text
    assert "official Pokémon 25 Years art book" in text
    assert "Pikachu" in text
    assert "15" in text


def test_template_values_are_plain_text_and_have_safe_defaults() -> None:
    text = render_product_template("topsun", card_name="<Pikachu>")

    assert "<Pikachu>" in text
    assert "<p>" not in text
    assert "Early Pokémon era" in text
    assert "Ken Sugimori" in text


def test_listing_names_infer_internal_product_lines_not_ebay_categories() -> None:
    assert infer_product_template("1997 Bandai Carddass Part 3 Pikachu") == "bandai_carddass_1997"
    assert infer_product_template("Amada Pokémon Sticker 1996") == "amada_stickers_1996"
    assert infer_product_template("Japanese TCG New Back 1997") == "japanese_tcg_new_back"
    assert infer_product_template("Japanese TCG Old Back") == "japanese_tcg_old_back"
    assert infer_product_template("Japanese Pokemon card") is None
