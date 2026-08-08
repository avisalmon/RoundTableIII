"""Verify that the generated interior meets Amazon KDP's paperback requirements.

Every rule here comes from KDP's "Set Trim Size, Bleed, and Margins" and "Print
Options" help pages. The build fails loudly rather than producing a file that KDP
would reject at upload time.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import book_pdf

try:  # pymupdf drives the inspection; without it the build still produces the PDF
    import fitz
except ImportError:  # pragma: no cover - optional dependency
    fitz = None


POINTS_PER_INCH = 72
TRIM_WIDTH_PT = book_pdf.TRIM_WIDTH_IN * POINTS_PER_INCH
TRIM_HEIGHT_PT = book_pdf.TRIM_HEIGHT_IN * POINTS_PER_INCH
SAFE_EDGE_PT = book_pdf.SAFE_EDGE_IN * POINTS_PER_INCH
MIN_TYPE_SIZE_PT = 7.0
MIN_PAGES, MAX_PAGES = 24, 828
FORBIDDEN_TEXT = ("flowchart TD", "flowchart LR", "| --- |", "```")


@dataclass
class Report:
    pages: int = 0
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    @property
    def summary(self) -> str:
        lines = [f"KDP interior check: {self.pages} pages"]
        lines.extend(f"  - {note}" for note in self.notes)
        if self.problems:
            lines.append("  FAILED:")
            lines.extend(f"  ! {problem}" for problem in self.problems)
        else:
            lines.append("  All KDP interior requirements met.")
        return "\n".join(lines)


def rewrite_outline(document, headings: list, page_map: dict) -> int:
    """Replace Chrome's outline with clean titles taken from the manuscript."""
    outline = []
    for heading in headings:
        page = page_map.get(heading.anchor)
        if not page:
            continue
        outline.append([min(heading.level, 3), book_pdf.smart(heading.title), int(page)])
    if outline:
        document.set_toc(outline)
    return len(outline)


def printed_folio(page) -> str:
    """The folio sits alone in the bottom margin, below the text block."""
    band = fitz.Rect(0, page.rect.height - book_pdf.MARGIN_BOTTOM_IN * POINTS_PER_INCH, page.rect.width, page.rect.height)
    return (page.get_textbox(band) or "").strip()


def check_folios(document, folios: dict) -> tuple[list[str], int]:
    problems, checked = [], 0
    for index, page in enumerate(document):
        expected = folios.get(str(index + 1), folios.get(index + 1))
        printed = printed_folio(page)
        if not printed:
            continue  # display pages and blanks deliberately carry no folio
        checked += 1
        if expected is not None and printed != expected:
            problems.append(f"page {index + 1} prints folio {printed!r} but should print {expected!r}")
    return problems[:5], checked


def check_contents(document, folios: dict) -> tuple[list[str], int]:
    """Compare each contents entry's printed number with its link destination."""
    problems, checked = [], 0
    for index, page in enumerate(document):
        for link in page.get_links():
            # Chrome writes internal links as named destinations, which pymupdf
            # resolves to a page index for us.
            if link.get("kind") not in (fitz.LINK_GOTO, fitz.LINK_NAMED) or link.get("page", -1) < 0:
                continue
            shown = page.get_textbox(link["from"]).split()
            if not shown:
                continue
            trailing = shown[-1].strip()
            if not re.fullmatch(r"[0-9ivxl]+", trailing):
                continue  # a wrapped first line carries no number
            checked += 1
            expected = folios.get(str(link["page"] + 1), folios.get(link["page"] + 1))
            if expected is not None and trailing != expected:
                problems.append(
                    f"page {index + 1}: entry points at page {expected!r} but prints {trailing!r}"
                )
    return problems[:5], checked


def check(pdf_path: Path, render_result: dict, headings: list | None = None) -> Report:
    report = Report()
    if fitz is None:
        report.notes.append("pymupdf is not installed; skipped the KDP compliance checks")
        return report

    document = fitz.open(pdf_path)

    # A printed interior needs an even leaf count; close the book on a blank page.
    if document.page_count % 2:
        document.new_page(width=TRIM_WIDTH_PT, height=TRIM_HEIGHT_PT)
        report.notes.append("added a closing blank page to reach an even page count")
    if headings:
        added = rewrite_outline(document, headings, render_result.get("map") or {})
        if added:
            report.notes.append(f"{added} PDF bookmarks written from the manuscript headings")
        meta = book_pdf.book_meta(headings, render_result.get("generated", ""))
        document.set_metadata(
            {
                "title": f"{meta.title}: {meta.subtitle}" if meta.subtitle else meta.title,
                "author": book_pdf.AUTHOR,
                "subject": meta.series,
                "keywords": "STEM education, artificial intelligence, teaching, professional development",
            }
        )
    document.save(pdf_path, incremental=True, encryption=fitz.PDF_ENCRYPT_KEEP)
    report.pages = document.page_count

    if not MIN_PAGES <= document.page_count <= MAX_PAGES:
        report.problems.append(
            f"page count {document.page_count} is outside KDP's {MIN_PAGES}-{MAX_PAGES} range"
        )

    gutter = book_pdf.required_gutter(document.page_count)
    if book_pdf.MARGIN_INSIDE_IN < gutter:
        report.problems.append(
            f"inside margin {book_pdf.MARGIN_INSIDE_IN}in is below KDP's {gutter}in minimum "
            f"for {document.page_count} pages"
        )
    else:
        report.notes.append(
            f"inside margin {book_pdf.MARGIN_INSIDE_IN}in clears the {gutter}in minimum for this page count"
        )

    wrong_size = [
        index + 1
        for index, page in enumerate(document)
        if abs(page.rect.width - TRIM_WIDTH_PT) > 0.5 or abs(page.rect.height - TRIM_HEIGHT_PT) > 0.5
    ]
    if wrong_size:
        report.problems.append(f"{len(wrong_size)} page(s) are not {TRIM_WIDTH_PT}x{TRIM_HEIGHT_PT}pt, e.g. page {wrong_size[0]}")
    else:
        report.notes.append(f"every page is exactly {book_pdf.TRIM_WIDTH_IN}x{book_pdf.TRIM_HEIGHT_IN}in with no bleed")

    outside_safe: list[str] = []
    small_type: list[str] = []
    coloured: list[str] = []
    leaked_source: list[str] = []
    blank_pages = 0

    for index, page in enumerate(document):
        number = index + 1
        safe = fitz.Rect(
            SAFE_EDGE_PT, SAFE_EDGE_PT, page.rect.width - SAFE_EDGE_PT, page.rect.height - SAFE_EDGE_PT
        )
        text = page.get_text()
        if not text.strip():
            blank_pages += 1
        for marker in FORBIDDEN_TEXT:
            if marker in text:
                leaked_source.append(f"page {number} still shows raw source ({marker!r})")
                break
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                for span in line["spans"]:
                    if not span["text"].strip():
                        continue
                    box = fitz.Rect(span["bbox"])
                    if not safe.contains(box) and len(outside_safe) < 5:
                        outside_safe.append(f"page {number}: text at {tuple(round(v) for v in box)}")
                    if span["size"] < MIN_TYPE_SIZE_PT - 0.05 and len(small_type) < 5:
                        small_type.append(f"page {number}: {span['size']:.1f}pt type")
                    if span["color"] not in (0, 0x000000) and len(coloured) < 5:
                        red, green, blue = (span["color"] >> 16) & 255, (span["color"] >> 8) & 255, span["color"] & 255
                        if not red == green == blue:
                            coloured.append(f"page {number}: coloured text #{span['color']:06x}")

    if outside_safe:
        report.problems.append("content inside the 0.25in trim safety margin: " + "; ".join(outside_safe))
    else:
        report.notes.append("all text sits inside the 0.25in trim safety margin")
    if small_type:
        report.problems.append("type below KDP's 7pt minimum: " + "; ".join(small_type))
    if coloured:
        report.problems.append("colour text in a black-and-white interior: " + "; ".join(coloured))
    else:
        report.notes.append("no colour text; the interior prints correctly in black ink")
    if leaked_source:
        report.problems.append("; ".join(leaked_source[:5]))

    fonts = {name for index in range(document.page_count) for _, _, _, name, _, _ in document.get_page_fonts(index)}
    unembedded = [
        name
        for index in range(document.page_count)
        for xref, ext, _, name, _, _ in document.get_page_fonts(index)
        if ext == "n/a" or xref == 0
    ]
    if unembedded:
        report.problems.append(f"fonts not embedded: {sorted(set(unembedded))}")
    else:
        report.notes.append(f"{len(fonts)} font subsets embedded")

    folio_problems, folio_checked = check_folios(document, render_result.get("folios") or {})
    report.problems.extend(folio_problems)
    if folio_checked and not folio_problems:
        report.notes.append(f"{folio_checked} printed folios run i-x then restart at 1 for the body")

    toc_problems, toc_checked = check_contents(document, render_result.get("labels") or {})
    report.problems.extend(toc_problems)
    if toc_checked and not toc_problems:
        report.notes.append(f"all {toc_checked} contents and figure-list numbers match the page they point to")

    figures = render_result.get("figures") or []
    if figures:
        smallest = min(item["scale"] for item in figures)
        report.notes.append(f"{len(figures)} diagrams drawn as vector art (smallest scale {smallest:.2f})")
    report.notes.append(f"{blank_pages} intentionally blank page(s)")
    document.close()
    return report
