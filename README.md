# RoundTableIII

This repository contains the working manuscript and generated reading site for the International STEM Skills Round Table Phase III personal summary.

Golden source: `book/manuscript.md`.

Generated outputs:

- `index.html` - website gateway.
- `book.html` - full web reader.
- `book.pdf` - print-ready paperback interior for Amazon KDP.

Regenerate the website and PDF with:

```powershell
python build_book.py
```

## Requirements

- Python 3.11 or later. Only the standard library is needed to build; `pymupdf` is
  optional and enables the KDP compliance report, the PDF bookmarks, and the closing
  blank page (`pip install pymupdf`).
- Google Chrome or Microsoft Edge, used headless to paginate and print the book.
- Network access on the **first** build only. The build downloads Paged.js, Mermaid,
  and the EB Garamond and Inter web fonts into `assets/` and reuses them afterwards.

## The PDF

`book.pdf` is built as a paperback interior, not as a printout of the website. The
manuscript is paginated by Paged.js inside headless Chrome and printed through the
DevTools protocol, which is what makes running heads, folios, a table of contents with
real page numbers, and recto chapter openings possible.

Settings to choose when uploading to KDP:

| KDP setting | Value |
| --- | --- |
| Trim size | 6 x 9 in (15.24 x 22.86 cm) |
| Bleed | No bleed |
| Interior type | Black & white |
| Paper | White or cream |

The build fails if the interior would breach a KDP requirement. It checks the trim
size, the inside/outside margins against KDP's gutter table for the final page count,
an even page count, font embedding, the 7pt minimum type size, that nothing is set in
colour, and that every table-of-contents entry matches the page it points to.

The cover is a separate upload and is not produced here. The ISBN line on the
copyright page is a placeholder to replace before publishing.

## Layout of the build

| File | Responsibility |
| --- | --- |
| `build_book.py` | Entry point. Parses the manuscript to HTML and writes the website. |
| `book_pdf.py` | The book design: page geometry, front matter, print stylesheet, diagram fitting. |
| `chrome_pdf.py` | Headless Chrome over the DevTools protocol, plus the asset cache. |
| `kdp_report.py` | Post-processing (bookmarks, metadata) and the KDP compliance checks. |
