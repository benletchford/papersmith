from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from watcher.naming import GENERIC_TITLES, clean_ocr_text_for_llm, normalize_date, slugify_title


@dataclass(frozen=True)
class NamingDecision:
    should_rename: bool
    date: str
    title_slug: str | None
    confidence: float
    reasons: list[str]
    cleaned_text: str
    metadata: dict[str, Any]


def decide_filename(
    *,
    ocr_text: str,
    metadata: dict[str, Any],
    source_path: Path,
    mtime: float,
    min_confidence: float,
) -> NamingDecision:
    cleaned_text = clean_ocr_text_for_llm(ocr_text)
    fallback_date = datetime.fromtimestamp(mtime).strftime("%Y%m%d")
    reasons: list[str] = []

    date = normalize_date(str(metadata.get("date") or ""), mtime)
    if date != fallback_date and not has_supported_date(metadata, cleaned_text):
        reasons.append("date_not_supported_by_evidence")
        date = fallback_date

    title_slug = slugify_title(str(metadata.get("title_slug") or ""), source_path.stem)
    if title_slug in GENERIC_TITLES or title_slug == "document-ocr":
        reasons.append("generic_or_missing_title")

    confidence = parse_confidence(metadata.get("confidence"))
    if confidence < min_confidence:
        reasons.append(f"confidence_below_threshold:{confidence:.2f}<{min_confidence:.2f}")

    evidence_lines = metadata.get("title_evidence")
    if not isinstance(evidence_lines, list) or not evidence_lines:
        reasons.append("missing_title_evidence")
    elif not evidence_is_in_text(evidence_lines, cleaned_text):
        reasons.append("title_evidence_not_found_in_ocr")

    if not title_tokens_supported(title_slug, cleaned_text, evidence_lines if isinstance(evidence_lines, list) else []):
        reasons.append("title_tokens_not_supported_by_ocr")

    should_rename = not reasons
    return NamingDecision(
        should_rename=should_rename,
        date=date,
        title_slug=title_slug if title_slug else None,
        confidence=confidence,
        reasons=reasons,
        cleaned_text=cleaned_text,
        metadata=metadata,
    )


def parse_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, confidence))


def has_supported_date(metadata: dict[str, Any], cleaned_text: str) -> bool:
    date_evidence = metadata.get("date_evidence")
    if isinstance(date_evidence, str) and normalize_for_match(date_evidence) in normalize_for_match(cleaned_text):
        return True
    date = str(metadata.get("date") or "")
    if not re.fullmatch(r"\d{8}", date):
        return False
    variants = {
        f"{date[:4]}-{date[4:6]}-{date[6:]}",
        f"{date[6:]}/{date[4:6]}/{date[:4]}",
        f"{date[4:6]}/{date[6:]}/{date[:4]}",
        f"{date[6:]}/{date[4:6]}/{date[2:4]}",
    }
    normalized_text = normalize_for_match(cleaned_text)
    return any(normalize_for_match(variant) in normalized_text for variant in variants)


def evidence_is_in_text(evidence_lines: list[Any], cleaned_text: str) -> bool:
    normalized_text = normalize_for_match(cleaned_text)
    found = 0
    for line in evidence_lines:
        if not isinstance(line, str) or len(line.strip()) < 3:
            continue
        candidates = evidence_candidates(line)
        if any(normalize_for_match(candidate) in normalized_text for candidate in candidates):
            found += 1
    return found > 0


def evidence_candidates(line: str) -> list[str]:
    quoted = re.findall(r'"([^"]+)"', line)
    candidates = [part for part in quoted if len(part.strip()) >= 3]
    candidates.extend(part for part in line.splitlines() if len(part.strip()) >= 3)
    candidates.append(line)
    return candidates


def title_tokens_supported(title_slug: str, cleaned_text: str, evidence_lines: list[Any]) -> bool:
    title_tokens = significant_tokens(title_slug.replace("-", " "))
    if not title_tokens:
        return False
    evidence_text = " ".join(line for line in evidence_lines if isinstance(line, str))
    support_text = f"{cleaned_text}\n{evidence_text}"
    support_tokens = set(significant_tokens(support_text))
    supported = [token for token in title_tokens if token in support_tokens]
    return len(supported) >= max(1, min(len(title_tokens), 2))


def significant_tokens(value: str) -> list[str]:
    stop = {
        "the",
        "and",
        "for",
        "with",
        "from",
        "copy",
        "document",
        "scan",
        "file",
        "pdf",
    }
    tokens = re.findall(r"[a-z0-9]{3,}", value.lower())
    return [token for token in tokens if token not in stop and not token.isdigit()]


def normalize_for_match(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()
