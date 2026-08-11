from __future__ import annotations

import copy
import hashlib
import mimetypes
import os
import secrets
import tempfile
from pathlib import Path
from typing import Any

import streamlit as st
import pandas as pd
import yaml
from streamlit_cookies_manager import EncryptedCookieManager

from ai_ingestion import (
    DEFAULT_AI_MODEL,
    EVENT_COLUMNS,
    extract_training_plan_with_ai,
    validate_reviewed_events,
)
from app_services import (
    generate_bookings,
    generate_bookings_from_events,
    generate_siao,
    generate_siao_from_events,
    load_editable_conduct_catalog,
    resolve_configured_path,
    save_editable_conduct_catalog,
    send_booking_email,
    validate_editable_conduct_catalog,
)


APP_ROOT = Path(__file__).resolve().parent
CONFIG_PATH = APP_ROOT / "ocs" / "config.yaml"
COOKIE_KEY = "local_config"

st.set_page_config(
    page_title="TP Automation",
    page_icon="◫",
    layout="wide",
    initial_sidebar_state="expanded",
)


def read_default_config() -> dict[str, Any]:
    with CONFIG_PATH.open("r", encoding="utf-8") as config_file:
        return yaml.safe_load(config_file) or {}


def nested_get(data: dict[str, Any], keys: tuple[str, ...], default: str = "") -> str:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
    return default if current is None else str(current)


def nested_set(data: dict[str, Any], keys: tuple[str, ...], value: str) -> None:
    current = data
    for key in keys[:-1]:
        current = current.setdefault(key, {})
    current[keys[-1]] = value


def run_action(action, success_message: str):
    try:
        with st.spinner("Working on it…"):
            result = action()
        st.success(success_message)
        return result
    except Exception as exc:
        st.error(str(exc))
        return None


def stage_uploaded_file(setting_key: str, uploaded_file) -> Path:
    """Keep an uploaded input available for the current Streamlit session."""
    if "upload_directory" not in st.session_state:
        st.session_state.upload_directory = tempfile.mkdtemp(prefix="tp_uploads_")

    data = uploaded_file.getvalue()
    safe_name = Path(uploaded_file.name).name
    signature = hashlib.sha256(data).hexdigest()
    state_key = f"uploaded_{setting_key}"
    previous = st.session_state.get(state_key, {})
    if previous.get("signature") == signature and Path(previous["path"]).is_file():
        return Path(previous["path"])

    destination = Path(st.session_state.upload_directory) / f"{setting_key}_{safe_name}"
    destination.write_bytes(data)
    st.session_state[state_key] = {
        "name": safe_name,
        "path": str(destination),
        "signature": signature,
    }
    return destination


def download_mime_type(path: Path) -> str:
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def deployment_secret(name: str, default: str = "") -> str:
    """Read a deployment secret without putting it into browser configuration."""
    environment_value = os.environ.get(name)
    if environment_value:
        return environment_value
    try:
        value = st.secrets.get(name, default)
    except (FileNotFoundError, KeyError):
        value = default
    return str(value or default)


def catalogue_to_frame(catalog: dict[str, Any]) -> pd.DataFrame:
    rows = []
    for rule in catalog.get("conducts", []):
        rows.append({
            "active": bool(rule.get("active", True)),
            "conduct_id": rule.get("conduct_id", ""),
            "lesson_plan_name": rule.get("lesson_plan_name", ""),
            "display_name": rule.get("display_name", ""),
            "use_display_name": bool(rule.get("use_display_name", False)),
            "aliases": "\n".join(str(value) for value in rule.get("aliases", [])),
            "exclusions": "\n".join(str(value) for value in rule.get("exclusions", [])),
            "multi_day": bool(rule.get("multi_day", False)),
            "exercise_display_name": rule.get("exercise_display_name", ""),
        })
    return pd.DataFrame(rows)


def _lines(value: Any) -> list[str]:
    if pd.isna(value):
        return []
    return [line.strip() for line in str(value).splitlines() if line.strip()]


def frame_to_catalog(frame: pd.DataFrame, original: dict[str, Any]) -> dict[str, Any]:
    catalog = copy.deepcopy(original)
    conducts = []
    for _, row in frame.iterrows():
        conduct_id = "" if pd.isna(row.get("conduct_id")) else str(row["conduct_id"]).strip()
        if not conduct_id and all(pd.isna(row.get(key)) for key in ("lesson_plan_name", "aliases")):
            continue
        rule = {
            "conduct_id": conduct_id,
            "lesson_plan_name": "" if pd.isna(row.get("lesson_plan_name")) else str(row["lesson_plan_name"]).strip(),
            "display_name": "" if pd.isna(row.get("display_name")) else str(row["display_name"]).strip(),
            "use_display_name": bool(row.get("use_display_name", False)),
            "aliases": _lines(row.get("aliases")),
            "exclusions": _lines(row.get("exclusions")),
            "multi_day": bool(row.get("multi_day", False)),
            "active": bool(row.get("active", True)),
        }
        exercise_name = row.get("exercise_display_name")
        if not pd.isna(exercise_name) and str(exercise_name).strip():
            rule["exercise_display_name"] = str(exercise_name).strip()
        conducts.append(rule)
    catalog["conducts"] = conducts
    return catalog


st.markdown(
    """
    <style>
      :root { --ink:#18231d; --muted:#66736c; --line:#dce4df; --accent:#176b4d; }
      .stApp { background:#f7f9f7; color:var(--ink); }
      [data-testid="stSidebar"] { background:#eef3ef; border-right:1px solid var(--line); }
      .block-container { max-width:1120px; padding-top:3.25rem; }
      h1, h2, h3 { letter-spacing:-0.025em; }
      .eyebrow { color:var(--accent); font-size:.78rem; font-weight:700; letter-spacing:.12em; text-transform:uppercase; }
      .lede { color:var(--muted); font-size:1.05rem; max-width:690px; margin-bottom:1.8rem; }
      .soft-card { background:#fff; border:1px solid var(--line); border-radius:16px; padding:1.25rem 1.4rem; margin:.4rem 0 1rem; }
      .soft-card strong { color:var(--ink); }
      div.stButton > button, div.stDownloadButton > button { border-radius:9px; min-height:2.7rem; font-weight:650; }
      div.stButton > button[kind="primary"] { background:var(--accent); border-color:var(--accent); }
      [data-testid="stDataFrame"] { border:1px solid var(--line); border-radius:12px; overflow:hidden; }
    </style>
    """,
    unsafe_allow_html=True,
)

@st.cache_resource
def get_cookie_password() -> str:
    return os.environ.get("TP_COOKIE_PASSWORD") or secrets.token_urlsafe(32)


cookie_password = get_cookie_password()
cookies = EncryptedCookieManager(prefix="tp_", password=cookie_password)
if not cookies.ready():
    st.stop()

default_config = read_default_config()
if "app_config" not in st.session_state:
    saved_yaml = cookies.get(COOKIE_KEY)
    try:
        st.session_state.app_config = yaml.safe_load(saved_yaml) if saved_yaml else copy.deepcopy(default_config)
    except yaml.YAMLError:
        st.session_state.app_config = copy.deepcopy(default_config)

config = st.session_state.app_config

with st.sidebar:
    st.markdown("### TP")
    st.caption("Planning automation")
    page = st.radio(
        "Workspace",
        ["AI TP reader", "SIAO generator", "Facility booking", "Conduct catalogue", "Settings"],
        label_visibility="collapsed",
    )
    st.divider()
    st.caption("Settings are kept in this browser only.")

if page == "AI TP reader":
    st.markdown('<div class="eyebrow">Flexible ingestion</div>', unsafe_allow_html=True)
    st.title("Read flexible training-plan layouts")
    st.markdown(
        '<div class="lede">Upload a spreadsheet, PDF, or scan. AI converts visual boxes and unfamiliar layouts into one editable event table before anything reaches SIAO or booking generation.</div>',
        unsafe_allow_html=True,
    )
    st.warning(
        "The uploaded plan is sent to OpenAI for document understanding. Do not use this feature if your information-handling policy prohibits third-party cloud processing. Always review the extracted table."
    )

    ai_api_key = deployment_secret("OPENAI_API_KEY")
    ai_model = DEFAULT_AI_MODEL
    ai_upload = st.file_uploader(
        "Training plan",
        type=["pdf", "png", "jpg", "jpeg", "webp", "gif", "csv", "tsv", "xlsx", "xls", "xlsm"],
        key="ai_training_plan_upload",
        help="Maximum 50 MB. PDFs may contain scans, pictures, or visual timetable boxes.",
    )
    st.caption("If a spreadsheet relies on drawings or embedded images, export it to PDF first so the visual layout is included.")
    if ai_upload is not None and Path(ai_upload.name).suffix.lower() == ".pdf":
        st.caption(
            "For completeness, PDFs are checked two pages at a time and merged. "
            "Long plans can take several minutes and use multiple API requests."
        )

    ai_source_path = None
    if ai_upload is not None:
        upload_signature = hashlib.sha256(ai_upload.getvalue()).hexdigest()
        if st.session_state.get("ai_source_signature") != upload_signature:
            st.session_state.ai_source_signature = upload_signature
            for state_key in (
                "ai_extraction",
                "ai_event_editor",
                "approved_ai_events",
                "approved_ai_events_hash",
                "siao_result",
                "siao_result_cadet_size",
                "booking_result",
            ):
                st.session_state.pop(state_key, None)
        ai_source_path = stage_uploaded_file("ai_input_data", ai_upload)

    # if not ai_api_key:
    #     st.info(
    #         'Add `OPENAI_API_KEY = "..."` to Streamlit Community Cloud Secrets. The key is never stored in config.yaml or browser cookies.'
    #     )

    if st.button(
        "Extract editable schedule with AI",
        type="primary",
        disabled=ai_source_path is None or not ai_api_key,
        use_container_width=True,
    ):
        for state_key in (
            "ai_extraction",
            "ai_event_editor",
            "approved_ai_events",
            "approved_ai_events_hash",
            "siao_result",
            "siao_result_cadet_size",
            "booking_result",
        ):
            st.session_state.pop(state_key, None)
        extraction = run_action(
            lambda: extract_training_plan_with_ai(
                ai_source_path,
                api_key=ai_api_key,
            ),
            "AI extraction completed. Review every row below.",
        )
        if extraction:
            st.session_state.ai_extraction = extraction
            st.session_state.pop("ai_event_editor", None)

    if extraction := st.session_state.get("ai_extraction"):
        title_col, model_col, event_col, coverage_col = st.columns([2, 1, 1, 1.2])
        title_col.metric("Document", extraction.get("document_title") or "Untitled")
        model_col.metric("Model", extraction.get("model") or ai_model)
        event_col.metric("Events", len(extraction["events"]))
        coverage_col.metric("Coverage", extraction.get("coverage_label") or "Complete file")
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
        st.caption("Correct uncertain text, dates, times, conducts, and locations. Add or delete rows as needed.")
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
                "conduct": st.column_config.TextColumn("Conduct", required=True, width="large"),
                "location": st.column_config.TextColumn("Location", width="medium"),
                "remarks": st.column_config.TextColumn("Remarks", width="large"),
                "source_reference": st.column_config.TextColumn("Source", disabled=True),
                "confidence": st.column_config.NumberColumn("Confidence", min_value=0.0, max_value=1.0, format="%.2f", disabled=True),
                "needs_review": st.column_config.CheckboxColumn("Review"),
            },
        )
        cleaned_events, event_errors, event_warnings = validate_reviewed_events(edited_events)
        review_hash = hashlib.sha256(cleaned_events.to_csv(index=False).encode("utf-8")).hexdigest()
        if (
            st.session_state.get("approved_ai_events_hash")
            and st.session_state.approved_ai_events_hash != review_hash
        ):
            st.session_state.pop("approved_ai_events", None)
            st.session_state.pop("approved_ai_events_hash", None)
            st.session_state.pop("siao_result", None)
            st.session_state.pop("siao_result_cadet_size", None)
            st.session_state.pop("booking_result", None)
            st.info("The table changed. Approve it again before generating outputs.")

        if event_errors:
            st.error("Resolve these issues before approval:\n\n- " + "\n- ".join(event_errors))
        for warning in event_warnings:
            st.warning(warning)

        approve_col, download_col = st.columns(2)
        with approve_col:
            if st.button(
                "Approve and use this schedule",
                type="primary",
                disabled=bool(event_errors),
                use_container_width=True,
            ):
                st.session_state.approved_ai_events = cleaned_events.copy()
                st.session_state.approved_ai_events_hash = review_hash
                st.session_state.pop("siao_result", None)
                st.session_state.pop("siao_result_cadet_size", None)
                st.session_state.pop("booking_result", None)
                st.success("Approved. SIAO and Facility booking will now use this reviewed table.")
        with download_col:
            st.download_button(
                "Download reviewed events CSV",
                cleaned_events.to_csv(index=False).encode("utf-8-sig"),
                file_name="reviewed_training_plan.csv",
                mime="text/csv",
                use_container_width=True,
            )

        if "approved_ai_events" in st.session_state:
            st.success(f"AI-reviewed schedule active · {len(st.session_state.approved_ai_events)} events")
            if st.button("Stop using this AI schedule", use_container_width=True):
                st.session_state.pop("approved_ai_events", None)
                st.session_state.pop("approved_ai_events_hash", None)
                st.session_state.pop("siao_result", None)
                st.session_state.pop("siao_result_cadet_size", None)
                st.session_state.pop("booking_result", None)
                st.rerun()

elif page == "SIAO generator":
    st.markdown('<div class="eyebrow">SIAO generator</div>', unsafe_allow_html=True)
    st.title("Build the draft in one pass")
    st.markdown(
        '<div class="lede">Use the configured timetable, lesson plan and SIAO template to prepare a downloadable draft.</div>',
        unsafe_allow_html=True,
    )

    left, right = st.columns([1, 1.45], gap="large")
    with left:
        cadet_size = st.number_input("Cadet strength", min_value=1, max_value=2000, value=120, step=1)
        if (
            "siao_result" in st.session_state
            and st.session_state.get("siao_result_cadet_size") != int(cadet_size)
        ):
            st.session_state.pop("siao_result", None)
            st.session_state.pop("siao_result_cadet_size", None)
        approved_events = st.session_state.get("approved_ai_events")
        if isinstance(approved_events, pd.DataFrame):
            st.info(f"Using approved AI-readable schedule · {len(approved_events)} events")
        if st.button("Generate SIAO draft", type="primary", use_container_width=True):
            st.session_state.pop("siao_result", None)
            st.session_state.pop("siao_result_cadet_size", None)
            result = run_action(
                lambda: (
                    generate_siao_from_events(config, approved_events, int(cadet_size))
                    if isinstance(approved_events, pd.DataFrame)
                    else generate_siao(config, int(cadet_size))
                ),
                "Your SIAO draft is ready.",
            )
            if result:
                st.session_state.siao_result = result
                st.session_state.siao_result_cadet_size = int(cadet_size)

    with right:
        st.markdown(
            """<div class="soft-card"><strong>Creates a siao_template based on the standardized TP</strong><br>
            runs <code>draft_siao</code> function against TP given, Update it in settings.</div>""",
            unsafe_allow_html=True,
        )

    if result := st.session_state.get("siao_result"):
        report = result.get("match_report", pd.DataFrame())
        if not report.empty:
            unique_report = report.drop_duplicates(
                subset=["conduct", "status", "lesson_plan_name", "candidates"]
            )
            counts = unique_report["status"].value_counts()
            matched = int(counts.get("exact", 0) + counts.get("catalog", 0))
            unresolved = int(counts.get("unmatched", 0))
            ambiguous = int(counts.get("ambiguous", 0) + counts.get("invalid_target", 0))
            inactive = int(counts.get("inactive", 0))
            metric_one, metric_two, metric_three, metric_four = st.columns(4)
            metric_one.metric("Matched", matched)
            metric_two.metric("Unresolved", unresolved)
            metric_three.metric("Needs review", ambiguous)
            metric_four.metric("Inactive", inactive)

            review_rows = unique_report[
                unique_report["status"].isin(["unmatched", "ambiguous", "invalid_target"])
            ]
            if not review_rows.empty:
                st.warning("Some timetable entries were not placed into the SIAO. Review them before using the draft.")
                st.dataframe(review_rows, use_container_width=True, hide_index=True)

        for error in result.get("catalog_validation_errors", []):
            st.warning(error)

        st.subheader("Downloads")
        download_one, download_two = st.columns(2)
        with download_one:
            st.download_button(
                "Download SIAO CSV",
                result["csv"],
                file_name="draft_siao.csv",
                mime="text/csv",
                use_container_width=True,
            )
        with download_two:
            st.download_button(
                "Download formatted workbook",
                result["xlsx"],
                file_name="draft_siao.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

elif page == "Facility booking":
    st.markdown('<div class="eyebrow">Resource booking</div>', unsafe_allow_html=True)
    st.title("Prepare OCS and SAFTI bookings")
    st.markdown(
        '<div class="lede">Generate the OCS copy-and-paste list and review the SAFTI email before choosing to send it.</div>',
        unsafe_allow_html=True,
    )

    approved_events = st.session_state.get("approved_ai_events")
    if isinstance(approved_events, pd.DataFrame):
        st.info(f"Using approved AI-readable schedule · {len(approved_events)} events")
    if st.button("Generate booking draft", type="primary"):
        st.session_state.pop("booking_result", None)
        result = run_action(
            lambda: (
                generate_bookings_from_events(config, approved_events)
                if isinstance(approved_events, pd.DataFrame)
                else generate_bookings(config)
            ),
            "Booking draft generated.",
        )
        if result:
            st.session_state.booking_result = result

    if result := st.session_state.get("booking_result"):
        ocs_tab, safti_tab = st.tabs([f"OCS facilities · {len(result['ocs'])}", f"SAFTI facilities · {len(result['safti'])}"])
        with ocs_tab:
            st.caption("Use the copy icon on the block below, or download the CSV.")
            st.code(result["ocs_copy_text"], language=None)
            st.dataframe(result["ocs"], use_container_width=True, hide_index=True)
            st.download_button(
                "Download OCS bookings",
                result["ocs_csv"],
                file_name="ocs_booking.csv",
                mime="text/csv",
            )

        with safti_tab:
            draft = result["email_draft"]
            st.text_input("To", value=draft["to"], disabled=True)
            st.text_input("Subject", value=draft["subject"], disabled=True)
            edited_body = st.text_area("Email introduction", value=draft["body"], height=110)
            st.caption("Booking details will be sent as the table shown below.")
            st.dataframe(result["safti"], use_container_width=True, hide_index=True)
            if st.button("Send reviewed email", type="primary"):
                reviewed_draft = {**draft, "body": edited_body}
                run_action(
                    lambda: send_booking_email(config, reviewed_draft),
                    f"Email sent to {draft['to']}.",
                )

elif page == "Conduct catalogue":
    st.markdown('<div class="eyebrow">Data management</div>', unsafe_allow_html=True)
    st.title("Conduct names and aliases")
    st.markdown(
        '<div class="lede">Map local timetable wording to a stable lesson-plan conduct. Changes are validated before the catalogue is replaced.</div>',
        unsafe_allow_html=True,
    )

    try:
        catalog = load_editable_conduct_catalog(config)
    except Exception as exc:
        st.error(str(exc))
        st.stop()

    st.info("Keep conduct IDs stable. To rename an exercise, update its display name and aliases while leaving its ID unchanged.")

    edited_frame = st.data_editor(
        catalogue_to_frame(catalog),
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        column_config={
            "active": st.column_config.CheckboxColumn("Active"),
            "conduct_id": st.column_config.TextColumn("Stable conduct ID", required=True),
            "lesson_plan_name": st.column_config.TextColumn("Lesson-plan name", required=True),
            "display_name": st.column_config.TextColumn("Display name"),
            "use_display_name": st.column_config.CheckboxColumn("Use display name in SIAO"),
            "aliases": st.column_config.TextColumn("Aliases · one per line", width="large"),
            "exclusions": st.column_config.TextColumn("Exclusions · one per line", width="large"),
            "multi_day": st.column_config.CheckboxColumn("Multi-day"),
            "exercise_display_name": st.column_config.TextColumn("Combined display name"),
        },
        key="conduct_catalog_editor",
    )
    edited_catalog = frame_to_catalog(edited_frame, catalog)
    validation_errors = validate_editable_conduct_catalog(config, edited_catalog)
    if validation_errors:
        st.error("Resolve these issues before saving:\n\n- " + "\n- ".join(validation_errors))
    else:
        st.success("Catalogue validation passed.")

    save_col, download_col = st.columns(2)
    with save_col:
        if st.button("Save validated catalogue", type="primary", disabled=bool(validation_errors), use_container_width=True):
            saved_path = run_action(
                lambda: save_editable_conduct_catalog(config, edited_catalog),
                "Conduct catalogue saved.",
            )
            if saved_path:
                st.session_state.pop("siao_result", None)
                st.session_state.pop("siao_result_cadet_size", None)
    with download_col:
        st.download_button(
            "Download catalogue YAML",
            yaml.safe_dump(edited_catalog, sort_keys=False, allow_unicode=True),
            file_name="conduct_catalog.yaml",
            mime="application/x-yaml",
            use_container_width=True,
        )
    st.caption("On a hosted server, use persistent storage or a database if these edits must survive redeployment.")

else:
    st.markdown('<div class="eyebrow">Local settings</div>', unsafe_allow_html=True)
    st.title("Paths and account details")
    st.markdown(
        '<div class="lede">These values are encrypted and stored in this browser. Saving here does not edit the repository’s config.yaml.</div>',
        unsafe_allow_html=True,
    )

    st.subheader("Automation files")
    st.caption("Drop a replacement file into a card or browse your device. The selected copy is used for this session.")
    st.caption("For a PDF, scan, image, or unfamiliar layout, use AI TP reader and approve its editable table.")
    managed_files = (
        ("input_data", "Training plan input - Commonly referred as TP", ["csv", "xlsx", "xlsm", "xls"]),
        ("lesson_plan", "Lesson plan input - Please add in required lesson plans and reupload", ["csv"]),
        ("siao_template", "SIAO template workbook", ["xlsx", "xlsm"]),
        ("conduct_catalog", "Conduct catalogue", ["yaml", "yml"]),
    )
    for key, label, file_types in managed_files:
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
                previous_path = str(nested_get(config, ("paths", key)))
                staged_path = stage_uploaded_file(key, uploaded)
                updated_config = copy.deepcopy(config)
                nested_set(updated_config, ("paths", key), str(staged_path))
                st.session_state.app_config = updated_config
                config = updated_config
                if str(staged_path) != previous_path:
                    if key == "input_data":
                        for state_key in (
                            "ai_extraction",
                            "ai_event_editor",
                            "approved_ai_events",
                            "approved_ai_events_hash",
                            "siao_result",
                            "siao_result_cadet_size",
                            "booking_result",
                        ):
                            st.session_state.pop(state_key, None)
                    elif key in {"lesson_plan", "siao_template", "conduct_catalog"}:
                        st.session_state.pop("siao_result", None)
                        st.session_state.pop("siao_result_cadet_size", None)
                st.success(f"Selected: {Path(uploaded.name).name}")
        with download_col:
            configured_path = resolve_configured_path(nested_get(config, ("paths", key)))
            if configured_path.is_file():
                st.download_button(
                    "Download current file",
                    data=configured_path.read_bytes(),
                    file_name=configured_path.name,
                    mime=download_mime_type(configured_path),
                    key=f"file_download_{key}",
                    use_container_width=True,
                )
                st.caption(configured_path.name)
            else:
                st.button(
                    "Current file unavailable",
                    key=f"file_download_unavailable_{key}",
                    disabled=True,
                    use_container_width=True,
                )
                st.caption("Upload a file to make it available here.")

    edited = copy.deepcopy(config)
    with st.form("settings_form"):
        st.subheader("Storage paths")
        for key, label in (
            ("output_folder", "Output folder"),
        ):
            value = st.text_input(label, value=nested_get(edited, ("paths", key)))
            nested_set(edited, ("paths", key), value)

        st.subheader("Booking email")
        recipient = st.text_input("Recipient email", value=nested_get(edited, ("user", "email")))
        sender = st.text_input("Gmail sender", value=nested_get(edited, ("gmail", "address")))
        app_password = st.text_input(
            "Gmail app password",
            value=nested_get(edited, ("gmail", "app_password")),
            type="password",
            help="Use a Gmail app password, not the account password.\n For more information see: https://support.reolink.com/articles/360039461654-How-to-Generate-an-App-Password-in-Gmail-Account/",
        )
        nested_set(edited, ("user", "email"), recipient)
        nested_set(edited, ("gmail", "address"), sender)
        nested_set(edited, ("gmail", "app_password"), app_password)

        save = st.form_submit_button("Save locally", type="primary")

    if save:
        st.session_state.app_config = edited
        st.session_state.pop("booking_result", None)
        cookies[COOKIE_KEY] = yaml.safe_dump(edited, sort_keys=False)
        cookies.save()
        st.success("Settings saved in this browser.")

    reset_col, export_col = st.columns(2)
    with reset_col:
        if st.button("Reset to config.yaml", use_container_width=True):
            st.session_state.app_config = copy.deepcopy(default_config)
            for state_key in (
                "ai_extraction",
                "ai_event_editor",
                "approved_ai_events",
                "approved_ai_events_hash",
                "siao_result",
                "siao_result_cadet_size",
                "booking_result",
            ):
                st.session_state.pop(state_key, None)
            cookies[COOKIE_KEY] = yaml.safe_dump(default_config, sort_keys=False)
            cookies.save()
            st.rerun()
    with export_col:
        downloadable_config = copy.deepcopy(config)
        downloadable_config.pop("gmail", None)
        st.download_button(
            "Download local config",
            yaml.safe_dump(downloadable_config, sort_keys=False),
            file_name="config.yaml",
            mime="application/x-yaml",
            use_container_width=True,
        )
