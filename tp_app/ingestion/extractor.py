"""OpenAI-backed extractor for flexible training-plan layouts."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import pandas as pd
from pypdf import PdfReader, PdfWriter

from .models import (
    DEFAULT_AI_MODEL,
    EVENT_COLUMNS,
    MAX_AI_FILE_BYTES,
    MAX_AI_OUTPUT_TOKENS,
    PDF_PAGES_PER_REQUEST,
    SUPPORTED_SUFFIXES,
    TrainingPlanExtraction,
)
from .sources import (
    build_ai_input,
    chunk_prompt,
    pdf_date_span,
    prompt_with_period_definitions,
)


class TrainingPlanExtractor:
    """Extract one uploaded training plan into the canonical event schema."""

    def __init__(
        self,
        *,
        api_key: str,
        client: Any | None = None,
        model: str = DEFAULT_AI_MODEL,
    ) -> None:
        self.api_key = str(api_key or "").strip()
        self.client = client
        self.model = model

    def _client(self) -> Any:
        if self.client is not None:
            return self.client
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError(
                "Install the OpenAI Python package from requirements.txt."
            ) from exc
        self.client = OpenAI(api_key=self.api_key)
        return self.client

    @staticmethod
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
                    raise RuntimeError(
                        f"The AI could not process this file: {item.refusal}"
                    )

    def _request(
        self,
        source_path: Path,
        *,
        prompt: str,
    ) -> tuple[TrainingPlanExtraction, Any]:
        try:
            response = self._client().responses.parse(
                model=self.model,
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
                raise RuntimeError(
                    "OpenAI rejected the API key. Check the personal key entered in the app."
                ) from exc
            if error_name == "RateLimitError":
                raise RuntimeError(
                    "OpenAI is rate-limited or the project has insufficient quota. Try again later."
                ) from exc
            if error_name in {"APIConnectionError", "APITimeoutError"}:
                raise RuntimeError(
                    "The app could not reach OpenAI. Try the extraction again."
                ) from exc
            raise

        self._raise_for_non_result(response)
        parsed = getattr(response, "output_parsed", None)
        if parsed is None:
            raise RuntimeError("The AI returned no structured training-plan data.")
        return parsed, response

    def _merge_chunks(
        self,
        chunks: list[tuple[int, int, TrainingPlanExtraction, Any]],
        *,
        total_pages: int,
        source_date_span: tuple[str | None, str | None] = (None, None),
    ) -> dict[str, Any]:
        records: list[dict[str, Any]] = []
        warnings: list[str] = []
        response_ids: list[str] = []
        document_title = ""
        response_model = self.model

        for start_page, end_page, parsed, response in chunks:
            document_title = document_title or parsed.document_title
            response_model = getattr(response, "model", response_model)
            response_id = str(getattr(response, "id", "") or "")
            if response_id:
                response_ids.append(response_id)
            records.extend(event.model_dump() for event in parsed.events)
            page_label = (
                str(start_page)
                if start_page == end_page
                else f"{start_page}-{end_page}"
            )
            warnings.extend(
                f"Pages {page_label}: {warning}" for warning in parsed.warnings
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
            str(start_page)
            if start_page == end_page
            else f"{start_page}-{end_page}"
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

    def extract(
        self,
        path: str | Path,
        *,
        period_definitions: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Extract the supplied file, chunking PDFs to guarantee page coverage."""
        source_path = Path(path)
        if not source_path.is_file():
            raise FileNotFoundError(f"Training plan was not found: {source_path}")
        if not self.api_key:
            raise ValueError("Enter an OpenAI API key before using AI reading.")
        if source_path.suffix.lower() not in SUPPORTED_SUFFIXES:
            raise ValueError(
                "AI reading supports PDF, PNG, JPG, WEBP, GIF, CSV, TSV, XLS, XLSX, and XLSM files."
            )
        if source_path.stat().st_size >= MAX_AI_FILE_BYTES:
            raise ValueError("The AI input must be smaller than 50 MB.")

        extraction_prompt = prompt_with_period_definitions(period_definitions)
        if source_path.suffix.lower() == ".pdf":
            try:
                reader = PdfReader(source_path)
                total_pages = len(reader.pages)
            except Exception as exc:
                raise ValueError(
                    "The PDF could not be opened for complete page-by-page extraction."
                ) from exc
            if total_pages < 1:
                raise ValueError("The PDF contains no pages.")
            source_date_span = pdf_date_span(reader)

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
                    parsed, response = self._request(
                        chunk_path,
                        prompt=chunk_prompt(
                            start_page,
                            end_page,
                            total_pages,
                            base_prompt=extraction_prompt,
                        ),
                    )
                    chunks.append((start_page, end_page, parsed, response))
            return self._merge_chunks(
                chunks,
                total_pages=total_pages,
                source_date_span=source_date_span,
            )

        parsed, response = self._request(source_path, prompt=extraction_prompt)
        events = pd.DataFrame(
            [event.model_dump() for event in parsed.events],
            columns=EVENT_COLUMNS,
        )
        response_id = getattr(response, "id", "")
        return {
            "document_title": parsed.document_title,
            "events": events,
            "warnings": list(parsed.warnings),
            "model": getattr(response, "model", self.model),
            "response_id": response_id,
            "response_ids": [response_id] if response_id else [],
            "source_page_count": None,
            "chunks_processed": 1,
            "page_ranges": [],
            "coverage_label": "Complete uploaded file",
            "source_date_start": None,
            "source_date_end": None,
            "event_date_start": None,
            "event_date_end": None,
        }

