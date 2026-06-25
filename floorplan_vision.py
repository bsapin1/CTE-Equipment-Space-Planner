"""Extract structured floor plan data from uploaded drawings using Gemini vision."""

from __future__ import annotations

import json
import re
from typing import Any

import google.generativeai as genai

try:
    from .config import DEFAULT_GEMINI_MODEL
    from .models import FloorPlan
except ImportError:
    from config import DEFAULT_GEMINI_MODEL
    from models import FloorPlan

VISION_MODELS = (DEFAULT_GEMINI_MODEL, "gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash")

MIME_BY_EXT = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".pdf": "application/pdf",
}


def _mime_type(filename: str) -> str:
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in MIME_BY_EXT:
        raise ValueError(f"Unsupported file type '{ext}'. Use JPG, PNG, or PDF.")
    return MIME_BY_EXT[ext]


def _parse_json_response(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned)
    if fence:
        cleaned = fence.group(1).strip()
    return json.loads(cleaned)


def _build_vision_prompt(user_instructions: str) -> str:
    instructions_block = ""
    if user_instructions.strip():
        instructions_block = f"""
USER INSTRUCTIONS (follow these carefully when interpreting the drawing):
{user_instructions.strip()}
"""

    return f"""You are an architectural floor plan analyst for CTE (Career & Technical Education) classroom planning.

Analyze the uploaded floor plan drawing and extract a structured layout for equipment placement.

{instructions_block}
RULES:
1. Estimate dimensions in FEET. If the drawing shows a scale or dimension strings, use them. If not, estimate from typical door width (~3 ft) or note assumptions in analysis_notes.
2. Use a coordinate system with origin at the SOUTHWEST corner of the room: +X east, +Y north.
3. Identify doors and windows on room walls: north, south, east, west.
4. offset_ft on a wall is measured from the west corner (north/south walls) or south corner (east/west walls) along that wall.
5. equipment_zones are areas where CTE equipment may be placed — open floor areas, shop zones, lab areas. Exclude restrooms, closets, corridors unless the user instructions say otherwise.
6. If multiple equipment areas exist, create a zone for each with a descriptive label.
7. If room size cannot be determined, use reasonable CTE classroom defaults (~40 x 30 ft) and explain in analysis_notes.

Respond with ONLY valid JSON (no markdown):
{{
  "floor_plan": {{
    "name": "string",
    "width_ft": 0.0,
    "depth_ft": 0.0,
    "doors": [{{ "wall": "south", "offset_ft": 0.0, "width_ft": 3.0 }}],
    "windows": [{{ "wall": "north", "offset_ft": 0.0, "width_ft": 6.0 }}],
    "equipment_zones": [
      {{
        "id": "zone-1",
        "label": "Shop / Lab Area",
        "x_ft": 0.0,
        "y_ft": 0.0,
        "width_ft": 0.0,
        "depth_ft": 0.0
      }}
    ]
  }},
  "analysis_notes": "Brief explanation of what you saw, assumptions, and how you mapped the drawing"
}}
"""


def analyze_floor_plan_drawing(
    file_bytes: bytes,
    filename: str,
    api_key: str,
    user_instructions: str = "",
) -> tuple[FloorPlan, str]:
    """Return (FloorPlan, analysis_notes) from an image or PDF drawing."""
    if not api_key.strip():
        raise ValueError("Gemini API key is required to analyze floor plan drawings.")

    mime = _mime_type(filename)
    prompt = _build_vision_prompt(user_instructions)
    genai.configure(api_key=api_key.strip())

    file_part = {"mime_type": mime, "data": file_bytes}
    last_error: Exception | None = None

    for model_name in VISION_MODELS:
        try:
            model = genai.GenerativeModel(
                model_name,
                generation_config={
                    "temperature": 0.1,
                    "response_mime_type": "application/json",
                },
            )
            response = model.generate_content([prompt, file_part])
            raw = _parse_json_response(response.text)
            floor_data = raw.get("floor_plan", raw)
            notes = str(raw.get("analysis_notes", ""))
            floor_plan = FloorPlan.model_validate(floor_data)
            if not floor_plan.equipment_zones:
                raise ValueError("No equipment zones identified in the drawing.")
            return floor_plan, notes
        except Exception as exc:
            last_error = exc
            continue

    raise RuntimeError(f"Could not analyze drawing: {last_error}")
