"""Generate equipment layouts using Gemini with a deterministic fallback."""

from __future__ import annotations

import json
import re
from typing import Any

import google.generativeai as genai

try:
    from .models import (
        EquipmentItem,
        EquipmentZone,
        FloorPlan,
        LayoutIssue,
        LayoutResult,
        Placement,
    )
    from .validation import (
        Rect,
        _clearance_rect,
        _equipment_rect,
        _rotated_dims,
        compute_fit_metrics,
        validate_layout,
    )
except ImportError:
    from models import (
        EquipmentItem,
        EquipmentZone,
        FloorPlan,
        LayoutIssue,
        LayoutResult,
        Placement,
    )
    from validation import (
        Rect,
        _clearance_rect,
        _equipment_rect,
        _rotated_dims,
        compute_fit_metrics,
        validate_layout,
    )

GEMINI_MODELS = ("gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash")


def _build_prompt(
    floor_plan: FloorPlan,
    equipment: list[EquipmentItem],
    user_instructions: str = "",
) -> str:
    fp = floor_plan.model_dump()
    eq = [e.model_dump() for e in equipment]

    instructions_block = ""
    if user_instructions.strip():
        instructions_block = f"""
ADDITIONAL INSTRUCTIONS FROM THE USER (follow these carefully — they take priority over the default rules where they conflict):
{user_instructions.strip()}
"""

    return f"""You are a CTE (Career & Technical Education) classroom equipment planner.

Design ONE test-fit layout placing all equipment instances inside the designated equipment zones.

FLOOR PLAN (feet, origin at southwest corner of room):
{json.dumps(fp, indent=2)}

EQUIPMENT LIST:
{json.dumps(eq, indent=2)}
{instructions_block}
RULES:
1. Every equipment instance must fit fully inside an equipment zone (x,y are relative to zone southwest corner).
2. Respect clearances: front, rear, left, right — clearance zones must not overlap between different items.
3. WALL PLACEMENT: Items with wall_preferred "yes" must be placed against a zone wall. The side of the equipment that has clearance_ft = 0 is the side that goes against the wall — place that side flush with the zone edge. Set wall_side to the matching direction.
4. DUPLICATE ADJACENCY: Multiple instances of the same equipment_id (qty > 1) must always be placed directly next to each other, side by side. Their clearance envelopes may touch but must not overlap. Group all instances of the same item together.
5. Honor named adjacency preferences when possible (place related item types within ~6 ft of each other).
6. Maintain circulation: leave a primary aisle at least 4 ft wide through each zone when possible.
7. Windows are on room walls — avoid placing tall equipment directly in front of windows.
8. rotation is degrees: 0, 90, 180, or 270 (clockwise from default orientation).
9. wall_side indicates which zone wall the equipment back is against: north/south/east/west or "none".
10. Create unique instance_id for each placed unit (e.g. "WLD-1", "WLD-2" for qty>1).
11. SWING DOORS: The equipment footprint must NOT be placed inside a swing door arc. The arc extends swing_clearance_ft (or door width_ft if swing_clearance_ft is 0) into the room from the door's wall. Keep this entire zone completely clear.
12. OVERHEAD DOORS: Equipment footprint AND clearance zones must not encroach on overhead door travel paths. The travel path extends door width_ft into the room along the full width of the door.
13. SCALE: Use the exact room and zone dimensions given in feet. Equipment dimensions are in feet. Place equipment at realistic positions that respect the stated room size — do not compress or scale dimensions.
14. ROOM BOUNDS: All equipment footprints and clearance zones must stay fully within the equipment zone boundaries. Clearances must not extend beyond the zone edge.

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
    try:
        from .config import DEFAULT_GEMINI_MODEL
    except ImportError:
        from config import DEFAULT_GEMINI_MODEL

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
    """
    Clearance-aware row packer used when Gemini is unavailable.

    Items are placed left-to-right in rows. The cursor tracks the minimum
    safe x that guarantees no clearance overlap with the previous item.
    When a row is full, the cursor advances by the tallest clearance envelope
    in that row (rear + depth + front) plus an aisle gap.
    """
    if not floor_plan.equipment_zones:
        return [], "No equipment zones defined."

    zone = floor_plan.equipment_zones[0]
    placements: list[Placement] = []

    # x_cursor = left edge of CLEARANCE envelope for next item
    x_cursor = 0.0
    y_cursor = 0.0   # bottom edge of CLEARANCE envelope for current row
    row_clr_height = 0.0
    aisle = 3.0

    # Wall-preferred items first so they land on zone edges
    sorted_items = sorted(equipment, key=lambda e: (0 if e.wall_preferred == "yes" else 1))

    for item in sorted_items:
        # Determine rotation for wall-preferred items (snap zero-clearance side to west wall)
        rotation = 0
        wall_side = "none"
        if item.wall_preferred == "yes":
            # Pick the rotation that puts the zero-clearance side against the west wall
            wxs, _ = _zero_clearance_wall_xs_ys(item, zone, 0)
            if not wxs:
                # Try other rotations
                for rot in (90, 180, 270):
                    wxs2, _ = _zero_clearance_wall_xs_ys(item, zone, rot)
                    if wxs2:
                        rotation = rot
                        break
            wall_side = "west"

        w, d = _rotated_dims(item, rotation)
        clr_w = item.clearance_left_ft + w + item.clearance_right_ft
        clr_h = item.clearance_rear_ft + d + item.clearance_front_ft

        for n in range(item.qty):
            eq_x = x_cursor + item.clearance_left_ft
            eq_y = y_cursor + item.clearance_rear_ft

            if x_cursor + clr_w > zone.width_ft:
                x_cursor = 0.0
                y_cursor += row_clr_height + aisle
                row_clr_height = 0.0
                eq_x = item.clearance_left_ft
                eq_y = y_cursor + item.clearance_rear_ft

            if y_cursor + clr_h > zone.depth_ft:
                break

            placements.append(
                Placement(
                    instance_id=f"{item.id}-{n + 1}",
                    equipment_id=item.id,
                    zone_id=zone.id,
                    x_ft=round(eq_x, 2),
                    y_ft=round(eq_y, 2),
                    rotation=rotation,  # type: ignore[arg-type]
                    wall_side=wall_side,  # type: ignore[arg-type]
                )
            )
            x_cursor += clr_w
            row_clr_height = max(row_clr_height, clr_h)

    return placements, "Fallback grid layout (Gemini unavailable or failed)."


_VALID_ROTATIONS = {0, 90, 180, 270}
_VALID_WALL_SIDES = {"none", "north", "south", "east", "west"}


def _safe_placement(raw: dict) -> Placement:
    """Coerce a raw Gemini placement dict into a valid Placement, fixing common bad values."""
    rotation = raw.get("rotation", 0)
    try:
        rotation = int(float(rotation))
    except (TypeError, ValueError):
        rotation = 0
    # Round to nearest 90, clamp to allowed set
    rotation = min(_VALID_ROTATIONS, key=lambda r: abs(r - (rotation % 360)))

    wall_side = str(raw.get("wall_side", "none")).lower().strip()
    if wall_side not in _VALID_WALL_SIDES:
        wall_side = "none"

    return Placement(
        instance_id=str(raw.get("instance_id", "unknown")),
        equipment_id=str(raw.get("equipment_id", "")),
        zone_id=str(raw.get("zone_id", "")),
        x_ft=float(raw.get("x_ft", 0.0)),
        y_ft=float(raw.get("y_ft", 0.0)),
        rotation=rotation,      # type: ignore[arg-type]
        wall_side=wall_side,    # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# Overlap-repair, wall-snap, and adjacency enforcement
# ---------------------------------------------------------------------------

_GRID_STEP = 1.0   # ft — resolution for the grid search


def _door_forbidden_rects(floor_plan: FloorPlan) -> list[Rect]:
    """Return room-coordinate Rects for swing arcs and overhead door travel paths."""
    rw, rd = floor_plan.width_ft, floor_plan.depth_ft
    rects: list[Rect] = []
    for door in floor_plan.doors:
        door_type = getattr(door, "door_type", "swing")
        off, wid = door.offset_ft, door.width_ft
        if door_type == "swing":
            sc = getattr(door, "swing_clearance_ft", 0.0)
            depth = sc if sc > 0 else wid
        elif door_type == "overhead":
            depth = wid
        else:
            continue
        if door.wall == "south":
            rects.append(Rect(off, 0.0, wid, depth))
        elif door.wall == "north":
            rects.append(Rect(off, rd - depth, wid, depth))
        elif door.wall == "west":
            rects.append(Rect(0.0, rd - off - wid, depth, wid))
        else:
            rects.append(Rect(rw - depth, rd - off - wid, depth, wid))
    return rects


def _placement_valid(
    p: Placement,
    item: EquipmentItem,
    zone: EquipmentZone,
    placed_clrs: list[Rect],
    door_rects: list[Rect],
) -> bool:
    """Return True if placement has no clearance overlap and fits within the zone."""
    w, d = _rotated_dims(item, p.rotation)
    cl, cr = item.clearance_left_ft, item.clearance_right_ft
    cf, cb = item.clearance_front_ft, item.clearance_rear_ft

    # Clearance must stay inside zone
    if p.x_ft < cl or p.y_ft < cb:
        return False
    if p.x_ft + w + cr > zone.width_ft + 0.01:
        return False
    if p.y_ft + d + cf > zone.depth_ft + 0.01:
        return False

    clr = _clearance_rect(p, item, zone)

    # No overlap with already-placed clearances
    for pc in placed_clrs:
        if clr.intersects(pc):
            return False

    # Equipment footprint must not enter door forbidden zones (translated to zone coords)
    eq = _equipment_rect(p, item, zone)
    for dr in door_rects:
        # door_rects are in room coords; zone sits at (zone.x_ft, zone.y_ft)
        dr_local = Rect(dr.x - zone.x_ft, dr.y - zone.y_ft, dr.w, dr.h)
        if eq.intersects(dr_local):
            return False

    return True


def _frange(lo: float, hi: float, step: float) -> list[float]:
    out: list[float] = []
    v = lo
    while v <= hi + 1e-6:
        out.append(round(v, 2))
        v += step
    return out


# Map rotation → (equipment frame side → room direction)
_ROTATION_MAP: dict[int, dict[str, str]] = {
    0:   {"rear": "south", "front": "north", "left": "west",  "right": "east"},
    90:  {"rear": "west",  "front": "east",  "left": "south", "right": "north"},
    180: {"rear": "north", "front": "south", "left": "east",  "right": "west"},
    270: {"rear": "east",  "front": "west",  "left": "north", "right": "south"},
}


def _zero_clearance_wall_xs_ys(
    item: EquipmentItem,
    zone: EquipmentZone,
    rotation: int,
) -> tuple[list[float], list[float]]:
    """
    Return (wall_xs, wall_ys) — the x/y positions (zone-relative SW corner of footprint)
    where the zero-clearance side of the item is flush against the zone boundary.
    Used to snap wall_preferred items correctly.
    """
    w, d = _rotated_dims(item, rotation)
    cl, cr = item.clearance_left_ft, item.clearance_right_ft
    cf, cb = item.clearance_rear_ft, item.clearance_front_ft

    mapping = _ROTATION_MAP.get(rotation, _ROTATION_MAP[0])
    clr_by_side = {
        "rear":  item.clearance_rear_ft,
        "front": item.clearance_front_ft,
        "left":  item.clearance_left_ft,
        "right": item.clearance_right_ft,
    }

    wall_xs: list[float] = []
    wall_ys: list[float] = []

    for eq_side, room_dir in mapping.items():
        if clr_by_side[eq_side] > 0.01:
            continue  # only snap zero-clearance sides
        if room_dir == "west":
            wall_xs.append(0.0)
        elif room_dir == "east":
            x = zone.width_ft - w
            if x >= 0:
                wall_xs.append(x)
        elif room_dir == "south":
            wall_ys.append(0.0)
        elif room_dir == "north":
            y = zone.depth_ft - d
            if y >= 0:
                wall_ys.append(y)

    return wall_xs, wall_ys


def _find_valid_position(
    p: Placement,
    item: EquipmentItem,
    zone: EquipmentZone,
    placed_clrs: list[Rect],
    door_rects: list[Rect],
    peer_positions: list[tuple[float, float]] | None = None,
) -> Placement | None:
    """
    Grid-search the zone for the nearest valid position to Gemini's suggestion.

    peer_positions: (x, y) of already-placed instances of the same equipment type.
    When provided, candidate positions are sorted by proximity to peers first,
    ensuring duplicates cluster together.
    """
    w, d = _rotated_dims(item, p.rotation)
    cl, cr = item.clearance_left_ft, item.clearance_right_ft
    cf, cb = item.clearance_front_ft, item.clearance_rear_ft

    x_min = cl
    x_max = zone.width_ft - w - cr
    y_min = cb
    y_max = zone.depth_ft - d - cf

    if x_max < x_min - 0.01 or y_max < y_min - 0.01:
        return None  # item cannot physically fit in this zone

    x_min = max(x_min, 0.0)
    y_min = max(y_min, 0.0)

    # For wall_preferred items, build a priority list of wall-snap positions
    priority_candidates: list[tuple[float, float]] = []
    if item.wall_preferred == "yes":
        wxs, wys = _zero_clearance_wall_xs_ys(item, zone, p.rotation)
        xs_grid = _frange(x_min, x_max, _GRID_STEP)
        ys_grid = _frange(y_min, y_max, _GRID_STEP)
        if wxs:
            for wx in wxs:
                if x_min - 0.01 <= wx <= x_max + 0.01:
                    for y in ys_grid:
                        priority_candidates.append((wx, y))
        if wys:
            for wy in wys:
                if y_min - 0.01 <= wy <= y_max + 0.01:
                    for x in xs_grid:
                        priority_candidates.append((x, wy))

    # Full grid fallback
    xs = _frange(x_min, x_max, _GRID_STEP)
    ys = _frange(y_min, y_max, _GRID_STEP)

    # Sort origin: peers first (for duplicate adjacency), otherwise Gemini's position
    if peer_positions:
        def dist_to_peers(xy: tuple[float, float]) -> float:
            return min(
                abs(xy[0] - px) + abs(xy[1] - py)
                for px, py in peer_positions
            )
        priority_candidates.sort(key=dist_to_peers)
        full_grid = [(x, y) for y in ys for x in xs]
        full_grid.sort(key=dist_to_peers)
    else:
        ox = max(x_min, min(x_max, p.x_ft))
        oy = max(y_min, min(y_max, p.y_ft))
        priority_candidates.sort(key=lambda xy: abs(xy[0] - ox) + abs(xy[1] - oy))
        full_grid = [(x, y) for y in ys for x in xs]
        full_grid.sort(key=lambda xy: abs(xy[0] - ox) + abs(xy[1] - oy))

    # Try priority (wall snaps) first, then the full grid
    seen: set[tuple[float, float]] = set()
    for x, y in priority_candidates + full_grid:
        xy = (round(x, 2), round(y, 2))
        if xy in seen:
            continue
        seen.add(xy)
        # Derive appropriate wall_side for this position
        ws = p.wall_side
        if item.wall_preferred == "yes":
            wxs, wys = _zero_clearance_wall_xs_ys(item, zone, p.rotation)
            if wxs and abs(x - wxs[0]) < 0.05:
                mapping = _ROTATION_MAP.get(p.rotation, _ROTATION_MAP[0])
                ws = next(
                    (mapping[s] for s, v in {"rear": item.clearance_rear_ft,
                     "front": item.clearance_front_ft, "left": item.clearance_left_ft,
                     "right": item.clearance_right_ft}.items() if v < 0.01), ws
                )
        candidate = Placement(
            instance_id=p.instance_id,
            equipment_id=p.equipment_id,
            zone_id=p.zone_id,
            x_ft=xy[0],
            y_ft=xy[1],
            rotation=p.rotation,
            wall_side=ws,  # type: ignore[arg-type]
        )
        if _placement_valid(candidate, item, zone, placed_clrs, door_rects):
            return candidate

    return None


def _repair_overlaps(
    placements: list[Placement],
    equipment: list[EquipmentItem],
    floor_plan: FloorPlan,
) -> tuple[list[Placement], list[str]]:
    """
    Post-process placements to guarantee:
    1. No clearance overlaps.
    2. Duplicate items (same equipment_id) are placed adjacent to each other.
    3. wall_preferred items are snapped to the zero-clearance side of the zone wall.

    Strategy:
    - Group placements by equipment_id so all instances of the same item are
      processed consecutively. The 2nd+ instance in a group gets the peer positions
      of already-placed instances so _find_valid_position clusters them together.
    - Within each group, sort by clearance footprint (largest first).
    - Across groups, wall_preferred items are processed before freestanding items.
    """
    eq_by_id   = {e.id: e for e in equipment}
    zone_by_id = {z.id: z for z in floor_plan.equipment_zones}
    door_rects = _door_forbidden_rects(floor_plan)
    notes: list[str] = []

    def _clr_area(p: Placement) -> float:
        item = eq_by_id.get(p.equipment_id)
        if not item:
            return 0.0
        w, d = _rotated_dims(item, p.rotation)
        return (
            (w + item.clearance_left_ft + item.clearance_right_ft)
            * (d + item.clearance_rear_ft + item.clearance_front_ft)
        )

    # Group by equipment_id, preserving Gemini's instance order within each group
    from collections import defaultdict
    groups: dict[str, list[Placement]] = defaultdict(list)
    for p in placements:
        groups[p.equipment_id].append(p)

    # Order groups: wall_preferred first, then by largest clearance footprint
    def _group_priority(eq_id: str) -> tuple:
        item = eq_by_id.get(eq_id)
        if not item:
            return (1, 0.0)
        wall_first = 0 if item.wall_preferred == "yes" else 1
        avg_area = sum(_clr_area(p) for p in groups[eq_id]) / max(len(groups[eq_id]), 1)
        return (wall_first, -avg_area)

    ordered_eq_ids = sorted(groups.keys(), key=_group_priority)

    placed: list[Placement] = []
    placed_clrs: list[Rect] = []
    unplaced: list[Placement] = []

    for eq_id in ordered_eq_ids:
        group = groups[eq_id]
        peer_positions: list[tuple[float, float]] = []   # positions of placed peers in this group

        for p in group:
            item = eq_by_id.get(p.equipment_id)
            zone = zone_by_id.get(p.zone_id)

            if not item or not zone:
                placed.append(p)
                continue

            if _placement_valid(p, item, zone, placed_clrs, door_rects):
                placed.append(p)
                placed_clrs.append(_clearance_rect(p, item, zone))
                peer_positions.append((p.x_ft, p.y_ft))
            else:
                repaired = _find_valid_position(
                    p, item, zone, placed_clrs, door_rects,
                    peer_positions=peer_positions or None,
                )
                if repaired:
                    placed.append(repaired)
                    placed_clrs.append(_clearance_rect(repaired, item, zone))
                    peer_positions.append((repaired.x_ft, repaired.y_ft))
                    notes.append(
                        f"{p.instance_id} repositioned ({p.x_ft:.1f},{p.y_ft:.1f})"
                        f"→({repaired.x_ft:.1f},{repaired.y_ft:.1f})"
                    )
                else:
                    unplaced.append(p)
                    notes.append(
                        f"{p.instance_id} could not be placed without overlap"
                    )

    return placed + unplaced, notes


def generate_layout(
    floor_plan: FloorPlan,
    equipment: list[EquipmentItem],
    api_key: str,
    user_instructions: str = "",
) -> LayoutResult:
    summary = ""
    placements: list[Placement] = []
    gemini_error: str | None = None

    if api_key.strip():
        try:
            raw = _call_gemini(
                api_key.strip(),
                _build_prompt(floor_plan, equipment, user_instructions),
            )
            summary = raw.get("summary", "")
            for p in raw.get("placements", []):
                placements.append(_safe_placement(p))
        except Exception as exc:
            gemini_error = str(exc)

    if not placements:
        placements, fallback_summary = _fallback_layout(floor_plan, equipment)
        summary = fallback_summary
        if gemini_error:
            summary += f" Gemini error: {gemini_error}"

    # Always run the overlap-repair pass — this guarantees no clearance overlaps
    # regardless of whether Gemini or the fallback produced the initial positions.
    placements, repair_notes = _repair_overlaps(placements, equipment, floor_plan)
    if repair_notes:
        repair_msg = f"Auto-repaired {len(repair_notes)} placement(s) to eliminate clearance overlaps."
        summary = (summary + "  " + repair_msg).strip()

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
