"""Compatibility facade for the modular AI ingestion package.

New application code should import the focused classes from ``tp_app.ingestion``.
These exports keep existing scripts and tests working while older callers migrate.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from tp_app.ingestion.extractor import TrainingPlanExtractor
from tp_app.ingestion.models import (
    DEFAULT_AI_MODEL,
    EVENT_COLUMNS,
    EXTRACTION_PROMPT,
    IMAGE_SUFFIXES,
    MAX_AI_FILE_BYTES,
    MAX_AI_OUTPUT_TOKENS,
    PDF_PAGES_PER_REQUEST,
    SUPPORTED_SUFFIXES,
    TrainingPlanEvent,
    TrainingPlanExtraction,
)
from tp_app.ingestion.review import ReviewedEventValidator
from tp_app.ingestion.sources import (
    build_ai_input,
    chunk_prompt as _chunk_prompt,
    date_span_from_texts as _date_span_from_texts,
    prompt_with_period_definitions as _prompt_with_period_definitions,
)


def extract_training_plan_with_ai(
    path: str | Path,
    *,
    api_key: str,
    client: Any | None = None,
    period_definitions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Backward-compatible functional entry point for AI extraction."""
    return TrainingPlanExtractor(api_key=api_key, client=client).extract(
        path,
        period_definitions=period_definitions,
    )


def validate_reviewed_events(
    frame: pd.DataFrame,
) -> tuple[pd.DataFrame, list[str], list[str]]:
    """Backward-compatible functional entry point for event validation."""
    return ReviewedEventValidator().validate(frame)


__all__ = [
    "DEFAULT_AI_MODEL",
    "EVENT_COLUMNS",
    "EXTRACTION_PROMPT",
    "IMAGE_SUFFIXES",
    "MAX_AI_FILE_BYTES",
    "MAX_AI_OUTPUT_TOKENS",
    "PDF_PAGES_PER_REQUEST",
    "SUPPORTED_SUFFIXES",
    "TrainingPlanEvent",
    "TrainingPlanExtraction",
    "TrainingPlanExtractor",
    "ReviewedEventValidator",
    "build_ai_input",
    "extract_training_plan_with_ai",
    "validate_reviewed_events",
]
