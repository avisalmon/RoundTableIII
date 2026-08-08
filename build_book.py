from __future__ import annotations

import html
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parent
MANUSCRIPT = ROOT / "book" / "manuscript.md"
INDEX_HTML = ROOT / "index.html"
BOOK_HTML = ROOT / "book.html"
BOOK_PDF = ROOT / "book.pdf"


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


def inline_markdown(text: str) -> str:
    escaped = html.escape(text)
    escaped = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", convert_link, escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    return escaped.replace("  \n", "<br>")


def convert_link(match: re.Match[str]) -> str:
    label = match.group(1)
    target = html.unescape(match.group(2))
    if target.startswith("../materials/"):
        target = target.replace("../materials/", "materials/", 1)
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
        match = re.match(r"^(#{1,3})\s+(.+?)\s*$", line)
        if match:
            title = match.group(2).strip()
            headings.append(Heading(len(match.group(1)), title, slugify(title, used), line_number))
    return headings


def markdown_to_html(markdown: str, headings: list[Heading]) -> str:
    anchor_by_line = {heading.line: heading.anchor for heading in headings}
    output: list[str] = []
    paragraph: list[str] = []
    list_stack: list[str] = []
    in_fence = False
    fence_lang = ""
    fence_lines: list[str] = []

    def close_paragraph() -> None:
        if paragraph:
            output.append(f"<p>{inline_markdown(' '.join(paragraph))}</p>")
            paragraph.clear()

    def close_lists() -> None:
        while list_stack:
            output.append(f"</{list_stack.pop()}>")

    for line_number, raw_line in enumerate(markdown.splitlines(), start=1):
        line = raw_line.rstrip()

        if line.startswith("<!--") and line.endswith("-->"):
            continue

        if line.startswith("```"):
            close_paragraph()
            close_lists()
            if not in_fence:
                in_fence = True
                fence_lang = line.strip("`").strip()
                fence_lines = []
            else:
                code = html.escape("\n".join(fence_lines))
                lang_class = f" language-{html.escape(fence_lang)}" if fence_lang else ""
                if fence_lang == "mermaid":
                    output.append(f'<pre class="mermaid">{code}</pre>')
                else:
                    output.append(f'<pre><code class="{lang_class.strip()}">{code}</code></pre>')
                in_fence = False
                fence_lang = ""
                fence_lines = []
            continue

        if in_fence:
            fence_lines.append(line)
            continue

        heading = re.match(r"^(#{1,3})\s+(.+?)\s*$", line)
        if heading:
            close_paragraph()
            close_lists()
            level = len(heading.group(1))
            title = heading.group(2).strip()
            anchor = anchor_by_line[line_number]
            output.append(f'<h{level} id="{anchor}">{inline_markdown(title)}</h{level}>')
            continue

        if not line.strip():
            close_paragraph()
            close_lists()
            continue

        bullet = re.match(r"^[-*]\s+(.+)$", line)
        numbered = re.match(r"^\d+\.\s+(.+)$", line)
        if bullet or numbered:
            close_paragraph()
            tag = "ul" if bullet else "ol"
            if not list_stack or list_stack[-1] != tag:
                close_lists()
                output.append(f"<{tag}>")
                list_stack.append(tag)
            item_text = (bullet or numbered).group(1)
            output.append(f"<li>{inline_markdown(item_text)}</li>")
            continue

        close_lists()
        paragraph.append(line)

    close_paragraph()
    close_lists()
    return "\n".join(output)


def title_from_headings(headings: list[Heading]) -> str:
    return headings[0].title if headings else "The Teacher Above AI"


def build_toc(headings: list[Heading], max_level: int = 2) -> str:
    links = []
    for heading in headings:
        if heading.level <= max_level:
            links.append(
                f'<a class="toc-level-{heading.level}" href="book.html#{heading.anchor}">{html.escape(heading.title)}</a>'
            )
    return "\n".join(links)


def build_summaries(headings: list[Heading]) -> str:
    cards = []
    for heading in headings:
        if heading.level == 2 and (heading.title.startswith("Chapter ") or heading.title.startswith("Appendix ")):
            cards.append(
                f'<a class="summary-card" href="book.html#{heading.anchor}"><span>{html.escape(heading.title)}</span></a>'
            )
    return "\n".join(cards)


def site_nav() -> str:
        return """
<header class="site-nav" id="top">
    <a class="brand" href="index.html">International STEM Skills Round Table Phase III</a>
    <nav aria-label="Main site navigation">
        <a href="index.html">Home</a>
        <a href="book.html">Book</a>
        <a href="book.pdf">PDF</a>
        <a href="index.html#main-skills">Main Skills</a>
        <a href="index.html#training-proposal">Training Proposal</a>
        <a href="index.html#model-reference">Model Reference</a>
        <a href="index.html#summaries">Summaries</a>
        <a href="materials/">Materials</a>
    </nav>
</header>
"""


def chrome_path() -> str | None:
    candidates = [
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return shutil.which("chrome") or shutil.which("msedge")


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
.site-shell { max-width: 1180px; margin: 0 auto; padding: 18px 24px 64px; }
.disclaimer {
    margin: 18px 0 22px;
    padding: 14px 18px;
    border: 1px solid var(--accent-2);
    background: #fff4e6;
    color: #54311f;
    font-family: Verdana, sans-serif;
    font-size: 0.92rem;
}
.hero {
  min-height: 74vh;
  display: grid;
  grid-template-columns: minmax(0, 1.25fr) minmax(280px, 0.75fr);
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
.placeholder-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 14px; }
.placeholder-card { min-height: 140px; padding: 16px; background: #fffaf0; border: 1px dashed var(--accent); }
.placeholder-card h3 { margin: 0 0 8px; font-size: 1.1rem; color: var(--accent-2); }
.placeholder-card p { margin: 0; color: var(--muted); }
.book-layout { display: grid; grid-template-columns: 280px minmax(0, 1fr); gap: 36px; max-width: 1320px; margin: 0 auto; padding: 24px; }
.reader-nav { position: sticky; top: 0; align-self: start; height: 100vh; overflow: auto; border-right: 1px solid var(--line); padding: 16px 18px 16px 0; font-family: Verdana, sans-serif; font-size: 0.88rem; }
.reader-nav a { display: block; text-decoration: none; padding: 4px 0; }
.reader-nav .toc-level-1 { margin-top: 10px; }
.book-content { max-width: 820px; background: rgba(255, 253, 246, 0.92); }
.book-content h1, .book-content h2, .book-content h3 { line-height: 1.15; scroll-margin-top: 24px; }
.book-content h1 { font-size: 3.2rem; margin-top: 28px; }
.book-content h2 { font-size: 2rem; margin-top: 42px; padding-top: 18px; border-top: 1px solid var(--line); }
.book-content h3 { font-size: 1.25rem; margin-top: 28px; color: var(--accent-2); }
.book-content p, .book-content li { font-size: 1.05rem; }
pre { white-space: pre-wrap; overflow: auto; background: #f0eadc; border: 1px solid var(--line); padding: 14px; }
.top-link { font-family: Verdana, sans-serif; font-size: 0.85rem; }
@media (max-width: 820px) {
    .site-nav { align-items: flex-start; flex-direction: column; }
    .site-nav nav { justify-content: flex-start; }
  .hero, .book-layout { grid-template-columns: 1fr; }
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


def render_book(markdown: str, headings: list[Heading]) -> str:
    title = title_from_headings(headings)
    body = markdown_to_html(markdown, headings)
    toc = build_toc(headings)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>{stylesheet()}</style>
  <script type="module">import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs'; mermaid.initialize({{ startOnLoad: true }});</script>
</head>
<body>
    {site_nav()}
  <div class="book-layout">
    <nav class="reader-nav">
      <a class="top-link" href="index.html">Gateway</a>
      <a class="top-link" href="book.pdf">PDF</a>
      {toc}
    </nav>
    <main class="book-content">
      {body}
    </main>
  </div>
</body>
</html>
"""


def render_index(headings: list[Heading]) -> str:
    title = title_from_headings(headings)
    toc = build_toc(headings)
    summaries = build_summaries(headings)
    generated = date.today().isoformat()
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)} - Gateway</title>
  <style>{stylesheet()}</style>
</head>
<body>
    {site_nav()}
  <main class="site-shell">
        <div class="disclaimer">
            This website is a personal summary by Avi Salmon of the Round Table in which he participated. It is a draft generated with AI and reviewed by Avi Salmon, and it is not a formal document for publication.
        </div>
    <section class="hero">
      <div>
        <div class="eyebrow">International STEM Skills Round Table Phase III</div>
        <h1>{html.escape(title)}</h1>
        <p class="subtitle">This web page serves as a gateway to: Read the full book, download the PDF, review chapters and appendices, and open the source material library. Please send any comment for improvements, edits and changes to <a href="mailto:avi.salmon@gmail.com">avi.salmon@gmail.com</a>.</p>
        <div class="actions">
          <a class="button primary" href="book.html">Read the book</a>
          <a class="button" href="book.pdf">Download PDF</a>
          <a class="button" href="book/manuscript.md">Open source manuscript</a>
          <a class="button" href="materials/">Source materials</a>
        </div>
      </div>
      <aside class="note-panel">
        <p><strong>Golden source:</strong> book/manuscript.md</p>
        <p><strong>Generated:</strong> {generated}</p>
        <p><strong>Rule:</strong> edit and comment on the manuscript only. Regenerate this website and PDF from that file.</p>
      </aside>
    </section>
        <section class="section" id="overview">
            <h2>Project Summary</h2>
            <div class="overview">
                <p>This work organizes the International STEM Skills Round Table Phase III material into a coherent book about the teacher and lecturer profile in the age of generative AI. The manuscript draws from meeting programs, presentations, discussion documents, background sources, and participant voices, then turns them into a structured argument about STEM education, competencies, assessment, professional development, learning environments, and the human role above AI.</p>
                <p>The main understanding is that AI does not reduce the importance of teachers. It changes the evidence of learning and raises the level of professional judgment required from educators. The central direction is a human-first STEM learning ecosystem: teachers design learning, students keep responsibility for thinking, AI supports but does not govern, and institutions build the conditions that make responsible practice possible.</p>
            </div>
        </section>
        <section class="section" id="site-sections">
            <h2>Site Sections in Progress</h2>
            <div class="placeholder-grid">
                <article class="placeholder-card" id="main-skills">
                    <h3>Main Skills</h3>
                    <p>Placeholder for the core STEM and AI-era skills framework.</p>
                </article>
                <article class="placeholder-card" id="training-proposal">
                    <h3>Training Proposal</h3>
                    <p>Placeholder for the teacher training program and implementation plan.</p>
                </article>
                <article class="placeholder-card" id="model-reference">
                    <h3>Model Reference</h3>
                    <p>Placeholder for the short model, diagrams, and reusable educator profile reference.</p>
                </article>
                <article class="placeholder-card" id="summaries">
                    <h3>Summaries</h3>
                    <p>Placeholder for short summaries, meeting notes, and reader-facing extracts.</p>
                </article>
            </div>
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


def write_outputs() -> None:
    markdown = read_manuscript()
    headings = extract_headings(markdown)
    BOOK_HTML.write_text(render_book(markdown, headings), encoding="utf-8")
    INDEX_HTML.write_text(render_index(headings), encoding="utf-8")


def build_pdf() -> None:
    browser = chrome_path()
    if browser is None:
        raise RuntimeError("Chrome or Edge was not found. HTML outputs were generated, but PDF cannot be rendered.")
    subprocess.run(
        [
            browser,
            "--headless=new",
            "--disable-gpu",
            "--no-pdf-header-footer",
            f"--print-to-pdf={BOOK_PDF}",
            BOOK_HTML.as_uri(),
        ],
        check=True,
    )


def main() -> int:
    write_outputs()
    build_pdf()
    print(f"Generated {INDEX_HTML.name}, {BOOK_HTML.name}, and {BOOK_PDF.name} from {MANUSCRIPT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())