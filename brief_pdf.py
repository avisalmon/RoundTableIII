"""Typeset the short version as a stand-alone A4 booklet.

This is not the paperback. book_pdf.py builds a 6x9in KDP interior with mirrored
margins, a binding gutter, roman front matter and recto chapter openings, because
that file is uploaded to a printer. The short version is a handout: it is read on a
screen or run off an office printer, so it is set on A4 with symmetric margins, one
title page, and nothing that assumes a spine.

What it does share with the paperback is the renderer. Pagination still happens in
headless Chrome through Paged.js (Chrome implements no CSS margin boxes of its own),
and page furniture is still assigned from script after the pages exist, for the same
reason as in book_pdf.py: Paged.js applies counter-reset only to the page an element
starts on, so a folio sequence written in CSS alone comes out wrong.
"""
from __future__ import annotations

import html
import re
from pathlib import Path

import chrome_pdf


ROOT = Path(__file__).resolve().parent
PRINT_HTML = ROOT / "short-print.html"
BRIEF_PDF = ROOT / "short-version.pdf"

SITE_BASE = "https://avisalmon.github.io/RoundTableIII/"

# --- page geometry: A4, symmetric margins, no gutter -------------------------------
PAGE_WIDTH_IN = 8.27
PAGE_HEIGHT_IN = 11.69
MARGIN_SIDE_IN = 1.05
MARGIN_TOP_IN = 0.85
MARGIN_BOTTOM_IN = 0.85

TEXT_WIDTH_IN = PAGE_WIDTH_IN - 2 * MARGIN_SIDE_IN
TEXT_HEIGHT_IN = PAGE_HEIGHT_IN - MARGIN_TOP_IN - MARGIN_BOTTOM_IN
FIGURE_MAX_WIDTH_PX = round(TEXT_WIDTH_IN * 96)
FIGURE_MAX_HEIGHT_PX = round(5.6 * 96)
FIGURE_FULL_PAGE_HEIGHT_PX = round((TEXT_HEIGHT_IN - 0.5) * 96)

DIAGRAM_TYPE_PX = 15
FIGURE_MIN_SCALE = 0.62

TITLE = "AI and the STEM Educator"
# Interpolated as markup rather than escaped, so a title can carry an italicized phrase.
SUBTITLE = "A short report from six meetings on teaching STEM in the age of generative AI"
SERIES = "International STEM Skills Round Table Phase III"
AUTHORS = ["Avi Salmon"]
CONTACT = "avi.salmon@gmail.com"


def absolute_links(body_html: str) -> str:
    """Point every in-site link at the published site.

    A relative href is dead in a downloaded PDF, and the reader has no address bar to
    repair it with, so the whole address is written out the way the book prints them.
    """

    def rewrite(match: re.Match[str]) -> str:
        target = match.group(1)
        if re.match(r"^(https?:|mailto:|#)", target):
            return match.group(0)
        return f'href="{SITE_BASE}{target.lstrip("./")}"'

    return re.sub(r'href="([^"]+)"', rewrite, body_html)


def strip_leading_title(body_html: str) -> tuple[str, str]:
    """Split the document's own <h1> off the body; the title page carries it instead."""
    match = re.match(r'\s*<h1 id="([^"]*)">(.*?)</h1>', body_html, re.S)
    if not match:
        return "", body_html
    return match.group(2), body_html[match.end() :]


def structure_body(body_html: str) -> str:
    """Tag headings so the stylesheet can set them, and so script can read the runhead."""

    def heading(match: re.Match[str]) -> str:
        level, anchor, text = match.group(1), match.group(2), match.group(3)
        kind = {"2": "brief-section", "3": "brief-subsection", "4": "brief-minor"}[level]
        return f'<h{level} class="{kind}" id="{anchor}">{text}</h{level}>'

    return re.sub(r"<h([234]) id=\"([^\"]+)\">(.*?)</h\1>", heading, body_html, flags=re.S)


def title_page_html(standfirst: str, generated: str) -> str:
    authors = "<br>".join(html.escape(author) for author in AUTHORS)
    return f"""
<section class="titlepage">
  <p class="title-series">{html.escape(SERIES)}</p>
  <h1 class="title-main">{html.escape(TITLE)}</h1>
  <p class="title-subtitle">{SUBTITLE}</p>
  <div class="title-standfirst">{standfirst}</div>
  <p class="title-author">{authors}</p>
  <p class="title-footer">
    The full record of the meetings, the source materials and the companion pages are at
    {html.escape(SITE_BASE)}<br>
    Comments and corrections: {html.escape(CONTACT)}<br>
    Prepared on {html.escape(generated)}.
  </p>
</section>
"""


def stylesheet(assets: Path) -> str:
    font_dir = assets.as_uri()
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

@page {{
  size: {PAGE_WIDTH_IN}in {PAGE_HEIGHT_IN}in;
  margin: {MARGIN_TOP_IN}in {MARGIN_SIDE_IN}in {MARGIN_BOTTOM_IN}in {MARGIN_SIDE_IN}in;
  bleed: 0;
  @top-center {{
    content: var(--runhead, "");
    font: 400 8pt/1 'Inter', sans-serif; letter-spacing: 0.13em; text-transform: uppercase;
    color: #4a4a4a; margin-top: 0.3in;
  }}
  @bottom-center {{
    content: var(--folio, "");
    font: 400 9pt/1 'Inter', sans-serif; color: #4a4a4a; margin-bottom: 0.35in;
  }}
}}

/* Paged.js marks a split element with [data-align-last-split-element] so its last
   fragment stays justified; text-align-last inherits, which stretched the final line
   of every paragraph inside. This zero-specificity reset stops the inheritance
   without beating Paged.js's own rule on the elements that really are split. */
* {{ text-align-last: auto; }}
html {{ background: #fff; }}
body {{
  margin: 0; background: #fff; color: #14140f;
  font-family: 'EB Garamond', Georgia, serif;
  font-size: 11pt; line-height: 1.44;
  text-align: justify; hyphens: auto; -webkit-hyphens: auto;
  orphans: 3; widows: 3;
}}
p {{ margin: 0 0 0.58em; }}
a {{ color: #1f6b5b; text-decoration: none; }}
strong {{ font-weight: 600; }}
em {{ font-style: italic; }}
code {{ font-family: 'Inter', monospace; font-size: 0.9em; overflow-wrap: anywhere; }}

/* ---------- title page ---------- */
.titlepage {{
  break-after: page;
  min-height: {TEXT_HEIGHT_IN}in;
  padding-top: 1.1in;
  display: flex; flex-direction: column;
}}
.titlepage .title-author {{ margin-top: auto; }}
.titlepage p {{ text-align: left; }}
.title-series {{
  font-family: 'Inter', sans-serif; font-size: 8.5pt; font-weight: 600;
  letter-spacing: 0.16em; text-transform: uppercase; color: #b6532b;
}}
.title-main {{
  margin: 0.28in 0 0; font-size: 40pt; font-weight: 400; line-height: 1.0;
  text-align: left; letter-spacing: -0.01em;
}}
.title-subtitle {{
  margin: 0.16in 0 0; padding-bottom: 0.26in; border-bottom: 1pt solid #14140f;
  font-size: 13pt; font-style: italic; line-height: 1.3;
}}
.title-standfirst {{ margin-top: 0.34in; font-size: 11.5pt; }}
.title-standfirst p {{ margin-bottom: 0.7em; }}
.title-author {{
  margin-top: 0.7in; font-family: 'Inter', sans-serif; font-size: 10pt;
  font-weight: 600; letter-spacing: 0.13em; text-transform: uppercase;
}}
.title-footer {{
  margin-top: 0.3in; font-family: 'Inter', sans-serif; font-size: 8pt;
  line-height: 1.7; color: #4a4a4a; hyphens: none;
}}

/* ---------- headings ---------- */
/* Sections are about a page long, which is the worst possible length for a forced
   break: nearly every one would spill a few lines onto an otherwise empty page. They
   flow instead, and the rule above the heading does the work of announcing them. */
h2.brief-section {{
  break-after: avoid; break-inside: avoid;
  margin: 0.36in 0 0.2in; padding-top: 0.13in; border-top: 1.5pt solid #14140f;
  font-size: 18pt; font-weight: 400; line-height: 1.15; text-align: left;
}}
.briefbody > h2.brief-section:first-child {{ margin-top: 0; }}
h3.brief-subsection {{
  margin: 1.5em 0 0.4em; font-size: 12.5pt; font-weight: 600; line-height: 1.25;
  text-align: left; color: #b6532b; break-after: avoid; break-inside: avoid;
}}
h4.brief-minor {{
  margin: 1.2em 0 0.35em; font-family: 'Inter', sans-serif; font-size: 9.6pt;
  font-weight: 600; text-align: left; break-after: avoid;
}}

/* ---------- lists, tables, figures ---------- */
ul, ol {{ margin: 0.6em 0; padding-left: 1.4em; }}
li {{ margin-bottom: 0.3em; text-align: justify; }}
li > ul, li > ol {{ margin: 0.3em 0 0; }}

figure.figure {{ margin: 1.5em 0; padding: 0; text-align: center; break-inside: avoid; }}
figure.figure.full-page {{ break-before: page; break-after: page; margin: 0; padding-top: 0.2in; }}
figure.figure pre.mermaid {{
  margin: 0; padding: 0; border: 0; background: none; white-space: normal; text-align: center;
}}
figure.figure svg {{ display: block; margin: 0 auto; }}
figcaption {{
  margin-top: 0.7em; font-family: 'Inter', sans-serif; font-size: 8.5pt; line-height: 1.4;
  text-align: center; color: #4a4a4a; hyphens: none;
}}
/* A seven-row table of full sentences is taller than the space usually left on a
   page. Held together it jumps the break and strands half a page of white, so it is
   allowed to split between rows instead, carrying its header with it. */
figure.figure-table {{ text-align: left; break-inside: auto; }}
figure.figure-table table {{ margin-top: 0; }}
thead {{ display: table-header-group; }}
tr {{ break-inside: avoid; }}

table {{
  width: 100%; margin: 1.1em 0; border-collapse: collapse; break-inside: auto;
  font-family: 'Inter', sans-serif; font-size: 8.3pt; line-height: 1.36;
}}
th, td {{ text-align: left; }}
thead th {{
  border-top: 1pt solid #14140f; border-bottom: 0.5pt solid #14140f;
  padding: 0.5em 0.8em 0.45em 0; font-weight: 600; vertical-align: bottom;
}}
tbody td {{
  padding: 0.5em 0.8em 0.5em 0; vertical-align: top; hyphens: none;
  border-bottom: 0.25pt solid #b8b8ae;
}}
tbody tr:last-child td {{ border-bottom: 1pt solid #14140f; }}
th:last-child, td:last-child {{ padding-right: 0; }}
.align-center {{ text-align: center; }}
.align-right {{ text-align: right; }}

/* ---------- the pocket card ---------- */
/* Set light rather than as the dark gradient card the web pages use: this file is
   meant to survive an office laser printer without draining a toner cartridge. */
.steps-card {{
  margin: 1.5em 0; padding: 0.22in 0.26in 0.24in;
  border: 0.75pt solid #14140f; break-inside: avoid;
  font-family: 'Inter', sans-serif;
}}
.steps-card-head {{
  margin-bottom: 0.16in; padding-bottom: 0.08in; border-bottom: 0.5pt solid #b8b8ae;
  font-size: 8pt; font-weight: 600; letter-spacing: 0.13em; text-transform: uppercase;
  color: #b6532b;
}}
.steps-card-list {{
  margin: 0; padding: 0; list-style: none;
  display: grid; grid-template-rows: repeat(5, auto); grid-auto-flow: column;
  grid-template-columns: 1fr 1fr; column-gap: 0.3in; row-gap: 0.09in;
}}
.steps-card-list li {{
  display: flex; align-items: baseline; gap: 0.09in;
  margin: 0; font-size: 9pt; line-height: 1.25; text-align: left;
}}
.steps-card .step-number {{
  flex: none; width: 1.55em; font-size: 8pt; font-weight: 600; color: #b6532b;
}}
.steps-card .step-highlight {{ font-weight: 600; }}

pre {{
  white-space: pre-wrap; font-family: 'Inter', monospace; font-size: 8.5pt;
  background: none; border: 0; padding: 0;
}}
"""


def render_script() -> str:
    """Draw the diagrams to vector art, fit them to the text block, then paginate."""
    return f"""
mermaid.initialize({{
  startOnLoad: false,
  theme: 'base',
  securityLevel: 'loose',
  fontFamily: "Inter, sans-serif",
  themeVariables: {{
    background: '#ffffff', primaryColor: '#ffffff', secondaryColor: '#f4efe2',
    tertiaryColor: '#ffffff', primaryTextColor: '#14140f', secondaryTextColor: '#14140f',
    tertiaryTextColor: '#14140f', primaryBorderColor: '#14140f',
    secondaryBorderColor: '#14140f', tertiaryBorderColor: '#14140f',
    lineColor: '#14140f', textColor: '#14140f', mainBkg: '#ffffff', nodeBorder: '#14140f',
    clusterBkg: '#ffffff', clusterBorder: '#14140f', edgeLabelBackground: '#ffffff',
    titleColor: '#14140f', fontSize: '{DIAGRAM_TYPE_PX}px'
  }},
  flowchart: {{ useMaxWidth: true, htmlLabels: true, curve: 'linear',
                padding: 6, nodeSpacing: 30, rankSpacing: 42, diagramPadding: 4 }},
  mindmap: {{ useMaxWidth: true, padding: 8 }},
  timeline: {{ useMaxWidth: true, padding: 8 }}
}});

const TEXT_WIDTH = {FIGURE_MAX_WIDTH_PX};
const INLINE_HEIGHT = {FIGURE_MAX_HEIGHT_PX};
const PAGE_HEIGHT = {FIGURE_FULL_PAGE_HEIGHT_PX};
const MIN_SCALE = {FIGURE_MIN_SCALE};

async function drawDiagrams() {{
  const report = [];
  const hosts = Array.from(document.querySelectorAll('figure.figure pre.mermaid'));
  for (let index = 0; index < hosts.length; index += 1) {{
    const host = hosts[index];
    const {{ svg }} = await mermaid.render('brief-diagram-' + index, host.textContent);
    host.innerHTML = svg;
    const node = host.querySelector('svg');
    const box = node.viewBox && node.viewBox.baseVal;
    const width = box && box.width ? box.width : node.getBoundingClientRect().width;
    const height = box && box.height ? box.height : node.getBoundingClientRect().height;

    let scale = Math.min(TEXT_WIDTH / width, INLINE_HEIGHT / height, 1);
    let placement = 'inline';
    if (scale < MIN_SCALE) {{
      // A4 is wide enough that this is rare, but a tall diagram still buys back type
      // size from the extra height of a page to itself.
      const fullPage = Math.min(TEXT_WIDTH / width, PAGE_HEIGHT / height, 1);
      if (fullPage > scale) {{
        scale = fullPage;
        placement = 'full page';
        host.closest('figure').classList.add('full-page');
      }}
    }}

    node.removeAttribute('style');
    node.setAttribute('width', (width * scale).toFixed(1));
    node.setAttribute('height', (height * scale).toFixed(1));
    node.style.width = (width * scale).toFixed(1) + 'px';
    node.style.height = (height * scale).toFixed(1) + 'px';
    report.push({{ figure: index + 1, width: Math.round(width), height: Math.round(height),
                   scale: Number(scale.toFixed(3)), placement: placement }});
  }}
  window.__figureReport = report;
}}

// Paged.js applies counter-reset only to the page an element starts on, so folios are
// assigned here instead, once the pages exist, and read back through custom properties.
function numberPages() {{
  let section = '';
  document.querySelectorAll('.pagedjs_page').forEach((page) => {{
    const number = Number(page.getAttribute('data-page-number'));
    const content = page.querySelector('.pagedjs_page_content');
    const blank = page.classList.contains('pagedjs_blank_page') ||
                  !content || !content.textContent.trim();
    const title = content && content.querySelector('.titlepage');
    // Sections flow, so a page can hold the tail of one and the head of the next.
    // The head names the section in force where the page begins, which is the part
    // the reader is actually in; only the first page of all has nothing to carry
    // forward, and it borrows the heading it opens with.
    const openers = content ? content.querySelectorAll('h2.brief-section') : [];
    const runhead = section || (openers.length ? openers[0].textContent.trim() : '');
    if (openers.length) section = openers[openers.length - 1].textContent.trim();

    const furniture = !(blank || title);
    page.style.setProperty('--folio', JSON.stringify(furniture ? String(number) : ''));
    page.style.setProperty('--runhead', JSON.stringify(furniture ? runhead : ''));
  }});
}}

window.PagedConfig = {{
  auto: true,
  before: async () => {{
    await document.fonts.ready;
    await drawDiagrams();
  }},
  after: (flow) => {{
    numberPages();
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


def split_standfirst(body_html: str, count: int = 2) -> tuple[str, str]:
    """Move the opening paragraphs onto the title page, where they introduce the piece."""
    paragraphs = list(re.finditer(r"<p>.*?</p>", body_html, re.S))
    if len(paragraphs) < count:
        return "", body_html
    end = paragraphs[count - 1].end()
    return body_html[:end].strip(), body_html[end:]


def render_print_html(body_html: str, generated: str) -> str:
    assets = chrome_pdf.ensure_assets()
    _, body = strip_leading_title(absolute_links(body_html))
    standfirst, body = split_standfirst(body)
    document = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{html.escape(TITLE)}</title>
<style>{stylesheet(assets)}</style>
<script src="{(assets / 'mermaid.min.js').as_uri()}"></script>
<script>{render_script()}</script>
<script src="{(assets / 'paged.polyfill.js').as_uri()}"></script>
</head>
<body>
{title_page_html(standfirst, generated)}
<div class="briefbody">
{structure_body(body)}
</div>
</body>
</html>
"""
    PRINT_HTML.write_text(document, encoding="utf-8")
    return document


def build_pdf(body_html: str, generated: str) -> dict:
    render_print_html(body_html, generated)
    pdf_bytes, collected = chrome_pdf.render_pdf(
        PRINT_HTML.as_uri(),
        {
            "printBackground": True,
            "preferCSSPageSize": True,
            "displayHeaderFooter": False,
            "generateTaggedPDF": True,
            "generateDocumentOutline": True,
        },
        collect="({pages: window.__pagedTotal, figures: window.__figureReport})",
    )
    BRIEF_PDF.write_bytes(pdf_bytes)
    result = dict(collected or {})
    result["generated"] = generated
    return result
