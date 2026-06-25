"""Generate equipment layouts using Gemini with a deterministic fallback."""

from __future__ import annotations

import json
import re
from typing import Any

import google.generativeai as genai

from .models import (
    EquipmentItem,
    EquipmentZone,
    FloorPlan,
    LayoutIssue,
    LayoutResult,
    Placement,
)
from .validation import compute_fit_metrics, validate_layout

GEMINI_MODELS = ("gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash")


def _build_prompt(floor_plan: FloorPlan, equipment: list[EquipmentItem]) -> str:
    fp = floor_plan.model_dump()
    eq = [e.model_dump() for e in equipment]
    return f"""You are a CTE (Career & Technical Education) classroom equipment planner.

Design ONE test-fit layout placing all equipment instances inside the designated equipment zones.

FLOOR PLAN (feet, origin at southwest corner of room):
{json.dumps(fp, indent=2)}

EQUIPMENT LIST:
{json.dumps(eq, indent=2)}

RULES:
1. Every equipment instance must fit fully inside an equipment zone (x,y are relative to zone southwest corner).
2. Respect clearances: front, rear, left, right — clearance zones must not overlap between different items.
3. Items with wall_preferred "yes" should be placed against a zone wall; avoid blocking doors/windows on room walls.
4. Honor adjacency preferences when possible (place related items within ~6 ft).
5. Maintain circulation: leave a primary aisle at least 4 ft wide through each zone when possible.
6. Windows are on room walls — avoid placing tall equipment directly in front of windows.
7. rotation is degrees: 0, 90, 180, or 270 (clockwise from default orientation).
8. wall_side indicates which zone wall the equipment back is against: north/south/east/west or "none".
9. Create unique instance_id for each placed unit (e.g. "WLD-1", "WLD-2" for qty>1).

Respond with ONLY valid JSON (no markdown fences):
{{
  "placements": [
    {{
      "instance_id": "string",
      "equipment_id": "string",
      "zone_id": "string",
      "x_ft": 0.0,
      "y_ft": 0.0,
      "rotation": 0,
      "wall_side": "none"
    }}
  ],
  "summary": "Brief narrative of layout strategy and any compromises"
}}
"""


def _parse_gemini_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned)
    if fence:
        cleaned = fence.group(1).strip()
    return json.loads(cleaned)


def _call_gemini(api_key: str, prompt: str) -> dict[str, Any]:
    from .config import DEFAULT_GEMINI_MODEL

    genai.configure(api_key=api_key)
    last_error: Exception | None = None

    for model_name in (DEFAULT_GEMINI_MODEL, *GEMINI_MODELS):
        try:
            model = genai.GenerativeModel(
                model_name,
                generation_config={
                    "temperature": 0.2,
                    "response_mime_type": "application/json",
                },
            )
            response = model.generate_content(prompt)
            return _parse_gemini_json(response.text)
        except Exception as exc:
            last_error = exc
            continue

    raise last_error or RuntimeError("All Gemini models failed")


def _fallback_layout(
    floor_plan: FloorPlan, equipment: list[EquipmentItem]
) -> tuple[list[Placement], str]:
    """Simple row-based placer when Gemini is unavailable."""
    if not floor_plan.equipment_zones:
        return [], "No equipment zones defined."

    zone = floor_plan.equipment_zones[0]
    placements: list[Placement] = []
    cursor_x = 1.0
    cursor_y = 1.0
    row_height = 0.0
    aisle = 4.0

    for item in equipment:
        for n in range(item.qty):
            w, d = item.width_ft, item.depth_ft
            if cursor_x + w + item.clearance_right_ft > zone.width_ft - 1:
                cursor_x = 1.0
                cursor_y += row_height + aisle
                row_height = 0.0

            if cursor_y + d + item.clearance_front_ft > zone.depth_ft - 1:
                break

            wall_side = "none"
            if item.wall_preferred == "yes" and cursor_x < 2.0:
                wall_side = "west"

            placements.append(
                Placement(
                    instance_id=f"{item.id}-{n + 1}",
                    equipment_id=item.id,
                    zone_id=zone.id,
                    x_ft=round(cursor_x, 2),
                    y_ft=round(cursor_y, 2),
                    rotation=0,
                    wall_side=wall_side,
                )
            )
            cursor_x += w + item.clearance_left_ft + item.clearance_right_ft + 1.0
            row_height = max(row_height, d)

    return placements, "Fallback grid layout (Gemini unavailable or failed)."


def generate_layout(
    floor_plan: FloorPlan,
    equipment: list[EquipmentItem],
    api_key: str,
) -> LayoutResult:
    summary = ""
    placements: list[Placement] = []
    gemini_error: str | None = None

    if api_key.strip():
        try:
            raw = _call_gemini(api_key.strip(), _build_prompt(floor_plan, equipment))
            summary = raw.get("summary", "")
            for p in raw.get("placements", []):
                placements.append(Placement(**p))
        except Exception as exc:
            gemini_error = str(exc)

    if not placements:
        placements, fallback_summary = _fallback_layout(floor_plan, equipment)
        summary = fallback_summary
        if gemini_error:
            summary += f" Gemini error: {gemini_error}"

    issues = validate_layout(floor_plan, equipment, placements)
    if gemini_error and not api_key.strip():
        issues.append(
            LayoutIssue(
                severity="info",
                message="No Gemini API key provided — using fallback layout.",
            )
        )
    elif gemini_error:
        issues.append(
            LayoutIssue(
                severity="warning",
                message=f"Gemini layout failed, used fallback: {gemini_error}",
            )
        )

    fits, extra_sqft, utilization = compute_fit_metrics(
        floor_plan, equipment, placements
    )

    if not fits:
        issues.append(
            LayoutIssue(
                severity="error",
                message=f"Insufficient space — approximately {extra_sqft:.0f} additional sq ft needed.",
            )
        )

    has_errors = any(i.severity == "error" for i in issues)

    return LayoutResult(
        placements=placements,
        issues=issues,
        fits=fits and not has_errors,
        additional_sqft_needed=extra_sqft,
        zone_utilization_pct=utilization,
        summary=summary,
    )
