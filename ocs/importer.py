"""Compatibility entry point for the refactored OCS automation modules.

Existing code may continue importing ``Importer``, ``Extractor``, and helper
functions from this file. New code should import the focused classes directly.
"""

from ocs.legacy_importer import *  # noqa: F403
from ocs.legacy_importer import _previous_working_day
from ocs.booking_service import BookingService
from ocs.conduct_catalogue import ConductCatalogue
from ocs.google_forms import GoogleFormSubmitter
from ocs.siao_extractor import Extractor, SIAOExtractor
from ocs.training_plan_importer import Importer, TrainingPlanImporter

__all__ = [
    "BookingService",
    "ConductCatalogue",
    "Extractor",
    "GoogleFormSubmitter",
    "Importer",
    "SIAOExtractor",
    "TrainingPlanImporter",
]


if __name__ == "__main__":
    import runpy

    runpy.run_module("ocs.legacy_importer", run_name="__main__")
