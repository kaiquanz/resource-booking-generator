"""Streamlit application bootstrap and page routing."""

from __future__ import annotations

import os
import secrets
from pathlib import Path

import streamlit as st

# streamlit-cookies-manager 0.2.0 uses the removed/deprecated st.cache
# decorator. Its cached key-derivation result is immutable, so cache_data is
# the correct modern equivalent on both old and new Streamlit versions.
st.cache = st.cache_data

from streamlit_cookies_manager import EncryptedCookieManager

from tp_app.context import ApplicationContext
from tp_app.pages import (
    AIReaderPage,
    BookingPage,
    CataloguePage,
    SettingsPage,
    SIAOPage,
)


APP_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = APP_ROOT / "ocs" / "config.yaml"
COOKIE_KEY = "local_config"


@st.cache_resource
def cookie_password() -> str:
    """Keep one fallback key for the current server process."""
    return os.environ.get("TP_COOKIE_PASSWORD") or secrets.token_urlsafe(32)


class TPAutomationApp:
    """Configure the shell and dispatch each workspace to its page class."""

    page_names = (
        "AI TP reader",
        "SIAO generator",
        "Facility booking",
        "Conduct catalogue",
        "Settings",
    )

    def run(self) -> None:
        st.set_page_config(
            page_title="TP Automation",
            page_icon="📋",
            layout="wide",
            initial_sidebar_state="expanded",
        )
        self._apply_styles()
        cookies = self._cookie_manager()
        if not cookies.ready():
            st.stop()
        context = ApplicationContext.create(
            app_root=APP_ROOT,
            config_path=CONFIG_PATH,
            cookies=cookies,
            cookie_key=COOKIE_KEY,
        )
        page_name = self._render_sidebar()
        pages = {
            "AI TP reader": AIReaderPage(context),
            "SIAO generator": SIAOPage(context),
            "Facility booking": BookingPage(context),
            "Conduct catalogue": CataloguePage(context),
            "Settings": SettingsPage(context),
        }
        pages[page_name].render()

    @staticmethod
    def _cookie_manager():
        try:
            import pyarrow  # noqa: F401
        except ImportError:
            # Custom Streamlit components require PyArrow. This lightweight
            # fallback keeps local source checkouts usable until requirements
            # are installed; deployed environments use encrypted cookies.
            class SessionCookieManager(dict):
                @staticmethod
                def ready() -> bool:
                    return True

                @staticmethod
                def save() -> None:
                    return None

            return SessionCookieManager()
        return EncryptedCookieManager(prefix="tp_", password=cookie_password())

    def _render_sidebar(self) -> str:
        with st.sidebar:
            st.markdown("### TP")
            st.caption("Planning automation")
            page = st.radio(
                "Workspace",
                self.page_names,
                label_visibility="collapsed",
            )
            st.divider()
            st.caption(
                "Saved settings stay in this browser. Personal OpenAI keys last only for the active session."
            )
        return page

    @staticmethod
    def _apply_styles() -> None:
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
