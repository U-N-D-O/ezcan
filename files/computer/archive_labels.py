from __future__ import annotations

import base64
import html
from io import BytesIO
from pathlib import Path
from typing import Iterable

import qrcode


LABELS_PER_PAGE = 10


def _qr_data_uri(value: str) -> str:
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=4,
    )
    qr.add_data(value)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _label(code: str) -> str:
    escaped = html.escape(code)
    qr = _qr_data_uri(code)
    return f"""
      <article class="label">
        <div class="label-copy">
          <div class="brand-line"><span class="brand-dot"></span> SUGIMORI GEM ARCHIVE</div>
          <div class="label-kind">ARCHIVE ID</div>
          <div class="code">{escaped}</div>
          <div class="scan-note">SCAN TO IDENTIFY</div>
        </div>
        <div class="qr-wrap"><img src="{qr}" alt="QR code for archive ID {escaped}"></div>
      </article>
    """


def build_label_sheet(codes: Iterable[str], destination: Path, paper: str = "A4") -> Path:
    ordered_codes = list(codes)
    if not ordered_codes:
        raise ValueError("At least one archive ID is required")
    if paper not in {"A4", "Letter"}:
        raise ValueError("Paper must be A4 or Letter")

    page_height = "277mm" if paper == "A4" else "259mm"
    label_height = "47mm" if paper == "A4" else "44mm"

    pages = []
    for start in range(0, len(ordered_codes), LABELS_PER_PAGE):
        page_codes = ordered_codes[start : start + LABELS_PER_PAGE]
        pages.append(
            '<section class="page">'
            + "".join(_label(code) for code in page_codes)
            + "</section>"
        )

    title = html.escape(f"Sugimori Gem Archive labels — {ordered_codes[0]} to {ordered_codes[-1]}")
    document = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    @page {{ size: {paper} portrait; margin: 10mm; }}
    :root {{ color-scheme: light; }}
    * {{ box-sizing: border-box; }}
    html, body {{ margin: 0; padding: 0; background: #e8eef0; }}
    body {{ color: #102033; font-family: "Segoe UI", Arial, sans-serif; }}
    .page {{
      width: 190mm;
      min-height: {page_height};
      margin: 10mm auto;
      padding: 0;
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      grid-template-rows: repeat(5, {label_height});
      gap: 4mm 5mm;
      page-break-after: always;
    }}
    .page:last-child {{ page-break-after: auto; }}
    .label {{
      position: relative;
      display: flex;
      align-items: center;
      justify-content: space-between;
      min-width: 0;
      overflow: hidden;
      padding: 7mm 6mm 7mm 7mm;
      border: 0.45mm solid #163f49;
      border-radius: 3mm;
      background:
        radial-gradient(circle at 100% 0%, rgba(18,199,209,.18), transparent 38%),
        linear-gradient(135deg, #fffefd 0%, #f3fbfa 100%);
    }}
    .label::after {{
      content: "";
      position: absolute;
      left: 0;
      top: 0;
      width: 2.5mm;
      height: 100%;
      background: #12c7d1;
    }}
    .label-copy {{ min-width: 0; padding-left: 1mm; }}
    .brand-line {{
      margin-bottom: 4mm;
      color: #48727b;
      font: 600 7pt/1.2 "Segoe UI", Arial, sans-serif;
      letter-spacing: .08em;
      white-space: nowrap;
    }}
    .brand-dot {{
      display: inline-block;
      width: 2.5mm;
      height: 2.5mm;
      margin-right: 1.5mm;
      border-radius: 50%;
      background: #d94d78;
      vertical-align: -0.3mm;
    }}
    .label-kind {{
      color: #12aab5;
      font: 700 7pt/1.1 Consolas, monospace;
      letter-spacing: .15em;
    }}
    .code {{
      margin: 1.5mm 0 1mm;
      color: #102033;
      font: 800 24pt/1 Consolas, "Courier New", monospace;
      letter-spacing: .04em;
    }}
    .scan-note {{
      color: #6d7d8c;
      font: 600 6.5pt/1.1 Consolas, monospace;
      letter-spacing: .12em;
    }}
    .qr-wrap {{
      flex: 0 0 28mm;
      width: 28mm;
      height: 28mm;
      padding: 1.5mm;
      border: 0.35mm solid #b9d5d8;
      border-radius: 2mm;
      background: #fff;
    }}
    .qr-wrap img {{ display: block; width: 100%; height: 100%; }}
    @media print {{
      html, body {{ background: #fff; }}
      .page {{ margin: 0; }}
    }}
    @media screen and (max-width: 850px) {{
      .page {{ transform-origin: top left; transform: scale(.75); margin-bottom: -70mm; }}
    }}
  </style>
</head>
<body>
{''.join(pages)}
</body>
</html>
"""
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(document, encoding="utf-8")
    return destination
