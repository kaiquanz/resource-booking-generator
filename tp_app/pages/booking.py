"""Facility-booking draft page."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app_services import (
    build_booking_email_content,
    generate_bookings,
    generate_bookings_from_events,
    send_booking_email,
)
from tp_app.context import ApplicationContext
from tp_app.ui_helpers import (
    BOOKING_DATE_COLUMNS,
    booking_table_for_display,
    content_hash,
    render_page_header,
    render_rich_email_copy_button,
    run_action,
)


class BookingPage:
    """Generate OCS rows and a reviewable SAFTI email draft."""

    def __init__(self, context: ApplicationContext) -> None:
        self.context = context

    def render(self) -> None:
        render_page_header(
            "Resource booking",
            "Prepare OCS and SAFTI bookings",
            "Generate the OCS copy-and-paste list and review the SAFTI email before choosing to send it.",
        )

        approved_events = st.session_state.get("approved_ai_events")
        if isinstance(approved_events, pd.DataFrame):
            st.info(f"Using approved AI-readable schedule · {len(approved_events)} events")
            unresolved = st.session_state.get("approved_ai_event_errors")
            if unresolved:
                st.warning(
                    f"This schedule was approved with {len(unresolved)} unresolved "
                    "issue(s). Check all booking times and dates carefully."
                )
        if st.button("Generate booking draft", type="primary"):
            st.session_state.pop("booking_result", None)
            result = run_action(
                lambda: (
                    generate_bookings_from_events(self.context.config, approved_events)
                    if isinstance(approved_events, pd.DataFrame)
                    else generate_bookings(self.context.config)
                ),
                "Booking draft generated.",
            )
            if result:
                st.session_state.booking_result = result

        result = st.session_state.get("booking_result")
        if result:
            self._render_result(result)

    def _render_result(self, result: dict) -> None:
        ocs_tab, safti_tab = st.tabs(
            [
                f"OCS facilities · {len(result['ocs'])}",
                f"SAFTI facilities · {len(result['safti'])}",
            ]
        )
        with ocs_tab:
            st.caption("Use the copy icon on the block below, or download the CSV.")
            st.code(result["ocs_copy_text"], language=None)
            st.dataframe(
                booking_table_for_display(result["ocs"]),
                width='stretch',
                hide_index=True,
                column_config=BOOKING_DATE_COLUMNS,
            )
            st.download_button(
                "Download OCS bookings",
                result["ocs_csv"],
                file_name="ocs_booking.csv",
                mime="text/csv",
            )

        with safti_tab:
            self._render_safti(result)

    def _render_safti(self, result: dict) -> None:
        draft = result["email_draft"]
        recipient = str(draft.get("to", "")).strip()
        st.text_input("To", value=recipient, disabled=True)
        st.text_input("Subject", value=draft["subject"], disabled=True)
        if not recipient:
            st.info(
                "No recipient email is configured. Copy the complete draft below into your preferred email app."
            )
            edited_body = draft["body"]
        else:
            edited_body = st.text_area(
                "Email introduction", value=draft["body"], height=110
            )

        copy_content = build_booking_email_content(draft, edited_body)
        copy_text = (
            f"Subject: {draft['subject']}\n\n{copy_content['plain']}"
        ).rstrip()
        render_rich_email_copy_button(copy_content["html"], copy_content["plain"])
        st.caption("Paste into Gmail or Outlook to retain the formatted booking table.")
        with st.expander("Plain-text copy fallback"):
            st.text_area(
                "Complete plain-text email draft",
                value=copy_text,
                height=260,
                key=f"safti_email_copy_{content_hash(copy_text)}",
            )
        st.dataframe(
            booking_table_for_display(result["safti"]),
            width='stretch',
            hide_index=True,
            column_config=BOOKING_DATE_COLUMNS,
        )
        if recipient and st.button("Send reviewed email", type="primary"):
            reviewed_draft = {**draft, "body": edited_body}
            run_action(
                lambda: send_booking_email(self.context.config, reviewed_draft),
                f"Email sent to {recipient}.",
            )

