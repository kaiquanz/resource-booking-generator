"""Session-only personal OpenAI API-key handling."""

from __future__ import annotations

from dataclasses import dataclass

import streamlit as st

from .context import ApplicationContext


OPENAI_API_KEYS_URL = "https://platform.openai.com/api-keys"
OPENAI_KEY_HELP_URL = (
    "https://help.openai.com/en/articles/4936850-where-do-i-find-my-api-key"
)
OPENAI_KEY_SAFETY_URL = (
    "https://help.openai.com/en/articles/5112595-best-practices-for-api-key-safety"
)


@dataclass(frozen=True)
class OpenAIKeyStatus:
    value: str
    source: str


class OpenAIKeyManager:
    """Resolve a personal session key before an optional deployment key."""

    input_state_key = "personal_openai_api_key"

    def __init__(self, context: ApplicationContext) -> None:
        self.context = context

    @staticmethod
    def choose(personal_key: str, deployment_key: str) -> OpenAIKeyStatus:
        """Choose a session key first without exposing either value."""
        personal = str(personal_key or "").strip()
        if personal:
            return OpenAIKeyStatus(personal, "personal")
        deployment = str(deployment_key or "").strip()
        if deployment:
            return OpenAIKeyStatus(deployment, "deployment")
        return OpenAIKeyStatus("", "missing")

    def resolve(self) -> OpenAIKeyStatus:
        personal_key = str(st.session_state.get(self.input_state_key, "") or "").strip()
        deployment_key = self.context.deployment_secret("OPENAI_API_KEY").strip()
        return self.choose(personal_key, deployment_key)

    def forget_personal_key(self) -> None:
        st.session_state.pop(self.input_state_key, None)

    def render(self) -> OpenAIKeyStatus:
        """Render credential controls and return the currently resolved key."""
        st.subheader("OpenAI API access")
        st.caption(
            "Paste your own key to use it only for this active app session. "
            "It is not written to config.yaml, browser cookies, downloads, or logs."
        )
        st.text_input(
            "Your OpenAI API key",
            type="password",
            placeholder="sk-…",
            key=self.input_state_key,
            help="Create a secret key on the OpenAI API key page. Never share or commit it.",
        )

        link_one, link_two, forget_col = st.columns([1.2, 1, 0.8])
        link_one.link_button(
            "Create or manage a key",
            OPENAI_API_KEYS_URL,
            use_container_width=True,
        )
        link_two.link_button(
            "Official setup guide",
            OPENAI_KEY_HELP_URL,
            use_container_width=True,
        )
        if forget_col.button(
            "Forget key",
            disabled=not bool(st.session_state.get(self.input_state_key)),
            use_container_width=True,
        ):
            self.forget_personal_key()
            st.rerun()

        status = self.resolve()
        if status.source == "personal":
            st.success("Your session key is ready. API usage will use its associated project.")
        elif status.source == "deployment":
            st.info(
                "No personal key entered. The app will use its server-managed OpenAI key."
            )
        else:
            st.warning("Enter an OpenAI API key to enable AI extraction.")
        st.caption(
            f"[Read OpenAI's API-key safety guidance]({OPENAI_KEY_SAFETY_URL})."
        )
        return status
