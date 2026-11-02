import os
from dataclasses import dataclass, field


def _bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    max_upload_mb: int = int(os.getenv("MAX_UPLOAD_MB", "10"))
    max_pages: int = int(os.getenv("MAX_PAGES", "30"))
    min_text_chars: int = int(os.getenv("MIN_TEXT_CHARS", "60"))
    ocr_dpi: int = int(os.getenv("OCR_DPI", "300"))
    ocr_lang: str = os.getenv("OCR_LANG", "eng")
    review_threshold: float = float(os.getenv("REVIEW_THRESHOLD", "0.75"))
    date_dayfirst: bool = _bool("DATE_DAYFIRST", True)

    ollama_enabled: bool = _bool("OLLAMA_ENABLED", False)
    ollama_url: str = os.getenv("OLLAMA_URL", "http://localhost:11434")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
    ollama_timeout: float = float(os.getenv("OLLAMA_TIMEOUT", "60"))

    db_path: str = os.getenv("DB_PATH", "data/statements.db")
    cors_origins: list[str] = field(
        default_factory=lambda: [
            o.strip()
            for o in os.getenv(
                "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
            ).split(",")
            if o.strip()
        ]
    )

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


def get_settings() -> Settings:
    return Settings()
