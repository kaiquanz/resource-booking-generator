"""SIAO draft-generation page."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app_services import generate_siao, generate_siao_from_events
from tp_app.context import ApplicationContext
from tp_app.ui_helpers import render_page_header, run_action


class SIAOPage:
    """Generate and review draft SIAO outputs."""

    def __init__(self, context: ApplicationContext) -> None:
        self.context = context

    def render(self) -> None:
        render_page_header(
            "SIAO generator",
            "Build the draft in one pass",
            "Use the configured timetable, lesson plan and SIAO template to prepare a downloadable draft.",
        )

        left, right = st.columns([1, 1.45], gap="large")
        with left:
            cadet_size = st.number_input(
                "Cadet strength", min_value=1, max_value=2000, value=140, step=1
            )
            if (
                "siao_result" in st.session_state
                and st.session_state.get("siao_result_cadet_size") != int(cadet_size)
            ):
                self.context.clear_state(("siao_result", "siao_result_cadet_size"))

            approved_events = st.session_state.get("approved_ai_events")
            if isinstance(approved_events, pd.DataFrame):
                st.info(
                    f"Using approved AI-readable schedule · {len(approved_events)} events"
                )
                unresolved = st.session_state.get("approved_ai_event_errors")
                if unresolved:
                    st.warning(
                        f"This schedule was approved with {len(unresolved)} unresolved "
                        "issue(s). Check the generated SIAO carefully."
                    )
            if st.button(
                "Generate SIAO draft", type="primary", width='stretch'
            ):
                self.context.clear_state(("siao_result", "siao_result_cadet_size"))
                result = run_action(
                    lambda: (
                        generate_siao_from_events(
                            self.context.config, approved_events, int(cadet_size)
                        )
                        if isinstance(approved_events, pd.DataFrame)
                        else generate_siao(self.context.config, int(cadet_size))
                    ),
                    "Your SIAO draft is ready.",
                )
                if result:
                    st.session_state.siao_result = result
                    st.session_state.siao_result_cadet_size = int(cadet_size)

        with right:
            st.markdown(
                """<div class="soft-card"><strong>Creates a SIAO template based on the standardised TP</strong><br>
                Runs the draft generator against the selected TP and files from Settings.</div>""",
                unsafe_allow_html=True,
            )

        result = st.session_state.get("siao_result")
        if result:
            self._render_result(result)

    @staticmethod
    def _render_result(result: dict) -> None:
        report = result.get("match_report", pd.DataFrame())
        if not report.empty:
            unique_report = report.drop_duplicates(
                subset=["conduct", "status", "lesson_plan_name", "candidates"]
            )
            counts = unique_report["status"].value_counts()
            matched = int(counts.get("exact", 0) + counts.get("catalog", 0))
            unresolved = int(counts.get("unmatched", 0))
            ambiguous = int(
                counts.get("ambiguous", 0) + counts.get("invalid_target", 0)
            )
            inactive = int(counts.get("inactive", 0))
            metric_one, metric_two, metric_three, metric_four = st.columns(4)
            metric_one.metric("Matched", matched)
            metric_two.metric("Unresolved", unresolved)
            metric_three.metric("Needs review", ambiguous)
            metric_four.metric("Inactive", inactive)

            review_rows = unique_report[
                unique_report["status"].isin(
                    ["unmatched", "ambiguous", "invalid_target"]
                )
            ]
            if not review_rows.empty:
                st.warning(
                    "Some timetable entries were not placed into the SIAO. Review them before using the draft."
                )
                st.dataframe(review_rows, width='stretch', hide_index=True)

        for error in result.get("catalog_validation_errors", []):
            st.warning(error)

        for message in result.get("ce_signals_warnings", []):
            st.warning(message)
        bookings = result.get("ce_signals_bookings", [])
        if bookings:
            with st.expander("CE & Signals bookings"):
                st.caption("Quantities and date buffers use your saved CE & Signals settings. Scaled quantities round up; fixed quantities stay unchanged.")
                st.dataframe(pd.DataFrame(bookings)[["name", "quantity", "start", "end"]],
                             width='stretch', hide_index=True)

        st.subheader("Downloads")
        download_one, download_two = st.columns(2)
        with download_one:
            st.download_button(
                "Download SIAO CSV",
                result["csv"],
                file_name="draft_siao.csv",
                mime="text/csv",
                width='stretch',
            )
        with download_two:
            st.download_button(
                "Download formatted workbook",
                result["xlsx"],
                file_name="draft_siao.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                width='stretch',
            )
