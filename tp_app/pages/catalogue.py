"""Conduct-catalogue editor page."""

from __future__ import annotations

import streamlit as st
import yaml

from app_services import (
    load_editable_conduct_catalog,
    save_editable_conduct_catalog,
    validate_editable_conduct_catalog,
)
from tp_app.catalogue_mapper import CatalogueMapper
from tp_app.context import ApplicationContext
from tp_app.ui_helpers import render_page_header, run_action


class CataloguePage:
    """Edit, validate, save, and export conduct matching rules."""

    def __init__(self, context: ApplicationContext) -> None:
        self.context = context
        self.mapper = CatalogueMapper()

    def render(self) -> None:
        render_page_header(
            "Data management",
            "Conduct names and aliases",
            "Map local timetable wording to a stable lesson-plan conduct. Changes are validated before the catalogue is replaced.",
        )
        try:
            catalog = load_editable_conduct_catalog(self.context.config)
        except Exception as exc:
            st.error(str(exc))
            return

        st.info(
            "Keep conduct IDs stable. Active controls whether the conduct appears in the SIAO. "
            "Timing is independent: choose In camp or Out of camp to apply a shared preset, "
            "or None to add the conduct without preparation timings. Preparation fields contain duration only. "
            "For a conduct that already matches the lesson plan exactly, use that exact Lesson-plan name. "
            "Vehicle timing fills the general vehicle Start/End fields. Enable Bus required to calculate "
            "40-seater buses and use the separate Transport timing."
        )

        edited_frame = st.data_editor(
            self.mapper.to_frame(catalog),
            num_rows="dynamic",
            use_container_width=True,
            hide_index=True,
            column_config=self._column_config(),
            key="conduct_catalog_editor",
        )
        edited_catalog = self.mapper.from_frame(edited_frame, catalog)
        validation_errors = validate_editable_conduct_catalog(
            self.context.config, edited_catalog
        )
        if validation_errors:
            st.error(
                "Resolve these issues before saving:\n\n- "
                + "\n- ".join(validation_errors)
            )
        else:
            st.success("Catalogue validation passed.")

        save_col, download_col = st.columns(2)
        with save_col:
            if st.button(
                "Save validated catalogue",
                type="primary",
                disabled=bool(validation_errors),
                use_container_width=True,
            ):
                saved_path = run_action(
                    lambda: save_editable_conduct_catalog(
                        self.context.config, edited_catalog
                    ),
                    "Conduct catalogue saved.",
                )
                if saved_path:
                    self.context.clear_state(("siao_result", "siao_result_cadet_size"))
        with download_col:
            st.download_button(
                "Download catalogue YAML",
                yaml.safe_dump(edited_catalog, sort_keys=False, allow_unicode=True),
                file_name="conduct_catalog.yaml",
                mime="application/x-yaml",
                use_container_width=True,
            )
        st.caption(
            "On a hosted server, use persistent storage or a database if these edits must survive redeployment."
        )

    @staticmethod
    def _column_config() -> dict:
        return {
            "active": st.column_config.CheckboxColumn(
                "Active", help="Turn this on to include the conduct in the SIAO."
            ),
            "timing": st.column_config.SelectboxColumn(
                "Timing profile",
                options=["None", "In camp", "Out of camp"],
                required=True,
                help="Choose the preset independently of whether the conduct is active.",
            ),
            "bus_required": st.column_config.CheckboxColumn("Bus required"),
            "conduct_id": st.column_config.TextColumn(
                "Stable conduct ID", required=True
            ),
            "lesson_plan_name": st.column_config.TextColumn(
                "Lesson-plan name", required=True
            ),
            "display_name": st.column_config.TextColumn("Display name"),
            "use_display_name": st.column_config.CheckboxColumn(
                "Use display name in SIAO"
            ),
            "aliases": st.column_config.TextColumn(
                "Aliases · one per line", width="large"
            ),
            "exclusions": st.column_config.TextColumn(
                "Exclusions · one per line", width="large"
            ),
            "multi_day": st.column_config.CheckboxColumn("Multi-day"),
            "exercise_display_name": st.column_config.TextColumn(
                "Combined display name"
            ),
            "medic_minutes": st.column_config.NumberColumn(
                "Medic · minutes", min_value=0, step=1
            ),
            "ammo_collection_minutes": st.column_config.NumberColumn(
                "Ammo collection · minutes", min_value=0, step=1
            ),
            "transport_minutes": st.column_config.NumberColumn(
                "Transport · minutes", min_value=0, step=1
            ),
            "vehicle_minutes": st.column_config.NumberColumn(
                "Vehicle · minutes", min_value=0, step=1
            ),
        }

