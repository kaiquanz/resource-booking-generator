"""AI-assisted training-plan extraction and canonical event validation."""

from __future__ import annotations

import base64
import io
import mimetypes
import re
from pathlib import Path
from typing import Any

import pandas as pd
import openpyxl
from pydantic import BaseModel, Field


MAX_AI_FILE_BYTES = 50 * 1024 * 1024
DEFAULT_AI_MODEL = "gpt-5.6"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
SUPPORTED_SUFFIXES = IMAGE_SUFFIXES | {
    ".pdf", ".csv", ".tsv", ".xlsx", ".xls", ".xlsm"
}
EVENT_COLUMNS = [
    "date",
    "start_time",
    "end_time",
    "conduct",
    "location",
    "remarks",
    "source_reference",
    "confidence",
    "needs_review",
]


class TrainingPlanEvent(BaseModel):
    date: str = Field(description="Calendar date in YYYY-MM-DD format")
    start_time: str = Field(description="Start time in 24-hour HH:MM format")
    end_time: str = Field(description="End time in 24-hour HH:MM format")
    conduct: str = Field(description="Training activity exactly as shown")
    location: str = Field(description="Location exactly as shown, or an empty string")
    remarks: str = Field(description="Relevant notes, or an empty string")
    source_reference: str = Field(description="Page, sheet, or visible box reference")
    confidence: float = Field(ge=0, le=1)
    needs_review: bool


class TrainingPlanExtraction(BaseModel):
    document_title: str
    events: list[TrainingPlanEvent]
    warnings: list[str]


EXTRACTION_PROMPT = """
Extract this training plan into individual scheduled events.

The source may be a spreadsheet, a normal PDF, a scanned PDF, or a visual
timetable made from text boxes, merged cells, colours, arrows, or pictures.
Read both text and spatial layout. Treat dates across columns, time periods down
rows, merged boxes, legends, and continuation markers as layout evidence.

Rules:
- Return one event for every distinct date, time range, conduct, and location.
- Expand boxes spanning multiple dates into one event per date when the layout
  clearly indicates that the event occurs on each date.
- Use YYYY-MM-DD dates and 24-hour HH:MM times.
- Preserve conduct and location wording; do not rename them to likely synonyms.
- Do not invent missing dates, times, activities, or locations.
- Use an empty string for a missing location or remark.
- Set needs_review=true whenever a date, time, merged-box boundary, conduct, or
  location is uncertain, and explain material uncertainty in warnings.
- Confidence is about the accuracy of the extracted row, not the importance of
  the activity.
- Ignore decorative elements and administrative headers that are not scheduled
  events.
- If the document is not a training plan, return no events and add a warning.
""".strip()


def _mime_type(path: Path) -> str:
    overrides = {
        ".pdf": "application/pdf",
        ".csv": "text/csv",
        ".tsv": "text/tsv",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xls": "application/vnd.ms-excel",
        ".xlsm": "application/vnd.ms-excel.sheet.macroEnabled.12",
    }
    return overrides.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def _api_file_payload(path: Path) -> tuple[bytes, str, str]:
    """Return API-compatible bytes, converting unsupported XLSM containers."""
    if path.suffix.lower() != ".xlsm":
        return path.read_bytes(), path.name, _mime_type(path)

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
        raise ValueError("The XLSM file could not be converted to an AI-readable XLSX file.") from exc
    finally:
        if workbook is not None:
            workbook.close()
    return (
        buffer.getvalue(),
        path.with_suffix(".xlsx").name,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def build_ai_input(path: Path) -> list[dict[str, Any]]:
    """Build a Responses API content list without uploading persistent files."""
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError(
            "AI reading supports PDF, PNG, JPG, WEBP, GIF, CSV, TSV, XLS, XLSX, and XLSM files."
        )
    file_size = path.stat().st_size
    if file_size >= MAX_AI_FILE_BYTES:
        raise ValueError("The AI input must be smaller than 50 MB.")

    file_bytes, api_filename, mime_type = _api_file_payload(path)
    if len(file_bytes) >= MAX_AI_FILE_BYTES:
        raise ValueError("The AI input must be smaller than 50 MB after conversion.")
    encoded = base64.b64encode(file_bytes).decode("ascii")
    data_url = f"data:{mime_type};base64,{encoded}"
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
    return [source, {"type": "input_text", "text": EXTRACTION_PROMPT}]


def _raise_for_non_result(response: Any) -> None:
    if getattr(response, "status", None) == "incomplete":
        details = getattr(response, "incomplete_details", None)
        reason = getattr(details, "reason", "unknown reason")
        raise RuntimeError(f"The AI response was incomplete: {reason}.")
    for output in getattr(response, "output", []) or []:
        if getattr(output, "type", None) != "message":
            continue
        for item in getattr(output, "content", []) or []:
            if getattr(item, "type", None) == "refusal":
                raise RuntimeError(f"The AI could not process this file: {item.refusal}")


def extract_training_plan_with_ai(
    path: str | Path,
    *,
    api_key: str,
    model: str = DEFAULT_AI_MODEL,
    client: Any | None = None,
) -> dict[str, Any]:
    """Extract a training plan with multimodal Structured Outputs."""
    source_path = Path(path)
    if not source_path.is_file():
        raise FileNotFoundError(f"Training plan was not found: {source_path}")
    if not api_key.strip():
        raise ValueError("Set OPENAI_API_KEY in Streamlit Secrets before using AI reading.")

    if client is None:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("Install the OpenAI Python package from requirements.txt.") from exc
        client = OpenAI(api_key=api_key)

    try:
        response = client.responses.parse(
            model=model,
            store=False,
            input=[
                {
                    "role": "user",
                    "content": build_ai_input(source_path),
                }
            ],
            text_format=TrainingPlanExtraction,
        )
    except Exception as exc:
        error_name = type(exc).__name__
        if error_name == "AuthenticationError":
            raise RuntimeError("OpenAI rejected the API key configured for this app.") from exc
        if error_name == "RateLimitError":
            raise RuntimeError("OpenAI is rate-limited or the project has insufficient quota. Try again later.") from exc
        if error_name in {"APIConnectionError", "APITimeoutError"}:
            raise RuntimeError("The app could not reach OpenAI. Try the extraction again.") from exc
        raise

    _raise_for_non_result(response)
    parsed = getattr(response, "output_parsed", None)
    if parsed is None:
        raise RuntimeError("The AI returned no structured training-plan data.")

    events = pd.DataFrame(
        [event.model_dump() for event in parsed.events],
        columns=EVENT_COLUMNS,
    )
    return {
        "document_title": parsed.document_title,
        "events": events,
        "warnings": list(parsed.warnings),
        "model": getattr(response, "model", model),
        "response_id": getattr(response, "id", ""),
    }


def _normalise_time(value: Any) -> str | None:
    if pd.isna(value):
        return None
    text = str(value).strip()
    if not text:
        return None
    compact = text.replace(":", "").replace(".", "")
    if compact.isdigit() and len(compact) in (3, 4):
        compact = compact.zfill(4)
        hour, minute = int(compact[:2]), int(compact[2:])
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return f"{hour:02d}:{minute:02d}"
    try:
        parsed = pd.to_datetime(text, errors="raise")
        return parsed.strftime("%H:%M")
    except Exception:
        return None


def _normalise_date(value: Any) -> str | None:
    if pd.isna(value):
        return None
    text = str(value).strip()
    if not text:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        parsed = pd.to_datetime(text, format="%Y-%m-%d", errors="coerce")
    else:
        parsed = pd.to_datetime(text, dayfirst=True, errors="coerce")
    return None if pd.isna(parsed) else parsed.strftime("%Y-%m-%d")


def _normalise_boolean(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes", "y", "checked"}
    return False if pd.isna(value) else bool(value)


def validate_reviewed_events(frame: pd.DataFrame) -> tuple[pd.DataFrame, list[str], list[str]]:
    """Normalise an edited event table and report blocking errors and warnings."""
    working = frame.copy()
    for column in EVENT_COLUMNS:
        if column not in working.columns:
            working[column] = False if column == "needs_review" else ""
    working = working[EVENT_COLUMNS]

    cleaned_rows: list[dict[str, Any]] = []
    errors: list[str] = []
    warnings: list[str] = []
    for position, (_, row) in enumerate(working.iterrows(), start=1):
        conduct = "" if pd.isna(row["conduct"]) else str(row["conduct"]).strip()
        if not conduct and all(
            pd.isna(row[column]) or str(row[column]).strip() == ""
            for column in ("date", "start_time", "end_time", "location")
        ):
            continue

        parsed_date = _normalise_date(row["date"])
        start_time = _normalise_time(row["start_time"])
        end_time = _normalise_time(row["end_time"])
        if parsed_date is None:
            errors.append(f"Row {position}: enter a valid date.")
        if start_time is None:
            errors.append(f"Row {position}: enter a valid start time.")
        if end_time is None:
            errors.append(f"Row {position}: enter a valid end time.")
        if not conduct:
            errors.append(f"Row {position}: conduct is required.")
        if start_time and end_time and start_time >= end_time:
            errors.append(f"Row {position}: end time must be later than start time.")

        location = "" if pd.isna(row["location"]) else str(row["location"]).strip()
        if not location:
            warnings.append(f"Row {position}: no location; it will not create a facility booking.")
        try:
            confidence = float(row["confidence"])
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = min(1.0, max(0.0, confidence))
        needs_review = _normalise_boolean(row["needs_review"]) or confidence < 0.75
        if needs_review:
            warnings.append(f"Row {position}: marked for human review.")

        cleaned_rows.append({
            "date": parsed_date or "",
            "start_time": start_time or "",
            "end_time": end_time or "",
            "conduct": conduct,
            "location": location,
            "remarks": "" if pd.isna(row["remarks"]) else str(row["remarks"]).strip(),
            "source_reference": "" if pd.isna(row["source_reference"]) else str(row["source_reference"]).strip(),
            "confidence": confidence,
            "needs_review": needs_review,
        })

    cleaned = pd.DataFrame(cleaned_rows, columns=EVENT_COLUMNS)
    if cleaned.empty:
        errors.append("The reviewed plan must contain at least one event.")
    if not cleaned.empty:
        duplicate_mask = cleaned.duplicated(
            subset=["date", "start_time", "end_time", "conduct", "location"],
            keep=False,
        )
        if duplicate_mask.any():
            warnings.append("The table contains duplicate scheduled events.")
    return cleaned, list(dict.fromkeys(errors)), list(dict.fromkeys(warnings))
