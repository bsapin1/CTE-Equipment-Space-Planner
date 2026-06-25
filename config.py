"""Load Gemini API key from Streamlit secrets, environment, or .env."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

SECRET_KEYS = ("gemini_api_key", "GEMINI_API_KEY")
DEFAULT_GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")


def _from_streamlit_secrets() -> str:
    try:
        import streamlit as st

        secrets = st.secrets
        for key in SECRET_KEYS:
            if key in secrets and secrets[key]:
                return str(secrets[key]).strip()
    except Exception:
        pass
    return ""


def _from_environment() -> str:
    for key in SECRET_KEYS:
        value = os.environ.get(key, "").strip()
        if value:
            return value
    return ""


def resolve_gemini_api_key(sidebar_value: str = "") -> tuple[str, str]:
    """Return (api_key, source). Sidebar overrides configured keys when non-empty."""
    override = sidebar_value.strip()
    if override:
        return override, "sidebar"

    secrets_key = _from_streamlit_secrets()
    if secrets_key:
        return secrets_key, "Streamlit secrets"

    env_key = _from_environment()
    if env_key:
        return env_key, ".env / environment"

    return "", "none"
