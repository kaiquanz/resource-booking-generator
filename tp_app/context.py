"""Application configuration, session state, and uploaded-file lifecycle."""

from __future__ import annotations

import copy
import hashlib
import mimetypes
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import streamlit as st
import yaml


AI_STATE_KEYS = (
    "ai_extraction",
    "ai_event_editor",
    "approved_ai_events",
    "approved_ai_events_hash",
    "approved_ai_event_errors",
    "siao_result",
    "siao_result_cadet_size",
    "booking_result",
)
OUTPUT_STATE_KEYS = (
    "siao_result",
    "siao_result_cadet_size",
    "booking_result",
)


@dataclass
class ApplicationContext:
    """Own mutable session configuration and shared app infrastructure."""

    app_root: Path
    config_path: Path
    cookies: Any
    cookie_key: str
    default_config: dict[str, Any]

    @classmethod
    def create(
        cls,
        *,
        app_root: Path,
        config_path: Path,
        cookies: Any,
        cookie_key: str,
    ) -> "ApplicationContext":
        with config_path.open("r", encoding="utf-8") as config_file:
            default_config = yaml.safe_load(config_file) or {}
        if not isinstance(default_config, dict):
            raise ValueError("config.yaml must contain a mapping at its root.")

        if "app_config" not in st.session_state:
            saved_yaml = cookies.get(cookie_key)
            try:
                loaded = yaml.safe_load(saved_yaml) if saved_yaml else None
            except yaml.YAMLError:
                loaded = None
            st.session_state.app_config = (
                loaded if isinstance(loaded, dict) else copy.deepcopy(default_config)
            )
        return cls(
            app_root=app_root,
            config_path=config_path,
            cookies=cookies,
            cookie_key=cookie_key,
            default_config=default_config,
        )

    @property
    def config(self) -> dict[str, Any]:
        return st.session_state.app_config

    @staticmethod
    def nested_get(
        data: dict[str, Any],
        keys: tuple[str, ...],
        default: str = "",
    ) -> str:
        current: Any = data
        for key in keys:
            if not isinstance(current, dict):
                return default
            current = current.get(key)
        return default if current is None else str(current)

    @staticmethod
    def nested_set(
        data: dict[str, Any],
        keys: tuple[str, ...],
        value: Any,
    ) -> None:
        current = data
        for key in keys[:-1]:
            current = current.setdefault(key, {})
        current[keys[-1]] = value

    def clear_state(self, keys: Iterable[str]) -> None:
        for key in keys:
            st.session_state.pop(key, None)

    def save_config(
        self,
        updated: dict[str, Any],
        *,
        clear_keys: Iterable[str] = (),
    ) -> None:
        st.session_state.app_config = updated
        self.clear_state(clear_keys)
        self.cookies[self.cookie_key] = yaml.safe_dump(updated, sort_keys=False)
        self.cookies.save()

    def reset_config(self) -> None:
        restored = copy.deepcopy(self.default_config)
        st.session_state.app_config = restored
        self.clear_state(AI_STATE_KEYS)
        self.cookies[self.cookie_key] = yaml.safe_dump(restored, sort_keys=False)
        self.cookies.save()

    def deployment_secret(self, name: str, default: str = "") -> str:
        """Read a server-side secret without copying it into browser settings."""
        environment_value = os.environ.get(name)
        if environment_value:
            return environment_value
        try:
            value = st.secrets.get(name, default)
        except (FileNotFoundError, KeyError):
            value = default
        return str(value or default)

    def stage_uploaded_file(self, setting_key: str, uploaded_file: Any) -> Path:
        """Keep an uploaded input in temporary storage for this app session."""
        if "upload_directory" not in st.session_state:
            st.session_state.upload_directory = tempfile.mkdtemp(prefix="tp_uploads_")

        data = uploaded_file.getvalue()
        safe_name = Path(uploaded_file.name).name
        signature = hashlib.sha256(data).hexdigest()
        state_key = f"uploaded_{setting_key}"
        previous = st.session_state.get(state_key, {})
        if (
            previous.get("signature") == signature
            and previous.get("path")
            and Path(previous["path"]).is_file()
        ):
            return Path(previous["path"])

        destination = (
            Path(st.session_state.upload_directory) / f"{setting_key}_{safe_name}"
        )
        destination.write_bytes(data)
        st.session_state[state_key] = {
            "name": safe_name,
            "path": str(destination),
            "signature": signature,
        }
        return destination

    @staticmethod
    def download_mime_type(path: Path) -> str:
        return mimetypes.guess_type(path.name)[0] or "application/octet-stream"

