#!/usr/bin/env python3
"""Quick Gemini API connectivity test."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from server.config import DEFAULT_GEMINI_MODEL, resolve_gemini_api_key
from server.layout_engine import GEMINI_MODELS


def main() -> int:
    api_key, source = resolve_gemini_api_key()
    if not api_key:
        print("FAIL: No API key found.")
        print("Set GEMINI_API_KEY in .env or gemini_api_key in .streamlit/secrets.toml")
        return 1

    masked = api_key[:4] + "..." + api_key[-4:] if len(api_key) > 8 else "(set)"
    print(f"Key source: {source}")
    print(f"Key preview: {masked}")

    try:
        import google.generativeai as genai
    except ImportError:
        print("FAIL: google-generativeai not installed. Run: pip install -r requirements.txt")
        return 1

    genai.configure(api_key=api_key)
    candidates = []
    for name in (DEFAULT_GEMINI_MODEL, *GEMINI_MODELS):
        if name not in candidates:
            candidates.append(name)

    for model_name in candidates:
        print(f"Trying {model_name}...")
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content('Reply with exactly: {"status":"ok"}')
            text = (response.text or "").strip()
            print(f"Response: {text[:200]}")
            print(f"SUCCESS: Gemini connection works ({model_name}).")
            return 0
        except Exception as exc:
            print(f"  Failed: {exc}")

    print("FAIL: No Gemini model succeeded.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
