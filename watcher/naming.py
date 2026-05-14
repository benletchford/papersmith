from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from pathlib import Path


RENAMED_RE = re.compile(r"^\d{8}-[^/]+\.pdf$", re.IGNORECASE)
GENERIC_TITLES = {
    "scan",
    "scanned-document",
    "document",
    "file",
    "pdf",
    "untitled",
    "ocr",
    "paperwork",
    "receipt",
    "invoice",
    "tax-invoice",
    "statement",
    "letter",
    "form",
}


def is_already_renamed(path: Path) -> bool:
    return RENAMED_RE.match(path.name) is not None


def normalize_date(value: str | None, fallback_mtime: float) -> str:
    fallback = datetime.fromtimestamp(fallback_mtime).strftime("%Y%m%d")
    if not value:
        return fallback
    digits = re.sub(r"\D", "", value)
    if re.fullmatch(r"\d{8}", digits):
        try:
            datetime.strptime(digits, "%Y%m%d")
            return digits
        except ValueError:
            return fallback
    return fallback


def slugify_title(value: str | None, original_stem: str) -> str:
    candidate = (value or "").strip().lower()
    candidate = unicodedata.normalize("NFKD", candidate).encode("ascii", "ignore").decode("ascii")
    candidate = candidate.replace("&", " and ")
    candidate = re.sub(r"[^a-z0-9]+", "-", candidate)
    candidate = re.sub(r"-{2,}", "-", candidate).strip("-")
    if not candidate or candidate in GENERIC_TITLES:
        candidate = fallback_slug(original_stem)
    if candidate in GENERIC_TITLES:
        candidate = f"{candidate}-ocr"
    return candidate[:120].strip("-") or "document-ocr"


def is_generic_title(value: str | None) -> bool:
    if not value:
        return True
    return slugify_title(value, "document") in GENERIC_TITLES | {"document-ocr"}


def clean_ocr_text_for_llm(text: str) -> str:
    return "\n".join(meaningful_lines(text))


def meaningful_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if not line:
            continue
        if re.fullmatch(r"[A-Za-z0-9$.,:/#&*<>-]", line):
            continue
        if len(line) < 3:
            continue
        lines.append(line)
    return lines


def fallback_slug(original_stem: str) -> str:
    stem = re.sub(r"^\d{8}-", "", original_stem.lower())
    stem = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode("ascii")
    stem = re.sub(r"[^a-z0-9]+", "-", stem)
    stem = re.sub(r"-{2,}", "-", stem).strip("-")
    return stem or "document-ocr"


def build_filename(date_yyyymmdd: str, title_slug: str) -> str:
    return f"{date_yyyymmdd}-{title_slug}.pdf"


def safe_collision_path(target: Path) -> Path:
    if not target.exists():
        return target
    for index in range(2, 10_000):
        candidate = target.with_name(f"{target.stem}-{index}{target.suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Could not find collision-free name for {target}")
