from __future__ import annotations

import html
import re
import subprocess
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import book_pdf
import brief_pdf
import cover_pdf
import kdp_report


ROOT = Path(__file__).resolve().parent
MANUSCRIPT = ROOT / "book" / "manuscript.md"
MATERIALS_DIR = ROOT / "materials"
INDEX_HTML = ROOT / "index.html"

# Round Table materials are published alongside the site so a citation can be opened.
# The steering-team summaries are withheld: internal working documents in Hebrew that
# record the group's own assessment of its meetings. They are named, never distributed.
WITHHELD_MATERIAL_PREFIXES = ("steering-",)
BOOK_HTML = ROOT / "book.html"
BOOK_PDF = ROOT / "book.pdf"
COVER_PDF = ROOT / "cover.pdf"
BRIEF_PDF = ROOT / "short-version.pdf"


@dataclass(frozen=True)
class Page:
    """A standalone page generated from its own markdown source.

    `pdf` and `markdown` name the downloadable forms of the same page. `markdown` is
    published as a copy at the site root rather than linked at its source path, so that
    the three forms of the short version share one name and one folder.
    """

    source: str
    output: str
    label: str
    blurb: str
    pdf: str | None = None
    markdown: str | None = None


# The second way into the argument. Not a companion to a chapter and not an extract:
# a stand-alone report of Phase III, and the only generated page that also ships as a PDF.
SHORT_VERSION = Page(
    source="book/pages/short_version.md",
    output="short.html",
    label="Short Version",
    blurb="The whole of Phase III in a short report: the six meetings and who was in "
    "them, the finding that survives scrutiny, the seven findings and what each costs, "
    "the twelve principles, the lesson cycle, the case against, and what was left open.",
    pdf="short-version.pdf",
    markdown="short-version.md",
)

COMPANION_PAGES = [
    Page(
        "book/pages/main_skills.md",
        "skills.html",
        "Main Skills",
        "The five competencies the Round Table converged on, what AI changed about each, "
        "and why AI literacy is a layer across all five rather than a sixth item.",
    ),
    Page(
        "book/pages/lesson_model.md",
        "model.html",
        "Lesson Model",
        "The Human-First AI Learning Cycle as a lesson skeleton: ten steps, a worked example, "
        "the three ways it fails, and how to assess the path rather than the artifact.",
    ),
    Page(
        "book/pages/training_program.md",
        "training.html",
        "Training Proposal",
        "A six-day teacher training program in three sections \u2014 AI knowledge, pedagogy, "
        "and leading change \u2014 with a deliverable and an evaluation for every day.",
    ),
    Page(
        "book/references.md",
        "references.html",
        "Materials & Sources",
        "Every document behind the book: the external frameworks, the research the Round "
        "Table was reading, and all thirty-five project materials, with a note on where "
        "each one is used and whether it can be opened.",
    ),
]

ALL_PAGES = [SHORT_VERSION, *COMPANION_PAGES]


@dataclass
class Heading:
    level: int
    title: str
    anchor: str
    line: int


def slugify(text: str, used: set[str]) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "section"
    base = slug
    counter = 2
    while slug in used:
        slug = f"{base}-{counter}"
        counter += 1
    used.add(slug)
    return slug


def smart_typography(text: str) -> str:
    """Book-quality punctuation: curly quotes, real apostrophes, en dashes."""
    text = re.sub(r'(^|[\s(\[])"', "\\1\u201c", text)
    text = text.replace('"', "\u201d")
    text = re.sub(r"(?<=[A-Za-z])'(?=[A-Za-z]|\s|$)", "\u2019", text)
    text = text.replace("...", "\u2026")
    return re.sub(r"(?<=\S) - (?=\S)", " \u2013 ", text)


def inline_markdown(text: str) -> str:
    escaped = html.escape(smart_typography(text))
    escaped = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", convert_link, escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", escaped)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    return escaped.replace("  \n", "<br>")


def material_is_published(filename: str) -> bool:
    """Steering-team summaries are named but never distributed. Everything else is."""
    return not filename.startswith(WITHHELD_MATERIAL_PREFIXES)


def convert_link(match: re.Match[str]) -> str:
    label = match.group(1)
    target = html.unescape(match.group(2))
    if target.startswith("../materials/"):
        filename = target.rsplit("/", 1)[-1]
        if not material_is_published(filename):
            return f'<span class="source-ref">{label}</span>'
        target = f"{MATERIALS_DIR.name}/{filename}"
    elif target.startswith("../book/"):
        target = target.replace("../book/", "book/", 1)
    return f'<a href="{html.escape(target, quote=True)}">{label}</a>'


def read_manuscript() -> str:
    if not MANUSCRIPT.exists():
        raise FileNotFoundError(f"Missing source manuscript: {MANUSCRIPT}")
    return MANUSCRIPT.read_text(encoding="utf-8")


def extract_headings(markdown: str) -> list[Heading]:
    headings: list[Heading] = []
    used: set[str] = set()
    in_fence = False
    for line_number, line in enumerate(markdown.splitlines(), start=1):
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = re.match(r"^(#{1,4})\s+(.+?)\s*$", line)
        if match:
            title = match.group(2).strip()
            headings.append(Heading(len(match.group(1)), title, slugify(title, used), line_number))
    return headings


TABLE_ROW = re.compile(r"^\s*\|(.+)\|\s*$")
TABLE_DIVIDER = re.compile(r"^\s*\|[\s:|-]+\|\s*$")
FIGURE_BLOCK = re.compile(
    # Each alternative is pinned to its own closing tag. A bare .*? backtracks past it
    # and swallows every block up to the next captioned one.
    r'(?P<art><pre class="mermaid">(?:(?!</pre>).)*</pre>|<table>(?:(?!</table>).)*</table>)'
    r'\s*<p>(?P<caption>Figure\s+(?P<number>\d+)\.\s*.*?)</p>',
    re.S,
)


def split_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def column_alignments(divider: str) -> list[str]:
    alignments = []
    for cell in split_table_row(divider):
        left, right = cell.startswith(":"), cell.endswith(":")
        alignments.append("center" if left and right else "right" if right else "left")
    return alignments


def render_table(lines: list[str]) -> str:
    alignments = column_alignments(lines[1])
    header = split_table_row(lines[0])

    def row(cells: list[str], tag: str) -> str:
        rendered = []
        for index, cell in enumerate(cells):
            align = alignments[index] if index < len(alignments) else "left"
            rendered.append(f'<{tag} class="align-{align}">{inline_markdown(cell)}</{tag}>')
        return f"<tr>{''.join(rendered)}</tr>"

    body = "".join(row(split_table_row(line), "td") for line in lines[2:])
    return f"<table><thead>{row(header, 'th')}</thead><tbody>{body}</tbody></table>"


def group_figures(document: str) -> str:
    """Bind each mermaid diagram to the caption that follows it."""

    def replace(match: re.Match[str]) -> str:
        art = match.group("art")
        kind = "diagram" if art.startswith("<pre") else "table"
        # The manuscript writes captions as "Figure 1. Title: ...". The label reads as
        # a template leftover once it is set as a real caption.
        caption = re.sub(r"^(Figure\s+\d+\.)\s*Title:\s*", r"\1 ", match.group("caption"))
        return (
            f'<figure class="figure figure-{kind}" id="figure-{match.group("number")}">'
            f"{art}<figcaption>{caption}</figcaption>"
            "</figure>"
        )

    return FIGURE_BLOCK.sub(replace, document)


def collect_figures(document: str) -> list[tuple[str, str]]:
    """Return (anchor, caption) for every figure, in reading order."""
    pattern = re.compile(r'<figure class="figure[^"]*" id="(figure-\d+)">.*?<figcaption>(.*?)</figcaption>', re.S)
    return [(match.group(1), match.group(2)) for match in pattern.finditer(document)]


def render_steps_card(lines: list[str]) -> str:
    """Fenced `steps-card` block: first line is the card title, the rest are steps.
    A step prefixed with * is the highlighted one."""
    entries = [line.strip() for line in lines if line.strip()]
    title, steps = entries[0], entries[1:]
    items = []
    for number, step in enumerate(steps, start=1):
        highlighted = step.startswith("*")
        label = html.escape(step.lstrip("*").strip())
        css_class = ' class="step-highlight"' if highlighted else ""
        items.append(f'<li{css_class}><span class="step-number">{number}</span><span>{label}</span></li>')
    return (
        '<div class="steps-card">'
        f'<div class="steps-card-head">{html.escape(title)}</div>'
        f'<ol class="steps-card-list">{"".join(items)}</ol>'
        "</div>"
    )


def markdown_to_html(markdown: str, headings: list[Heading]) -> str:
    anchor_by_line = {heading.line: heading.anchor for heading in headings}
    lines = markdown.splitlines()
    output: list[str] = []
    paragraph: list[str] = []
    list_stack: list[dict] = []
    in_fence = False
    fence_lang = ""
    fence_lines: list[str] = []

    def close_paragraph() -> None:
        if paragraph:
            output.append(f"<p>{inline_markdown(' '.join(paragraph))}</p>")
            paragraph.clear()

    def close_lists(indent: int = -1) -> None:
        while list_stack and list_stack[-1]["indent"] > indent:
            level = list_stack.pop()
            if level["item_open"]:
                output.append("</li>")
            output.append(f"</{level['tag']}>")

    index = 0
    while index < len(lines):
        raw_line = lines[index]
        line_number = index + 1
        index += 1
        line = raw_line.rstrip()

        if line.startswith("<!--") and line.endswith("-->"):
            continue

        if line.lstrip().startswith("```"):
            close_paragraph()
            close_lists()
            if not in_fence:
                in_fence = True
                fence_lang = line.strip().strip("`").strip()
                fence_lines = []
            else:
                code = html.escape("\n".join(fence_lines))
                if fence_lang == "mermaid":
                    output.append(f'<pre class="mermaid">{code}</pre>')
                elif fence_lang == "steps-card":
                    output.append(render_steps_card(fence_lines))
                else:
                    lang_class = f"language-{html.escape(fence_lang)}" if fence_lang else ""
                    output.append(f'<pre><code class="{lang_class}">{code}</code></pre>')
                in_fence = False
                fence_lang = ""
                fence_lines = []
            continue

        if in_fence:
            fence_lines.append(line)
            continue

        heading = re.match(r"^(#{1,4})\s+(.+?)\s*$", line)
        if heading:
            close_paragraph()
            close_lists()
            level = len(heading.group(1))
            anchor = anchor_by_line[line_number]
            output.append(f'<h{level} id="{anchor}">{inline_markdown(heading.group(2).strip())}</h{level}>')
            continue

        if TABLE_ROW.match(line) and index < len(lines) and TABLE_DIVIDER.match(lines[index]):
            close_paragraph()
            close_lists()
            table_lines = [line, lines[index].rstrip()]
            index += 1
            while index < len(lines) and TABLE_ROW.match(lines[index]):
                table_lines.append(lines[index].rstrip())
                index += 1
            output.append(render_table(table_lines))
            continue

        if not line.strip():
            close_paragraph()
            close_lists()
            continue

        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        bullet = re.match(r"^[-*]\s+(.+)$", stripped)
        numbered = re.match(r"^\d+\.\s+(.+)$", stripped)
        if bullet or numbered:
            close_paragraph()
            tag = "ul" if bullet else "ol"
            close_lists(indent)
            if not list_stack or list_stack[-1]["indent"] < indent:
                output.append(f"<{tag}>")
                list_stack.append({"tag": tag, "indent": indent, "item_open": False})
            elif list_stack[-1]["tag"] != tag:
                close_lists(indent - 1)
                output.append(f"<{tag}>")
                list_stack.append({"tag": tag, "indent": indent, "item_open": False})
            level = list_stack[-1]
            if level["item_open"]:
                output.append("</li>")
            output.append(f"<li>{inline_markdown((bullet or numbered).group(1))}")
            level["item_open"] = True
            continue

        close_lists()
        paragraph.append(stripped)

    close_paragraph()
    close_lists()
    return group_figures("\n".join(output))


def title_from_headings(headings: list[Heading]) -> str:
    return headings[0].title if headings else "The Teacher Above AI"


def build_toc(headings: list[Heading], max_level: int = 2) -> str:
    links = []
    for heading in headings:
        if heading.level <= max_level:
            links.append(
                f'<a class="toc-level-{heading.level}" href="book.html#{heading.anchor}">'
                f"{html.escape(smart_typography(heading.title))}</a>"
            )
    return "\n".join(links)


def build_summaries(headings: list[Heading]) -> str:
    cards = []
    for heading in headings:
        if heading.level == 2 and (heading.title.startswith("Chapter ") or heading.title.startswith("Appendix ")):
            cards.append(
                f'<a class="summary-card" href="book.html#{heading.anchor}">'
                f"<span>{html.escape(smart_typography(heading.title))}</span></a>"
            )
    return "\n".join(cards)


def site_nav() -> str:
        return """
<header class="site-nav" id="top">
    <a class="brand" href="index.html">International STEM Skills Round Table Phase III</a>
    <nav aria-label="Main site navigation">
        <a href="index.html">Home</a>
        <a href="book.html">Book</a>
        <a href="short.html">Short Version</a>
        <details class="nav-menu">
            <summary>Download</summary>
            <div class="nav-menu-panel">
                <a href="short-version.pdf">Short Version (PDF)</a>
                <a href="short-version.md">Short Version (Markdown)</a>
                <a href="book.pdf">KDP Interior (PDF)</a>
                <a href="cover.pdf">KDP Cover (PDF)</a>
            </div>
        </details>
        <a href="skills.html">Main Skills</a>
        <a href="model.html">Lesson Model</a>
        <a href="training.html">Training Proposal</a>
        <a href="references.html">Materials &amp; Sources</a>
    </nav>
</header>
"""


def stylesheet() -> str:
    return """
:root {
  --ink: #17201a;
  --muted: #5b655d;
  --paper: #fffdf6;
  --panel: #f4efe2;
  --line: #d9ceb7;
  --accent: #1f6b5b;
  --accent-2: #b6532b;
  --shadow: rgba(44, 35, 20, 0.13);
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: radial-gradient(circle at top left, #f2e1c8 0, transparent 34rem), var(--paper);
  color: var(--ink);
  font-family: Georgia, 'Times New Roman', serif;
  line-height: 1.65;
}
a { color: var(--accent); }
.source-ref { color: var(--muted); font-style: italic; }
.site-nav {
    position: sticky;
    top: 0;
    z-index: 20;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 24px;
    padding: 12px 24px;
    border-bottom: 1px solid var(--line);
    background: rgba(255, 253, 246, 0.96);
    backdrop-filter: blur(12px);
    font-family: Verdana, sans-serif;
}
.brand { font-weight: 700; color: var(--ink); text-decoration: none; white-space: nowrap; }
.site-nav nav { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px 16px; }
.site-nav nav a { color: var(--ink); font-size: 0.86rem; text-decoration: none; }
.site-nav nav a:hover { color: var(--accent); }
.nav-menu { position: relative; font-family: Verdana, sans-serif; }
.nav-menu summary { cursor: pointer; list-style: none; color: var(--ink); font-size: 0.86rem; }
.nav-menu summary::-webkit-details-marker { display: none; }
.nav-menu summary::after { content: "▾"; margin-left: 5px; font-size: 0.72rem; color: var(--muted); }
.nav-menu-panel {
    position: absolute;
    right: 0;
    top: calc(100% + 8px);
    min-width: 132px;
    padding: 8px;
    border: 1px solid var(--line);
    background: #fffdf6;
    box-shadow: 0 12px 28px var(--shadow);
}
.nav-menu-panel a { display: block; padding: 6px 8px; white-space: nowrap; }
.site-shell { max-width: 1180px; margin: 0 auto; padding: 18px 24px 64px; }
.hero {
  min-height: 74vh;
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 48px;
  align-items: center;
  border-bottom: 1px solid var(--line);
}
.eyebrow { color: var(--accent-2); font: 700 0.8rem/1.2 Verdana, sans-serif; letter-spacing: 0; text-transform: uppercase; }
h1 { font-size: clamp(2.6rem, 6vw, 5.8rem); line-height: 0.95; margin: 14px 0 20px; font-weight: 500; }
.subtitle { font-size: 1.25rem; color: var(--muted); max-width: 48rem; }
.actions { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 28px; }
.button {
  display: inline-flex;
  align-items: center;
  min-height: 44px;
  padding: 10px 16px;
  border: 1px solid var(--ink);
  color: var(--ink);
  text-decoration: none;
  font: 700 0.9rem/1.2 Verdana, sans-serif;
  background: #fffaf0;
}
.button.primary { background: var(--ink); color: #fffdf6; }
.note-panel {
  background: var(--panel);
  border: 1px solid var(--line);
  padding: 22px;
  box-shadow: 0 16px 40px var(--shadow);
}
.section { padding: 42px 0; border-bottom: 1px solid var(--line); }
.section h2 { font-size: 2rem; line-height: 1.1; margin: 0 0 18px; }
.overview { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 24px; }
.overview p { margin-top: 0; }
.toc-grid { columns: 2 280px; column-gap: 36px; }
.toc-grid a { display: block; break-inside: avoid; padding: 5px 0; text-decoration: none; }
.toc-level-1 { font-weight: 700; color: var(--accent-2); margin-top: 12px; }
.toc-level-2 { padding-left: 12px; }
.summary-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }
.summary-card { min-height: 86px; display: flex; align-items: end; padding: 14px; background: #fffaf0; border: 1px solid var(--line); text-decoration: none; color: var(--ink); }
.summary-card:hover { border-color: var(--accent); }
.card-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 16px; }
.link-card {
  display: block;
  padding: 20px;
  background: #fffaf0;
  border: 1px solid var(--line);
  text-decoration: none;
  color: var(--ink);
}
.link-card:hover { border-color: var(--accent); box-shadow: 0 10px 24px var(--shadow); }
.link-card h3 { margin: 0 0 10px; font-size: 1.2rem; color: var(--accent-2); }
.link-card p { margin: 0; color: var(--muted); font-size: 0.98rem; }
.page-layout { display: grid; grid-template-columns: 260px minmax(0, 1fr); gap: 40px; max-width: 1180px; margin: 0 auto; padding: 24px; }
.page-content { max-width: 780px; }
.page-content h1 { font-size: clamp(2.4rem, 5vw, 3.6rem); line-height: 1.02; margin: 8px 0 22px; }
.page-content h2 { font-size: 1.75rem; margin-top: 46px; padding-top: 20px; border-top: 1px solid var(--line); line-height: 1.15; }
.page-content h3 { font-size: 1.15rem; margin-top: 30px; color: var(--accent-2); }
.page-content p, .page-content li { font-size: 1.05rem; }
.page-content h1 + p { font-size: 1.22rem; color: var(--muted); }
.page-content table { width: 100%; margin: 24px 0; border-collapse: collapse; font-family: Verdana, sans-serif; font-size: 0.86rem; }
.page-content thead th { border-bottom: 2px solid var(--ink); text-align: left; }
.page-content th, .page-content td { padding: 8px 12px 8px 0; border-bottom: 1px solid var(--line); vertical-align: top; }
.page-content tbody tr:last-child td { border-bottom: 2px solid var(--ink); }
.steps-card {
  width: min(100%, 520px);
  aspect-ratio: 1.586;
  margin: 30px 0;
  padding: 18px 22px 20px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  border-radius: 12px;
  color: #fff8e6;
  font-family: Verdana, sans-serif;
  background:
    radial-gradient(circle at 82% 14%, rgba(235, 185, 82, 0.5), transparent 38%),
    radial-gradient(circle at 12% 84%, rgba(111, 182, 164, 0.42), transparent 36%),
    linear-gradient(130deg, #18382f 0%, #10251f 48%, #241b13 100%);
  box-shadow: 0 14px 34px var(--shadow);
  print-color-adjust: exact;
  -webkit-print-color-adjust: exact;
}
.steps-card-head { color: #efc978; font: 700 0.72rem/1.3 Verdana, sans-serif; letter-spacing: 0.11em; text-transform: uppercase; }
.steps-card-list {
  flex: 1;
  margin: 0;
  padding: 0;
  list-style: none;
  display: grid;
  grid-template-rows: repeat(5, 1fr);
  grid-auto-flow: column;
  grid-template-columns: 1fr 1fr;
  column-gap: 20px;
}
.steps-card-list li { display: flex; align-items: center; gap: 9px; font-size: 0.78rem; line-height: 1.15; }
.steps-card .step-number {
  flex: none;
  width: 19px;
  height: 19px;
  border-radius: 50%;
  border: 1px solid rgba(239, 201, 120, 0.55);
  color: #efc978;
  font-size: 0.62rem;
  display: flex;
  align-items: center;
  justify-content: center;
}
.steps-card .step-highlight { color: #f8e7bd; font-weight: 700; }
.steps-card .step-highlight .step-number { background: #efc978; border-color: #efc978; color: #10251f; }
@media (max-width: 520px) {
  .steps-card { aspect-ratio: auto; }
  .steps-card-list { grid-template-columns: 1fr; grid-template-rows: none; grid-auto-flow: row; row-gap: 7px; }
}
.book-layout { display: grid; grid-template-columns: 280px minmax(0, 1fr); gap: 36px; max-width: 1320px; margin: 0 auto; padding: 24px; }
.reader-nav { position: sticky; top: 0; align-self: start; height: 100vh; overflow: auto; border-right: 1px solid var(--line); padding: 16px 18px 16px 0; font-family: Verdana, sans-serif; font-size: 0.88rem; }
.reader-nav a { display: block; text-decoration: none; padding: 4px 0; }
.reader-nav .toc-level-1 { margin-top: 10px; }
.book-content { max-width: 820px; background: rgba(255, 253, 246, 0.92); }
.book-cover-gate {
    min-height: calc(100vh - 74px);
    display: grid;
    grid-template-columns: minmax(250px, 0.62fr) minmax(280px, 0.9fr);
    gap: 38px;
    align-items: center;
    padding: 18px 0 46px;
    border-bottom: 1px solid var(--line);
}
.cover-card {
    aspect-ratio: 2 / 3;
    max-width: 390px;
    padding: 34px 30px 28px;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    color: #fff8e6;
    background:
        radial-gradient(circle at 78% 18%, rgba(235, 185, 82, 0.62), transparent 34%),
        radial-gradient(circle at 18% 70%, rgba(111, 182, 164, 0.5), transparent 32%),
        linear-gradient(130deg, #18382f 0%, #10251f 48%, #241b13 100%);
    box-shadow: 0 18px 44px var(--shadow);
}
.cover-card .series { color: #efc978; font: 700 0.72rem/1.35 Verdana, sans-serif; letter-spacing: 0.12em; text-transform: uppercase; }
.cover-card h2 { margin: 1.6rem 0 0.8rem; font-size: clamp(2.6rem, 7vw, 4.8rem); line-height: 0.9; color: #fff8e6; }
.cover-card .cover-subtitle { color: #f8e7bd; font-size: 1.22rem; line-height: 1.12; }
.cover-card .cover-authors { color: #efc978; font: 700 0.75rem/1.35 Verdana, sans-serif; letter-spacing: 0.08em; text-transform: uppercase; }
.book-entry h2 { margin: 0 0 14px; font-size: 2.2rem; line-height: 1.05; }
.book-entry p { color: var(--muted); font-size: 1.08rem; margin: 0 0 18px; }
.book-entry .actions { margin-top: 22px; }
.book-start { padding-top: 28px; }
.book-content h1, .book-content h2, .book-content h3, .book-content h4 { line-height: 1.15; scroll-margin-top: 24px; }
.book-content h1 { font-size: 3.2rem; margin-top: 28px; }
.book-content h2 { font-size: 2rem; margin-top: 42px; padding-top: 18px; border-top: 1px solid var(--line); }
.book-content h3 { font-size: 1.25rem; margin-top: 28px; color: var(--accent-2); }
.book-content h4 { font-size: 1.05rem; margin-top: 22px; font-family: Verdana, sans-serif; color: var(--ink); }
.book-content p, .book-content li { font-size: 1.05rem; }
pre { white-space: pre-wrap; overflow: auto; background: #f0eadc; border: 1px solid var(--line); padding: 14px; }
pre.mermaid { background: none; border: 0; text-align: center; }
.book-content table { width: 100%; margin: 22px 0; border-collapse: collapse; font-family: Verdana, sans-serif; font-size: 0.86rem; }
.book-content thead th { border-bottom: 2px solid var(--ink); text-align: left; }
.book-content th, .book-content td { padding: 8px 12px 8px 0; border-bottom: 1px solid var(--line); vertical-align: top; }
.book-content tbody tr:last-child td { border-bottom: 2px solid var(--ink); }
.align-center { text-align: center; }
.align-right { text-align: right; }
.figure { margin: 26px 0; padding: 0; }
.figure figcaption { margin-top: 10px; font-family: Verdana, sans-serif; font-size: 0.82rem; color: var(--muted); text-align: center; }
.top-link { font-family: Verdana, sans-serif; font-size: 0.85rem; }
@media (max-width: 820px) {
    .site-nav { align-items: flex-start; flex-direction: column; }
    .site-nav nav { justify-content: flex-start; }
    .nav-menu-panel { left: 0; right: auto; }
    .hero, .book-layout, .book-cover-gate, .page-layout { grid-template-columns: 1fr; }
  .reader-nav { position: static; height: auto; border-right: 0; border-bottom: 1px solid var(--line); }
}
@media print {
  body { background: #fff; }
    .site-nav, .reader-nav, .top-link { display: none; }
  .book-layout { display: block; padding: 0; }
  .book-content { max-width: none; }
  .book-content h1 { page-break-before: always; }
  .book-content h1:first-child { page-break-before: auto; }
  .book-content h2 { page-break-before: always; border-top: 0; }
  a { color: #17201a; text-decoration: none; }
}
"""


def render_book(body: str, headings: list[Heading]) -> str:
        title = title_from_headings(headings)
        toc = build_toc(headings)
        authors = "<br>".join(html.escape(author.upper()) for author in cover_pdf.AUTHORS)
        cover_intro = f"""
            <section class="book-cover-gate" id="cover">
                <div class="cover-card" aria-label="Book cover">
                    <div>
                        <div class="series">International STEM Skills Round Table Phase III</div>
                        <h2>The Teacher<br>Above AI</h2>
                        <div class="cover-subtitle">STEM Education, Human Judgment, and the New Learning Ecosystem</div>
                    </div>
                    <div class="cover-authors">{authors}</div>
                </div>
                <div class="book-entry">
                    <h2>Enter the Book</h2>
                    <p>Start with the cover, then continue into the full web edition. The paperback files are available as separate KDP uploads: cover and book interior.</p>
                    <div class="actions">
                        <a class="button primary" href="#book-start">Start reading</a>
                        <a class="button" href="cover.pdf">KDP Cover PDF</a>
                        <a class="button" href="book.pdf">KDP Interior PDF</a>
                    </div>
                </div>
            </section>
        """
        return f"""<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
        <meta name="robots" content="noindex,nofollow">
    <title>{html.escape(title)}</title>
    <style>{stylesheet()}</style>
    <script type="module">import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs'; mermaid.initialize({{ startOnLoad: true }});</script>
</head>
<body>
        {site_nav()}
    <div class="book-layout">
        <nav class="reader-nav">
            <a class="top-link" href="index.html">Gateway</a>
            <a class="top-link" href="#cover">Cover</a>
            <a class="top-link" href="#book-start">Book</a>
            <a class="top-link" href="cover.pdf">KDP Cover PDF</a>
            <a class="top-link" href="book.pdf">KDP Interior PDF</a>
            {toc}
        </nav>
        <main class="book-content">
            {cover_intro}
            <div class="book-start" id="book-start">
                {body}
            </div>
        </main>
    </div>
</body>
</html>
"""


def render_index(headings: list[Heading]) -> str:
    title = title_from_headings(headings)
    toc = build_toc(headings)
    summaries = build_summaries(headings)
    cards = "\n".join(
        f'<a class="link-card" href="{page.output}"><h3>{html.escape(page.label)}</h3>'
        f"<p>{html.escape(page.blurb)}</p></a>"
        for page in COMPANION_PAGES
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="robots" content="noindex,nofollow">
  <title>{html.escape(title)} - Gateway</title>
  <style>{stylesheet()}</style>
</head>
<body>
    {site_nav()}
  <main class="site-shell">
    <section class="hero">
      <div>
        <div class="eyebrow">International STEM Skills Round Table Phase III</div>
        <h1>{html.escape(title)}</h1>
        <p class="subtitle">This web page serves as a gateway to: Read the full book, download the PDF, review chapters and appendices, and open the source material library. Please send any comment for improvements, edits and changes to <a href="mailto:avi.salmon@gmail.com">avi.salmon@gmail.com</a>.</p>
        <div class="actions">
          <a class="button primary" href="book.html">Read the book</a>
          <a class="button" href="short.html">Read the short version</a>
          <a class="button" href="book.pdf">Download KDP interior PDF</a>
          <a class="button" href="references.html">Materials &amp; sources</a>
        </div>
      </div>
    </section>
        <section class="section" id="overview">
            <h2>Project Summary</h2>
            <div class="overview">
                <p>This work organizes the International STEM Skills Round Table Phase III material into a coherent book about the teacher and lecturer profile in the age of generative AI. The manuscript draws from meeting programs, presentations, discussion documents, background sources, and participant voices, then turns them into a structured argument about STEM education, competencies, assessment, professional development, learning environments, and the human role above AI.</p>
                <p>The main understanding is that AI does not reduce the importance of teachers. It changes the evidence of learning and raises the level of professional judgment required from educators. The central direction is a human-first STEM learning ecosystem: teachers design learning, students keep responsibility for thinking, AI supports but does not govern, and institutions build the conditions that make responsible practice possible.</p>
            </div>
        </section>
        <section class="section" id="short-version">
            <h2>The Short Version</h2>
            <div class="overview">
                <p>A stand-alone report on Phase III, written to be read on its own in about twenty minutes. It sets out the six meetings and the people in them, then states the finding that survives scrutiny: producing a correct-looking answer no longer demonstrates learning, so educators need new ways to see whether a student understands.</p>
                <p>It carries the seven findings and what each one costs, the twelve principles sorted by whether they need attention, money, or a change in the shape of an institution, the ten-step lesson cycle, the strongest objections to all of it, and the four questions the six meetings left open. It is also published as an A4 booklet for printing and circulation.</p>
            </div>
            <div class="actions">
                <a class="button primary" href="short.html">Read the short version</a>
                <a class="button" href="short-version.pdf">Download the PDF</a>
                <a class="button" href="short-version.md">Download the Markdown</a>
            </div>
        </section>
        <section class="section" id="site-sections">
            <h2>Companion Pages</h2>
            <div class="card-grid">{cards}</div>
        </section>
        <section class="section">
      <h2>Read by Chapter</h2>
      <div class="summary-grid">{summaries}</div>
    </section>
    <section class="section">
      <h2>Full Table of Contents</h2>
      <div class="toc-grid">{toc}</div>
    </section>
  </main>
</body>
</html>
"""


def render_standalone_page(page: Page) -> tuple[str, str]:
    """Render one markdown page. Returns (html document, body html).

    The body is handed back because the short version is also typeset as a PDF, and
    re-parsing the same markdown a second time would let the two drift apart.
    """
    markdown = (ROOT / page.source).read_text(encoding="utf-8")
    if PUBLISHED_MARKER in markdown:
        markdown = markdown.replace(PUBLISHED_MARKER, published_resource_index())
    headings = extract_headings(markdown)
    body = markdown_to_html(markdown, headings)
    title = title_from_headings(headings)
    section_links = "\n".join(
        f'<a class="toc-level-{heading.level}" href="#{heading.anchor}">'
        f"{html.escape(smart_typography(heading.title))}</a>"
        for heading in headings
        if heading.level == 2
    )
    # Only the pages that actually carry a diagram pay for the renderer.
    mermaid = (
        "<script type=\"module\">import mermaid from "
        "'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs'; "
        "mermaid.initialize({ startOnLoad: true });</script>"
        if 'class="mermaid"' in body
        else ""
    )
    downloads = ""
    if page.pdf:
        downloads += f'<a class="top-link" href="{page.pdf}">Download as PDF</a>'
    if page.markdown:
        downloads += f'<a class="top-link" href="{page.markdown}">Download as Markdown</a>'
    document = f"""<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="robots" content="noindex,nofollow">
    <title>{html.escape(title)}</title>
    <style>{stylesheet()}</style>
    {mermaid}
</head>
<body>
    {site_nav()}
    <div class="page-layout">
        <nav class="reader-nav">
            <a class="top-link" href="index.html">Gateway</a>
            <a class="top-link" href="book.html">Full book</a>
            {downloads}
            {section_links}
        </nav>
        <main class="page-content">
            {body}
        </main>
    </div>
</body>
</html>
"""
    return document, body


def write_outputs(markdown: str, headings: list[Heading]) -> tuple[str, str]:
    """Write every HTML output. Returns the book body and the short version body."""
    body = markdown_to_html(markdown, headings)
    BOOK_HTML.write_text(render_book(body, headings), encoding="utf-8")
    INDEX_HTML.write_text(render_index(headings), encoding="utf-8")
    bodies = {}
    for page in ALL_PAGES:
        # Copied before the pages are rendered, so the index of published files that
        # references.html generates can see it and report its size.
        if page.markdown:
            (ROOT / page.markdown).write_text(
                (ROOT / page.source).read_text(encoding="utf-8"), encoding="utf-8"
            )
    for page in ALL_PAGES:
        document, page_body = render_standalone_page(page)
        (ROOT / page.output).write_text(document, encoding="utf-8")
        bodies[page.output] = page_body
    return body, bodies[SHORT_VERSION.output]


# references.md carries this marker where the index of published files belongs. The list
# is generated from the repository rather than maintained by hand, because a hand-kept
# list of what is downloadable is the first thing to go stale.
PUBLISHED_MARKER = "<!-- generated: published-files -->"

# Written by this build, so they are published whether or not they exist yet on a first run.
SITE_OUTPUTS = (
    "index.html", "book.html", "short.html", "skills.html", "model.html",
    "training.html", "references.html",
    "book.pdf", "cover.pdf", "short-version.pdf", "short-version.md",
)

READING_PAGES = {
    "index.html": "The gateway page: what the project is, and every way into it.",
    "book.html": "The full book in the browser, with its table of contents and figures.",
    "short.html": "The short version in the browser: the whole of Phase III in about twenty minutes.",
    "skills.html": "The five competencies, one page each, and what AI changed about them.",
    "model.html": "The Human-First AI Learning Cycle written out as a lesson.",
    "training.html": "The six-day teacher training proposal, with a deliverable for each day.",
    "references.html": "This page.",
}

DOWNLOADS = {
    "short-version.pdf": "The short version as an A4 booklet, for printing and circulation.",
    "short-version.md": "The short version as plain markdown, for reuse, translation or quoting.",
    "book.pdf": "The print-ready paperback interior, 6 x 9 in, as uploaded to KDP.",
    "cover.pdf": "The paperback wrap cover: back, spine and front on one sheet.",
}

TEXT_SOURCES = {
    "book/manuscript.md": "The manuscript every page of the book is generated from.",
    "book/references.md": "The source text of this page.",
    "book/pages/short_version.md": "The source text of the short version.",
    "book/pages/main_skills.md": "The source text of the competencies page.",
    "book/pages/lesson_model.md": "The source text of the lesson model page.",
    "book/pages/training_program.md": "The source text of the training proposal.",
}

BUILD_FILES = {
    "build_book.py": "The build: parses the manuscript, writes the site, checks the links.",
    "book_pdf.py": "The paperback design: page geometry, front matter, print stylesheet.",
    "brief_pdf.py": "The short version's A4 booklet design.",
    "cover_pdf.py": "The wrap-cover design and the spine arithmetic.",
    "chrome_pdf.py": "Headless Chrome over the DevTools protocol, and the asset cache.",
    "kdp_report.py": "The KDP compliance checks the build refuses to ship without.",
    "README.md": "How to rebuild all of the above.",
    "LICENSE": "The terms this material is published under.",
    ".gitignore": "What is deliberately not published, including the steering-team summaries.",
    "robots.txt": "The crawler instructions for this site.",
}

MATERIAL_TITLE_OVERRIDES = {
    "phase-1-report.pdf": "International Round Table Phase I report",
    "phase-2-report.pdf": "International Round Table Phase II report",
}


def published_files() -> list[str]:
    """Every path this site actually serves.

    Tracked files, plus the outputs and sources this build writes, which are published on
    the next commit even when they are new. Untracked files in general are deliberately
    excluded: scratch left in the working tree is not published and must not be listed.
    """
    result = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    listed = {line.strip() for line in result.stdout.splitlines() if line.strip()}
    listed.update(SITE_OUTPUTS)
    listed.update(name for name in TEXT_SOURCES if (ROOT / name).exists())
    listed.update(name for name in BUILD_FILES if (ROOT / name).exists())
    return sorted(listed)


def file_size(relative: str) -> str:
    path = ROOT / relative
    if not path.exists():
        return ""
    kilobytes = path.stat().st_size / 1024
    return f"{kilobytes / 1024:.1f} MB" if kilobytes >= 1024 else f"{kilobytes:.0f} KB"


def material_titles() -> dict[str, str]:
    """Reuse the titles the page already gives each material, so the index agrees with it."""
    text = (ROOT / "book" / "references.md").read_text(encoding="utf-8")
    found: dict[str, str] = {}
    for label, filename in re.findall(r"\[([^\]]+)\]\(\.\./materials/([A-Za-z0-9._-]+)\)", text):
        # A file cited more than once picks up its fullest title rather than its first.
        if len(label) > len(found.get(filename, "")):
            found[filename] = label
    found.update(MATERIAL_TITLE_OVERRIDES)
    return found


def published_resource_index() -> str:
    """Render the list of every published file as markdown, grouped by what it is for."""
    files = published_files()
    titles = material_titles()

    def entry(target: str, label: str, note: str = "") -> str:
        size = file_size(target.replace("../", ""))
        suffix = f" ({size})" if size else ""
        return f"- [{label}]({target}){suffix}.{' ' + note if note else ''}"

    def described(group: dict[str, str], present: list[str]) -> list[str]:
        return [entry(name, name, group[name]) for name in group if name in present]

    materials = [name for name in files if name.startswith("materials/")]
    lines: list[str] = []

    lines.append("### Pages")
    lines.append("")
    lines.extend(described(READING_PAGES, files))
    lines.append("")
    lines.append("### Downloads")
    lines.append("")
    lines.extend(described(DOWNLOADS, files))
    lines.append("")
    lines.append("### Source Text")
    lines.append("")
    lines.append(
        "Every page on this site is generated from one of these files. They are published "
        "so that the text can be read, quoted or corrected without going through the HTML."
    )
    lines.append("")
    lines.extend(
        entry(f"../{name}", name.split("/")[-1], TEXT_SOURCES[name])
        for name in TEXT_SOURCES
        if name in files
    )
    lines.append("")
    lines.append("### Round Table Materials")
    lines.append("")
    lines.append(
        f"All {len(materials)} published documents, in one list. Each is described above under "
        "the claim it supports; here they are simply the files, with their sizes."
    )
    lines.append("")
    for path in materials:
        filename = path.split("/")[-1]
        title = titles.get(filename, filename)
        lines.append(entry(f"../materials/{filename}", title, f"`{filename}`"))
    lines.append("")
    lines.append("### The Build")
    lines.append("")
    lines.append(
        "The site is a set of Python scripts and a manuscript. Nothing here is needed to read "
        "the book, and all of it is published so the result can be reproduced or checked."
    )
    lines.append("")
    lines.extend(described(BUILD_FILES, files))

    unlisted = sorted(
        name
        for name in files
        if name not in READING_PAGES
        and name not in DOWNLOADS
        and name not in TEXT_SOURCES
        and name not in BUILD_FILES
        and not name.startswith("materials/")
    )
    if unlisted:
        lines.append("")
        lines.append("### Also Published")
        lines.append("")
        lines.extend(entry(name, name) for name in unlisted)
    return "\n".join(lines)


def check_site_links() -> list[str]:
    """Every link the site writes must resolve, on disk and to a real anchor.

    The site is read as files rather than served, so a wrong relative path fails silently
    in a browser and not at all in the build. This is the check that would have caught it.
    """
    problems: list[str] = []
    pages = [INDEX_HTML, BOOK_HTML] + [ROOT / page.output for page in ALL_PAGES]
    anchors: dict[str, set[str]] = {}
    for page in pages:
        anchors[page.name] = set(re.findall(r'id="([^"]+)"', page.read_text(encoding="utf-8")))

    for page in pages:
        for href in re.findall(r'href="([^"]+)"', page.read_text(encoding="utf-8")):
            if href.startswith(("http://", "https://", "mailto:")):
                continue
            target, _, anchor = href.partition("#")
            if target and not (ROOT / target).exists():
                problems.append(f"{page.name}: {href} does not exist")
                continue
            known = anchors.get(target or page.name)
            if anchor and known is not None and anchor not in known:
                problems.append(f"{page.name}: {href} points at no anchor")
    return problems


def check_materials() -> list[str]:
    """Every published citation must resolve, and no withheld file may be tracked.

    Getting this wrong is not a broken link, it is a disclosure, so the build stops
    rather than shipping a site that publishes a document the project chose to hold.
    """
    problems: list[str] = []
    cited = set()
    for source in (MANUSCRIPT, ROOT / "book" / "references.md"):
        cited.update(
            re.findall(r"\.\./materials/([A-Za-z0-9._-]+)", source.read_text(encoding="utf-8"))
        )

    for filename in sorted(cited):
        if not (MATERIALS_DIR / filename).exists():
            problems.append(f"cited but missing from materials/: {filename}")

    tracked = subprocess.run(
        ["git", "ls-files", "materials/"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    ).stdout.split()
    for path in tracked:
        name = path.rsplit("/", 1)[-1]
        if not material_is_published(name):
            problems.append(f"withheld material is tracked by git: {name}")

    published = sorted(f.name for f in MATERIALS_DIR.glob("*") if material_is_published(f.name))
    withheld = sorted(f.name for f in MATERIALS_DIR.glob("*") if not material_is_published(f.name))
    print(
        f"Materials: {len(published)} published, {len(withheld)} withheld "
        f"({', '.join(w.split('.')[0] for w in withheld) or 'none'})"
    )
    return problems


def main() -> int:
    markdown = read_manuscript()
    headings = extract_headings(markdown)

    material_problems = check_materials()
    if material_problems:
        for problem in material_problems:
            print(f"  - {problem}")
        print("Materials check failed; nothing was written.")
        return 1

    generated = date.today().isoformat()
    body, short_body = write_outputs(markdown, headings)
    page_names = ", ".join(page.output for page in ALL_PAGES)
    print(f"Generated {INDEX_HTML.name}, {BOOK_HTML.name} and {page_names}")

    brief = brief_pdf.build_pdf(body_html=short_body, generated=generated)
    print(f"Generated {BRIEF_PDF.name}: {brief.get('pages')} pages on A4")

    result = book_pdf.build_pdf(
        markdown=markdown,
        headings=headings,
        body_html=body,
        generated=generated,
        figures=collect_figures(body),
    )
    report = kdp_report.check(BOOK_PDF, result, headings)
    print(report.summary)
    if not report.ok:
        return 1

    page_count = report.pages or int(result["pages"])
    cover = cover_pdf.build_cover(page_count=page_count)
    print(
        f"Generated {COVER_PDF.name}: {cover.full_width:.3f}x{cover.full_height:.3f}in, "
        f"spine {cover.spine_width:.3f}in for {page_count} pages"
    )

    link_problems = check_site_links()
    if link_problems:
        for problem in link_problems:
            print(f"  - {problem}")
        print(f"Link check failed: {len(link_problems)} broken links.")
        return 1
    print("Links: every internal link and anchor resolves")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())