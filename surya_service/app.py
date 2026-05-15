from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()


def int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


RENDERED_FALLBACK_MAX_DIMENSION = max(400, int_env("SURYA_RENDERED_FALLBACK_MAX_DIMENSION", 1600))
DIRECT_OCR_MAX_PAGE_DIMENSION_POINTS = max(0, int_env("SURYA_DIRECT_OCR_MAX_PAGE_DIMENSION_POINTS", 1600))
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("surya-service")

app = FastAPI(title="Docker Surya OCR Service", version="1.0.0")


class OcrRequest(BaseModel):
    container_path: str = Field(..., description="Absolute path to the PDF inside Docker")


class OcrResponse(BaseModel):
    text: str
    pages: int
    confidence_optional: float | None = None


@app.get("/health")
def health() -> dict[str, Any]:
    executable = shutil.which("surya_ocr")
    return {
        "ok": executable is not None,
        "surya_ocr": executable,
        "rendered_fallback_max_dimension": RENDERED_FALLBACK_MAX_DIMENSION,
        "direct_ocr_max_page_dimension_points": DIRECT_OCR_MAX_PAGE_DIMENSION_POINTS,
    }


@app.post("/ocr", response_model=OcrResponse)
def ocr(request: OcrRequest) -> OcrResponse:
    started = time.time()
    pdf_path = Path(request.container_path).expanduser().resolve()
    logger.info("ocr_request container_path=%s", pdf_path)

    if not pdf_path.exists():
        raise HTTPException(
            status_code=400,
            detail=f"container_path does not exist in the OCR container: {pdf_path}",
        )
    if not pdf_path.is_file():
        raise HTTPException(status_code=400, detail=f"container_path is not a file: {pdf_path}")
    if pdf_path.suffix.lower() != ".pdf":
        raise HTTPException(status_code=400, detail=f"container_path is not a PDF: {pdf_path}")

    try:
        response = run_surya(pdf_path)
        logger.info(
            "ocr_success container_path=%s pages=%s chars=%s duration_seconds=%.2f",
            pdf_path,
            response.pages,
            len(response.text),
            time.time() - started,
        )
        return response
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("ocr_failed container_path=%s", pdf_path)
        raise HTTPException(
            status_code=500,
            detail={
                "error": type(exc).__name__,
                "message": str(exc),
                "container_path": str(pdf_path),
            },
        ) from exc


def run_surya(pdf_path: Path) -> OcrResponse:
    executable = shutil.which("surya_ocr")
    if executable is None:
        raise RuntimeError("surya_ocr executable not found in the OCR container.")

    if should_use_rendered_fallback_first(pdf_path):
        return run_surya_rendered_fallback(executable, pdf_path)

    with tempfile.TemporaryDirectory(prefix="surya-ocr-") as tmp_dir:
        output_dir = Path(tmp_dir)
        completed = run_surya_command(executable, pdf_path, output_dir)
        if completed.returncode != 0:
            logger.error(
                "surya_nonzero returncode=%s stdout=%s stderr=%s",
                completed.returncode,
                completed.stdout,
                completed.stderr,
            )
            if completed.returncode == -9:
                logger.warning("surya_low_memory_retry container_path=%s", pdf_path)
                return run_surya_rendered_fallback(executable, pdf_path)
            raise RuntimeError(
                "surya_ocr failed "
                f"with exit code {completed.returncode}: {completed.stderr[-4000:]}"
            )

        logger.debug("surya_stdout=%s", completed.stdout)
        return parse_surya_output(output_dir, source_path=pdf_path)


def should_use_rendered_fallback_first(pdf_path: Path) -> bool:
    if DIRECT_OCR_MAX_PAGE_DIMENSION_POINTS <= 0:
        return False

    try:
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(str(pdf_path))
        for index in range(len(pdf)):
            page = pdf[index]
            width, height = page.get_size()
            max_dimension = max(width, height)
            if max_dimension > DIRECT_OCR_MAX_PAGE_DIMENSION_POINTS:
                logger.warning(
                    "surya_direct_skipped_large_page container_path=%s page=%s points=%sx%s "
                    "max_dimension=%.1f threshold=%s",
                    pdf_path,
                    index + 1,
                    width,
                    height,
                    max_dimension,
                    DIRECT_OCR_MAX_PAGE_DIMENSION_POINTS,
                )
                return True
    except Exception:
        logger.warning("surya_large_page_probe_failed container_path=%s", pdf_path, exc_info=True)
    return False


def run_surya_command(executable: str, input_path: Path, output_dir: Path) -> subprocess.CompletedProcess[str]:
    cmd = [
        executable,
        str(input_path),
        "--output_dir",
        str(output_dir),
    ]
    logger.info("surya_start command=%s", json.dumps(cmd))
    return subprocess.run(
        cmd,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def run_surya_rendered_fallback(executable: str, pdf_path: Path) -> OcrResponse:
    import pypdfium2 as pdfium

    with tempfile.TemporaryDirectory(prefix="surya-rendered-") as tmp_dir:
        work_dir = Path(tmp_dir)
        image_dir = work_dir / "images"
        image_dir.mkdir()
        pdf = pdfium.PdfDocument(str(pdf_path))
        responses: list[OcrResponse] = []

        for index in range(len(pdf)):
            page = pdf[index]
            width, height = page.get_size()
            scale = min(1.0, RENDERED_FALLBACK_MAX_DIMENSION / max(width, height))
            image = page.render(scale=scale).to_pil().convert("RGB")
            image_path = image_dir / f"page-{index + 1:04d}.jpg"
            image.save(image_path, quality=90)
            logger.info(
                "surya_rendered_page page=%s points=%sx%s pixels=%sx%s scale=%.3f max_dimension=%s",
                index + 1,
                width,
                height,
                image.width,
                image.height,
                scale,
                RENDERED_FALLBACK_MAX_DIMENSION,
            )

            page_output_dir = work_dir / f"page-{index + 1:04d}-ocr"
            completed = run_surya_command(executable, image_path, page_output_dir)
            if completed.returncode != 0:
                logger.error(
                    "surya_rendered_nonzero page=%s returncode=%s stdout=%s stderr=%s",
                    index + 1,
                    completed.returncode,
                    completed.stdout,
                    completed.stderr,
                )
                raise RuntimeError(
                    "surya_ocr fallback failed "
                    f"on page {index + 1} with exit code {completed.returncode}: "
                    f"{completed.stderr[-4000:]}"
                )
            responses.append(parse_surya_output(page_output_dir, source_path=image_path))

        text = "\n\n".join(response.text for response in responses if response.text).strip()
        confidences = [
            response.confidence_optional
            for response in responses
            if response.confidence_optional is not None
        ]
        confidence = sum(confidences) / len(confidences) if confidences else None
        return OcrResponse(text=text, pages=len(pdf), confidence_optional=confidence)


def parse_surya_output(output_dir: Path, *, source_path: Path) -> OcrResponse:
    result_files = sorted(output_dir.rglob("results.json"))
    if not result_files:
        result_files = sorted(output_dir.rglob("*.json"))
    if not result_files:
        raise RuntimeError(f"surya_ocr produced no JSON results under {output_dir}")

    texts: list[str] = []
    confidences: list[float] = []
    pages_seen = 0
    for result_file in result_files:
        with result_file.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        extracted = extract_text_nodes(payload)
        texts.extend(extracted)
        confidences.extend(extract_confidences(payload))
        pages_seen = max(pages_seen, infer_page_count(payload))

    text = "\n\n".join(part.strip() for part in texts if part and part.strip()).strip()
    if not text:
        raise RuntimeError(f"surya_ocr returned JSON but no text for {source_path}")

    confidence = sum(confidences) / len(confidences) if confidences else None
    return OcrResponse(
        text=text,
        pages=pages_seen or 1,
        confidence_optional=confidence,
    )


def extract_text_nodes(node: Any) -> list[str]:
    found: list[str] = []
    if isinstance(node, dict):
        for collection_key in ("text_lines", "lines", "blocks"):
            value = node.get(collection_key)
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict) and isinstance(item.get("text"), str):
                        found.append(item["text"])
                    else:
                        found.extend(extract_text_nodes(item))

        for key, value in node.items():
            if key in {"text", "plain_text"} and isinstance(value, str):
                found.append(value)
            elif key in {"chars", "char_boxes", "text_lines", "lines", "blocks"}:
                continue
            else:
                found.extend(extract_text_nodes(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(extract_text_nodes(item))
    return found


def extract_confidences(node: Any) -> list[float]:
    found: list[float] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key in {"confidence", "score", "text_confidence"} and isinstance(value, int | float):
                found.append(float(value))
            else:
                found.extend(extract_confidences(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(extract_confidences(item))
    return found


def infer_page_count(node: Any) -> int:
    if isinstance(node, dict):
        for key in ("pages", "page_count"):
            value = node.get(key)
            if isinstance(value, int):
                return value
            if isinstance(value, list):
                return len(value)
        if "page" in node and isinstance(node["page"], int):
            return node["page"] + 1
        child_counts = [infer_page_count(value) for value in node.values()]
        return max(child_counts, default=0)
    if isinstance(node, list):
        return max((infer_page_count(item) for item in node), default=len(node))
    return 0
