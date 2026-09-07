"""Training-plan workbook importer."""

from .legacy_importer import Importer as _LegacyImporter


class TrainingPlanImporter(_LegacyImporter):
    """Read and normalise timetable workbooks before schedule extraction."""


# Preserve the established public name used by app_services and older scripts.
Importer = TrainingPlanImporter

__all__ = ["Importer", "TrainingPlanImporter"]

