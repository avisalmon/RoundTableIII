"""Typeset the manuscript as a print-ready paperback interior for Amazon KDP.

The web pages in build_book.py are laid out by the browser as one long scroll. A
printed book needs pages: a trim size, mirrored margins with a binding gutter,
running heads, folios, chapters that open on a right-hand page, and blanks where
the structure demands them. Chrome cannot do that on its own because it does not
implement CSS margin boxes, so the document is paginated by Paged.js inside a
headless browser and printed through the DevTools protocol (see chrome_pdf.py).
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass
from pathlib import Path

import chrome_pdf


ROOT = Path(__file__).resolve().parent
PRINT_HTML = ROOT / "book-print.html"
BOOK_PDF = ROOT / "book.pdf"

# --- KDP paperback specification -------------------------------------------------
# Trim size and margins follow KDP's "Set Trim Size, Bleed, and Margins" guidance.
# The gutter is set well above the minimum for our page band so the inner text
# stays readable in a perfect-bound book.
TRIM_WIDTH_IN = 6.0
TRIM_HEIGHT_IN = 9.0
MARGIN_INSIDE_IN = 0.75
MARGIN_OUTSIDE_IN = 0.55
MARGIN_TOP_IN = 0.70
MARGIN_BOTTOM_IN = 0.75
SAFE_EDGE_IN = 0.25  # KDP minimum for a no-bleed interior

# Minimum inside margin required by KDP, by page count.
GUTTER_BANDS = ((150, 0.375), (300, 0.5), (500, 0.625), (700, 0.75), (828, 0.875))

TEXT_WIDTH_IN = TRIM_WIDTH_IN - MARGIN_INSIDE_IN - MARGIN_OUTSIDE_IN
TEXT_HEIGHT_IN = TRIM_HEIGHT_IN - MARGIN_TOP_IN - MARGIN_BOTTOM_IN
FIGURE_MAX_WIDTH_PX = round(TEXT_WIDTH_IN * 96)
FIGURE_MAX_HEIGHT_PX = round(4.9 * 96)
FIGURE_FULL_PAGE_HEIGHT_PX = round((TEXT_HEIGHT_IN - 0.45) * 96)  # leave room for the caption
# A broadside figure is turned a quarter turn, so the page's height becomes its width.
FIGURE_ROTATED_WIDTH_PX = round(TEXT_HEIGHT_IN * 96)
FIGURE_ROTATED_HEIGHT_PX = round((TEXT_WIDTH_IN - 0.45) * 96)

# Diagram labels are set at 15px (11.25pt). TARGET is what the renderer aims for while
# choosing between equally faithful layouts; MIN (7.2pt, just above KDP's 7pt floor) is
# the point at which it will spend a whole page, or turn the figure broadside, to keep
# the diagram readable.
DIAGRAM_TYPE_PX = 15
FIGURE_TARGET_SCALE = 0.72
FIGURE_MIN_SCALE = 0.64

AUTHORS = [
  "Avi Salmon",
]
AUTHOR = "; ".join(AUTHORS)
CONTACT = "avi.salmon@gmail.com"
# Set to the KDP-assigned ISBN before publishing. Empty means the line is omitted.
ISBN = ""


@dataclass
class BookMeta:
    series: str
    title: str
    subtitle: str
    year: str
    generated: str


def required_gutter(page_count: int) -> float:
    for limit, gutter in GUTTER_BANDS:
        if page_count <= limit:
            return gutter
    return GUTTER_BANDS[-1][1]


def split_front_matter(body_html: str) -> tuple[str, str]:
    """Return (front matter, body) split at the manuscript's second <h1>."""
    starts = [match.start() for match in re.finditer(r"<h1 id=", body_html)]
    if len(starts) < 2:
        return "", body_html
    return body_html[: starts[1]], body_html[starts[1] :]


def extract_section(front_html: str, anchor: str) -> str:
    """Pull one <h2 id="anchor"> section out of the front matter chunk."""
    match = re.search(rf'<h2 id="{anchor}">(.*?)</h2>(.*)', front_html, re.S)
    if not match:
        return ""
    return f'<h2 class="frontmatter-heading">{match.group(1)}</h2>{match.group(2)}'


def book_meta(headings: list, generated: str) -> BookMeta:
    series = headings[0].title if headings else "International STEM Skills Round Table"
    combined = headings[1].title if len(headings) > 1 else series
    title, _, subtitle = combined.partition(":")
    return BookMeta(
        series=series.strip(),
        title=title.strip(),
        subtitle=subtitle.strip(),
        year=generated[:4],
        generated=generated,
    )


def is_part(title: str) -> bool:
    return bool(re.match(r"^(Part\s|Appendices\b)", title))


def structure_body(body_html: str) -> str:
    """Tag headings so the stylesheet can open parts and chapters as book pages."""

    def heading(match: re.Match[str]) -> str:
        level, anchor, text = match.group(1), match.group(2), match.group(3)
        plain = re.sub(r"<[^>]+>", "", text)
        if level == "1":
            kind = "part-opener" if is_part(plain) else "section-opener"
            label, _, rest = plain.partition("–")
            if kind == "part-opener" and rest:
                return (
                    f'<h1 class="part-opener" id="{anchor}">'
                    f'<span class="opener-label">{label.strip()}</span>'
                    f'<span class="opener-title">{rest.strip()}</span></h1>'
                )
            return f'<h1 class="{kind}" id="{anchor}"><span class="opener-title">{text}</span></h1>'
        if level == "2":
            label, _, rest = plain.partition("–")
            if rest:
                return (
                    f'<h2 class="chapter-opener" id="{anchor}">'
                    f'<span class="opener-label">{label.strip()}</span>'
                    f'<span class="opener-title">{rest.strip()}</span></h2>'
                )
            return f'<h2 class="chapter-opener" id="{anchor}"><span class="opener-title">{text}</span></h2>'
        if level == "4":
            return f'<h4 class="subsection-heading" id="{anchor}">{text}</h4>'
        extra = " sources" if plain.strip().lower() == "sources" else ""
        return f'<h3 class="section-heading{extra}" id="{anchor}">{text}</h3>'

    return re.sub(r"<h([1234]) id=\"([^\"]+)\">(.*?)</h\1>", heading, body_html, flags=re.S)


def contents_html(headings: list, body_start_line: int) -> str:
    entries = []
    for item in headings:
        if item.line < body_start_line or item.level > 2:
            continue
        title = html.escape(smart(item.title))
        if item.level == 1:
            style = "toc-part" if is_part(item.title) else "toc-section"
        else:
            style = "toc-chapter"
        entries.append(
            f'<a class="toc-entry {style}" href="#{item.anchor}"><span class="toc-text">{title}</span></a>'
        )
    return "".join(entries)


def figures_html(figures: list[tuple[str, str]]) -> str:
    entries = []
    for anchor, caption in figures:
        text = re.sub(r"<[^>]+>", "", caption).strip()
        entries.append(
            f'<a class="toc-entry toc-figure" href="#{anchor}"><span class="toc-text">{text}</span></a>'
        )
    return "".join(entries)


def smart(text: str) -> str:
    text = re.sub(r"(?<=\S) - (?=\S)", " – ", text)
    return re.sub(r"(?<=[A-Za-z])'(?=[A-Za-z])", "’", text)


def front_matter_html(meta: BookMeta, editorial_note: str, contents: str, figures: str) -> str:
    title = html.escape(meta.title)
    subtitle = html.escape(meta.subtitle)
    series = html.escape(meta.series)
    author_lines = "<br>".join(html.escape(author) for author in AUTHORS)
    isbn_line = f"<p>ISBN: {html.escape(ISBN)}</p>" if ISBN else ""
    return f"""
<section class="halftitle">
  <p class="halftitle-text">{title}</p>
</section>

<section class="titlepage">
  <p class="title-series">{series}</p>
  <h1 class="title-main">{title}</h1>
  <p class="title-subtitle">{subtitle}</p>
  <p class="title-author">{author_lines}</p>
</section>

<section class="copyright">
  <p class="copyright-title">{title}</p>
  <p class="copyright-subtitle">{subtitle}</p>
  <p>Copyright &copy; {meta.year} {html.escape(AUTHOR)}</p>
  <p>All rights reserved.</p>
  <p>First edition, {meta.year}</p>
  {isbn_line}
  <p>No part of this publication may be reproduced, distributed, or transmitted in any form or by
     any means, including photocopying, recording, or other electronic or mechanical methods,
     without the prior written permission of the author, except in the case of brief quotations
     embodied in critical reviews and certain other non-commercial uses permitted by copyright law.</p>
  <p class="copyright-note-heading">About this book</p>
    <p>This book is a synthesis of the {series}, written by a Round Table participant.
      It is not an official publication of the Samuel Neaman Institute or of any other
     organisation represented in the discussions, and it does not speak on behalf of the
     participants named in it.</p>
  <p>The manuscript was drafted with the assistance of generative AI tools working from the
      collected Round Table materials, and every part of it was reviewed and edited by the author,
      who is responsible for the final text. Where the sources named speakers and summarised their
     contributions, the book refers to them by name and role rather than by direct quotation.</p>
  <p>Comments, corrections, and suggestions are welcome at {html.escape(CONTACT)}.</p>
  <p class="colophon">Set in EB Garamond and Inter. Generated from the manuscript on {meta.generated}.</p>
</section>

<section class="editorial-note">{editorial_note}</section>

<section class="contents">
  <h2 class="frontmatter-heading">Table of Contents</h2>
  {contents}
</section>

<section class="list-of-figures">
  <h2 class="frontmatter-heading">List of Figures</h2>
  {figures}
</section>
"""


def print_stylesheet(meta: BookMeta, assets: Path) -> str:
    font_dir = assets.as_uri()
    running_title = meta.title.replace('"', "'")
    return f"""
@font-face {{ font-family: 'EB Garamond'; font-style: normal; font-weight: 400;
  src: url('{font_dir}/eb-garamond-400-normal.woff2') format('woff2'); font-display: block; }}
@font-face {{ font-family: 'EB Garamond'; font-style: italic; font-weight: 400;
  src: url('{font_dir}/eb-garamond-400-italic.woff2') format('woff2'); font-display: block; }}
@font-face {{ font-family: 'EB Garamond'; font-style: normal; font-weight: 600;
  src: url('{font_dir}/eb-garamond-600-normal.woff2') format('woff2'); font-display: block; }}
@font-face {{ font-family: 'EB Garamond'; font-style: italic; font-weight: 600;
  src: url('{font_dir}/eb-garamond-600-italic.woff2') format('woff2'); font-display: block; }}
@font-face {{ font-family: 'Inter'; font-style: normal; font-weight: 400;
  src: url('{font_dir}/inter-400-normal.woff2') format('woff2'); font-display: block; }}
@font-face {{ font-family: 'Inter'; font-style: normal; font-weight: 600;
  src: url('{font_dir}/inter-600-normal.woff2') format('woff2'); font-display: block; }}

/* ---------- page geometry: 6x9in, mirrored margins, binding gutter inside ---------- */
@page {{
  size: {TRIM_WIDTH_IN}in {TRIM_HEIGHT_IN}in;
  margin: {MARGIN_TOP_IN}in {MARGIN_OUTSIDE_IN}in {MARGIN_BOTTOM_IN}in {MARGIN_INSIDE_IN}in;
  bleed: 0;
}}
/* Running heads and folios are written into these boxes after pagination, from
   script, rather than through named pages. Assigning a named page to a chapter
   heading (page: opener) makes the named page change mid-flow, and a named page
   change forces a page break, which left every chapter opener alone on its page. */
@page :right {{
  margin-left: {MARGIN_INSIDE_IN}in;
  margin-right: {MARGIN_OUTSIDE_IN}in;
  @top-center {{
    content: var(--runhead, "");
    font: 400 8pt/1 'Inter', sans-serif; letter-spacing: 0.14em; text-transform: uppercase;
    color: #1a1a1a; margin-top: 0.24in; text-align: center;
  }}
  @bottom-right {{
    content: var(--folio, "");
    font: 400 9.5pt/1 'Inter', sans-serif; color: #1a1a1a; margin-bottom: 0.3in; text-align: right;
  }}
  @bottom-center {{
    content: var(--dropfolio, "");
    font: 400 9.5pt/1 'Inter', sans-serif; color: #1a1a1a; margin-bottom: 0.3in; text-align: center;
  }}
}}
@page :left {{
  margin-left: {MARGIN_OUTSIDE_IN}in;
  margin-right: {MARGIN_INSIDE_IN}in;
  @top-center {{
    content: var(--runhead, "");
    font: 400 8pt/1 'Inter', sans-serif; letter-spacing: 0.14em; text-transform: uppercase;
    color: #1a1a1a; margin-top: 0.24in; text-align: center;
  }}
  @bottom-left {{
    content: var(--folio, "");
    font: 400 9.5pt/1 'Inter', sans-serif; color: #1a1a1a; margin-bottom: 0.3in; text-align: left;
  }}
  @bottom-center {{
    content: var(--dropfolio, "");
    font: 400 9.5pt/1 'Inter', sans-serif; color: #1a1a1a; margin-bottom: 0.3in; text-align: center;
  }}
}}

/* ---------- text ---------- */
/* Paged.js marks an element it splits across a page break with
   [data-align-last-split-element='justify'] so the fragment's last line stays
   justified. text-align-last inherits, so every paragraph inside a split section
   inherited it too and had its final line stretched edge to edge. This reset has
   zero specificity: it stops the inheritance but still loses to Paged.js's own
   attribute rule on the elements that really are split. */
* {{ text-align-last: auto; }}
html {{ background: #fff; }}
body {{
  margin: 0; background: #fff; color: #000;
  font-family: 'EB Garamond', Georgia, serif;
  font-size: 11pt; line-height: 1.45;
  text-align: justify; hyphens: auto; -webkit-hyphens: auto;
  orphans: 3; widows: 3;
  font-variant-numeric: oldstyle-num;
}}
p {{ margin: 0; text-indent: 1.4em; }}
h1 + p, h2 + p, h3 + p, h4 + p, figure + p, table + p, ul + p, ol + p, pre + p,
p.first, .opener-rule + p {{ text-indent: 0; }}
a {{ color: inherit; text-decoration: none; }}
strong {{ font-weight: 600; }}
em {{ font-style: italic; }}
code {{ font-family: 'Inter', monospace; font-size: 0.92em; }}

/* ---------- front matter ---------- */
.halftitle, .titlepage, .copyright {{ text-align: center; }}
.halftitle {{ break-before: right; padding-top: 2.6in; }}
.halftitle-text {{
  text-indent: 0; font-size: 15pt; letter-spacing: 0.16em; text-transform: uppercase;
  font-family: 'Inter', sans-serif; font-weight: 400;
}}
.titlepage {{ break-before: right; padding-top: 1.5in; }}
.title-series {{
  text-indent: 0; font-family: 'Inter', sans-serif; font-size: 8.5pt; font-weight: 400;
  letter-spacing: 0.18em; text-transform: uppercase; line-height: 1.6;
}}
.title-main {{
  margin: 0.55in 0 0; font-size: 30pt; font-weight: 400; line-height: 1.1;
  letter-spacing: 0.01em; text-align: center;
}}
.title-subtitle {{
  text-indent: 0; margin: 0.22in auto 0; max-width: 3.6in; font-size: 12.5pt;
  font-style: italic; line-height: 1.35; text-align: center;
}}
.title-author {{
  text-indent: 0; margin-top: 1.9in; font-family: 'Inter', sans-serif;
  font-size: 10.5pt; letter-spacing: 0.14em; text-transform: uppercase;
}}
.copyright {{
  break-before: page; display: flex; flex-direction: column; justify-content: flex-end;
  min-height: 7.4in; text-align: left; font-size: 8.5pt; line-height: 1.4;
}}
.copyright p {{ text-indent: 0; margin-bottom: 0.9em; text-align: left; }}
.copyright-title {{ font-size: 10pt; font-weight: 600; margin-bottom: 0.1em !important; }}
.copyright-subtitle {{ font-style: italic; margin-bottom: 1.2em !important; }}
.copyright-note-heading {{
  font-family: 'Inter', sans-serif; font-size: 7.5pt; font-weight: 600;
  letter-spacing: 0.12em; text-transform: uppercase; margin-bottom: 0.5em !important;
}}
.placeholder {{ font-family: 'Inter', sans-serif; font-size: 7pt; color: #555; }}
.colophon {{ margin-top: 0.4em; color: #333; }}

.editorial-note, .contents, .list-of-figures {{ break-before: right; }}
.frontmatter-heading {{
  text-align: center; font-weight: 400; font-size: 13pt; letter-spacing: 0.2em;
  text-transform: uppercase; font-family: 'Inter', sans-serif;
  margin: 0.35in 0 0.42in; break-after: avoid;
}}
.editorial-note p {{ margin-bottom: 0.75em; }}

/* Contents and figure list. The leader is drawn as an absolutely positioned rule on
   the entry's last line, so an entry that wraps to two lines still ends in dots with
   its page number on the right, instead of stranding the number mid-entry. */
.toc-entry {{
  display: block; position: relative; text-decoration: none;
  text-align: left; text-indent: 0; break-inside: avoid;
  margin-top: 0.16em; padding-right: 2.6em;
}}
.toc-entry::before {{
  content: ""; position: absolute; left: 0; right: 2.6em; bottom: 0.32em;
  border-bottom: 0.5pt dotted #777;
}}
.toc-entry::after {{
  content: target-counter(attr(href), page);
  position: absolute; right: 0; bottom: 0;
  font-family: 'Inter', sans-serif; font-size: 9pt;
}}
.toc-text {{ position: relative; background: #fff; padding-right: 0.4em; }}
.toc-part {{
  margin-top: 1.15em; margin-bottom: 0.3em;
  font-family: 'Inter', sans-serif; font-size: 8pt; font-weight: 600;
  letter-spacing: 0.07em; text-transform: uppercase; line-height: 1.5;
}}
.toc-part::before {{ border-bottom: none; }}
.toc-section {{ margin-top: 0.85em; font-size: 11pt; }}
/* Indent with margin, not padding: the leader is positioned against the padding box,
   so padding would leave a stub of dots in front of the entry. */
.toc-chapter {{ margin-left: 0.16in; font-size: 11pt; }}
.toc-figure {{ margin-left: 0.16in; font-size: 10pt; margin-top: 0.34em; }}

/* ---------- body openers ---------- */
/* The reset does not drive the printed folio (script does that), but Paged.js uses
   this counter to resolve target-counter(), so it keeps the contents numbers
   body-relative and in step with the folios. */
.bookbody {{ break-before: right; counter-reset: page 1; }}
h1.part-opener {{
  break-before: right; break-after: page;
  margin: 0; padding-top: 2.9in; text-align: center; font-weight: 400;
}}
h1.part-opener .opener-label {{
  display: block; font-family: 'Inter', sans-serif; font-size: 10pt; font-weight: 600;
  letter-spacing: 0.24em; text-transform: uppercase;
}}
h1.part-opener .opener-title {{
  display: block; margin: 0.3in auto 0; max-width: 3.7in;
  font-size: 21pt; line-height: 1.22; font-weight: 400;
}}
h1.section-opener, h2.chapter-opener {{
  break-before: right; break-after: avoid;
  margin: 0 0 0.42in; padding-top: 1.15in; text-align: left; font-weight: 400;
}}
h1.section-opener .opener-label, h2.chapter-opener .opener-label {{
  display: block; margin-bottom: 0.22in;
  font-family: 'Inter', sans-serif; font-size: 9pt; font-weight: 600;
  letter-spacing: 0.22em; text-transform: uppercase; color: #1a1a1a;
}}
h1.section-opener .opener-title, h2.chapter-opener .opener-title {{
  display: block; font-size: 20pt; line-height: 1.2; font-weight: 400;
  padding-bottom: 0.16in; border-bottom: 0.5pt solid #000;
}}
h3.section-heading {{
  margin: 1.5em 0 0.45em; font-size: 11.5pt; font-weight: 600; line-height: 1.3;
  text-align: left; break-after: avoid; break-inside: avoid;
}}
h4.subsection-heading {{
  margin: 1.15em 0 0.35em; font-family: 'Inter', sans-serif; font-size: 9.6pt;
  font-weight: 600; line-height: 1.25; text-align: left; break-after: avoid;
  break-inside: avoid; text-indent: 0;
}}
h3.sources {{
  font-family: 'Inter', sans-serif; font-size: 8pt; font-weight: 600;
  letter-spacing: 0.14em; text-transform: uppercase; margin-top: 1.6em;
}}
h3.sources + p {{
  font-size: 9.5pt; line-height: 1.35; text-align: left; hyphens: none;
  padding-left: 1.2em; text-indent: -1.2em; color: #1a1a1a;
}}

/* ---------- body elements ---------- */
ul, ol {{ margin: 0.6em 0; padding-left: 1.5em; }}
li {{ margin-bottom: 0.28em; text-align: justify; }}
li > ul, li > ol {{ margin: 0.28em 0 0; }}

figure.figure {{
  margin: 1.5em 0; padding: 0; text-align: center; break-inside: avoid;
}}
figure.figure.full-page {{ break-before: page; break-after: page; margin: 0; padding-top: 0.2in; }}
/* Broadside figure: turned a quarter turn anticlockwise, so the top of the figure is
   at the left edge of the page and the reader turns the book clockwise. */
figure.figure.rotated {{ break-before: page; break-after: page; margin: 0; padding: 0; }}
figure.figure.rotated .rotate-outer {{
  display: flex; align-items: center; justify-content: center; overflow: hidden;
}}
figure.figure.rotated .rotate-inner {{
  flex: none; display: flex; flex-direction: column;
  align-items: center; justify-content: center;
  transform: rotate(-90deg);
}}
figure.figure pre.mermaid {{
  margin: 0; padding: 0; border: 0; background: none; white-space: normal; text-align: center;
}}
figure.figure svg {{ display: block; margin: 0 auto; }}
figcaption {{
  margin-top: 0.75em; font-family: 'Inter', sans-serif; font-size: 8.5pt; line-height: 1.35;
  text-align: center; color: #1a1a1a; hyphens: none;
}}
.diagram-title {{
  text-indent: 0; margin-bottom: 0.6em; font-family: 'Inter', sans-serif;
  font-size: 8.5pt; font-weight: 600; letter-spacing: 0.1em; text-transform: uppercase;
  text-align: center;
}}

table {{
  width: 100%; margin: 1.4em 0; border-collapse: collapse; break-inside: avoid;
  font-family: 'Inter', sans-serif; font-size: 8.5pt; line-height: 1.32;
}}
th, td {{ text-align: left; }}
thead th {{
  border-top: 1pt solid #000; border-bottom: 0.5pt solid #000;
  padding: 0.5em 0.7em 0.45em 0; font-weight: 600; vertical-align: bottom;
}}
tbody td {{
  padding: 0.42em 0.7em 0.42em 0; vertical-align: top; hyphens: none;
  border-bottom: 0.25pt solid #999;
}}
figure.figure-table {{ text-align: left; }}
figure.figure-table table {{ margin-top: 0; }}
tbody tr:last-child td {{ border-bottom: 1pt solid #000; }}
th:last-child, td:last-child {{ padding-right: 0; }}
.align-center {{ text-align: center; }}
.align-right {{ text-align: right; }}

pre {{
  white-space: pre-wrap; font-family: 'Inter', monospace; font-size: 8.5pt;
  background: none; border: 0; padding: 0;
}}
"""


def render_script(meta: BookMeta, assets: Path) -> str:
    """Render diagrams to vector art, size them to the text block, then paginate.

    Several source diagrams are left-to-right chains up to 1700px wide. Scaled into
    a 6in page they would print at 4pt, well under KDP's 7pt legibility floor, so an
    over-wide chart is re-flowed top-to-bottom (direction is presentation, not
    content) and, if it is still too small, given a page of its own.
    """
    return f"""
mermaid.initialize({{
  startOnLoad: false,
  theme: 'base',
  securityLevel: 'loose',
  fontFamily: "Inter, sans-serif",
  themeVariables: {{
    background: '#ffffff', primaryColor: '#ffffff', secondaryColor: '#f2f2f2',
    tertiaryColor: '#ffffff', primaryTextColor: '#000000', secondaryTextColor: '#000000',
    tertiaryTextColor: '#000000', primaryBorderColor: '#000000',
    secondaryBorderColor: '#000000', tertiaryBorderColor: '#000000',
    lineColor: '#000000', textColor: '#000000', mainBkg: '#ffffff', nodeBorder: '#000000',
    clusterBkg: '#ffffff', clusterBorder: '#000000', edgeLabelBackground: '#ffffff',
    titleColor: '#000000', fontSize: '{DIAGRAM_TYPE_PX}px',
    cScale0: '#ffffff', cScale1: '#ededed', cScale2: '#ffffff', cScale3: '#ededed',
    cScale4: '#ffffff', cScale5: '#ededed', cScale6: '#ffffff', cScale7: '#ededed',
    cScale8: '#ffffff', cScale9: '#ededed', cScale10: '#ffffff', cScale11: '#ededed',
    cScaleLabel0: '#000000', cScaleLabel1: '#000000', cScaleLabel2: '#000000',
    cScaleLabel3: '#000000', cScaleLabel4: '#000000', cScaleLabel5: '#000000',
    cScaleLabel6: '#000000', cScaleLabel7: '#000000', cScaleLabel8: '#000000',
    cScaleLabel9: '#000000', cScaleLabel10: '#000000', cScaleLabel11: '#000000'
  }},
  flowchart: {{
    useMaxWidth: true, htmlLabels: true, curve: 'linear',
    padding: 6, nodeSpacing: 30, rankSpacing: 42, diagramPadding: 4
  }},
  mindmap: {{ useMaxWidth: true, padding: 8 }},
  timeline: {{ useMaxWidth: true, padding: 8 }}
}});

const TEXT_WIDTH = {FIGURE_MAX_WIDTH_PX};
const INLINE_HEIGHT = {FIGURE_MAX_HEIGHT_PX};
const PAGE_HEIGHT = {FIGURE_FULL_PAGE_HEIGHT_PX};
const ROTATED_WIDTH = {FIGURE_ROTATED_WIDTH_PX};
const ROTATED_HEIGHT = {FIGURE_ROTATED_HEIGHT_PX};
const TARGET_SCALE = {FIGURE_TARGET_SCALE};
const MIN_SCALE = {FIGURE_MIN_SCALE};

function measure(host, svgMarkup, maxWidth, maxHeight) {{
  host.innerHTML = svgMarkup;
  const svg = host.querySelector('svg');
  const box = svg.viewBox && svg.viewBox.baseVal;
  const width = box && box.width ? box.width : svg.getBoundingClientRect().width;
  const height = box && box.height ? box.height : svg.getBoundingClientRect().height;
  return {{ svg, width, height, scale: Math.min(maxWidth / width, maxHeight / height, 1) }};
}}

function applySize(svg, width, height, scale) {{
  svg.removeAttribute('style');
  svg.setAttribute('width', (width * scale).toFixed(1));
  svg.setAttribute('height', (height * scale).toFixed(1));
  svg.style.width = (width * scale).toFixed(1) + 'px';
  svg.style.height = (height * scale).toFixed(1) + 'px';
}}

// Break a long node label across lines so a diagram is not forced wide by one caption.
function wrapLabel(text, limit) {{
  if (text.length <= limit || text.includes('<br')) return text;
  const lines = [];
  let current = '';
  for (const word of text.split(' ')) {{
    if (current && (current + ' ' + word).length > limit) {{
      lines.push(current);
      current = word;
    }} else {{
      current = current ? current + ' ' + word : word;
    }}
  }}
  if (current) lines.push(current);
  return lines.join('<br/>');
}}

function wrapDiagramLabels(source, limit) {{
  return source.replace(/\\[([^\\[\\]]+)\\]/g, (whole, label) => {{
    if (/^["`]/.test(label.trim())) return whole;
    return '[' + wrapLabel(label, limit) + ']';
  }});
}}

// A mermaid timeline lays its events out side by side and cannot be made legible on a
// 6in page. The same events read perfectly well as a vertical chain, so the renderer
// re-expresses them without changing a word.
function timelineToChain(source) {{
  const rows = source.split('\\n').slice(1);
  const events = [];
  let title = '';
  for (const row of rows) {{
    const line = row.trim();
    if (!line) continue;
    if (/^title\\s+/i.test(line)) {{ title = line.replace(/^title\\s+/i, ''); continue; }}
    if (/^section\\s+/i.test(line)) continue;
    const parts = line.split(':').map((part) => part.trim()).filter(Boolean);
    if (parts.length) events.push(parts);
  }}
  if (!events.length) return null;
  const nodes = events.map((parts, index) => {{
    const head = parts[0];
    const rest = parts.slice(1).join(': ');
    const label = rest ? head + '<br/>' + wrapLabel(rest, 34) : head;
    return `  n${{index}}["${{label.replace(/"/g, "'")}}"]`;
  }});
  const edges = events.slice(1).map((_, index) => `  n${{index}} --> n${{index + 1}}`);
  return {{ title: title, source: ['flowchart TD', ...nodes, ...edges].join('\\n') }};
}}

async function drawDiagrams() {{
  const report = [];
  const hosts = Array.from(document.querySelectorAll('figure.figure pre.mermaid'));
  for (let index = 0; index < hosts.length; index += 1) {{
    const host = hosts[index];
    let source = host.textContent;
    let note = 'as written';

    if (/^\\s*timeline\\b/.test(source)) {{
      const chain = timelineToChain(source);
      if (chain) {{
        source = chain.source;
        note = 'timeline set vertically';
        if (chain.title) {{
          const heading = document.createElement('p');
          heading.className = 'diagram-title';
          heading.textContent = chain.title;
          host.parentNode.insertBefore(heading, host);
        }}
      }}
    }}

    const flow = source.match(/^(\\s*)(flowchart|graph)\\s+(TD|TB|LR|RL)\\b/);
    const variants = [];
    if (flow) {{
      // Least invasive option first: keep the author's direction and loose label
      // wrapping, and only tighten if the diagram will not fit legibly.
      const flipped = /LR|RL/.test(flow[3]) ? 'TD' : 'LR';
      for (const limit of [30, 22, 16]) {{
        const wrapped = wrapDiagramLabels(source, limit);
        variants.push([note, wrapped]);
        variants.push([
          note === 'as written' ? 'reflowed to fit the page' : note + ', reflowed to fit the page',
          wrapped.replace(/^(\\s*)(flowchart|graph)\\s+(TD|TB|LR|RL)\\b/, `$1$2 ${{flipped}}`)
        ]);
      }}
    }} else {{
      variants.push([note, source]);
    }}

    let best = null;
    for (let variant = 0; variant < variants.length; variant += 1) {{
      const {{ svg }} = await mermaid.render(`diagram-${{index}}-${{variant}}`, variants[variant][1]);
      const fitted = measure(host, svg, TEXT_WIDTH, INLINE_HEIGHT);
      if (!best || fitted.scale > best.scale) {{
        best = Object.assign({{ markup: svg, variant: variants[variant][0] }}, fitted);
      }}
      if (best.scale >= TARGET_SCALE) break;
    }}

    const figure = host.closest('figure');
    let placement = 'inline';
    if (best.scale < MIN_SCALE) {{
      // Give the diagram the whole page; the extra height often buys back the type size.
      const fullPage = Math.min(TEXT_WIDTH / best.width, PAGE_HEIGHT / best.height, 1);
      if (fullPage > best.scale) {{
        best.scale = fullPage;
        placement = 'full page';
        figure.classList.add('full-page');
      }}
    }}
    if (best.scale < MIN_SCALE) {{
      // Last resort for a genuinely wide diagram: set it broadside, as a printed book
      // does, with the top of the figure at the left edge of the page.
      const rotated = Math.min(ROTATED_WIDTH / best.width, ROTATED_HEIGHT / best.height, 1);
      if (rotated > best.scale) {{
        best.scale = rotated;
        placement = 'broadside';
        figure.classList.remove('full-page');
        figure.classList.add('rotated');
      }}
    }}

    const fitted = measure(host, best.markup, TEXT_WIDTH, INLINE_HEIGHT);
    applySize(fitted.svg, fitted.width, fitted.height, best.scale);
    if (placement === 'broadside') {{
      // Both wrappers stay in normal flow with explicit sizes. Paged.js measures
      // boxes to decide where a page breaks, and an absolutely positioned rotated
      // box confused it into emitting an empty page.
      const outer = document.createElement('div');
      outer.className = 'rotate-outer';
      const inner = document.createElement('div');
      inner.className = 'rotate-inner';
      inner.style.width = ROTATED_WIDTH + 'px';
      inner.style.height = TEXT_WIDTH + 'px';
      while (figure.firstChild) inner.appendChild(figure.firstChild);
      outer.appendChild(inner);
      outer.style.height = ROTATED_WIDTH + 'px';
      figure.appendChild(outer);
    }}
    report.push({{
      figure: index + 1,
      width: Math.round(best.width),
      height: Math.round(best.height),
      scale: Number(best.scale.toFixed(3)),
      variant: best.variant,
      placement: placement
    }});
  }}
  window.__figureReport = report;
}}

const BOOK_TITLE = {meta.title!r};
const ROMAN = [[1000,'m'],[900,'cm'],[500,'d'],[400,'cd'],[100,'c'],[90,'xc'],
               [50,'l'],[40,'xl'],[10,'x'],[9,'ix'],[5,'v'],[4,'iv'],[1,'i']];

function toRoman(value) {{
  let out = '';
  for (const [amount, numeral] of ROMAN) {{
    while (value >= amount) {{ out += numeral; value -= amount; }}
  }}
  return out;
}}

// Paged.js applies `counter-reset: page` only to the page the element starts on, so
// the folio would run i...x, 1, 12, 13 instead of restarting at the body. Every piece
// of page furniture is therefore assigned here, once the pages exist, and read back
// through custom properties.
function numberPages() {{
  const firstBody = document.querySelector('.bookbody');
  const bodyPage = firstBody && firstBody.closest('.pagedjs_page');
  const bodyStart = bodyPage ? Number(bodyPage.getAttribute('data-page-number')) : 1;
  const folios = {{}};
  const labels = {{}};
  let chapter = '';

  document.querySelectorAll('.pagedjs_page').forEach((page) => {{
    const number = Number(page.getAttribute('data-page-number'));
    const content = page.querySelector('.pagedjs_page_content');
    const blank = page.classList.contains('pagedjs_blank_page') ||
                  !content || !content.textContent.trim();
    const opener = content && content.querySelector('h2.chapter-opener, h1.section-opener');
    const part = content && content.querySelector('h1.part-opener');
    const cover = content && content.querySelector('.halftitle, .titlepage, .copyright');
    if (opener) chapter = (opener.querySelector('.opener-title') || opener).textContent.trim();
    if (part) chapter = '';

    const label = number < bodyStart ? toRoman(number) : String(number - bodyStart + 1);
    let folio = label;
    let dropFolio = '';
    let runhead = '';

    if (blank || cover || part) {{
      folio = '';                       // display pages and blanks carry no number
    }} else if (opener) {{
      folio = '';
      dropFolio = label;                // chapter openers take a centred drop folio
    }} else if (number >= bodyStart) {{
      runhead = number % 2 === 0 ? BOOK_TITLE : chapter;
    }}

    page.style.setProperty('--folio', JSON.stringify(folio));
    page.style.setProperty('--dropfolio', JSON.stringify(dropFolio));
    page.style.setProperty('--runhead', JSON.stringify(runhead));
    folios[number] = folio || dropFolio;
    labels[number] = label;
  }});
  window.__folios = folios;   // what is actually printed on the page
  window.__labels = labels;   // the page's number, including display pages that hide it
  window.__bodyStart = bodyStart;
}}

window.PagedConfig = {{
  auto: true,
  before: async () => {{
    await document.fonts.ready;
    await drawDiagrams();
  }},
  after: (flow) => {{
    numberPages();
    window.__pageMap = Object.fromEntries(
      Array.from(document.querySelectorAll('[id]')).map((node) => {{
        const page = node.closest('.pagedjs_page');
        return [node.id, page ? Number(page.getAttribute('data-page-number')) : null];
      }})
    );
    window.__pagedTotal = flow.total;
    window.__pagedDone = true;
  }}
}};

window.addEventListener('error', (event) => {{
  window.__pagedError = String((event.error && event.error.stack) || event.message);
}});
window.addEventListener('unhandledrejection', (event) => {{
  window.__pagedError = String((event.reason && event.reason.stack) || event.reason);
}});
"""


def render_print_html(markdown: str, headings: list, body_html: str, generated: str, figures: list) -> str:
    assets = chrome_pdf.ensure_assets()
    meta = book_meta(headings, generated)
    front_chunk, body_chunk = split_front_matter(body_html)
    body_start_line = next((item.line for item in headings if item.level == 1 and item.line > 1), 1)
    document = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{html.escape(meta.title)}</title>
<style>{print_stylesheet(meta, assets)}</style>
<script src="{(assets / 'mermaid.min.js').as_uri()}"></script>
<script>{render_script(meta, assets)}</script>
<script src="{(assets / 'paged.polyfill.js').as_uri()}"></script>
</head>
<body>
<div class="frontmatter">
{front_matter_html(meta, extract_section(front_chunk, "editorial-note"),
                   contents_html(headings, body_start_line), figures_html(figures))}
</div>
<div class="bookbody">
{structure_body(body_chunk)}
</div>
</body>
</html>
"""
    PRINT_HTML.write_text(document, encoding="utf-8")
    return document


def build_pdf(markdown: str, headings: list, body_html: str, generated: str, figures: list) -> dict:
    render_print_html(markdown, headings, body_html, generated, figures)
    pdf_bytes, collected = chrome_pdf.render_pdf(
        PRINT_HTML.as_uri(),
        {
            "printBackground": True,
            "preferCSSPageSize": True,
            "displayHeaderFooter": False,
            "generateTaggedPDF": True,
            "generateDocumentOutline": True,
        },
        collect=(
            "({pages: window.__pagedTotal, map: window.__pageMap, figures: window.__figureReport,"
            " folios: window.__folios, labels: window.__labels, bodyStart: window.__bodyStart})"
        ),
    )
    BOOK_PDF.write_bytes(pdf_bytes)
    result = dict(collected or {})
    result["generated"] = generated
    return result
