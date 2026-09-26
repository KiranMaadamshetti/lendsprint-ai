"""PDF -> text that preserves table structure, so the LLM sees clean columns.

Tables are rendered as pipe-delimited rows; text outside tables is kept as-is.
Each page is prefixed with a [PAGE n] marker so the model can cite page numbers.
"""
import io

import pdfplumber


def _table_to_text(table):
    lines = []
    for row in table:
        cells = [(c or "").replace("\n", " ").strip() for c in row]
        lines.append(" | ".join(cells))
    return "\n".join(lines)


def extract_pages(pdf_bytes: bytes) -> list[str]:
    pages = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            tables = page.find_tables()
            if tables:
                outside = page
                for t in tables:
                    outside = outside.outside_bbox(t.bbox)
                body = (outside.extract_text() or "").strip()
                rendered = "\n\n".join("TABLE:\n" + _table_to_text(t.extract()) for t in tables)
                text = (body + "\n\n" + rendered).strip()
            else:
                text = (page.extract_text() or "").strip()
            pages.append(f"[PAGE {i}]\n{text}")
    return pages


def has_text(pages: list[str]) -> bool:
    return sum(len(p) for p in pages) > 50 * len(pages)
