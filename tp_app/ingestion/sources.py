"""Prepare supported training-plan files for the OpenAI Responses API."""

from __future__ import annotations

import base64
import io
import mimetypes
import re
from pathlib import Path
from typing import Any

import openpyxl
import pandas as pd
from pypdf import PdfReader

from .models import (
    EXTRACTION_PROMPT,
    IMAGE_SUFFIXES,
    MAX_AI_FILE_BYTES,
    SUPPORTED_SUFFIXES,
)


def mime_type(path: Path) -> str:
    overrides = {
        ".pdf": "application/pdf",
        ".csv": "text/csv",
        ".tsv": "text/tsv",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xls": "application/vnd.ms-excel",
        ".xlsm": "application/vnd.ms-excel.sheet.macroEnabled.12",
    }
    return (
        overrides.get(path.suffix.lower())
        or mimetypes.guess_type(path.name)[0]
        or "application/octet-stream"
    )


def api_file_payload(path: Path) -> tuple[bytes, str, str]:
    """Return API-compatible bytes, converting XLSM containers to XLSX."""
    if path.suffix.lower() != ".xlsm":
        return path.read_bytes(), path.name, mime_type(path)

    workbook = None
    try:
        workbook = openpyxl.load_workbook(
            path,
            data_only=False,
            keep_vba=False,
            keep_links=False,
        )
        buffer = io.BytesIO()
        workbook.save(buffer)
    except Exception as exc:
        raise ValueError(
            "The XLSM file could not be converted to an AI-readable XLSX file."
        ) from exc
    finally:
        if workbook is not None:
            workbook.close()
    return (
        buffer.getvalue(),
        path.with_suffix(".xlsx").name,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def build_ai_input(
    path: Path,
    *,
    prompt: str = EXTRACTION_PROMPT,
) -> list[dict[str, Any]]:
    """Build request content without uploading a persistent OpenAI file."""
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError(
            "AI reading supports PDF, PNG, JPG, WEBP, GIF, CSV, TSV, XLS, XLSX, and XLSM files."
        )
    if path.stat().st_size >= MAX_AI_FILE_BYTES:
        raise ValueError("The AI input must be smaller than 50 MB.")

    file_bytes, api_filename, detected_mime_type = api_file_payload(path)
    if len(file_bytes) >= MAX_AI_FILE_BYTES:
        raise ValueError("The AI input must be smaller than 50 MB after conversion.")
    encoded = base64.b64encode(file_bytes).decode("ascii")
    data_url = f"data:{detected_mime_type};base64,{encoded}"
    if suffix in IMAGE_SUFFIXES:
        source: dict[str, Any] = {
            "type": "input_image",
            "image_url": data_url,
            "detail": "original",
        }
    else:
        source = {
            "type": "input_file",
            "filename": api_filename,
            "file_data": data_url,
        }
        if suffix == ".pdf":
            source["detail"] = "high"
    return [source, {"type": "input_text", "text": prompt}]


def prompt_with_period_definitions(
    period_definitions: dict[str, Any] | None,
) -> str:
    lines = []
    for period_number, settings in (period_definitions or {}).items():
        if not isinstance(settings, dict):
            continue
        start = str(settings.get("start_time", "")).strip()
        end = str(settings.get("end_time", "")).strip()
        if start and end:
            lines.append(f"- Period {period_number}: {start}-{end}")
    if not lines:
        return EXTRACTION_PROMPT
    return (
        f"{EXTRACTION_PROMPT}\n\n"
        "Configured period fallback:\n"
        + "\n".join(lines)
        + "\nUse these times only when the source names that period but omits its time range."
    )


def chunk_prompt(
    start_page: int,
    end_page: int,
    total_pages: int,
    *,
    base_prompt: str = EXTRACTION_PROMPT,
) -> str:
    page_label = (
        f"original page {start_page}"
        if start_page == end_page
        else f"original pages {start_page}-{end_page}"
    )
    return (
        f"{base_prompt}\n\n"
        "PDF coverage contract:\n"
        f"- This file contains {page_label} of a {total_pages}-page source PDF.\n"
        "- Extract every scheduled event visible on every supplied page, including "
        "the bottom row and the final supplied page.\n"
        "- Use the original source page number in source_reference.\n"
        "- Do not return early merely because a month or week appears complete.\n"
        "- If any supplied page or row cannot be read, name that page in warnings."
    )


def date_span_from_texts(texts: list[str]) -> tuple[str | None, str | None]:
    date_tokens: list[str] = []
    patterns = (
        r"\b\d{1,2}-[A-Za-z]{3}-\d{2,4}\b",
        r"\b\d{4}-\d{1,2}-\d{1,2}\b",
        r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b",
    )
    for text in texts:
        for pattern in patterns:
            date_tokens.extend(re.findall(pattern, text or ""))

    if not date_tokens:
        return None, None
    parsed = pd.to_datetime(
        pd.Series(date_tokens),
        format="mixed",
        dayfirst=True,
        errors="coerce",
    ).dropna()
    if parsed.empty:
        return None, None
    return parsed.min().strftime("%Y-%m-%d"), parsed.max().strftime("%Y-%m-%d")


def pdf_date_span(reader: PdfReader) -> tuple[str | None, str | None]:
    return date_span_from_texts([(page.extract_text() or "") for page in reader.pages])

