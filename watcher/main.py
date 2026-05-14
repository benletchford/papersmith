from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from watcher.analysis import decide_filename
from watcher.config import Config, load_config
from watcher.logging_json import extra, setup_logging
from watcher.naming import (
    build_filename,
    clean_ocr_text_for_llm,
    is_already_renamed,
    safe_collision_path,
)
from watcher.ollama import infer_name


logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Watch and OCR-rename local PDFs in Docker")
    parser.add_argument("--once", type=Path, help="Process one PDF and exit")
    parser.add_argument("--healthcheck", action="store_true", help="Check Docker services and exit")
    args = parser.parse_args(argv)

    config = load_config()
    setup_logging(config.log_level)
    validate_config(config)

    if args.healthcheck:
        check_services(config)
        return 0
    if args.once:
        process_one(args.once, config)
        return 0

    logger.info(
        "watcher_started",
        extra=extra(
            watch_dir_container=str(config.watch_dir_container),
            dry_run=config.dry_run,
            poll_interval_seconds=config.poll_interval_seconds,
        ),
    )
    check_services(config)
    poll_forever(config)
    return 0


def validate_config(config: Config) -> None:
    if not config.watch_dir_container.exists():
        raise ValueError(f"Docker watch folder does not exist: {config.watch_dir_container}")
    if not config.watch_dir_container.is_dir():
        raise ValueError(f"Docker watch folder is not a directory: {config.watch_dir_container}")
    validate_docker_service_url("Surya OCR URL", config.surya_service_url)
    validate_docker_service_url("Surya health URL", config.surya_health_url)
    validate_docker_service_url("Ollama base URL", config.ollama_base_url)


def validate_docker_service_url(name: str, value: str) -> None:
    host = urlparse(value).hostname
    host_local = {"host.docker.internal", "localhost", "127.0.0.1", "::1", "0.0.0.0"}
    if not host:
        raise ValueError(f"{name} must be a valid URL")
    if host in host_local:
        raise ValueError(
            f"{name} points at {host}. Docker-only mode requires Compose service names "
            "such as surya and ollama, not host-local services."
        )


def check_services(config: Config) -> None:
    surya = requests.get(config.surya_health_url, timeout=10)
    surya.raise_for_status()
    tags = requests.get(f"{config.ollama_base_url.rstrip('/')}/api/tags", timeout=10)
    tags.raise_for_status()
    models = {model.get("name") for model in tags.json().get("models", [])}
    if config.ollama_model not in models:
        logger.warning(
            "ollama_model_not_listed",
            extra=extra(model=config.ollama_model, available=sorted(models)),
        )


def poll_forever(config: Config) -> None:
    attempted: set[tuple[str, int, int]] = set()
    while True:
        try:
            for pdf in find_candidate_pdfs(config.watch_dir_container):
                if not is_stable(pdf, config.stable_seconds):
                    continue
                fingerprint = file_fingerprint(pdf)
                if fingerprint in attempted:
                    continue
                process_one(pdf, config)
                attempted.add(fingerprint)
        except Exception:
            logger.exception("poll_cycle_failed")
        time.sleep(config.poll_interval_seconds)


def find_candidate_pdfs(root: Path) -> list[Path]:
    candidates: list[Path] = []
    for path in root.rglob("*.pdf"):
        if is_already_renamed(path):
            continue
        candidates.append(path)
    return sorted(candidates)


def is_stable(path: Path, stable_seconds: float) -> bool:
    try:
        first = path.stat()
        if time.time() - first.st_mtime < stable_seconds:
            return False
        time.sleep(0.25)
        second = path.stat()
    except FileNotFoundError:
        return False
    return first.st_size == second.st_size and first.st_mtime_ns == second.st_mtime_ns


def file_fingerprint(path: Path) -> tuple[str, int, int]:
    stat = path.stat()
    return (str(path), stat.st_size, stat.st_mtime_ns)


def process_one(path: Path, config: Config) -> Path | None:
    container_path = normalize_container_path(path, config)
    if is_already_renamed(container_path):
        logger.info("skip_already_renamed", extra=extra(path=str(container_path)))
        return None

    try:
        mtime = container_path.stat().st_mtime
        fallback_date = datetime.fromtimestamp(mtime).strftime("%Y%m%d")
        ocr = call_surya(container_path=container_path, config=config)
        inferred = infer_name(
            ollama_base_url=config.ollama_base_url,
            model=config.ollama_model,
            text=clean_ocr_text_for_llm(ocr["text"]),
            fallback_date=fallback_date,
            source_path=container_path,
        )
        decision = decide_filename(
            ocr_text=ocr["text"],
            metadata=inferred,
            source_path=container_path,
            mtime=mtime,
            min_confidence=config.auto_rename_min_confidence,
        )
        if not decision.should_rename:
            event = {
                "status": "needs_review",
                "source_container_path": str(container_path),
                "ocr_pages": ocr.get("pages"),
                "ocr_chars": len(ocr.get("text", "")),
                "confidence_optional": ocr.get("confidence_optional"),
                "ollama": inferred,
                "final_date": decision.date,
                "final_title_slug": decision.title_slug,
                "metadata_confidence": decision.confidence,
                "review_reasons": decision.reasons,
            }
            logger.warning("needs_review", extra=extra(**event))
            return None

        final_name = build_filename(decision.date, decision.title_slug or "document")
        target = safe_collision_path(container_path.with_name(final_name))

        event = {
            "status": "dry_run" if config.dry_run else "renamed",
            "source_container_path": str(container_path),
            "target_container_path": str(target),
            "ocr_pages": ocr.get("pages"),
            "ocr_chars": len(ocr.get("text", "")),
            "confidence_optional": ocr.get("confidence_optional"),
            "ollama": inferred,
            "final_date": decision.date,
            "final_title_slug": decision.title_slug,
            "metadata_confidence": decision.confidence,
            "title_source": "ollama_validated_by_evidence",
        }

        if config.dry_run:
            logger.info("dry_run_rename", extra=extra(**event))
            return target

        container_path.rename(target)
        logger.info("renamed", extra=extra(**event))
        return target
    except Exception as exc:
        logger.exception(
            "process_failed",
            extra=extra(
                status="failed",
                source_container_path=str(container_path),
                error_type=type(exc).__name__,
                error=str(exc),
            ),
        )
        return None


def normalize_container_path(path: Path, config: Config) -> Path:
    if path.is_absolute():
        if not is_relative_to(path, config.watch_dir_container):
            raise ValueError(f"PDF path must be under the Docker watch folder: {config.watch_dir_container}")
        return path
    return config.watch_dir_container / path


def is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def call_surya(*, container_path: Path, config: Config) -> dict[str, Any]:
    payload = {
        "container_path": str(container_path),
    }
    logger.info("surya_request", extra=extra(**payload))
    response = requests.post(config.surya_service_url, json=payload, timeout=900)
    if not response.ok:
        raise RuntimeError(f"Surya service error {response.status_code}: {response.text[:4000]}")
    data = response.json()
    if not data.get("text"):
        raise RuntimeError("Surya service returned no text")
    return data


if __name__ == "__main__":
    sys.exit(main())
