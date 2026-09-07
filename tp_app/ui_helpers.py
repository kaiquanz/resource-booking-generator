"""Small reusable Streamlit presentation helpers."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Callable

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components


def render_page_header(eyebrow: str, title: str, description: str) -> None:
    st.markdown(f'<div class="eyebrow">{eyebrow}</div>', unsafe_allow_html=True)
    st.title(title)
    st.markdown(f'<div class="lede">{description}</div>', unsafe_allow_html=True)


def run_action(action: Callable[[], Any], success_message: str) -> Any | None:
    try:
        with st.spinner("Working on it…"):
            result = action()
        st.success(success_message)
        return result
    except Exception as exc:
        st.error(str(exc))
        return None


def booking_table_for_display(bookings: pd.DataFrame) -> pd.DataFrame:
    displayed = bookings.copy()
    for column in ("START DATE", "END DATE"):
        parsed = pd.to_datetime(displayed[column], format="%d-%b-%y", errors="coerce")
        if parsed.notna().all():
            displayed[column] = parsed
    return displayed


BOOKING_DATE_COLUMNS = {
    "START DATE": st.column_config.DateColumn(format="DD-MMM-YY"),
    "END DATE": st.column_config.DateColumn(format="DD-MMM-YY"),
}


def render_rich_email_copy_button(html_body: str, plain_body: str) -> None:
    """Copy an email as rich HTML, with a plain-text browser fallback."""
    safe_html = json.dumps(str(html_body)).replace("<", "\\u003c")
    safe_plain = json.dumps(str(plain_body)).replace("<", "\\u003c")
    components.html(
        f"""
        <button id="copy-email" type="button">Copy formatted email body</button>
        <script>
          const button = document.getElementById("copy-email");
          const htmlBody = {safe_html};
          const plainBody = {safe_plain};
          function copyFormattedFallback() {{
            const field = document.createElement("div");
            field.contentEditable = "true"; field.innerHTML = htmlBody;
            field.style.position = "fixed"; field.style.left = "-10000px";
            document.body.appendChild(field);
            const range = document.createRange(); range.selectNodeContents(field);
            const selection = window.getSelection(); selection.removeAllRanges();
            selection.addRange(range); const copied = document.execCommand("copy");
            selection.removeAllRanges(); field.remove(); return copied;
          }}
          function copyPlainText() {{
            const field = document.createElement("textarea"); field.value = plainBody;
            field.style.position = "fixed"; field.style.opacity = "0";
            document.body.appendChild(field); field.select();
            document.execCommand("copy"); field.remove();
          }}
          button.addEventListener("click", async () => {{
            try {{
              if (navigator.clipboard && navigator.clipboard.write && window.ClipboardItem) {{
                await navigator.clipboard.write([new ClipboardItem({{
                  "text/html": new Blob([htmlBody], {{type: "text/html"}}),
                  "text/plain": new Blob([plainBody], {{type: "text/plain"}}),
                }})]);
              }} else if (!copyFormattedFallback()) {{ copyPlainText(); }}
              button.textContent = "✓ Copied with table formatting";
            }} catch (error) {{
              if (copyFormattedFallback()) button.textContent = "✓ Copied with table formatting";
              else {{ copyPlainText(); button.textContent = "✓ Copied as plain text"; }}
            }}
          }});
        </script>
        <style>
          body {{ margin:0; font-family:Arial, sans-serif; }}
          #copy-email {{ width:100%; min-height:44px; border:1px solid #176b4d;
            border-radius:9px; background:#176b4d; color:white; font-size:15px;
            font-weight:650; cursor:pointer; }}
          #copy-email:hover {{ background:#12563e; }}
        </style>
        """,
        height=52,
    )


def content_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]

