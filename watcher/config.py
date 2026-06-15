from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


DOCKER_WATCH_DIR = Path("/watch")
DOCKER_SURYA_OCR_URL = "http://surya:8077/ocr"
DOCKER_SURYA_HEALTHCHECK_URL = "http://surya:8077/health"
DOCKER_OLLAMA_URL = "http://ollama:11434"
DEFAULT_OLLAMA_MODEL = "qwen3:4b"
POLL_SECONDS = 5
PDF_STABLE_SECONDS = 10
MIN_RENAME_CONFIDENCE = 0.72
MAX_PROCESS_ATTEMPTS = 3
FAILED_RETRY_DELAY_SECONDS = 300
DEFAULT_OCR_MAX_PAGES = 3
DEFAULT_SURYA_TIMEOUT_SECONDS = 1200
DEFAULT_OLLAMA_TIMEOUT_SECONDS = 1200


def bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


@dataclass(frozen=True)
class Config:
    watch_dir_container: Path
    surya_service_url: str
    surya_health_url: str
    ollama_base_url: str
    ollama_model: str
    dry_run: bool
    poll_interval_seconds: float
    stable_seconds: float
    auto_rename_min_confidence: float
    max_process_attempts: int
    failed_retry_delay_seconds: float
    ocr_max_pages: int
    surya_timeout_seconds: int
    ollama_timeout_seconds: int
    log_level: str


def load_config() -> Config:
    return Config(
        watch_dir_container=DOCKER_WATCH_DIR,
        surya_service_url=DOCKER_SURYA_OCR_URL,
        surya_health_url=DOCKER_SURYA_HEALTHCHECK_URL,
        ollama_base_url=DOCKER_OLLAMA_URL,
        ollama_model=os.getenv("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL),
        dry_run=bool_env("DRY_RUN", False),
        poll_interval_seconds=POLL_SECONDS,
        stable_seconds=PDF_STABLE_SECONDS,
        auto_rename_min_confidence=MIN_RENAME_CONFIDENCE,
        max_process_attempts=max(1, int_env("MAX_PROCESS_ATTEMPTS", MAX_PROCESS_ATTEMPTS)),
        failed_retry_delay_seconds=max(0.0, float_env("FAILED_RETRY_DELAY_SECONDS", FAILED_RETRY_DELAY_SECONDS)),
        ocr_max_pages=max(0, int_env("OCR_MAX_PAGES", DEFAULT_OCR_MAX_PAGES)),
        surya_timeout_seconds=max(1, int_env("SURYA_TIMEOUT_SECONDS", DEFAULT_SURYA_TIMEOUT_SECONDS)),
        ollama_timeout_seconds=max(1, int_env("OLLAMA_TIMEOUT_SECONDS", DEFAULT_OLLAMA_TIMEOUT_SECONDS)),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
    )
