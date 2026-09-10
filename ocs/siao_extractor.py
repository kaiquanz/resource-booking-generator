"""SIAO and facility-booking extraction service."""

from . import legacy_importer as _legacy
from .legacy_importer import Extractor as _LegacyExtractor


class SIAOExtractor(_LegacyExtractor):
    """Map normalised training events into SIAO and booking outputs."""

    def draft_siao(self, cadet_size: int, output_path=None):
        # The original method resolves its current extractor through a module
        # global. Keep that legacy contract contained inside this adapter.
        _legacy.data_change = self
        return super().draft_siao(cadet_size, output_path=output_path)


Extractor = SIAOExtractor

__all__ = ["Extractor", "SIAOExtractor"]
