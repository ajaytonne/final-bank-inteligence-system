import pytest

from app.services.file_validation import FileValidationError, sniff, validate_upload

MB = 1024 * 1024
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20
PDF = b"%PDF-1.7\n" + b"0" * 20


def test_accepts_pdf():
    vf = validate_upload("st.pdf", PDF, MB)
    assert vf.kind == "pdf" and vf.name == "st.pdf"


def test_accepts_png_case_insensitive():
    assert validate_upload("SCAN.PNG", PNG, MB).kind == "image"


def test_strips_path_from_name():
    assert validate_upload("../../etc/st.pdf", PDF, MB).name == "st.pdf"


@pytest.mark.parametrize(
    "name,data,code",
    [
        ("st.exe", PDF, 415),
        ("st", PDF, 415),
        ("st.pdf", b"", 400),
        ("st.pdf", PNG, 415),  # mismatch
        ("st.png", PDF, 415),  # mismatch
        ("st.pdf", b"not a pdf at all", 415),
        ("", PDF, 400),
    ],
)
def test_rejects(name, data, code):
    with pytest.raises(FileValidationError) as exc:
        validate_upload(name, data, MB)
    assert exc.value.status_code == code


def test_rejects_large():
    with pytest.raises(FileValidationError) as exc:
        validate_upload("big.pdf", PDF + b"0" * MB, MB)
    assert exc.value.status_code == 413


def test_sniff_webp():
    assert sniff(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == "webp"
