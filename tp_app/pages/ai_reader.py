"""AI training-plan reader page."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import streamlit as st

from tp_app.context import AI_STATE_KEYS, ApplicationContext
from tp_app.ingestion import (
    DEFAULT_AI_MODEL,
    EVENT_COLUMNS,
    ReviewedEventValidator,
    TrainingPlanExtractor,
)
from tp_app.openai_access import OpenAIKeyManager
from tp_app.ui_helpers import render_page_header, run_action


class AIReaderPage:
    """Collect credentials and turn an uploaded plan into reviewed events."""

    def __init__(self, context: ApplicationContext) -> None:
        self.context = context
        self.key_manager = OpenAIKeyManager(context)
        self.validator = ReviewedEventValidator()

    def render(self) -> None:
        render_page_header(
            "Flexible ingestion",
            "Read flexible training-plan layouts",
            "Upload a spreadsheet, PDF, or scan. AI converts visual boxes and unfamiliar layouts into one editable event table before anything reaches SIAO or booking generation.",
        )
        st.warning(
            "The uploaded plan is sent to OpenAI for document understanding. Do not use this feature if your information-handling policy prohibits third-party cloud processing. Always review the extracted table."
        )

        key_status = self.key_manager.render()
        st.divider()
        ai_upload = st.file_uploader(
            "Training plan",
            type=[
                "pdf",
                "png",
                "jpg",
                "jpeg",
                "webp",
                "gif",
                "csv",
                "tsv",
                "xlsx",
                "xls",
                "xlsm",
            ],
            key="ai_training_plan_upload",
            help="Maximum 50 MB. PDFs may contain scans, pictures, or visual timetable boxes.",
        )
        st.caption(
            "If a spreadsheet relies on drawings or embedded images, export it to PDF first so the visual layout is included."
        )
        if ai_upload is not None and Path(ai_upload.name).suffix.lower() == ".pdf":
            st.caption(
                "For completeness, PDFs are checked two pages at a time and merged. "
                "Long plans can take several minutes and use multiple API requests."
            )

        source_path = self._stage_source(ai_upload)
        if st.button(
            "Extract editable schedule with AI",
            type="primary",
            disabled=source_path is None or not key_status.value,
            use_container_width=True,
        ):
            self.context.clear_state(AI_STATE_KEYS)
            extraction = run_action(
                lambda: TrainingPlanExtractor(api_key=key_status.value).extract(
                    source_path,
                    period_definitions=self.context.config.get("timetable", {}).get(
                        "periods", {}
                    ),
                ),
                "AI extraction completed. Review every row below.",
            )
            if extraction:
                st.session_state.ai_extraction = extraction
                st.session_state.pop("ai_event_editor", None)

        extraction = st.session_state.get("ai_extraction")
        if extraction:
            self._render_extraction(extraction)

    def _stage_source(self, upload: Any | None) -> Path | None:
        if upload is None:
            return None
        upload_signature = hashlib.sha256(upload.getvalue()).hexdigest()
        if st.session_state.get("ai_source_signature") != upload_signature:
            st.session_state.ai_source_signature = upload_signature
            self.context.clear_state(AI_STATE_KEYS)
        return self.context.stage_uploaded_file("ai_input_data", upload)

    def _render_extraction(self, extraction: dict[str, Any]) -> None:
        title_col, model_col, event_col, coverage_col = st.columns([2, 1, 1, 1.2])
        title_col.metric("Document", extraction.get("document_title") or "Untitled")
        model_col.metric("Model", extraction.get("model") or DEFAULT_AI_MODEL)
        event_col.metric("Events", len(extraction["events"]))
        coverage_col.metric(
            "Coverage", extraction.get("coverage_label") or "Complete file"
        )
        if extraction.get("source_date_start") and extraction.get("source_date_end"):
            extracted_span = "unknown"
            if extraction.get("event_date_start") and extraction.get("event_date_end"):
                extracted_span = (
                    f"{extraction['event_date_start']} to {extraction['event_date_end']}"
                )
            st.caption(
                "Detected PDF span: "
                f"{extraction['source_date_start']} to {extraction['source_date_end']} · "
                f"extracted event span: {extracted_span}"
            )
        for warning in extraction.get("warnings", []):
            st.warning(warning)

        st.subheader("Review and edit")
        st.caption(
            "Correct uncertain text, dates, times, conducts, and locations. Add or delete rows as needed."
        )
        edited_events = st.data_editor(
            extraction["events"],
            num_rows="dynamic",
            height=480,
            use_container_width=True,
            hide_index=True,
            key="ai_event_editor",
            column_order=EVENT_COLUMNS,
            column_config={
                "date": st.column_config.TextColumn("Date · YYYY-MM-DD", required=True),
                "start_time": st.column_config.TextColumn("Start · HH:MM", required=True),
                "end_time": st.column_config.TextColumn("End · HH:MM", required=True),
                "conduct": st.column_config.TextColumn(
                    "Conduct", required=True, width="large"
                ),
                "location": st.column_config.TextColumn("Location", width="medium"),
                "remarks": st.column_config.TextColumn("Remarks", width="large"),
                "source_reference": st.column_config.TextColumn(
                    "Source", disabled=True
                ),
                "confidence": st.column_config.NumberColumn(
                    "Confidence",
                    min_value=0.0,
                    max_value=1.0,
                    format="%.2f",
                    disabled=True,
                ),
                "needs_review": st.column_config.CheckboxColumn("Review"),
            },
        )
        cleaned_events, event_errors, event_warnings = self.validator.validate(
            edited_events
        )
        review_hash = hashlib.sha256(
            cleaned_events.to_csv(index=False).encode("utf-8")
        ).hexdigest()
        self._invalidate_changed_approval(review_hash)
        self._render_review_messages(event_errors, event_warnings)
        self._render_approval_actions(cleaned_events, event_errors, review_hash)

    def _invalidate_changed_approval(self, review_hash: str) -> None:
        approved_hash = st.session_state.get("approved_ai_events_hash")
        if approved_hash and approved_hash != review_hash:
            self.context.clear_state(
                (
                    "approved_ai_events",
                    "approved_ai_events_hash",
                    "approved_ai_event_errors",
                    "siao_result",
                    "siao_result_cadet_size",
                    "booking_result",
                )
            )
            st.info("The table changed. Approve it again before generating outputs.")

    @staticmethod
    def _render_review_messages(
        event_errors: list[str],
        event_warnings: list[str],
    ) -> None:
        if event_errors:
            st.caption(f"Approval issues · {len(event_errors)}")
            with st.container(height=260, border=True, key="ai_approval_issues_scroll"):
                st.error(
                    "Resolve these issues before approval:\n\n- "
                    + "\n- ".join(event_errors)
                )
            st.warning(
                "You can approve the schedule without resolving these issues, "
                "but SIAO or booking generation may reject incomplete rows."
            )
        if event_warnings:
            st.caption(f"Review warnings · {len(event_warnings)}")
            with st.container(height=260, border=True, key="ai_review_warnings_scroll"):
                for warning in event_warnings:
                    st.warning(warning)

    def _approve(self, cleaned_events: Any, review_hash: str, errors=None) -> None:
        st.session_state.approved_ai_events = cleaned_events.copy()
        st.session_state.approved_ai_events_hash = review_hash
        if errors:
            st.session_state.approved_ai_event_errors = list(errors)
        else:
            st.session_state.pop("approved_ai_event_errors", None)
        self.context.clear_state(("siao_result", "siao_result_cadet_size", "booking_result"))

    def _render_approval_actions(
        self,
        cleaned_events: Any,
        event_errors: list[str],
        review_hash: str,
    ) -> None:
        if event_errors:
            approve_col, warning_col, download_col = st.columns(3)
        else:
            approve_col, download_col = st.columns(2)
            warning_col = None

        with approve_col:
            if st.button(
                "Approve and use this schedule",
                type="primary",
                disabled=bool(event_errors),
                use_container_width=True,
            ):
                self._approve(cleaned_events, review_hash)
                st.success(
                    "Approved. SIAO and Facility booking will now use this reviewed table."
                )
        if warning_col is not None:
            with warning_col:
                if st.button(
                    "⚠ Approve with issues",
                    disabled=cleaned_events.empty,
                    use_container_width=True,
                ):
                    self._approve(cleaned_events, review_hash, event_errors)
                    st.warning(
                        "Approved with unresolved issues. Check generated outputs carefully."
                    )
        with download_col:
            st.download_button(
                "Download reviewed events CSV",
                cleaned_events.to_csv(index=False).encode("utf-8-sig"),
                file_name="reviewed_training_plan.csv",
                mime="text/csv",
                use_container_width=True,
            )

        if "approved_ai_events" in st.session_state:
            st.success(
                f"AI-reviewed schedule active · {len(st.session_state.approved_ai_events)} events"
            )
            unresolved = st.session_state.get("approved_ai_event_errors")
            if unresolved:
                st.warning(
                    f"This active schedule has {len(unresolved)} unresolved issue(s). "
                    "Output generation may fail for incomplete rows."
                )
            if st.button("Stop using this AI schedule", use_container_width=True):
                self.context.clear_state(
                    (
                        "approved_ai_events",
                        "approved_ai_events_hash",
                        "approved_ai_event_errors",
                        "siao_result",
                        "siao_result_cadet_size",
                        "booking_result",
                    )
                )
                st.rerun()

