"""Translate between conduct-catalogue YAML and the editable table."""

from __future__ import annotations

import copy
from typing import Any

import pandas as pd


class CatalogueMapper:
    """Pure conversion helpers for the Streamlit catalogue editor."""

    @staticmethod
    def _timing_mode(value: Any) -> str | None | Any:
        if pd.isna(value) or str(value).strip().casefold() in {
            "",
            "none",
            "inactive",
            "disabled",
        }:
            return None
        normalized = str(value).strip().casefold().replace("-", "_").replace(" ", "_")
        if normalized in {"in_camp", "incamp"}:
            return "in_camp"
        if normalized in {"external", "out_of_camp", "outcamp"}:
            return "external"
        return value

    @staticmethod
    def _lines(value: Any) -> list[str]:
        if pd.isna(value):
            return []
        return [line.strip() for line in str(value).splitlines() if line.strip()]

    @staticmethod
    def _integer(value: Any, default: int | None) -> Any:
        if pd.isna(value) or str(value).strip() == "":
            return default
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return value
        return int(numeric) if numeric.is_integer() else numeric

    @staticmethod
    def _boolean(value: Any, default: bool = False) -> bool | Any:
        if pd.isna(value) or str(value).strip() == "":
            return default
        if isinstance(value, bool):
            return value
        normalized = str(value).strip().casefold()
        if normalized in {"true", "yes", "1"}:
            return True
        if normalized in {"false", "no", "0"}:
            return False
        return value

    def to_frame(self, catalog: dict[str, Any]) -> pd.DataFrame:
        rows = []
        for rule in catalog.get("conducts", []):
            preparation = rule.get("preparation", {})
            if not isinstance(preparation, dict):
                preparation = {}

            def prep_value(item: str, field: str, default: Any = "") -> Any:
                item_settings = preparation.get(item, {})
                if not isinstance(item_settings, dict):
                    return default
                return item_settings.get(field, default)

            active_value = rule.get("active", True)
            active = (
                active_value
                if isinstance(active_value, bool)
                else self._timing_mode(active_value) in {"in_camp", "external"}
            )
            timing_mode = self._timing_mode(rule.get("timing", active_value))
            timing_label = {
                "in_camp": "In camp",
                "external": "Out of camp",
            }.get(timing_mode, "None")

            rows.append(
                {
                    "active": active,
                    "timing": timing_label,
                    "bus_required": bool(rule.get("bus_required", False)),
                    "conduct_id": rule.get("conduct_id", ""),
                    "lesson_plan_name": rule.get("lesson_plan_name", ""),
                    "display_name": rule.get("display_name", ""),
                    "use_display_name": bool(rule.get("use_display_name", False)),
                    "aliases": "\n".join(str(value) for value in rule.get("aliases", [])),
                    "exclusions": "\n".join(
                        str(value) for value in rule.get("exclusions", [])
                    ),
                    "multi_day": bool(rule.get("multi_day", False)),
                    "exercise_display_name": rule.get("exercise_display_name", ""),
                    "medic_minutes": prep_value("medic", "duration_minutes", 0),
                    "ammo_collection_minutes": prep_value(
                        "ammo_collection", "duration_minutes", 0
                    ),
                    "transport_minutes": prep_value(
                        "transport", "duration_minutes", 0
                    ),
                    "vehicle_minutes": prep_value("vehicle", "duration_minutes", 0),
                }
            )
        return pd.DataFrame(rows)

    def from_frame(
        self,
        frame: pd.DataFrame,
        original: dict[str, Any],
    ) -> dict[str, Any]:
        catalog = copy.deepcopy(original)
        conducts = []
        for _, row in frame.iterrows():
            conduct_id = (
                "" if pd.isna(row.get("conduct_id")) else str(row["conduct_id"]).strip()
            )
            if not conduct_id and all(
                pd.isna(row.get(key)) for key in ("lesson_plan_name", "aliases")
            ):
                continue
            rule = {
                "conduct_id": conduct_id,
                "lesson_plan_name": ""
                if pd.isna(row.get("lesson_plan_name"))
                else str(row["lesson_plan_name"]).strip(),
                "display_name": ""
                if pd.isna(row.get("display_name"))
                else str(row["display_name"]).strip(),
                "use_display_name": self._boolean(row.get("use_display_name"), False),
                "aliases": self._lines(row.get("aliases")),
                "exclusions": self._lines(row.get("exclusions")),
                "multi_day": self._boolean(row.get("multi_day"), False),
                "active": self._boolean(row.get("active"), False),
                "timing": self._timing_mode(row.get("timing")),
                "bus_required": self._boolean(row.get("bus_required"), False),
                "preparation": {
                    "medic": {
                        "duration_minutes": self._integer(row.get("medic_minutes"), 0)
                    },
                    "ammo_collection": {
                        "duration_minutes": self._integer(
                            row.get("ammo_collection_minutes"), 0
                        )
                    },
                    "transport": {
                        "duration_minutes": self._integer(
                            row.get("transport_minutes"), 0
                        )
                    },
                    "vehicle": {
                        "duration_minutes": self._integer(
                            row.get("vehicle_minutes"), 0
                        )
                    },
                },
            }
            exercise_name = row.get("exercise_display_name")
            if not pd.isna(exercise_name) and str(exercise_name).strip():
                rule["exercise_display_name"] = str(exercise_name).strip()
            conducts.append(rule)
        catalog["conducts"] = conducts
        catalog["version"] = max(int(catalog.get("version", 1) or 1), 3)
        return catalog

