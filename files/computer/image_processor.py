from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".tif", ".tiff"}


def find_front_image(card_folder: Path) -> Path:
    original = card_folder / "original"
    candidates = [
        path
        for path in original.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    ]
    if not candidates:
        raise FileNotFoundError(f"No image was found in {original}")
    candidates.sort(key=lambda path: (not path.stem.lower().startswith("front"), path.name.lower()))
    return candidates[0]


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
