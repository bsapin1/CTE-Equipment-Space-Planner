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
EXTRACTION RULES:

DIMENSIONS & SCALE:
1. Look for a scale bar, scale notation (e.g. "1/4\" = 1'-0\""), or labeled dimensions on the drawing.
   Use these to compute accurate room sizes in FEET. Do not estimate if a scale or dimension is visible.
2. If dimension strings label specific rooms (e.g. "100' x 80'"), use those exact values.
3. Use a coordinate system with origin at the SOUTHWEST corner of the room: +X east, +Y north.

DOORS:
4. Classify every door by type:
   - "swing"    = hinged door with a visible arc drawn on plan. swing_clearance_ft = arc radius (usually = door width).
   - "overhead" = garage/roll-up/coiling door. Often shown with a dashed rectangle on the floor indicating the travel path. swing_clearance_ft = 0.
   - "sliding"  = no arc, track indicated. swing_clearance_ft = 0.
   - "passage"  = open cased opening, no door. swing_clearance_ft = 0.
5. offset_ft on a wall is measured from the west corner (north/south walls) or south corner (east/west walls).

WINDOWS:
7. Identify windows on room walls (door_type = "window" in the doors list is NOT needed — windows go in the windows array with wall/offset_ft/width_ft).

ZONES:
8. equipment_zones are open areas where CTE equipment may be placed — workshops, labs, shop floors. Exclude offices, restrooms, storage closets, corridors.
9. If multiple equipment areas exist, create a zone for each with a descriptive label and accurate dimensions.

ROOM BOUNDS:
10. room_bounds_pct: Estimate where the OUTER WALLS of the primary room sit within the image as fractions (0=left/top edge, 1=right/bottom edge). Account for title blocks, borders, north arrows, scale bars, and margins. If the room fills the entire image, use 0/0/1/1.

Respond with ONLY valid JSON (no markdown):
{{
  "floor_plan": {{
    "name": "string",
    "width_ft": 0.0,
    "depth_ft": 0.0,
    "doors": [
      {{
        "wall": "south",
        "offset_ft": 0.0,
        "width_ft": 3.0,
        "door_type": "swing",
        "swing_clearance_ft": 3.0
      }}
    ],
    "windows": [{{ "wall": "north", "offset_ft": 0.0, "width_ft": 6.0, "door_type": "window", "swing_clearance_ft": 0 }}],
    "equipment_zones": [
      {{
        "id": "zone-1",
        "label": "Open Workshop",
        "x_ft": 0.0,
        "y_ft": 0.0,
        "width_ft": 0.0,
        "depth_ft": 0.0
      }}
    ]
  }},
  "room_bounds_pct": {{
    "left": 0.05,
    "top": 0.05,
    "right": 0.95,
    "bottom": 0.90
  }},
  "analysis_notes": "Brief explanation: scale used, door types found, assumptions made"
}}
"""


RoomBounds = dict  # {"left": float, "top": float, "right": float, "bottom": float}
DEFAULT_BOUNDS: RoomBounds = {"left": 0.0, "top": 0.0, "right": 1.0, "bottom": 1.0}


def _parse_bounds(raw: dict) -> RoomBounds:
    b = raw.get("room_bounds_pct", {})
    if not isinstance(b, dict):
        return DEFAULT_BOUNDS.copy()

    def _clamp(v: Any, fallback: float) -> float:
        try:
            return max(0.0, min(1.0, float(v)))
        except (TypeError, ValueError):
            return fallback

    left = _clamp(b.get("left"), 0.0)
    top = _clamp(b.get("top"), 0.0)
    right = _clamp(b.get("right"), 1.0)
    bottom = _clamp(b.get("bottom"), 1.0)

    # Sanity: ensure non-zero area
    if right <= left or bottom <= top:
        return DEFAULT_BOUNDS.copy()
    return {"left": left, "top": top, "right": right, "bottom": bottom}


def analyze_floor_plan_drawing(
    file_bytes: bytes,
    filename: str,
    api_key: str,
    user_instructions: str = "",
) -> tuple[FloorPlan, str, RoomBounds]:
    """Return (FloorPlan, analysis_notes, room_bounds_pct) from an image or PDF drawing.

    room_bounds_pct is a dict with keys left/top/right/bottom as fractions of
    image size indicating where the room's outer walls sit in the image.
    """
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
            bounds = _parse_bounds(raw)
            floor_plan = FloorPlan.model_validate(floor_data)
            if not floor_plan.equipment_zones:
                raise ValueError("No equipment zones identified in the drawing.")
            return floor_plan, notes, bounds
        except Exception as exc:
            last_error = exc
            continue

    raise RuntimeError(f"Could not analyze drawing: {last_error}")
