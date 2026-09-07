"""Google Form pre-filled URL generation."""

from .legacy_importer import GoogleFormSubmitter as _LegacyGoogleFormSubmitter


class GoogleFormSubmitter(_LegacyGoogleFormSubmitter):
    """Generate a pre-filled resource-booking form URL."""


__all__ = ["GoogleFormSubmitter"]

