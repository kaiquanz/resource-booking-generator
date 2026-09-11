"""Lesson, timing, and general settings pages."""

from __future__ import annotations

import copy
import re
from pathlib import Path

import streamlit as st
import yaml

from app_services import resolve_configured_path
from tp_app.context import AI_STATE_KEYS, OUTPUT_STATE_KEYS, ApplicationContext
from tp_app.ui_helpers import render_page_header
from tp_app.ce_signals_settings import render_ce_settings


class SettingsPage:
    """Edit browser-scoped app settings without changing repository defaults."""

    def __init__(self, context: ApplicationContext) -> None:
        self.context = context

    def render(self) -> None:
        render_page_header(
            "Local settings",
            "Settings",
            "Lesson inputs, shared timing presets, and account details are kept in separate sections. Saved values are encrypted and kept in this browser.",
        )
        section = st.radio(
            "Settings section",
            ["Lesson settings", "Timing settings", "CE & Signals", "General settings"],
            horizontal=True,
            label_visibility="collapsed",
        )
        if section == "Lesson settings":
            self._render_lesson_settings()
        elif section == "Timing settings":
            self._render_timing_settings()
        elif section == "CE & Signals":
            render_ce_settings(self.context)
        else:
            self._render_general_settings()
        self._render_reset_and_export()

    def _render_lesson_settings(self) -> None:
        st.subheader("Lesson files")
        st.caption(
            "Upload the training plan, lesson plan, SIAO workbook, or conduct catalogue used by this browser session."
        )
        managed_files = (
            ("input_data", "Training plan input (TP)", ["csv", "xlsx", "xlsm", "xls"]),
            ("lesson_plan", "Lesson plan input", ["csv"]),
            ("siao_template", "SIAO template workbook", ["xlsx", "xlsm"]),
            ("conduct_catalog", "Conduct catalogue", ["yaml", "yml"]),
        )
        for key, label, file_types in managed_files:
            self._render_managed_file(key, label, file_types)

        edited = copy.deepcopy(self.context.config)
        with st.form("lesson_settings_form"):
            st.subheader("Timetable periods")
            period_col_one, period_col_two = st.columns(2)
            with period_col_one:
                period_zero_start = st.text_input(
                    "Period 0 start (HH:MM)",
                    value=self.context.nested_get(
                        edited,
                        ("timetable", "periods", "0", "start_time"),
                        "07:00",
                    ),
                )
            with period_col_two:
                period_zero_end = st.text_input(
                    "Period 0 end (HH:MM)",
                    value=self.context.nested_get(
                        edited,
                        ("timetable", "periods", "0", "end_time"),
                        "07:50",
                    ),
                )
            save_lesson = st.form_submit_button(
                "Save lesson settings", type="primary"
            )

        if not save_lesson:
            return
        lesson_times = {
            "Period 0 start": period_zero_start,
            "Period 0 end": period_zero_end,
        }
        invalid = [
            label
            for label, value in lesson_times.items()
            if not self._is_time(value)
        ]
        if invalid:
            st.error("Use 24-hour HH:MM for: " + ", ".join(invalid))
            return
        self.context.nested_set(
            edited,
            ("timetable", "periods", "0", "start_time"),
            period_zero_start.strip(),
        )
        self.context.nested_set(
            edited,
            ("timetable", "periods", "0", "end_time"),
            period_zero_end.strip(),
        )
        self.context.save_config(edited, clear_keys=OUTPUT_STATE_KEYS)
        st.success("Lesson settings saved in this browser.")

    def _render_managed_file(
        self,
        key: str,
        label: str,
        file_types: list[str],
    ) -> None:
        st.markdown(f"**{label}**")
        upload_col, download_col = st.columns([1.55, 1], gap="medium")
        with upload_col:
            uploaded = st.file_uploader(
                f"Upload {label}",
                type=file_types,
                key=f"file_upload_{key}",
                label_visibility="collapsed",
            )
            if uploaded is not None:
                previous_path = self.context.nested_get(
                    self.context.config, ("paths", key)
                )
                staged_path = self.context.stage_uploaded_file(key, uploaded)
                if str(staged_path) != previous_path:
                    updated = copy.deepcopy(self.context.config)
                    self.context.nested_set(updated, ("paths", key), str(staged_path))
                    st.session_state.app_config = updated
                    self.context.clear_state(
                        AI_STATE_KEYS if key == "input_data" else OUTPUT_STATE_KEYS
                    )
                st.success(f"Selected: {Path(uploaded.name).name}")
        with download_col:
            configured_path = resolve_configured_path(
                self.context.nested_get(self.context.config, ("paths", key))
            )
            if configured_path.is_file():
                st.download_button(
                    "Download current file",
                    data=configured_path.read_bytes(),
                    file_name=configured_path.name,
                    mime=self.context.download_mime_type(configured_path),
                    key=f"file_download_{key}",
                    width='stretch',
                )
                st.caption(configured_path.name)
            else:
                st.button(
                    "Current file unavailable",
                    key=f"file_download_unavailable_{key}",
                    disabled=True,
                    width='stretch',
                )

    def _render_timing_settings(self) -> None:
        st.subheader("Shared timing presets")
        st.caption(
            "An active catalogue conduct can choose In camp, Out of camp, or no timing. Its duration is combined with the selected preset below."
        )
        edited = copy.deepcopy(self.context.config)
        with st.form("timing_settings_form"):
            morning_cutoff = st.text_input(
                "Morning conduct cutoff (HH:MM)",
                value=self.context.nested_get(
                    edited, ("timing", "morning_cutoff"), "12:00"
                ),
                help="Medic and in-camp SOUV timing applies when the conduct starts before this time.",
            )
            in_camp_col, external_col = st.columns(2, gap="large")
            timing_values: dict[tuple[str, str], str] = {}
            with in_camp_col:
                st.markdown("#### In camp")
                st.caption("SOUV uses the Vehicle reporting preset.")
                for item_key, label, default in (
                    ("medic", "Medic reporting", "05:45"),
                    ("ammo_collection", "Ammo collection", "05:30"),
                    ("transport", "Bus transport", "07:00"),
                    ("vehicle", "Vehicle reporting (SOUV)", "05:45"),
                ):
                    timing_values[("in_camp", item_key)] = st.text_input(
                        f"{label} (HH:MM)",
                        value=self.context.nested_get(
                            edited, ("timing", "in_camp", item_key), default
                        ),
                        key=f"in_camp_{item_key}_time",
                    )
            with external_col:
                st.markdown("#### Out of camp")
                st.caption(
                    "Ammo and LUV (HQ) use 04:45. MMRC rows suppress those two timings."
                )
                for item_key, label, default in (
                    ("medic", "Medic reporting", "04:45"),
                    ("ammo_collection", "Ammo collection", "04:45"),
                    ("transport", "Bus transport", "06:15"),
                    ("vehicle", "Vehicle reporting (LUV HQ)", "04:45"),
                ):
                    timing_values[("external", item_key)] = st.text_input(
                        f"{label} (HH:MM)",
                        value=self.context.nested_get(
                            edited, ("timing", "external", item_key), default
                        ),
                        key=f"external_{item_key}_time",
                    )
            save_timing = st.form_submit_button(
                "Save timing settings", type="primary"
            )

        if not save_timing:
            return
        all_values = {
            "Morning cutoff": morning_cutoff,
            **{
                f"{mode} {item_key}": value
                for (mode, item_key), value in timing_values.items()
            },
        }
        invalid = [
            label for label, value in all_values.items() if not self._is_time(value)
        ]
        if invalid:
            st.error("Use 24-hour HH:MM for: " + ", ".join(invalid))
            return
        self.context.nested_set(
            edited,
            ("timing", "morning_cutoff"),
            morning_cutoff.strip(),
        )
        for (mode, item_key), value in timing_values.items():
            self.context.nested_set(
                edited, ("timing", mode, item_key), value.strip()
            )
        self.context.save_config(edited, clear_keys=OUTPUT_STATE_KEYS)
        st.success("Timing presets saved in this browser.")

    def _render_general_settings(self) -> None:
        edited = copy.deepcopy(self.context.config)
        with st.form("general_settings_form"):
            st.subheader("Storage")
            output_folder = st.text_input(
                "Output folder",
                value=self.context.nested_get(edited, ("paths", "output_folder")),
            )
            self.context.nested_set(
                edited, ("paths", "output_folder"), output_folder
            )

            st.subheader("Booking email")
            recipient = st.text_input(
                "Recipient email",
                value=self.context.nested_get(edited, ("user", "email")),
            )
            sender = st.text_input(
                "Gmail sender",
                value=self.context.nested_get(edited, ("gmail", "address")),
            )
            app_password = st.text_input(
                "Gmail app password",
                value=self.context.nested_get(edited, ("gmail", "app_password")),
                type="password",
                help="Use a Gmail app password, not the account password.",
            )
            self.context.nested_set(edited, ("user", "email"), recipient)
            self.context.nested_set(edited, ("gmail", "address"), sender)
            self.context.nested_set(
                edited, ("gmail", "app_password"), app_password
            )
            save_general = st.form_submit_button(
                "Save general settings", type="primary"
            )

        if save_general:
            self.context.save_config(edited, clear_keys=("booking_result",))
            st.success("General settings saved in this browser.")

    def _render_reset_and_export(self) -> None:
        st.divider()
        reset_col, export_col = st.columns(2)
        with reset_col:
            if st.button("Reset to config.yaml", width='stretch'):
                self.context.reset_config()
                st.rerun()
        with export_col:
            downloadable_config = copy.deepcopy(self.context.config)
            downloadable_config.pop("gmail", None)
            downloadable_config.pop("openai", None)
            st.download_button(
                "Download local config",
                yaml.safe_dump(downloadable_config, sort_keys=False),
                file_name="config.yaml",
                mime="application/x-yaml",
                width='stretch',
            )

    @staticmethod
    def _is_time(value: str) -> bool:
        return bool(
            re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", str(value).strip())
        )
