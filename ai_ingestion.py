"""AI-assisted training-plan extraction and canonical event validation."""

from __future__ import annotations

import base64
import io
import mimetypes
import re
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd
import openpyxl
from pydantic import BaseModel, Field
from pypdf import PdfReader, PdfWriter


MAX_AI_FILE_BYTES = 50 * 1024 * 1024
MAX_AI_OUTPUT_TOKENS = 64_000
PDF_PAGES_PER_REQUEST = 2
DEFAULT_AI_MODEL = "gpt-5.6-luna"
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
- Completeness is mandatory: inspect every supplied page through its final row
  and do not stop after finding a plausible partial schedule.
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


def build_ai_input(
    path: Path,
    *,
    prompt: str = EXTRACTION_PROMPT,
) -> list[dict[str, Any]]:
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
    return [source, {"type": "input_text", "text": prompt}]


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


def _prompt_with_period_definitions(
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


def _chunk_prompt(
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


def _date_span_from_texts(texts: list[str]) -> tuple[str | None, str | None]:
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
    )
    parsed = parsed.dropna()
    if parsed.empty:
        return None, None
    return parsed.min().strftime("%Y-%m-%d"), parsed.max().strftime("%Y-%m-%d")


def _pdf_date_span(reader: PdfReader) -> tuple[str | None, str | None]:
    return _date_span_from_texts(
        [(page.extract_text() or "") for page in reader.pages]
    )


def _request_extraction(
    client: Any,
    source_path: Path,
    *,
    prompt: str,
) -> tuple[TrainingPlanExtraction, Any]:
    try:
        response = client.responses.parse(
            model=DEFAULT_AI_MODEL,
            store=False,
            max_output_tokens=MAX_AI_OUTPUT_TOKENS,
            input=[
                {
                    "role": "user",
                    "content": build_ai_input(source_path, prompt=prompt),
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
    return parsed, response


def _merge_extraction_chunks(
    chunks: list[tuple[int, int, TrainingPlanExtraction, Any]],
    *,
    total_pages: int,
    source_date_span: tuple[str | None, str | None] = (None, None),
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    warnings: list[str] = []
    response_ids: list[str] = []
    document_title = ""
    response_model = DEFAULT_AI_MODEL

    for start_page, end_page, parsed, response in chunks:
        document_title = document_title or parsed.document_title
        response_model = getattr(response, "model", response_model)
        response_id = str(getattr(response, "id", "") or "")
        if response_id:
            response_ids.append(response_id)
        records.extend(event.model_dump() for event in parsed.events)
        page_label = str(start_page) if start_page == end_page else f"{start_page}-{end_page}"
        warnings.extend(
            f"Pages {page_label}: {warning}"
            for warning in parsed.warnings
        )
        if not parsed.events:
            warnings.append(
                f"Pages {page_label} produced no scheduled events. Confirm those pages are intentionally empty."
            )

    events = pd.DataFrame(records, columns=EVENT_COLUMNS)
    event_date_start = None
    event_date_end = None
    if not events.empty:
        event_identity = [
            "date",
            "start_time",
            "end_time",
            "conduct",
            "location",
            "remarks",
        ]
        events = events.drop_duplicates(subset=event_identity, keep="first")
        events["_date_sort"] = pd.to_datetime(events["date"], errors="coerce")
        valid_event_dates = events["_date_sort"].dropna()
        if not valid_event_dates.empty:
            event_date_start = valid_event_dates.min().strftime("%Y-%m-%d")
            event_date_end = valid_event_dates.max().strftime("%Y-%m-%d")
        events = (
            events.sort_values(
                ["_date_sort", "start_time", "end_time", "conduct"],
                kind="stable",
                na_position="last",
            )
            .drop(columns="_date_sort")
            .reset_index(drop=True)
        )

    source_date_start, source_date_end = source_date_span
    if source_date_end and event_date_end:
        source_end_month = pd.Period(source_date_end, freq="M")
        event_end_month = pd.Period(event_date_end, freq="M")
        if event_end_month < source_end_month:
            warnings.insert(
                0,
                "Possible incomplete extraction: the PDF reaches "
                f"{source_end_month.strftime('%B %Y')}, but extracted events stop in "
                f"{event_end_month.strftime('%B %Y')}. Review the final page groups.",
            )

    page_ranges = [
        str(start_page) if start_page == end_page else f"{start_page}-{end_page}"
        for start_page, end_page, _, _ in chunks
    ]
    return {
        "document_title": document_title,
        "events": events,
        "warnings": list(dict.fromkeys(warnings)),
        "model": response_model,
        "response_id": response_ids[0] if response_ids else "",
        "response_ids": response_ids,
        "source_page_count": total_pages,
        "chunks_processed": len(chunks),
        "page_ranges": page_ranges,
        "coverage_label": f"{total_pages}/{total_pages} PDF pages",
        "source_date_start": source_date_start,
        "source_date_end": source_date_end,
        "event_date_start": event_date_start,
        "event_date_end": event_date_end,
    }


def extract_training_plan_with_ai(
    path: str | Path,
    *,
    api_key: str,
    client: Any | None = None,
    period_definitions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Extract a training plan with GPT-5.6 Luna Structured Outputs."""
    source_path = Path(path)
    if not source_path.is_file():
        raise FileNotFoundError(f"Training plan was not found: {source_path}")
    if not api_key.strip():
        raise ValueError("Set OPENAI_API_KEY in Streamlit Secrets before using AI reading.")
    if source_path.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise ValueError(
            "AI reading supports PDF, PNG, JPG, WEBP, GIF, CSV, TSV, XLS, XLSX, and XLSM files."
        )
    if source_path.stat().st_size >= MAX_AI_FILE_BYTES:
        raise ValueError("The AI input must be smaller than 50 MB.")

    if client is None:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("Install the OpenAI Python package from requirements.txt.") from exc
        client = OpenAI(api_key=api_key)

    extraction_prompt = _prompt_with_period_definitions(period_definitions)

    if source_path.suffix.lower() == ".pdf":
        try:
            reader = PdfReader(source_path)
            total_pages = len(reader.pages)
        except Exception as exc:
            raise ValueError("The PDF could not be opened for complete page-by-page extraction.") from exc
        if total_pages < 1:
            raise ValueError("The PDF contains no pages.")
        source_date_span = _pdf_date_span(reader)

        chunks: list[tuple[int, int, TrainingPlanExtraction, Any]] = []
        with tempfile.TemporaryDirectory(prefix="tp_ai_pdf_") as temp_dir:
            temp_path = Path(temp_dir)
            for first_index in range(0, total_pages, PDF_PAGES_PER_REQUEST):
                last_index = min(first_index + PDF_PAGES_PER_REQUEST, total_pages)
                start_page = first_index + 1
                end_page = last_index
                writer = PdfWriter()
                for page_index in range(first_index, last_index):
                    writer.add_page(reader.pages[page_index])
                chunk_path = temp_path / (
                    f"{source_path.stem}_pages_{start_page:03d}-{end_page:03d}.pdf"
                )
                with chunk_path.open("wb") as chunk_file:
                    writer.write(chunk_file)
                parsed, response = _request_extraction(
                    client,
                    chunk_path,
                    prompt=_chunk_prompt(
                        start_page,
                        end_page,
                        total_pages,
                        base_prompt=extraction_prompt,
                    ),
                )
                chunks.append((start_page, end_page, parsed, response))
        return _merge_extraction_chunks(
            chunks,
            total_pages=total_pages,
            source_date_span=source_date_span,
        )

    parsed, response = _request_extraction(
        client,
        source_path,
        prompt=extraction_prompt,
    )
    events = pd.DataFrame(
        [event.model_dump() for event in parsed.events],
        columns=EVENT_COLUMNS,
    )
    return {
        "document_title": parsed.document_title,
        "events": events,
        "warnings": list(parsed.warnings),
        "model": getattr(response, "model", DEFAULT_AI_MODEL),
        "response_id": getattr(response, "id", ""),
        "response_ids": [getattr(response, "id", "")] if getattr(response, "id", "") else [],
        "source_page_count": None,
        "chunks_processed": 1,
        "page_ranges": [],
        "coverage_label": "Complete uploaded file",
        "source_date_start": None,
        "source_date_end": None,
        "event_date_start": None,
        "event_date_end": None,
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
