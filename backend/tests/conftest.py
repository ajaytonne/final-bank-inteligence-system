from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import app, settings_dep, store_dep
from app.services.storage import StatementStore
from app.services.text_extraction import Line, Word, split_cells
from scripts.sample_data import build_pdf, image_png, make_txns, scanned_pdf


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(db_path=str(tmp_path / "test.db"), ollama_enabled=False)


@pytest.fixture
def client(settings):
    store = StatementStore(settings.db_path)
    app.dependency_overrides[settings_dep] = lambda: settings
    app.dependency_overrides[store_dep] = lambda: store
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture(scope="session")
def txns():
    return make_txns()


@pytest.fixture(scope="session")
def text_pdf(txns) -> bytes:
    return build_pdf(None, txns)


@pytest.fixture(scope="session")
def tampered_pdf(txns) -> bytes:
    return build_pdf(None, txns, tamper_row=5)


@pytest.fixture(scope="session")
def no_header_pdf(txns) -> bytes:
    return build_pdf(None, txns, with_header_row=False)


@pytest.fixture(scope="session")
def full_account_pdf(txns) -> bytes:
    return build_pdf(None, txns, account="123456781234")


@pytest.fixture(scope="session")
def scanned(text_pdf) -> bytes:
    return scanned_pdf(text_pdf)


@pytest.fixture(scope="session")
def png_statement(txns) -> bytes:
    return image_png(build_pdf(None, txns[:6], rows_per_page=20))


@pytest.fixture(scope="session")
def expected_closing(txns) -> Decimal:
    bal = Decimal("25000.00")
    for t in txns:
        bal += (t.deposit or 0) - (t.withdrawal or 0)
    return bal


def make_line(cells: list[tuple[float, str]], y: float = 100, page: int = 1, source="pdf_text", conf=95.0) -> Line:
    """Build a Line from (x, text) cells."""
    words = []
    for x, text in cells:
        cx = x
        for tok in text.split():
            width = 5.0 * len(tok)
            words.append(Word(tok, cx, y, cx + width, y + 10, conf, page))
            cx += width + 3
    words.sort(key=lambda w: w.x0)
    return Line(page=page, words=words, source=source, cells=split_cells(words))
