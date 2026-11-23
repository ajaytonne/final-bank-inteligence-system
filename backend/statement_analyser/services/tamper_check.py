"""Tamper checks on the PDF file itself. A statement downloaded from a bank's system normally has no trace of an editor,
one save, and no annotations on top of the text. These are warning signs for a person to look at, never proof.

Rules (each flag has a code, a severity and a plain-language detail):
  editor_software     the file was last produced by a general PDF/image editor (iLovePDF, Sejda, Photoshop, Canva ...)
  modified_after_creation  the modification time is later than the creation time
  incremental_save    the file has more than one %%EOF, i.e. it was edited and saved on top of the original
  annotations         notes, stamps, whiteout boxes or redactions drawn on the pages
  many_fonts          far more fonts than a system generated statement uses
  image_over_text     a large image sits on a page that also has text (a pasted-over patch)
  balance_chain       (added by the caller) the running balance does not add up
Images are only checked for PDFs; a photo or a scan has no file trail to inspect."""
import re
from typing import Optional

import pymupdf

EDITORS = re.compile(
    r"(ilovepdf|smallpdf|sejda|pdfescape|pdf24|pdfcandy|foxit|nitro|pdf-?xchange|wps|photoshop|illustrator|canva|gimp|inkscape|"
    r"libreoffice|openoffice|microsoft.{0,6}word|pages|google docs|paint|acrobat\s*(pro|distiller)?\s*(dc)?)", re.I)
# Acrobat/Word can also be a bank's own generator; so on its own an editor name is a "medium" flag, not "high".
STRONG = re.compile(r"(ilovepdf|smallpdf|sejda|pdfescape|pdf24|pdfcandy|photoshop|canva|gimp|inkscape|paint)", re.I)
MAX_FONTS = 6


def _flag(code: str, severity: str, detail: str) -> dict:
    return {"code": code, "severity": severity, "detail": detail}


def _parse_pdf_date(s: str):
    m = re.match(r"D:(\d{4})(\d{2})?(\d{2})?(\d{2})?(\d{2})?(\d{2})?", s or "")
    if not m:
        return None
    import datetime as dt
    parts = [int(x) if x else d for x, d in zip(m.groups(), (1970, 1, 1, 0, 0, 0))]
    try:
        return dt.datetime(*parts)
    except ValueError:
        return None


def check_pdf(data: bytes, password: Optional[str] = None) -> dict:
    """{"status": "clean" | "suspicious" | "unavailable", "flags": [...], "metadata": {...}}"""
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
        if doc.needs_pass and not (password and doc.authenticate(password)):
            return {"status": "unavailable", "flags": [], "metadata": {}, "note": "The PDF is locked, so its file trail could not be checked."}
    except Exception:  # noqa: BLE001
        return {"status": "unavailable", "flags": [], "metadata": {}, "note": "The file could not be opened for checking."}

    flags = []
    meta = {k: (v or "") for k, v in (doc.metadata or {}).items() if k in ("producer", "creator", "creationDate", "modDate")}
    tools = f"{meta.get('producer', '')} {meta.get('creator', '')}".strip()
    if tools and EDITORS.search(tools):
        strong = bool(STRONG.search(tools))
        flags.append(_flag("editor_software", "high" if strong else "medium",
                           f"The file was produced by '{tools}', which is an editing tool, not a bank system."))
    created, modified = _parse_pdf_date(meta.get("creationDate", "")), _parse_pdf_date(meta.get("modDate", ""))
    if created and modified and (modified - created).total_seconds() > 60:
        flags.append(_flag("modified_after_creation", "medium", f"Modified {modified:%Y-%m-%d %H:%M} after it was created {created:%Y-%m-%d %H:%M}."))
    saves = data.count(b"%%EOF")
    if saves > 1:
        flags.append(_flag("incremental_save", "medium", f"The file was saved {saves} times on top of the original (an edit trail)."))

    fonts, annots, overlays = set(), 0, 0
    for page in doc:
        annots += sum(1 for a in (page.annots() or []) if a.type[1] not in ("Link",))
        fonts.update(f[3] for f in page.get_fonts())
        text_chars = len(page.get_text().strip())
        area = page.rect.width * page.rect.height or 1
        for img in page.get_image_info():
            x0, y0, x1, y1 = img["bbox"]
            if text_chars > 200 and 0.03 < ((x1 - x0) * (y1 - y0)) / area < 0.6:
                overlays += 1
    if annots:
        flags.append(_flag("annotations", "high", f"{annots} annotation(s) (notes, stamps or boxes) are drawn on the pages."))
    if len(fonts) > MAX_FONTS:
        flags.append(_flag("many_fonts", "low", f"{len(fonts)} different fonts. A system generated statement normally uses only a few."))
    if overlays:
        flags.append(_flag("image_over_text", "medium", f"{overlays} image(s) sit on pages that also have text, which can hide changed values."))
    doc.close()
    return {"status": "suspicious" if flags else "clean", "flags": flags, "metadata": meta,
            "note": "Warning signs only. A clean result does not prove the statement is genuine."}
