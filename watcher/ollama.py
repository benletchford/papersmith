from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

import requests

from watcher.logging_json import extra


logger = logging.getLogger(__name__)


def infer_name(
    *,
    ollama_base_url: str,
    model: str,
    text: str,
    fallback_date: str,
    source_path: Path,
    timeout_seconds: int = 600,
) -> dict[str, Any]:
    prompt = build_prompt(text=text, fallback_date=fallback_date, source_path=source_path)
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "think": False,
        "options": {
            "temperature": 0,
            "num_ctx": 4096,
            "num_predict": 512,
        },
    }
    url = f"{ollama_base_url.rstrip('/')}/api/generate"
    logger.info("ollama_request", extra=extra(url=url, model=model, source=str(source_path)))
    response = requests.post(url, json=payload, timeout=timeout_seconds)
    response.raise_for_status()
    data = response.json()
    generated, response_field = extract_generated_text(data)
    logger.info(
        "ollama_response",
        extra=extra(
            model=model,
            source=str(source_path),
            response_field=response_field,
            response_chars=len(generated),
            response_preview=generated[:1000],
        ),
    )
    parsed = parse_json_object(generated)
    return normalize_metadata(
        parsed,
        fallback_date=fallback_date,
        source_path=source_path,
        raw_response=generated,
    )


def extract_generated_text(data: dict[str, Any]) -> tuple[str, str]:
    response = str(data.get("response") or "")
    if response.strip():
        return response, "response"

    thinking = str(data.get("thinking") or "")
    if thinking.strip():
        return thinking, "thinking"

    return "", "response"


def build_prompt(*, text: str, fallback_date: str, source_path: Path) -> str:
    clipped = text[:6000]
    return f"""
You extract metadata from OCR text. Ignore the source filename unless OCR text is empty.

Return JSON only. Use these keys:
date, date_evidence, document_type, issuer, subject, title_slug, title_evidence, confidence.

Rules:
- Use a document date only when an OCR line clearly supports it. If no clear document date exists, use {fallback_date} and set date_evidence to "".
- title_slug must be specific and descriptive, lowercase kebab-case, ASCII only, under 12 words.
- Never use generic titles like scan, document, file, pdf, untitled, paperwork, receipt, invoice, or tax-invoice by themselves.
- For receipts or tax invoices, prefer issuer + location if visible + document_type. Do not include purchased item details unless there is no issuer.
- For statements, prefer issuer + statement period. For letters, prefer sender + subject.
- Do not include the date in title_slug.
- title_evidence must quote exact lines from the OCR text below. Do not invent evidence.
- confidence is your confidence that title_slug and date are correct, from 0 to 1.
- Example for a Bunnings Wagga Wagga tax invoice: title_slug "bunnings-wagga-wagga-tax-invoice".

Source file name: {source_path.name}
OCR text:
{clipped}
""".strip()


def normalize_metadata(
    parsed: dict[str, Any],
    *,
    fallback_date: str,
    source_path: Path,
    raw_response: str,
) -> dict[str, Any]:
    title_evidence = parsed.get("title_evidence")
    if isinstance(title_evidence, str):
        title_evidence = [title_evidence]
    if not isinstance(title_evidence, list):
        title_evidence = []
    confidence = parsed.get("confidence", 0)
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        confidence = 0.0
    return {
        "date": str(parsed.get("date") or fallback_date),
        "date_evidence": str(parsed.get("date_evidence") or ""),
        "document_type": str(parsed.get("document_type") or "other"),
        "issuer": str(parsed.get("issuer") or ""),
        "subject": str(parsed.get("subject") or ""),
        "title_slug": str(parsed.get("title_slug") or source_path.stem),
        "title_evidence": [str(line) for line in title_evidence if str(line).strip()],
        "confidence": max(0.0, min(1.0, confidence)),
        "raw_response": raw_response,
    }


def parse_json_object(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", value, flags=re.DOTALL)
    if not match:
        raise ValueError(f"Ollama response did not contain a JSON object: {value[:500]}")
    parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("Ollama JSON response was not an object")
    return parsed
