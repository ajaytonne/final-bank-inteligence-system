import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import statement_analyser as sa
from statement_analyser.main import app as analyser_app, settings_dep, store_dep
from statement_analyser.services.file_validation import FileValidationError
from statement_analyser.services.storage import StatementStore


def test_package_exports():
    assert set(sa.__all__) == {"analyse", "analyse_full", "mount", "create_app", "DEFAULT_PREFIX"}
    assert sa.DEFAULT_PREFIX == "/statement-analyser"


# ---- analyse() -----------------------------------------------------------------------------------
def test_analyse_from_bytes(text_pdf):
    result = sa.analyse(text_pdf, name="march.pdf")
    assert len(result.transactions) == 14
    assert result.header.account_holder.value == "Priya Sharma"
    assert result.file_name == "march.pdf"


def test_analyse_from_a_path(tmp_path, text_pdf):
    p = tmp_path / "s.pdf"
    p.write_bytes(text_pdf)
    assert len(sa.analyse(p).transactions) == 14
    assert len(sa.analyse(str(p)).transactions) == 14


def test_analyse_needs_a_name_for_bytes(text_pdf):
    with pytest.raises(ValueError, match="file name"):
        sa.analyse(text_pdf)


def test_analyse_rejects_unsafe_files():
    with pytest.raises(FileValidationError):
        sa.analyse(b"not a pdf at all", name="evil.pdf")
    with pytest.raises(FileValidationError):
        sa.analyse(b"%PDF-1.4 hi", name="notes.txt")


# ---- mount() -------------------------------------------------------------------------------------
@pytest.fixture
def host(settings):
    store = StatementStore(settings.db_path)
    analyser_app.dependency_overrides[settings_dep] = lambda: settings
    analyser_app.dependency_overrides[store_dep] = lambda: store
    host = FastAPI()

    @host.get("/hello")
    def hello():
        return {"host": "ok"}

    yield host
    analyser_app.dependency_overrides.clear()


def test_mount_adds_the_api_under_a_prefix_and_keeps_host_routes(host):
    sa.mount(host, "/analyser")
    c = TestClient(host)
    assert c.get("/hello").json() == {"host": "ok"}
    h = c.get("/analyser/api/health")
    assert h.status_code == 200 and h.json()["status"] == "ok"
    assert c.get("/api/health").status_code == 404  # nothing leaks into the host's own namespace


def test_mounted_module_works_end_to_end(host, text_pdf):
    sa.mount(host)
    c = TestClient(host)
    r = c.post("/statement-analyser/api/extract", files={"file": ("s.pdf", text_pdf, "application/pdf")})
    assert r.status_code == 200 and len(r.json()["transactions"]) == 14
    body = {"file_name": "s.pdf", "header": {}, "transactions": [{"date": "2026-09-02", "description": "UPI/SWIGGY/1", "withdrawal": "100.00"}]}
    sid = c.post("/statement-analyser/api/statements", json=body).json()["id"]
    assert c.get(f"/statement-analyser/api/statements/{sid}").status_code == 200
    ident = c.post("/statement-analyser/api/merchants/identify", json={"descriptions": ["UPI/SWIGGY/1"]}).json()
    assert ident[0]["merchant_name"] == "Swiggy"
    assert [e["action"] for e in c.get("/statement-analyser/api/audit").json()] == ["saved"]


@pytest.mark.parametrize("prefix", ["analyser", "/analyser/", ""])
def test_mount_rejects_bad_prefixes(host, prefix):
    with pytest.raises(ValueError, match="prefix"):
        sa.mount(host, prefix)


def test_a_second_database_path_is_refused_once_loaded(tmp_path):
    with pytest.raises(RuntimeError, match="already loaded"):
        sa.create_app(str(tmp_path / "other.db"))
