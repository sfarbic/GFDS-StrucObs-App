"""PRE-VISIT: turn an uploaded plan set into sheets you can pin photos on.

Owner: allenmarden
Suggested library: PyMuPDF (pip install pymupdf)

Pages render at 150 dpi, capped so the long side is at most 4000 px; a
36" x 24" sheet comes out 4000 x 2667. PyMuPDF also opens JPEG/PNG plans,
which come back as a single sheet.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from .models import PlanSheet

_DPI = 150
_MAX_SIDE_PX = 4000


def load_plan_set(pdf_path: Path, out_dir: Path) -> list[PlanSheet]:
    """Render every page of the plan PDF to a PNG in out_dir.

    Return one PlanSheet per page, with image_path, width_px and height_px
    filled in. Use the sheet number/title from the title block as the name if
    you can find it, otherwise "Sheet 1", "Sheet 2", ...
    """
    pymupdf = _pymupdf()
    pdf_path, out_dir = Path(pdf_path), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    sheets = []
    with pymupdf.open(pdf_path) as doc:
        for index, page in enumerate(doc):
            zoom = min(_DPI / 72, _MAX_SIDE_PX / max(page.rect.width, page.rect.height))
            pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
            image_path = out_dir / f"{pdf_path.stem}_p{index + 1:03d}.png"
            pix.save(image_path)
            sheets.append(PlanSheet(
                name=f"Sheet {index + 1}",
                source_pdf=pdf_path,
                page_index=index,
                image_path=image_path,
                width_px=pix.width,
                height_px=pix.height,
            ))
    return sheets


def _pymupdf():
    try:
        import pymupdf
    except ImportError as exc:
        raise ImportError("plans.py needs PyMuPDF: pip install pymupdf") from exc
    return pymupdf


# ----------------------------------------------------------------------------
# naming a sheet for the report
# ----------------------------------------------------------------------------
_DATED_RE = re.compile(r"^(\d{2})(\d{2})(\d{2})[\s_-]+(.+)$")
# "S1.0", "S-201", "A2.1B", "SL1" - a drawing number as a title block prints it
_SHEET_RE = re.compile(r"^[A-Z]{1,3}[-\s]?\d{1,3}(?:\.\d{1,2})?[A-Z]?$")


def set_info(file_name: str) -> tuple[str, str]:
    """(plan set name, date) from an uploaded file name.

    "220627 Martis Camp Structure - Permit Addendum.pdf" ->
    ("Martis Camp Structure - Permit Addendum", "06/27/2022"). A name that
    does not start with a real YYMMDD date gives ("<name>", "")."""
    stem = re.sub(r"\.(pdf|png|jpe?g|heic)$", "", str(file_name or "").strip(),
                  flags=re.IGNORECASE)
    m = _DATED_RE.match(stem)
    if m:
        yy, mm, dd, rest = m.groups()
        try:
            date(2000 + int(yy), int(mm), int(dd))
        except ValueError:
            return stem, ""
        return rest.strip(), f"{mm}/{dd}/20{yy}"
    return stem, ""


def read_sheet_number(page) -> str:
    """The sheet number printed in a PyMuPDF page's lower-right corner, as
    the page is viewed: the largest text there shaped like "S1.0". "" when
    there is none - a title block exported as drawn shapes has no text."""
    width, height = page.rect.width, page.rect.height     # as viewed (rotation applied)
    best = None
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            text = "".join(s["text"] for s in line["spans"]).strip()
            if not text or not _SHEET_RE.match(text):
                continue
            x0, y0, x1, y1 = line["bbox"]
            # text coordinates are unrotated; turn them into the viewed page's
            r = _viewed(page, (x0, y0, x1, y1))
            if r[0] < width * 0.6 or r[1] < height * 0.6:
                continue
            size = max(s["size"] for s in line["spans"])
            key = (round(size, 1), r[2] + r[3])
            if best is None or key > best[0]:
                best = (key, text.replace(" ", ""))
    return best[1] if best else ""


def _viewed(page, bbox):
    import pymupdf
    rect = pymupdf.Rect(bbox) * page.rotation_matrix
    return rect.x0, rect.y0, rect.x1, rect.y1


def read_sheet_numbers(pdf_path: Path) -> list[str]:
    """read_sheet_number for every page of a PDF ("" where none is found)."""
    pymupdf = _pymupdf()
    with pymupdf.open(pdf_path) as doc:
        return [read_sheet_number(page) for page in doc]


def sheet_title(plan: dict, page: int) -> str:
    """How a sheet is named wherever a location is shown: its sheet number
    ("S1.0"), else the set and its number as uploaded ("Martis Camp, sheet 3"),
    else just the set for a one-sheet plan."""
    nos = plan.get("sheet_nos") or []
    if 0 < page <= len(nos) and str(nos[page - 1] or "").strip():
        return str(nos[page - 1]).strip()
    name, _ = set_info(plan.get("name") or plan.get("file") or "")
    labels = plan.get("page_labels") or []
    if 0 < page <= len(labels):
        return f"{name}, sheet {labels[page - 1]}"
    return name if (plan.get("pages") or 1) == 1 else f"{name}, sheet {page}"


def sheet_heading(plan: dict, page: int) -> dict:
    """The lines over a plan page in the report: {set, date, sheet}."""
    name, when = set_info(plan.get("name") or plan.get("file") or "")
    nos = plan.get("sheet_nos") or []
    labels = plan.get("page_labels") or []
    number = (str(nos[page - 1]).strip() if 0 < page <= len(nos) else "") \
        or str(labels[page - 1] if 0 < page <= len(labels) else page)
    return {"set": name, "date": when, "sheet": number}
