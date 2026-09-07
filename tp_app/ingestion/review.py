"""Normalise and validate the editable event table before downstream use."""

from __future__ import annotations

import re
from typing import Any

import pandas as pd

from .models import EVENT_COLUMNS


class ReviewedEventValidator:
    """Validate human-reviewed AI events and return canonical values."""

    @staticmethod
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
            return pd.to_datetime(text, errors="raise").strftime("%H:%M")
        except Exception:
            return None

    @staticmethod
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

    @staticmethod
    def _normalise_boolean(value: Any) -> bool:
        if isinstance(value, str):
            return value.strip().casefold() in {"1", "true", "yes", "y", "checked"}
        return False if pd.isna(value) else bool(value)

    def validate(
        self,
        frame: pd.DataFrame,
    ) -> tuple[pd.DataFrame, list[str], list[str]]:
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

            parsed_date = self._normalise_date(row["date"])
            start_time = self._normalise_time(row["start_time"])
            end_time = self._normalise_time(row["end_time"])
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
                warnings.append(
                    f"Row {position}: no location; it will not create a facility booking."
                )
            try:
                confidence = float(row["confidence"])
            except (TypeError, ValueError):
                confidence = 0.0
            confidence = min(1.0, max(0.0, confidence))
            needs_review = self._normalise_boolean(row["needs_review"]) or confidence < 0.75
            if needs_review:
                warnings.append(f"Row {position}: marked for human review.")

            cleaned_rows.append(
                {
                    "date": parsed_date or "",
                    "start_time": start_time or "",
                    "end_time": end_time or "",
                    "conduct": conduct,
                    "location": location,
                    "remarks": "" if pd.isna(row["remarks"]) else str(row["remarks"]).strip(),
                    "source_reference": ""
                    if pd.isna(row["source_reference"])
                    else str(row["source_reference"]).strip(),
                    "confidence": confidence,
                    "needs_review": needs_review,
                }
            )

        cleaned = pd.DataFrame(cleaned_rows, columns=EVENT_COLUMNS)
        if cleaned.empty:
            errors.append("The reviewed plan must contain at least one event.")
        else:
            duplicate_mask = cleaned.duplicated(
                subset=["date", "start_time", "end_time", "conduct", "location"],
                keep=False,
            )
            if duplicate_mask.any():
                warnings.append("The table contains duplicate scheduled events.")
        return cleaned, list(dict.fromkeys(errors)), list(dict.fromkeys(warnings))

