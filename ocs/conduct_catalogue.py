"""Object-oriented access to conduct-catalogue operations."""

from .legacy_importer import (
    build_preparation_schedule,
    load_conduct_catalog,
    match_catalog_conduct,
    normalize_conduct_name,
    validate_conduct_catalog,
)


class ConductCatalogue:
    """Load, validate, and match stable conduct rules."""

    load = staticmethod(load_conduct_catalog)
    validate = staticmethod(validate_conduct_catalog)
    match = staticmethod(match_catalog_conduct)
    normalize_name = staticmethod(normalize_conduct_name)
    build_preparation_schedule = staticmethod(build_preparation_schedule)


__all__ = ["ConductCatalogue"]

