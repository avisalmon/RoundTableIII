# RoundTableIII

This repository contains the working manuscript and generated reading site for the International STEM Skills Round Table Phase III personal summary.

Golden source: `book/manuscript.md`. The short version has its own source,
`report/phase3_report.md`, because it is the Phase III summary report rather than an
extract: it is structured as the steering committee asked for it in August 2026, and is
written by hand rather than generated from the manuscript.

That source is authored for Word, with front matter, a contents marker and one H1 per
numbered section. `build_book.py` adapts it for the web through `report_page_markdown`,
which drops the markers and demotes every heading one level.

Generated outputs:

- `index.html` - website gateway.
- `book.html` - full web reader.
- `book.pdf` - print-ready paperback interior for Amazon KDP.
- `cover.pdf` - full-wrap paperback cover for Amazon KDP.
- `phase3-report.docx` - the report as an editable Word document, built by `report_docx.py`.
- `short.html`, `short-version.pdf` and `short-version.md` - the same report on the web, as
  an A4 booklet, and as plain markdown. All are generated from the one source, and all are
  offered from the site's Download menu.

`references.html` ends with a generated index of every file the site publishes, built from
`git ls-files` so it cannot drift from what is actually there. The build fails if any internal
link or anchor on any generated page does not resolve.

Regenerate the Word report and then the website and PDF with:

```powershell
python report_docx.py
python build_book.py
```

The order matters: the site links `phase3-report.docx`, and the build's link check fails
if it is not on disk.

## Requirements

- Python 3.11 or later. Only the standard library is needed to build the site; `pymupdf` is
  optional and enables the KDP compliance report, the PDF bookmarks, and the closing
  blank page (`pip install pymupdf`). `report_docx.py` additionally needs `python-docx`.
- Google Chrome or Microsoft Edge, used headless to paginate and print the book.
- Network access on the **first** build only. The build downloads Paged.js, Mermaid,
  and the EB Garamond and Inter web fonts into `assets/` and reuses them afterwards.

## The PDF

`book.pdf` is built as a paperback interior, not as a printout of the website. The
manuscript is paginated by Paged.js inside headless Chrome and printed through the
DevTools protocol, which is what makes running heads, folios, a table of contents with
real page numbers, and recto chapter openings possible.

`cover.pdf` is the separate paperback cover upload for KDP. It is a full-bleed wrap
cover containing the back cover, spine, and front cover on one page. The default cover
math assumes a 6 x 9 in paperback, 0.125 in bleed, black-and-white white paper, and the
final page count produced by `book.pdf`. If the KDP paper choice changes to cream,
update the spine factor in `cover_pdf.py` and regenerate.

Settings to choose when uploading to KDP:

| KDP setting | Value |
| --- | --- |
| Trim size | 6 x 9 in (15.24 x 22.86 cm) |
| Bleed | No bleed |
| Interior type | Black & white |
| Paper | White, unless `cover_pdf.py` is adjusted for cream spine width |

The build fails if the interior would breach a KDP requirement. It checks the trim
size, the inside/outside margins against KDP's gutter table for the final page count,
an even page count, font embedding, the 7pt minimum type size, that nothing is set in
colour, and that every table-of-contents entry matches the page it points to.

The ISBN line on the copyright page is a placeholder to replace before publishing. The
back cover includes a blank barcode area for a KDP-generated barcode.

## Layout of the build

| File | Responsibility |
| --- | --- |
| `build_book.py` | Entry point. Parses the manuscript to HTML and writes the website. |
| `book_pdf.py` | The book design: page geometry, front matter, print stylesheet, diagram fitting. |
| `brief_pdf.py` | The short version as an A4 booklet: its own geometry and stylesheet, the same renderer. |
| `report_docx.py` | The Word edition of the report: heading styles, a TOC field, editable tables. |
| `cover_pdf.py` | The KDP wrap-cover design and cover geometry. |
| `chrome_pdf.py` | Headless Chrome over the DevTools protocol, plus the asset cache. |
| `kdp_report.py` | Post-processing (bookmarks, metadata) and the KDP compliance checks. |
