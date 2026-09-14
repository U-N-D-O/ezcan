from description_html import IMAGE_GALLERY_MARKER, fill_image_gallery, render_description_template


def test_description_template_contains_archive_id_and_fixed_store_facts() -> None:
    draft = render_description_template(
        archive_code="SGA-A0C4",
        title="Japanese Pikachu | Topsun | 1997 | Sugimori",
        body="Early Japanese card from the archive.",
        card_name="Pikachu",
        store_category="Non-TCG",
    )

    assert "SGA-A0C4" in draft
    assert "Early Japanese card from the archive." in draft
    assert "Poor" in draft
    assert "Ungraded" in draft
    assert "Expedited International Shipping" in draft
    assert "$35.00" in draft
    assert "Nuuk" in draft
    assert "Greenland" in draft
    assert "Immediate payment is not required" in draft
    assert IMAGE_GALLERY_MARKER in draft
    assert "<script" not in draft.lower()
    assert "javascript:" not in draft.lower()


def test_image_gallery_is_filled_only_with_https_images_and_opens_in_new_tab() -> None:
    draft = render_description_template(
        archive_code="SGA-A0C5",
        title="Pikachu",
        body="Description",
    )
    result = fill_image_gallery(
        draft,
        [
            "https://i.ebayimg.com/images/g/example/s-l1600.jpg",
            "http://insecure.example/front.jpg",
        ],
    )

    assert IMAGE_GALLERY_MARKER not in result
    assert "https://i.ebayimg.com/images/g/example/s-l1600.jpg" in result
    assert "target=\"_blank\"" in result
    assert "http://insecure.example" not in result
    assert "max-width:700px" in result
