"""Generate a KDP paperback wrap cover PDF for the book.

The interior PDF and the cover PDF are separate KDP uploads. This module renders
one full-bleed spread containing the back cover, spine, and front cover.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import chrome_pdf


ROOT = Path(__file__).resolve().parent
COVER_HTML = ROOT / "cover-print.html"
COVER_PDF = ROOT / "cover.pdf"

TRIM_WIDTH_IN = 6.0
TRIM_HEIGHT_IN = 9.0
BLEED_IN = 0.125
PAGE_COUNT = 242

# KDP paperback spine factor for black-and-white white paper, in inches per page.
PAPER_TYPE = "black-and-white white paper"
SPINE_FACTOR_IN = 0.002252

AUTHORS = [
  "Avi Salmon",
  "Dr. Eli Eisenberg",
  "Prof. Arnon Bentur",
  "Tamar Dayan",
  "Yael Granot",
  "Dr. Revital Duek",
  "Inna",
]
AUTHOR = "; ".join(AUTHORS)
SPINE_AUTHOR = "Avi Salmon et al."
SERIES = "International STEM Skills Round Table Phase III"
TITLE = "The Teacher Above AI"
SUBTITLE = "STEM Education, Human Judgment, and the New Learning Ecosystem"


@dataclass(frozen=True)
class CoverGeometry:
    trim_width: float
    trim_height: float
    bleed: float
    spine_width: float

    @property
    def full_width(self) -> float:
        return self.trim_width * 2 + self.spine_width + self.bleed * 2

    @property
    def full_height(self) -> float:
        return self.trim_height + self.bleed * 2


def geometry(page_count: int = PAGE_COUNT, spine_factor: float = SPINE_FACTOR_IN) -> CoverGeometry:
    return CoverGeometry(
        trim_width=TRIM_WIDTH_IN,
        trim_height=TRIM_HEIGHT_IN,
        bleed=BLEED_IN,
        spine_width=page_count * spine_factor,
    )


def cover_html(cover: CoverGeometry) -> str:
    front_left = cover.bleed + cover.trim_width + cover.spine_width
    spine_left = cover.bleed + cover.trim_width
    barcode_left = cover.bleed + cover.trim_width - 2.35
    barcode_top = cover.bleed + cover.trim_height - 1.65
    safe = 0.28
    author_lines = "<br>".join(AUTHORS)

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{TITLE} - KDP Paperback Cover</title>
  <style>
    @font-face {{ font-family: 'EB Garamond'; font-weight: 400;
      src: url('{(chrome_pdf.ASSETS / 'eb-garamond-400-normal.woff2').as_uri()}') format('woff2'); }}
    @font-face {{ font-family: 'EB Garamond'; font-weight: 600;
      src: url('{(chrome_pdf.ASSETS / 'eb-garamond-600-normal.woff2').as_uri()}') format('woff2'); }}
    @font-face {{ font-family: 'Inter'; font-weight: 400;
      src: url('{(chrome_pdf.ASSETS / 'inter-400-normal.woff2').as_uri()}') format('woff2'); }}
    @font-face {{ font-family: 'Inter'; font-weight: 600;
      src: url('{(chrome_pdf.ASSETS / 'inter-600-normal.woff2').as_uri()}') format('woff2'); }}
    @page {{ size: {cover.full_width:.3f}in {cover.full_height:.3f}in; margin: 0; }}
    * {{ box-sizing: border-box; }}
    html, body {{ width: {cover.full_width:.3f}in; height: {cover.full_height:.3f}in; margin: 0; }}
    body {{
      color: #fff8e6;
      font-family: 'Inter', sans-serif;
      background:
        radial-gradient(circle at {front_left + 5.0:.2f}in 1.05in, rgba(235, 185, 82, 0.62), transparent 1.95in),
        radial-gradient(circle at 1.55in 1.35in, rgba(111, 182, 164, 0.55), transparent 1.95in),
        linear-gradient(125deg, #18382f 0%, #10251f 44%, #241b13 100%);
    }}
    .cover {{ position: relative; width: 100%; height: 100%; overflow: hidden; }}
    .panel {{ position: absolute; top: {cover.bleed:.3f}in; height: {cover.trim_height:.3f}in; }}
    .back {{ left: {cover.bleed:.3f}in; width: {cover.trim_width:.3f}in; padding: 0.66in 0.62in; }}
    .front {{ left: {front_left:.3f}in; width: {cover.trim_width:.3f}in; padding: 0.72in 0.66in 0.62in; }}
    .spine {{ left: {spine_left:.3f}in; width: {cover.spine_width:.3f}in; padding: 0.18in 0; }}
    .safe-front {{ position: absolute; inset: {safe:.3f}in; border: 0 solid transparent; }}
    .series {{ margin: 0; color: #efc978; font-size: 9pt; line-height: 1.35; letter-spacing: 0.13em; text-transform: uppercase; }}
    h1 {{ margin: 1.06in 0 0.16in; font-family: 'EB Garamond', serif; font-size: 54pt; line-height: 0.88; font-weight: 600; letter-spacing: 0; }}
    .subtitle {{ max-width: 4.7in; margin: 0; font-family: 'EB Garamond', serif; font-size: 20pt; line-height: 1.08; color: #f8e7bd; }}
    .author {{ position: absolute; left: 0.66in; right: 0.66in; bottom: 0.52in; margin: 0; color: #efc978; font-size: 8.4pt; line-height: 1.35; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; }}
    .network {{ position: absolute; right: 0.34in; bottom: 1.72in; width: 4.9in; height: 3.4in; opacity: 0.74; }}
    .network path, .network line {{ stroke: #efd58b; stroke-width: 1.2; fill: none; }}
    .network circle {{ fill: #fff8e6; }}
    .back h2 {{ margin: 0 0 0.28in; font-family: 'EB Garamond', serif; font-size: 26pt; line-height: 1; font-weight: 600; }}
    .back p {{ margin: 0 0 0.16in; color: #f7ead0; font-size: 10.2pt; line-height: 1.48; }}
    .back .note {{ margin-top: 0.26in; padding-top: 0.19in; border-top: 1px solid rgba(239, 201, 120, 0.55); color: #d8c9aa; font-size: 8.7pt; line-height: 1.42; }}
    .barcode {{ position: absolute; left: {barcode_left:.3f}in; top: {barcode_top:.3f}in; width: 2.0in; height: 1.2in; background: #fff; color: #2a2a2a; display: flex; align-items: center; justify-content: center; padding: 0.08in; text-align: center; font-size: 7pt; line-height: 1.25; }}
    .spine-title {{ position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%) rotate(90deg); transform-origin: center; width: {cover.trim_height - 2.0:.3f}in; text-align: center; font-family: 'EB Garamond', serif; font-size: 13pt; line-height: 1; font-weight: 600; letter-spacing: 0.03em; white-space: nowrap; }}
    .spine-author {{ position: absolute; bottom: 0.72in; left: 50%; transform: translateX(-50%) rotate(90deg); transform-origin: center; width: 2.0in; text-align: center; color: #efc978; font-size: 7pt; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; white-space: nowrap; }}
    .fold {{ position: absolute; top: 0; bottom: 0; width: 1px; background: rgba(255,255,255,0.16); }}
    .fold.back-spine {{ left: {spine_left:.3f}in; }}
    .fold.spine-front {{ left: {front_left:.3f}in; }}
  </style>
</head>
<body>
  <div class="cover">
    <div class="panel back">
      <h2>About the Book</h2>
      <p>AI can now explain, draft, summarize, calculate, and code. That does not make teachers less important. It changes the evidence of learning and raises the level of judgment expected from every STEM educator.</p>
      <p><em>{TITLE}</em> synthesizes the International STEM Skills Round Table Phase III into a professional compass for education in the age of generative AI. It follows the discussion across competencies, assessment, teacher roles, AI-supported learning, professional development, and the learning environments that connect schools, higher education, and industry.</p>
      <p>The book's central claim is direct: human judgment must remain above the machine. Teachers design the conditions for responsible learning. Students keep responsibility for thinking. AI supports the work, but does not govern it.</p>
      <p class="note">A synthesis by {AUTHOR}. Not an official publication of the Samuel Neaman Institute or any organization represented in the Round Table.</p>
    </div>
    <div class="barcode">Barcode / ISBN area<br>Leave blank for KDP-generated barcode</div>
    <div class="panel spine">
      <div class="spine-title">{TITLE}</div>
      <div class="spine-author">{SPINE_AUTHOR}</div>
    </div>
    <div class="panel front">
      <div class="safe-front">
        <p class="series">{SERIES}</p>
        <h1>{TITLE}</h1>
        <p class="subtitle">{SUBTITLE}</p>
      </div>
      <svg class="network" viewBox="0 0 480 330" aria-hidden="true">
        <path d="M44 246 C124 160, 168 278, 250 170 S396 86, 440 134" />
        <path d="M70 76 C148 112, 162 176, 240 144 S336 58, 414 78" />
        <line x1="88" y1="238" x2="162" y2="184" />
        <line x1="162" y1="184" x2="242" y2="232" />
        <line x1="242" y1="232" x2="334" y2="158" />
        <line x1="334" y1="158" x2="414" y2="206" />
        <line x1="126" y1="92" x2="214" y2="132" />
        <line x1="214" y1="132" x2="306" y2="86" />
        <circle cx="88" cy="238" r="7" /><circle cx="162" cy="184" r="6" />
        <circle cx="242" cy="232" r="8" /><circle cx="334" cy="158" r="6" />
        <circle cx="414" cy="206" r="7" /><circle cx="126" cy="92" r="6" />
        <circle cx="214" cy="132" r="8" /><circle cx="306" cy="86" r="6" />
      </svg>
      <p class="author">{author_lines}</p>
    </div>
    <div class="fold back-spine"></div>
    <div class="fold spine-front"></div>
  </div>
</body>
</html>
"""


def build_cover(page_count: int = PAGE_COUNT, spine_factor: float = SPINE_FACTOR_IN) -> CoverGeometry:
    chrome_pdf.ensure_assets()
    cover = geometry(page_count=page_count, spine_factor=spine_factor)
    COVER_HTML.write_text(cover_html(cover), encoding="utf-8")
    pdf, _ = chrome_pdf.render_pdf(
        COVER_HTML.as_uri(),
        {
            "printBackground": True,
            "paperWidth": cover.full_width,
            "paperHeight": cover.full_height,
            "marginTop": 0,
            "marginBottom": 0,
            "marginLeft": 0,
            "marginRight": 0,
            "preferCSSPageSize": True,
        },
        ready_expression="document.fonts && document.fonts.status === 'loaded'",
        timeout=120,
    )
    COVER_PDF.write_bytes(pdf)
    return cover


def main() -> int:
    cover = build_cover()
    print(
        f"Generated {COVER_PDF.name}: {cover.full_width:.3f}x{cover.full_height:.3f}in "
        f"({TRIM_WIDTH_IN:g}x{TRIM_HEIGHT_IN:g} trim, {PAGE_COUNT} pages, "
        f"{cover.spine_width:.3f}in spine, {PAPER_TYPE})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())