from dataclasses import dataclass
from pathlib import Path
from typing import Literal

PDF_EXT = {".pdf"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}

# Magic bytes
_SIGNATURES: list[tuple[bytes, str]] = [
    (b"%PDF-", "pdf"),
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpeg"),
    (b"II*\x00", "tiff"),
    (b"MM\x00*", "tiff"),
    (b"BM", "bmp"),
]


class FileValidationError(ValueError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


@dataclass
class ValidatedFile:
    name: str
    kind: Literal["pdf", "image"]
    data: bytes


def sniff(data: bytes) -> str | None:
    head = data[:16]
    for sig, kind in _SIGNATURES:
        if head.startswith(sig):
            return kind
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    return None


def validate_upload(filename: str | None, data: bytes, max_bytes: int) -> ValidatedFile:
    name = Path(filename or "").name
    if not name:
        raise FileValidationError("File name is missing.")
    ext = Path(name).suffix.lower()
    if ext not in PDF_EXT | IMAGE_EXT:
        raise FileValidationError(
            f"Unsupported file type '{ext or 'none'}'. Upload a PDF or image "
            "(png, jpg, jpeg, tif, tiff, bmp, webp).",
            415,
        )
    if len(data) == 0:
        raise FileValidationError("Uploaded file is empty.")
    if len(data) > max_bytes:
        raise FileValidationError(
            f"File is too large ({len(data) / 1048576:.1f} MB). "
            f"Limit is {max_bytes // 1048576} MB.",
            413,
        )

    detected = sniff(data)
    if detected is None:
        raise FileValidationError("File content is not a recognised PDF or image.", 415)
    is_pdf_ext = ext in PDF_EXT
    if is_pdf_ext != (detected == "pdf"):
        raise FileValidationError("File extension does not match its content.", 415)

    return ValidatedFile(name=name, kind="pdf" if is_pdf_ext else "image", data=data)
