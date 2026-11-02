import io
import importlib.util
import logging
import os
import shutil
import statistics
import threading
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import pymupdf
from PIL import Image, ImageOps

from app.config import Settings

log = logging.getLogger(__name__)

PageSource = Literal["pdf_text", "ocr"]


@dataclass
class Word:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    conf: float  # 0-100
    page: int

    @property
    def xc(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def yc(self) -> float:
        return (self.y0 + self.y1) / 2

    @property
    def height(self) -> float:
        return max(self.y1 - self.y0, 1.0)


@dataclass
class Line:
    page: int
    words: list[Word]
    source: PageSource
    cells: list[list[Word]] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "  ".join(" ".join(w.text for w in c) for c in self.cells)

    @property
    def cell_texts(self) -> list[str]:
        return [" ".join(w.text for w in c) for c in self.cells]

    @property
    def mean_conf(self) -> float:
        return statistics.fmean(w.conf for w in self.words) if self.words else 0.0


@dataclass
class PageText:
    number: int  # 1-based
    source: PageSource
    lines: list[Line]


@dataclass
class DocumentText:
    pages: list[PageText]
    warnings: list[str] = field(default_factory=list)

    @property
    def lines(self) -> list[Line]:
        return [ln for p in self.pages for ln in p.lines]

    @property
    def text(self) -> str:
        return "\n".join(ln.text for ln in self.lines)

    @property
    def ocr_pages(self) -> list[int]:
        return [p.number for p in self.pages if p.source == "ocr"]


class OCRUnavailableError(RuntimeError):
    pass


# Default install folders of the Windows installer (it does not add itself to PATH).
_WIN_TESSERACT_PATHS = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
)


def find_tesseract() -> str | None:
    """Return the tesseract executable path, or None. Order: TESSERACT_CMD env, PATH, Windows defaults."""
    for candidate in (os.getenv("TESSERACT_CMD"), "tesseract", *_WIN_TESSERACT_PATHS):
        found = shutil.which(candidate) if candidate else None
        if found:
            return found
    return None


def tesseract_available() -> bool:
    exe = find_tesseract()
    if exe is None:
        return False
    try:
        import pytesseract

        pytesseract.pytesseract.tesseract_cmd = exe  # tell pytesseract exactly where it is
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def rapidocr_available() -> bool:
    """Pip-installed fallback OCR (rapidocr-onnxruntime). Works with no system install."""
    return importlib.util.find_spec("rapidocr_onnxruntime") is not None


def ocr_available() -> bool:
    return tesseract_available() or rapidocr_available()


_rapid_engine = None
_rapid_lock = threading.Lock()


def rapid_image_words(img: Image.Image, number: int) -> list[Word]:
    global _rapid_engine
    from rapidocr_onnxruntime import RapidOCR

    with _rapid_lock:
        if _rapid_engine is None:
            _rapid_engine = RapidOCR()
    result, _ = _rapid_engine(np.array(ImageOps.exif_transpose(img).convert("RGB")))
    out = []
    for box, text, score in result or []:
        xs, ys = [p[0] for p in box], [p[1] for p in box]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        parts = text.split()
        if not parts:
            continue
        total = sum(len(p) for p in parts) + len(parts) - 1  # chars incl. spaces
        cx = x0
        for part in parts:  # RapidOCR returns lines; split into words by character share
            w = (x1 - x0) * len(part) / total
            out.append(Word(part, cx, y0, cx + w, y1, float(score) * 100, number))
            cx += w + (x1 - x0) / total
    return out


# Line grouping


def group_lines(words: list[Word], page: int, source: PageSource) -> list[Line]:
    words = [w for w in words if w.text.strip()]
    if not words:
        return []
    words.sort(key=lambda w: (w.yc, w.x0))
    rows: list[list[Word]] = []
    for w in words:
        if rows:
            row = rows[-1]
            row_yc = statistics.fmean(x.yc for x in row)
            row_h = statistics.median(x.height for x in row)
            if abs(w.yc - row_yc) <= 0.5 * max(row_h, w.height):
                row.append(w)
                continue
        rows.append([w])

    lines = []
    for row in rows:
        row.sort(key=lambda w: w.x0)
        lines.append(Line(page=page, words=row, source=source, cells=split_cells(row)))
    return lines


def split_cells(row: list[Word]) -> list[list[Word]]:
    h = statistics.median(w.height for w in row)
    gap_limit = 0.9 * h
    cells: list[list[Word]] = [[row[0]]]
    for prev, w in zip(row, row[1:]):
        if w.x0 - prev.x1 > gap_limit:
            cells.append([w])
        else:
            cells[-1].append(w)
    return cells


# PDF text


def _pdf_page_words(page: pymupdf.Page, number: int) -> list[Word]:
    out = []
    for x0, y0, x1, y1, text, *_ in page.get_text("words", sort=True):
        out.append(Word(text, x0, y0, x1, y1, 95.0, number))
    return out


# OCR


def remove_rules(gray: Image.Image, ratio: float = 0.35) -> Image.Image:
    arr = np.array(gray)
    dark = arr < 140
    rows = np.where(dark.mean(axis=1) > ratio)[0]
    cols = np.where(dark.mean(axis=0) > ratio)[0]
    arr[rows, :] = 255  # table rules
    arr[:, cols] = 255
    return Image.fromarray(arr)


def estimate_skew(gray: Image.Image, max_angle: float = 3.0, step: float = 0.1) -> float:
    small = gray.copy()
    small.thumbnail((900, 900))
    inv = ImageOps.invert(small)
    best, best_score = 0.0, -1.0
    n = int(max_angle / step)
    for i in range(-n, n + 1):
        angle = i * step
        rot = np.asarray(inv.rotate(angle, resample=Image.BILINEAR, fillcolor=0), dtype=np.float32)
        score = float(np.var(rot.sum(axis=1)))
        if score > best_score:
            best, best_score = angle, score
    return best


def deskew(gray: Image.Image) -> Image.Image:
    angle = estimate_skew(gray)
    if abs(angle) < 0.05:
        return gray
    return gray.rotate(angle, resample=Image.BICUBIC, expand=True, fillcolor=255)


def preprocess(img: Image.Image) -> Image.Image:
    img = ImageOps.exif_transpose(img)
    gray = ImageOps.grayscale(img)
    gray = ImageOps.autocontrast(gray, cutoff=1)
    # Upscale small
    if gray.width < 1500:
        scale = 1500 / gray.width
        gray = gray.resize((int(gray.width * scale), int(gray.height * scale)), Image.LANCZOS)
    return remove_rules(deskew(gray))


def ocr_image_words(img: Image.Image, number: int, lang: str) -> list[Word]:
    if not tesseract_available():
        if rapidocr_available():
            return rapid_image_words(img, number)
        raise OCRUnavailableError(
            "Tesseract not found. Install it, add it to PATH, or set TESSERACT_CMD to tesseract.exe "
            "(or run: pip install rapidocr-onnxruntime)."
        )
    import pytesseract

    data = pytesseract.image_to_data(
        preprocess(img), lang=lang, config="--psm 6", output_type=pytesseract.Output.DICT
    )
    out = []
    for i, text in enumerate(data["text"]):
        text = (text or "").strip()
        conf = float(data["conf"][i])
        if not text or conf < 0:
            continue
        x, y, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
        out.append(Word(text, x, y, x + w, y + h, conf, number))
    return out


# Public API


def extract_pdf(data: bytes, settings: Settings) -> DocumentText:
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise ValueError(f"Could not open PDF: {exc}") from exc

    warnings: list[str] = []
    if doc.needs_pass:
        raise ValueError("PDF is password protected.")
    if doc.page_count == 0:
        raise ValueError("PDF has no pages.")
    if doc.page_count > settings.max_pages:
        raise ValueError(f"PDF has {doc.page_count} pages; limit is {settings.max_pages}.")

    pages: list[PageText] = []
    ocr_ok = ocr_available()
    skipped: list[int] = []
    for idx, page in enumerate(doc, start=1):
        words = _pdf_page_words(page, idx)
        char_count = sum(len(w.text) for w in words)
        if char_count >= settings.min_text_chars:
            pages.append(PageText(idx, "pdf_text", group_lines(words, idx, "pdf_text")))
            continue
        if not ocr_ok:
            skipped.append(idx)
            warnings.append(
                f"Page {idx} has little text and OCR is unavailable; page skipped."
            )
            pages.append(PageText(idx, "pdf_text", group_lines(words, idx, "pdf_text")))
            continue
        pix = page.get_pixmap(dpi=settings.ocr_dpi)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        ocr_words = ocr_image_words(img, idx, settings.ocr_lang)
        pages.append(PageText(idx, "ocr", group_lines(ocr_words, idx, "ocr")))
    page_total = doc.page_count
    doc.close()
    if len(skipped) == page_total:  # whole PDF is scanned and there is no OCR engine
        raise OCRUnavailableError(
            "Tesseract not found. Install it, add it to PATH, or set TESSERACT_CMD to tesseract.exe "
            "(or run: pip install rapidocr-onnxruntime)."
        )
    return DocumentText(pages, warnings)


def extract_image(data: bytes, settings: Settings) -> DocumentText:
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception as exc:
        raise ValueError(f"Could not open image: {exc}") from exc
    if img.width * img.height > 60_000_000:
        raise ValueError("Image dimensions are too large.")
    words = ocr_image_words(img, 1, settings.ocr_lang)
    return DocumentText([PageText(1, "ocr", group_lines(words, 1, "ocr"))])
