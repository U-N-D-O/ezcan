from __future__ import annotations

import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".tif", ".tiff"}


def _shipping_overlay_font(text: str, max_width: int, maximum_size: int, minimum_size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    font_paths = (
        Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "segoeuib.ttf",
        Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "arialbd.ttf",
    )
    for font_path in font_paths:
        if not font_path.is_file():
            continue
        for size in range(maximum_size, minimum_size - 1, -1):
            font = ImageFont.truetype(str(font_path), size)
            if font.getbbox(text)[2] <= max_width:
                return font
    return ImageFont.load_default()


def add_shipping_overlay(source: Path, destination: Path) -> Path:
    """Create a listing-ready copy with a prominent additional-card shipping message."""
    with Image.open(source) as image:
        prepared = ImageOps.exif_transpose(image).convert("RGB")
        width, height = prepared.size
        canvas = prepared.convert("RGBA")
        overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        margin = max(12, width // 32)
        banner_height = min(height - (margin * 2), max(150, int(height * 0.24)))
        banner_top = height - banner_height - margin
        banner_box = (margin, banner_top, width - margin, height - margin)
        draw.rounded_rectangle(banner_box, radius=max(12, margin), fill=(8, 29, 43, 232))
        accent_height = max(6, height // 180)
        draw.rounded_rectangle(
            (margin, banner_top, width - margin, banner_top + accent_height),
            radius=accent_height // 2,
            fill=(255, 188, 66, 255),
        )

        text_area_width = width - (margin * 4)
        headline = "FREE SHIPPING"
        subline = "AFTER YOUR FIRST PURCHASE"
        headline_font = _shipping_overlay_font(headline, text_area_width, max(24, width // 15), 14)
        subline_font = _shipping_overlay_font(subline, text_area_width, max(18, width // 25), 11)
        headline_box = draw.textbbox((0, 0), headline, font=headline_font)
        subline_box = draw.textbbox((0, 0), subline, font=subline_font)
        center_x = width // 2
        headline_y = banner_top + (banner_height // 3) - ((headline_box[3] - headline_box[1]) // 2)
        subline_y = banner_top + (banner_height * 2 // 3) - ((subline_box[3] - subline_box[1]) // 2)
        draw.text(
            (center_x - ((headline_box[2] - headline_box[0]) // 2), headline_y),
            headline,
            font=headline_font,
            fill=(255, 255, 255, 255),
        )
        draw.text(
            (center_x - ((subline_box[2] - subline_box[0]) // 2), subline_y),
            subline,
            font=subline_font,
            fill=(255, 220, 142, 255),
        )
        result = Image.alpha_composite(canvas, overlay).convert("RGB")

    destination.parent.mkdir(parents=True, exist_ok=True)
    result.save(destination, format="JPEG", quality=94, optimize=True)
    return destination


def find_original_images(card_folder: Path) -> list[Path]:
    original = card_folder / "original"
    return sorted(
        (
            path
            for path in original.iterdir()
            if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
        ),
        key=lambda path: path.name.lower(),
    )


def find_front_image(card_folder: Path) -> Path:
    candidates = find_original_images(card_folder)
    if not candidates:
        raise FileNotFoundError(f"No image was found in {card_folder / 'original'}")
    candidates.sort(key=lambda path: (not path.stem.lower().startswith("front"), path.name.lower()))
    return candidates[0]


def find_back_image(card_folder: Path) -> Path | None:
    candidates = find_original_images(card_folder)
    if not candidates:
        return None
    named_back = next((path for path in candidates if path.stem.lower().startswith("back")), None)
    if named_back is not None:
        return named_back
    front = find_front_image(card_folder)
    return next((path for path in candidates if path != front), None)


def prepare_search_image(card_folder: Path) -> Path:
    source = find_front_image(card_folder)
    generated = card_folder / "generated"
    generated.mkdir(parents=True, exist_ok=True)
    destination = generated / "ebay-search.jpg"

    with Image.open(source) as image:
        prepared = ImageOps.exif_transpose(image).convert("RGB")
        prepared.thumbnail((1200, 1600), Image.Resampling.LANCZOS)
        prepared.save(destination, format="JPEG", quality=94, optimize=True)

    return destination
