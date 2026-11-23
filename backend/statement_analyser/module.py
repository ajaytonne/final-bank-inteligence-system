"""The Statement Analyser as a module another application can use.

Two ways to use it from Python:

    from statement_analyser import analyse, mount

    result = analyse("statement.pdf")                      # read one statement, get structured data back
    mount(host_app, prefix="/statement-analyser", db_path="/data/analyser.db")   # add the whole API to a FastAPI app

Nothing here changes how the standalone app works. Heavy imports happen inside the functions, so
`import statement_analyser` stays cheap.
"""
import os
import sys
from pathlib import Path
from typing import Optional, Union

DEFAULT_PREFIX = "/statement-analyser"


def _read(source, name, settings):
    from statement_analyser.services.file_validation import validate_upload

    if isinstance(source, (str, Path)):
        path = Path(source)
        data, name = path.read_bytes(), name or path.name
    else:
        data = source
    if not name:
        raise ValueError("Give the file name (for example 'march.pdf') when passing bytes.")
    return validate_upload(name, data, settings.max_upload_bytes)


def analyse_full(source: Union[str, Path, bytes], name: Optional[str] = None, *, password: Optional[str] = None, settings=None) -> dict:
    """The complete analysis as a plain dict (JSON-ready): extraction, bank, analytics, tamper checks and flags.

    analytics: balances, monthly view, salary, EMI/NACH, bounces, cash, circular transfers.   tamper: file-trail warning signs.
    `password` opens a password protected PDF. Same errors as analyse().
    """
    from statement_analyser.config import get_settings
    from statement_analyser.services.analysis import analyse_file

    settings = settings or get_settings()
    return analyse_file(_read(source, name, settings), settings, password)


def analyse(source: Union[str, Path, bytes], name: Optional[str] = None, *, password: Optional[str] = None, settings=None):
    """Read one bank statement (PDF or image) and return an ExtractionResult.

    `source` is a file path or the file's bytes (then give `name`, for example "march.pdf").
    The result lists the header fields and transactions with a confidence score each and a
    `needs_review` flag. Nothing is saved: saving is the host's decision.
    Raises FileValidationError (unsupported or unsafe file), OCRUnavailableError (a scan but no OCR engine)
    or ValueError (nothing readable in the file).
    """
    from statement_analyser.config import get_settings
    from statement_analyser.services.pipeline import run_extraction

    settings = settings or get_settings()
    return run_extraction(_read(source, name, settings), settings, password)


def create_app(db_path: Optional[str] = None):
    """The complete Statement Analyser API as a FastAPI app (all routes under /api/...).

    Settings are read from the environment when the module is first loaded (DB_PATH, MAX_UPLOAD_MB, OCR_LANG ...).
    `db_path` is a shortcut for DB_PATH; it must be given before the first call, because the settings are fixed after that.
    """
    if db_path:
        loaded = "statement_analyser.main" in sys.modules
        if loaded and os.environ.get("DB_PATH") != db_path:
            raise RuntimeError("The Statement Analyser is already loaded with another database path. Pass db_path on the first call.")
        os.environ["DB_PATH"] = db_path
    from statement_analyser.main import app

    return app


def mount(host, prefix: str = DEFAULT_PREFIX, db_path: Optional[str] = None):
    """Add the Statement Analyser to a FastAPI/Starlette app under `prefix`.

    Its API is then at {prefix}/api/... (for example {prefix}/api/health). Returns the mounted app.
    The host's own routes and docs are not touched. Note: there is no login inside the module yet,
    so protect the prefix in the host (for example with middleware) until user accounts are added.
    """
    if not prefix.startswith("/") or prefix.endswith("/"):
        raise ValueError("prefix must start with '/' and not end with '/' (for example '/statement-analyser').")
    sub = create_app(db_path)
    host.mount(prefix, sub, name="statement-analyser")
    return sub
