"""Facility-booking and booking-email helpers."""

from .legacy_importer import (
    build_booking_email_html,
    dataframe_to_email_table,
    match_facility,
    merge_bookings,
    send_email,
)


class BookingService:
    """Group booking operations behind one named service."""

    match_facility = staticmethod(match_facility)
    merge = staticmethod(merge_bookings)
    email_table = staticmethod(dataframe_to_email_table)
    email_html = staticmethod(build_booking_email_html)
    send_email = staticmethod(send_email)


__all__ = ["BookingService"]

