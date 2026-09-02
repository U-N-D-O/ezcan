from __future__ import annotations

import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


EBAY_HOME_URL = "https://www.ebay.com/"


@dataclass(frozen=True)
class PictureSearchLaunch:
    image_path: Path
    url: str = EBAY_HOME_URL
    instructions: str = "Click eBay's camera icon, then choose the prepared image file."


def open_picture_search(
    image_path: Path,
    opener: Callable[[str], bool] = webbrowser.open_new_tab,
) -> PictureSearchLaunch:
    if not image_path.is_file():
        raise FileNotFoundError(f"Prepared search image does not exist: {image_path}")
    if not opener(EBAY_HOME_URL):
        raise OSError("The default browser could not be opened")
    return PictureSearchLaunch(image_path=image_path)
