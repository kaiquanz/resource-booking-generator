"""Editable CE & Signals settings and compact browser overrides."""

from copy import deepcopy

import pandas as pd

from ocs.ce_signals import load_rules


ACTIVITIES = {
    "course_start": "Course start", "course_end": "Course end",
    "xaw_stores": "XAW stores preparation", "uo": "UO drills",
    "ptco": "PTCO / tactical scenario training", "lmg_start": "First LMG lesson",
    "lmg_shoot": "LMG qualification shoot", "relentless": "Relentless start",
    "gpmg_shoot": "GPMG live firing", "dekitting": "Last dekitting day",
}
WINDOWS = {
    "course": "Course allocation", "uoce": "UOCE", "heartlanders": "Heartlanders",
    "field_support": "Field support", "lmg": "LMG", "mcn": "MCN",
    "gpmg": "GPMG", "diesel": "Relentless through GPMG",
}


def settings_frames(rules):
    items = pd.DataFrame([{
        "row": item["row"], "Equipment": item["name"],
        "Baseline quantity": item["reference_quantity"],
        "Quantity rule": "Fixed" if item.get("scaling") == "fixed" else "Scale with cadets",
        "Booking": WINDOWS.get(item["window"], item["window"]),
    } for item in rules["items"]]).set_index("row")
    windows = pd.DataFrame([{
        "id": name, "Booking": WINDOWS.get(name, name), "Enabled": spec.get("enabled", True),
        "Start activity": ACTIVITIES[spec["start"]], "Start offset (days)": spec.get("start_offset", 0),
        "End activity": ACTIVITIES[spec["end"]], "End offset (days)": spec.get("end_offset", 0),
    } for name, spec in rules["windows"].items()]).set_index("id")
    return items, windows


def settings_overrides(defaults, base, items, windows):
    """Only changed fields enter the browser cookie/config export."""
    result = {}
    if int(base) != base or base < 1:
        raise ValueError("Baseline cadets must be a positive whole number")
    if base != defaults["base_cadets"]:
        result["base_cadets"] = int(base)
    reverse_windows = {v: k for k, v in WINDOWS.items()}
    reverse_activities = {v: k for k, v in ACTIVITIES.items()}
    by_row = {item["row"]: item for item in defaults["items"]}
    for row, item in items.iterrows():
        quantity = item["Baseline quantity"]
        if pd.isna(quantity) or quantity < 0 or int(quantity) != quantity:
            raise ValueError(f"Enter a non-negative whole quantity for {item['Equipment']}")
        if item["Quantity rule"] not in ("Fixed", "Scale with cadets"):
            raise ValueError("Choose Fixed or Scale with cadets")
        changes = {
            "reference_quantity": int(quantity),
            "scaling": "fixed" if item["Quantity rule"] == "Fixed" else "cadets",
            "window": reverse_windows[item["Booking"]],
        }
        original = by_row[row]
        changes = {k: v for k, v in changes.items() if v != original.get(k, "cadets" if k == "scaling" else None)}
        if changes:
            result.setdefault("items", {})[str(row)] = changes
    for name, window in windows.iterrows():
        changes = {"start": reverse_activities[window["Start activity"]],
                   "end": reverse_activities[window["End activity"]],
                   "enabled": bool(window["Enabled"])}
        for key, label in (("start_offset", "Start offset (days)"), ("end_offset", "End offset (days)")):
            value = window[label]
            if pd.isna(value) or int(value) != value or abs(value) > 365:
                raise ValueError("Date offsets must be whole days between -365 and 365")
            changes[key] = int(value)
        original = defaults["windows"][name]
        changes = {k: v for k, v in changes.items() if v != original.get(k, True if k == "enabled" else 0)}
        if changes:
            result.setdefault("windows", {})[name] = changes
    return result


def render_ce_settings(context):
    import streamlit as st
    from app_services import resolve_configured_path
    from tp_app.context import OUTPUT_STATE_KEYS

    path = resolve_configured_path(context.config.get("paths", {}).get("ce_signals_rules", "ocs/ce_signals.yaml"))
    try:
        defaults = load_rules(path)
        rules = load_rules(path, context.config.get("ce_signals", {}))
    except (OSError, ValueError, KeyError) as error:
        st.error(f"Cannot load CE & Signals settings: {error}")
        return
    st.subheader("CE & Signals")
    st.caption("Set baseline quantities and booking periods. Changes are saved in this browser and included in Download local config.")
    with st.form("ce_signals_settings_form"):
        base = st.number_input("Baseline cadets", min_value=1, max_value=2000,
                               value=int(rules["base_cadets"]), step=1)
        st.caption("Scaled quantity = baseline quantity × current cadets ÷ baseline cadets, rounded up. Fixed quantities stay unchanged.")
        item_frame, window_frame = settings_frames(rules)
        items = st.data_editor(item_frame, hide_index=True, num_rows="fixed", use_container_width=True,
            disabled=["Equipment"], key="ce_items_editor",
            column_config={
                "Baseline quantity": st.column_config.NumberColumn(min_value=0, step=1, required=True),
                "Quantity rule": st.column_config.SelectboxColumn(options=["Scale with cadets", "Fixed"], required=True),
                "Booking": st.column_config.SelectboxColumn(options=list(WINDOWS.values()), required=True),
            })
        st.markdown("**Booking periods**")
        st.caption("Negative offsets start earlier; positive offsets end later. For example, -3 starts three days before the selected activity. Missing required activities leave the booking blank.")
        windows = st.data_editor(window_frame, hide_index=True, num_rows="fixed", use_container_width=True,
            disabled=["Booking"], key="ce_windows_editor",
            column_config={
                "Start activity": st.column_config.SelectboxColumn(options=list(ACTIVITIES.values()), required=True),
                "End activity": st.column_config.SelectboxColumn(options=list(ACTIVITIES.values()), required=True),
                "Start offset (days)": st.column_config.NumberColumn(min_value=-365, max_value=365, step=1, required=True),
                "End offset (days)": st.column_config.NumberColumn(min_value=-365, max_value=365, step=1, required=True),
            })
        st.caption("LANCER does not trigger equipment bookings. Standing compasses remain held through it. Late-November radio/MCN records remain unassigned.")
        saved = st.form_submit_button("Save CE & Signals settings", type="primary")
    if saved:
        try:
            overrides = settings_overrides(defaults, base, items, windows)
            load_rules(path, overrides)
        except (ValueError, KeyError, TypeError) as error:
            st.error(str(error))
            return
        updated = deepcopy(context.config)
        updated["ce_signals"] = overrides
        context.save_config(updated, clear_keys=OUTPUT_STATE_KEYS)
        st.success("CE & Signals settings saved. Generate a new SIAO draft to apply them.")
