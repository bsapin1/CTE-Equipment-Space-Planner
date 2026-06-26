"""Streamlit UI for CTE Equipment Space Planner."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st
from PIL import Image

ROOT = Path(__file__).resolve().parent

# Support flat GitHub uploads (all .py files at repo root) and normal server/ layout
if (ROOT / "server" / "config.py").exists():
    from server.config import resolve_gemini_api_key
    from server.csv_parser import equipment_to_dataframe, parse_equipment_file
    from server.equipment_ai import smart_parse_equipment
    from server.floorplan_vision import analyze_floor_plan_drawing
    from server.layout_engine import generate_layout
    from server.models import EquipmentItem, EquipmentZone, ExportRequest, FloorPlan, Opening
    from server.renderer import render_layout_on_drawing, render_layout_png
else:
    sys.path.insert(0, str(ROOT))
    from config import resolve_gemini_api_key
    from csv_parser import equipment_to_dataframe, parse_equipment_file
    from equipment_ai import smart_parse_equipment
    from floorplan_vision import analyze_floor_plan_drawing
    from layout_engine import generate_layout
    from models import EquipmentItem, EquipmentZone, ExportRequest, FloorPlan, Opening
    from renderer import render_layout_on_drawing, render_layout_png

TEMPLATES = ROOT / "templates" if (ROOT / "templates").is_dir() else ROOT

st.set_page_config(
    page_title="CTE Equipment Space Planner",
    page_icon="🏗️",
    layout="wide",
)

st.title("CTE Equipment Space Planner")
st.caption(
    "Test-fit CTE equipment in a blank classroom floor plan. "
    "Define the space, upload an equipment spreadsheet, and generate a layout "
    "that respects clearances, adjacencies, circulation, and wall/door/window placement."
)


def render_bounds_preview(
    image_bytes: bytes,
    bounds: dict,
    room_dims: tuple[float, float] | None = None,
) -> bytes | None:
    """Draw the room bounds rectangle on the image and return PNG bytes."""
    try:
        from PIL import Image as _Image, ImageDraw as _Draw, ImageFont as _Font

        img = _Image.open(io.BytesIO(image_bytes)).convert("RGBA")
        w, h = img.size

        # Keep preview width reasonable — scale down if very large
        max_w = 900
        if w > max_w:
            scale = max_w / w
            img = img.resize((int(w * scale), int(h * scale)), _Image.LANCZOS)
            w, h = img.size

        overlay = _Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = _Draw.Draw(overlay)

        x0 = int(bounds["left"] * w)
        y0 = int(bounds["top"] * h)
        x1 = int(bounds["right"] * w)
        y1 = int(bounds["bottom"] * h)

        # Semi-transparent fill inside room bounds
        draw.rectangle([x0, y0, x1, y1], fill=(37, 99, 235, 35))
        # Bright border
        draw.rectangle([x0, y0, x1, y1], outline=(37, 99, 235, 230), width=3)

        # Corner tick marks
        tick = max(8, int(min(w, h) * 0.025))
        for cx, cy in [(x0, y0), (x1, y0), (x0, y1), (x1, y1)]:
            dx = tick if cx == x0 else -tick
            dy = tick if cy == y0 else -tick
            draw.line([(cx, cy), (cx + dx, cy)], fill=(37, 99, 235, 255), width=3)
            draw.line([(cx, cy), (cx, cy + dy)], fill=(37, 99, 235, 255), width=3)

        # Label (include dimensions if provided)
        if room_dims:
            label = f"Room: {room_dims[0]:.0f}' × {room_dims[1]:.0f}'"
        else:
            label = "Room boundary"
        try:
            font = _Font.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 14)
        except OSError:
            font = _Font.load_default()
        text_x = x0 + 6
        text_y = y0 + 6
        draw.text((text_x + 1, text_y + 1), label, fill=(0, 0, 0, 200), font=font)
        draw.text((text_x, text_y), label, fill=(37, 99, 235, 255), font=font)

        preview = _Image.alpha_composite(img, overlay).convert("RGB")
        buf = io.BytesIO()
        preview.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return None


def _sanitize_equipment(items: list) -> list:
    """Coerce a list of EquipmentItem objects or dicts into valid EquipmentItem objects."""
    safe = []
    for raw in items:
        try:
            d = raw if isinstance(raw, dict) else raw.model_dump()
            wall = str(d.get("wall_preferred", "any")).lower().strip()
            if wall not in ("yes", "no", "any"):
                wall = "any"
            adj = d.get("adjacency", [])
            if isinstance(adj, str):
                adj = [s.strip() for s in adj.replace("|", ";").split(";") if s.strip()]
            safe.append(EquipmentItem(
                id=str(d.get("id") or "EQ").strip() or "EQ",
                name=str(d.get("name") or "Unknown").strip() or "Unknown",
                width_ft=max(0.1, float(d.get("width_ft") or 1.0)),
                depth_ft=max(0.1, float(d.get("depth_ft") or 1.0)),
                qty=max(1, int(float(d.get("qty") or 1))),
                clearance_front_ft=max(0.0, float(d.get("clearance_front_ft") or 3.0)),
                clearance_rear_ft=max(0.0, float(d.get("clearance_rear_ft") or 1.0)),
                clearance_left_ft=max(0.0, float(d.get("clearance_left_ft") or 1.5)),
                clearance_right_ft=max(0.0, float(d.get("clearance_right_ft") or 1.5)),
                wall_preferred=wall,  # type: ignore[arg-type]
                adjacency=[str(a).strip() for a in adj if str(a).strip()],
                category=str(d.get("category") or "general").strip() or "general",
                notes=str(d.get("notes") or "").strip(),
            ))
        except Exception:
            continue
    return safe


def load_sample_floor_plan() -> dict:
    return json.loads((TEMPLATES / "sample-floor-plan.json").read_text())


def load_sample_equipment_bytes() -> bytes:
    """Return the sample equipment file (xlsx preferred, csv fallback)."""
    xlsx = TEMPLATES / "sample-equipment.xlsx"
    if xlsx.exists():
        return xlsx.read_bytes()
    return (TEMPLATES / "sample-equipment.csv").read_bytes()


def parse_floor_plan_json(raw: str | bytes) -> FloorPlan:
    return FloorPlan.model_validate(json.loads(raw))


def build_floor_plan_from_form(
    name: str,
    width_ft: float,
    depth_ft: float,
    door_wall: str,
    door_offset: float,
    door_width: float,
    win_wall: str,
    win1_offset: float,
    win1_width: float,
    win2_offset: float,
    win2_width: float,
    zone_label: str,
    zone_x: float,
    zone_y: float,
    zone_w: float,
    zone_d: float,
) -> FloorPlan:
    windows: list[Opening] = []
    if win1_width > 0:
        windows.append(Opening(wall=win_wall, offset_ft=win1_offset, width_ft=win1_width))  # type: ignore[arg-type]
    if win2_width > 0:
        windows.append(Opening(wall=win_wall, offset_ft=win2_offset, width_ft=win2_width))  # type: ignore[arg-type]

    return FloorPlan(
        name=name,
        width_ft=width_ft,
        depth_ft=depth_ft,
        doors=[Opening(wall=door_wall, offset_ft=door_offset, width_ft=door_width)],  # type: ignore[arg-type]
        windows=windows,
        equipment_zones=[
            EquipmentZone(
                id="zone-1",
                label=zone_label,
                x_ft=zone_x,
                y_ft=zone_y,
                width_ft=zone_w,
                depth_ft=zone_d,
            )
        ],
    )


def show_issues(issues: list) -> None:
    for issue in issues:
        if issue.severity == "error":
            st.error(issue.message)
        elif issue.severity == "warning":
            st.warning(issue.message)
        else:
            st.info(issue.message)


def render_visual_editor() -> FloorPlan:
    sample_fp = load_sample_floor_plan()
    zone0 = sample_fp["equipment_zones"][0]
    door0 = sample_fp["doors"][0]
    win0 = sample_fp["windows"][0]
    win1 = sample_fp["windows"][1] if len(sample_fp["windows"]) > 1 else win0

    name = st.text_input("Room name", value=sample_fp["name"], key="fp_name")
    c1, c2 = st.columns(2)
    width_ft = c1.number_input("Room width (ft)", min_value=10.0, value=float(sample_fp["width_ft"]), key="fp_w")
    depth_ft = c2.number_input("Room depth (ft)", min_value=10.0, value=float(sample_fp["depth_ft"]), key="fp_d")

    st.markdown("**Door**")
    d1, d2, d3 = st.columns(3)
    door_wall = d1.selectbox("Wall", ["south", "north", "east", "west"], index=0, key="door_wall")
    door_offset = d2.number_input("Offset (ft)", min_value=0.0, value=float(door0["offset_ft"]), key="door_off")
    door_width = d3.number_input("Width (ft)", min_value=2.0, value=float(door0["width_ft"]), key="door_w")

    st.markdown("**Windows**")
    w1, w2, w3 = st.columns(3)
    win_wall = w1.selectbox("Window wall", ["north", "south", "east", "west"], index=0, key="win_wall")
    win1_offset = w2.number_input("Window 1 offset (ft)", min_value=0.0, value=float(win0["offset_ft"]), key="win1_off")
    win1_width = w3.number_input("Window 1 width (ft)", min_value=0.0, value=float(win0["width_ft"]), key="win1_w")
    w4, w5 = st.columns(2)
    win2_offset = w4.number_input("Window 2 offset (ft)", min_value=0.0, value=float(win1["offset_ft"]), key="win2_off")
    win2_width = w5.number_input("Window 2 width (ft)", min_value=0.0, value=float(win1["width_ft"]), key="win2_w")

    st.markdown("**Equipment zone**")
    zone_label = st.text_input("Zone label", value=zone0["label"], key="zone_label")
    z2, z3, z4 = st.columns(3)
    zone_x = z2.number_input("Zone X (ft)", min_value=0.0, value=float(zone0["x_ft"]), key="zone_x")
    zone_y = z3.number_input("Zone Y (ft)", min_value=0.0, value=float(zone0["y_ft"]), key="zone_y")
    zone_w = z4.number_input("Zone width (ft)", min_value=4.0, value=float(zone0["width_ft"]), key="zone_w")
    zone_d = st.number_input("Zone depth (ft)", min_value=4.0, value=float(zone0["depth_ft"]), key="zone_d")

    return build_floor_plan_from_form(
        name, width_ft, depth_ft,
        door_wall, door_offset, door_width,
        win_wall, win1_offset, win1_width, win2_offset, win2_width,
        zone_label, zone_x, zone_y, zone_w, zone_d,
    )


# --- Sidebar ---
with st.sidebar:
    st.header("Settings")

    sidebar_key = st.text_input(
        "Gemini API Key (override)",
        type="password",
        help=(
            "Optional. Leave blank to use `.streamlit/secrets.toml` or `.env`. "
            "Enter a value here to override for this session."
        ),
        placeholder="Leave blank if configured in secrets / .env",
    )
    api_key, key_source = resolve_gemini_api_key(sidebar_key)

    if api_key:
        if key_source == "sidebar":
            st.success("Using API key from sidebar.")
        elif key_source == "Streamlit secrets":
            st.success("Using API key from Streamlit secrets.")
        else:
            st.success("Using API key from `.env` / environment.")
    else:
        st.info(
            "No API key configured. Add one to `.streamlit/secrets.toml` or `.env`, "
            "or enter it above. Without a key, a basic fallback grid layout is used."
        )

    with st.expander("How to configure API key"):
        st.markdown(
            """
**Option 1 — Streamlit secrets** (recommended)

Create `.streamlit/secrets.toml`:
```toml
gemini_api_key = "AIza..."
```

**Option 2 — Environment / `.env`**

Copy `.env.example` to `.env`:
```
GEMINI_API_KEY=AIza...
```

**Option 3 — Sidebar**

Enter the key in the field above (overrides options 1 & 2).

Get a key at [Google AI Studio](https://aistudio.google.com/apikey).
            """
        )

    st.divider()
    st.markdown("**Sample files**")
    _fp_png = TEMPLATES / "sample-floor-plan.png"
    if _fp_png.exists():
        st.download_button(
            "Download sample floor plan (PNG)",
            data=_fp_png.read_bytes(),
            file_name="sample-floor-plan.png",
            mime="image/png",
        )
    st.download_button(
        "Download sample equipment list (Excel)",
        data=load_sample_equipment_bytes(),
        file_name="sample-equipment.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# --- Inputs ---
col_fp, col_eq = st.columns(2)
floor_plan: FloorPlan | None = None
equipment: list | None = None

with col_fp:
    st.subheader("1. Floor Plan")
    fp_mode = st.radio(
        "Floor plan input",
        ["Upload drawing", "Visual editor", "Upload JSON"],
        horizontal=True,
        label_visibility="collapsed",
    )

    if fp_mode == "Upload drawing":
        st.caption("Upload a floor plan image or PDF. Gemini will read the drawing and extract room dimensions, zones, doors, and windows.")
        drawing_file = st.file_uploader(
            "Floor plan drawing",
            type=["jpg", "jpeg", "png", "pdf"],
            help="JPG, PNG, or PDF",
        )
        reading_instructions = st.text_area(
            "Instructions for reading the drawing (optional)",
            height=120,
            placeholder=(
                "Example: North is up. The main shop area is the large open space on the left. "
                "Door is on the south wall. Dimensions are in feet — room is 42' x 28'. "
                "Do not use the storage closet in the northeast corner as equipment space."
            ),
            help="Tell Gemini how to interpret labels, scale, north arrow, which areas are for equipment, etc.",
        )

        if drawing_file:
            st.session_state["drawing_bytes"] = drawing_file.getvalue()
            st.session_state["drawing_name"] = drawing_file.name
            mime = drawing_file.type or ""
            if mime.startswith("image/") or drawing_file.name.lower().endswith((".jpg", ".jpeg", ".png")):
                st.image(st.session_state["drawing_bytes"], caption="Uploaded drawing", use_container_width=True)

            if st.button("Analyze drawing", type="secondary", use_container_width=True):
                if not api_key:
                    st.error("Gemini API key is required to analyze drawings. Add it in Streamlit Secrets.")
                else:
                    with st.spinner("Analyzing floor plan with Gemini…"):
                        try:
                            result = analyze_floor_plan_drawing(
                                st.session_state["drawing_bytes"],
                                st.session_state["drawing_name"],
                                api_key,
                                reading_instructions,
                            )
                            # Support both old (2-tuple) and new (3-tuple) return value
                            if len(result) == 3:
                                fp, notes, bounds = result
                            else:
                                fp, notes = result
                                bounds = {"left": 0.0, "top": 0.0, "right": 1.0, "bottom": 1.0}
                            st.session_state["drawing_floor_plan"] = fp
                            st.session_state["drawing_analysis_notes"] = notes
                            st.session_state["drawing_filename"] = drawing_file.name
                            st.session_state["drawing_bg_bytes"] = st.session_state["drawing_bytes"]
                            st.session_state["drawing_bg_name"] = drawing_file.name
                            st.session_state["room_bounds_pct"] = bounds
                        except Exception as exc:
                            st.error(f"Analysis failed: {exc}")

        if "drawing_floor_plan" in st.session_state:
            floor_plan = st.session_state["drawing_floor_plan"]
            st.success(
                f"Analyzed: **{floor_plan.name}** ({floor_plan.width_ft}' × {floor_plan.depth_ft}') "
                f"— {len(floor_plan.equipment_zones)} equipment zone(s)"
            )
            notes = st.session_state.get("drawing_analysis_notes", "")
            if notes:
                st.markdown(f"**Analysis:** {notes}")

            with st.expander("🔲 Adjust room bounds and dimensions", expanded=True):
                st.caption(
                    "Set the actual room size, then drag the sliders to align the blue box "
                    "with the room walls in the image."
                )

                # ── Room dimension inputs ─────────────────────────────────────
                fp_cur = st.session_state["drawing_floor_plan"]
                dim_c1, dim_c2 = st.columns(2)
                room_w_input = dim_c1.number_input(
                    "Room width (ft)",
                    min_value=5.0,
                    max_value=1000.0,
                    value=float(fp_cur.width_ft),
                    step=1.0,
                    key="room_w_override",
                    help="Actual room width in feet (east–west)",
                )
                room_d_input = dim_c2.number_input(
                    "Room depth (ft)",
                    min_value=5.0,
                    max_value=1000.0,
                    value=float(fp_cur.depth_ft),
                    step=1.0,
                    key="room_d_override",
                    help="Actual room depth in feet (north–south)",
                )

                # If the user changed either dimension, rebuild the floor plan
                # and scale equipment zones proportionally.
                if abs(room_w_input - fp_cur.width_ft) > 0.01 or abs(room_d_input - fp_cur.depth_ft) > 0.01:
                    sw = room_w_input / fp_cur.width_ft if fp_cur.width_ft else 1.0
                    sd = room_d_input / fp_cur.depth_ft if fp_cur.depth_ft else 1.0
                    updated_zones = [
                        EquipmentZone(
                            id=z.id,
                            label=z.label,
                            x_ft=round(z.x_ft * sw, 2),
                            y_ft=round(z.y_ft * sd, 2),
                            width_ft=round(z.width_ft * sw, 2),
                            depth_ft=round(z.depth_ft * sd, 2),
                        )
                        for z in fp_cur.equipment_zones
                    ]
                    updated_fp = FloorPlan(
                        name=fp_cur.name,
                        width_ft=room_w_input,
                        depth_ft=room_d_input,
                        doors=fp_cur.doors,
                        windows=fp_cur.windows,
                        equipment_zones=updated_zones,
                    )
                    st.session_state["drawing_floor_plan"] = updated_fp
                    floor_plan = updated_fp

                # ── Boundary sliders ─────────────────────────────────────────
                st.markdown("**Image boundary alignment**")
                st.caption("0% = left/top edge of image · 100% = right/bottom edge")
                bounds = st.session_state.get("room_bounds_pct", {"left": 0.0, "top": 0.0, "right": 1.0, "bottom": 1.0})
                bc1, bc2 = st.columns(2)
                b_left   = bc1.slider("Left edge (%)",   0,  50, int(bounds["left"]   * 100), 1, key="b_left")
                b_right  = bc2.slider("Right edge (%)",  50, 100, int(bounds["right"]  * 100), 1, key="b_right")
                b_top    = bc1.slider("Top edge (%)",    0,  50, int(bounds["top"]    * 100), 1, key="b_top")
                b_bottom = bc2.slider("Bottom edge (%)", 50, 100, int(bounds["bottom"] * 100), 1, key="b_bottom")

                adjusted_bounds = {
                    "left":   b_left   / 100,
                    "top":    b_top    / 100,
                    "right":  b_right  / 100,
                    "bottom": b_bottom / 100,
                }
                st.session_state["room_bounds_pct"] = adjusted_bounds

                # Live preview with dimension label
                cur_fp = st.session_state["drawing_floor_plan"]
                preview_bytes = render_bounds_preview(
                    st.session_state["drawing_bg_bytes"],
                    adjusted_bounds,
                    room_dims=(cur_fp.width_ft, cur_fp.depth_ft),
                )
                if preview_bytes:
                    st.image(
                        preview_bytes,
                        caption="Adjust sliders until the blue box aligns with the room walls",
                        use_container_width=True,
                    )

            with st.expander("Extracted floor plan JSON (review or edit)"):
                edited = st.text_area(
                    "Floor plan JSON",
                    value=floor_plan.model_dump_json(indent=2),
                    height=220,
                    key="drawing_fp_json_edit",
                )
                if st.button("Apply JSON edits", key="apply_drawing_json"):
                    try:
                        floor_plan = parse_floor_plan_json(edited)
                        st.session_state["drawing_floor_plan"] = floor_plan
                        st.success("Floor plan updated.")
                    except Exception as exc:
                        st.error(f"Invalid JSON: {exc}")

    elif fp_mode == "Upload JSON":
        json_file = st.file_uploader("Upload floor plan JSON", type=["json"])
        if st.button("Load sample floor plan", key="load_sample_fp"):
            st.session_state["fp_json_text"] = json.dumps(load_sample_floor_plan(), indent=2)
        json_text = st.text_area(
            "Or paste floor plan JSON",
            height=200,
            value=st.session_state.get("fp_json_text", ""),
            key="fp_json_area",
        )
        raw = json_file.read() if json_file else json_text.strip()
        if raw:
            try:
                floor_plan = parse_floor_plan_json(raw)
                st.success(f"Loaded: **{floor_plan.name}** ({floor_plan.width_ft}' × {floor_plan.depth_ft}')")
            except Exception as exc:
                st.error(f"Invalid floor plan JSON: {exc}")
    else:
        floor_plan = render_visual_editor()

with col_eq:
    st.subheader("2. Equipment List")

    eq_mode = st.radio(
        "Equipment parsing mode",
        ["Smart parse (Gemini)", "Strict columns"],
        horizontal=True,
        help=(
            "Smart parse lets Gemini read any spreadsheet layout and map it to the fields "
            "the tool needs. Strict columns requires the exact template headers."
        ),
        label_visibility="collapsed",
    )

    eq_file = st.file_uploader("Upload equipment spreadsheet (CSV or Excel)", type=["csv", "xlsx", "xlsm"])

    if eq_file and st.session_state.get("ai_equipment_file") != eq_file.name:
        st.session_state.pop("ai_equipment", None)
        st.session_state.pop("ai_equipment_notes", None)
        st.session_state["ai_equipment_file"] = eq_file.name

    if eq_mode == "Smart parse (Gemini)":
        eq_instructions = st.text_area(
            "Instructions for reading the spreadsheet (optional)",
            height=110,
            placeholder=(
                "Example: Dimensions are in inches. 'Footprint' column is width x depth. "
                "Treat the 'Location' column as wall preference. Ignore the pricing columns. "
                "Quantity is in the 'Count' column."
            ),
            help="Tell Gemini about units, which columns mean what, rows to ignore, etc.",
            key="eq_instructions",
        )

        if eq_file and st.button("Analyze spreadsheet", type="secondary", use_container_width=True):
            if not api_key:
                st.error("Gemini API key is required for smart parsing. Add it in Streamlit Secrets.")
            else:
                with st.spinner("Analyzing spreadsheet with Gemini… (usually 5–20s)"):
                    try:
                        parsed, notes = smart_parse_equipment(
                            io.BytesIO(eq_file.getvalue()),
                            eq_file.name,
                            api_key,
                            eq_instructions,
                        )
                        st.session_state["ai_equipment"] = [e.model_dump() for e in parsed]
                        st.session_state["ai_equipment_notes"] = notes
                    except Exception as exc:
                        st.error(f"Smart parse failed: {exc}")

        if "ai_equipment" in st.session_state:
            equipment = [EquipmentItem.model_validate(e) for e in st.session_state["ai_equipment"]]
            st.success(
                f"Interpreted **{len(equipment)}** equipment types "
                f"({sum(e.qty for e in equipment)} total units)"
            )
            notes = st.session_state.get("ai_equipment_notes", "")
            if notes:
                st.markdown(f"**Mapping notes:** {notes}")
            st.caption("Review and edit the interpreted data below before generating the layout.")

    else:
        if eq_file:
            try:
                equipment = parse_equipment_file(eq_file, eq_file.name)
                st.success(
                    f"Loaded **{len(equipment)}** equipment types "
                    f"({sum(e.qty for e in equipment)} total units)"
                )
            except Exception as exc:
                st.error(f"CSV error: {exc}")

    if not eq_file and st.button("Load sample equipment"):
        st.session_state["use_sample_equipment"] = True

    if st.session_state.get("use_sample_equipment") and not eq_file and equipment is None:
        try:
            _sample_name = "sample-equipment.xlsx" if (TEMPLATES / "sample-equipment.xlsx").exists() else "sample-equipment.csv"
            equipment = parse_equipment_file(io.BytesIO(load_sample_equipment_bytes()), _sample_name)
            st.success(
                f"Sample data: **{len(equipment)}** types ({sum(e.qty for e in equipment)} units)"
            )
        except Exception as exc:
            st.error(str(exc))

    if equipment:
        edited_df = st.data_editor(
            equipment_to_dataframe(equipment),
            use_container_width=True,
            height=260,
            num_rows="dynamic",
            key="equipment_editor",
        )
        try:
            equipment = [
                EquipmentItem(
                    id=str(r["id"]).strip() or f"EQ-{i + 1:03d}",
                    name=str(r["name"]).strip(),
                    width_ft=float(r["width_ft"]),
                    depth_ft=float(r["depth_ft"]),
                    qty=max(1, int(r["qty"])),
                    clearance_front_ft=float(r["clearance_front_ft"]),
                    clearance_rear_ft=float(r["clearance_rear_ft"]),
                    clearance_left_ft=float(r["clearance_left_ft"]),
                    clearance_right_ft=float(r["clearance_right_ft"]),
                    wall_preferred=(str(r["wall_preferred"]).lower().strip()
                                    if str(r["wall_preferred"]).lower().strip() in ("yes", "no", "any") else "any"),
                    adjacency=[s.strip() for s in str(r["adjacency"]).replace("|", ";").split(";") if s.strip()],
                    category=str(r["category"]).strip() or "general",
                    notes=str(r["notes"]).strip() if r.get("notes") is not None else "",
                )
                for i, r in enumerate(edited_df.to_dict(orient="records"))
                if str(r.get("name", "")).strip()
            ]
        except (ValueError, TypeError, KeyError) as exc:
            st.warning(f"Some edited rows are invalid and were ignored: {exc}")

st.divider()

layout_instructions = st.text_area(
    "Additional layout instructions (optional)",
    height=100,
    placeholder=(
        "Example: Place all welding equipment along the north wall. "
        "Keep a 6 ft aisle down the center. "
        "Group cutting and grinding equipment together near the exhaust fan. "
        "Workbenches should face the windows."
    ),
    help=(
        "Any extra direction for Gemini when generating the test layout — "
        "priority groupings, aisle widths, specific wall preferences, "
        "equipment to exclude, safety zones, etc."
    ),
    key="layout_instructions",
)

if st.button("Generate Test Layout", type="primary", use_container_width=True):
    if floor_plan is None and "drawing_floor_plan" in st.session_state:
        floor_plan = st.session_state["drawing_floor_plan"]
    if floor_plan is None:
        st.error("Define or upload a floor plan first.")
        st.stop()
    if not equipment:
        st.error("Upload or load an equipment spreadsheet first.")
        st.stop()
    if not floor_plan.equipment_zones:
        st.error("Floor plan must include at least one equipment zone.")
        st.stop()

    with st.spinner("Generating layout with Gemini…"):
        layout = generate_layout(floor_plan, equipment, api_key or "", layout_instructions)

    st.session_state["layout_result"] = layout
    st.session_state["layout_floor_plan"] = floor_plan
    st.session_state["layout_equipment"] = _sanitize_equipment(equipment)

if "layout_result" in st.session_state:
    layout = st.session_state["layout_result"]
    fp = st.session_state["layout_floor_plan"]
    eq = st.session_state["layout_equipment"]

    st.subheader("3. Layout Result")

    if layout.fits:
        st.success(f"Layout fits — **{layout.zone_utilization_pct:.0f}%** zone utilization")
    else:
        st.error(
            f"Space insufficient — approximately **{layout.additional_sqft_needed:.0f} sq ft** "
            "of additional equipment zone area is needed."
        )

    if layout.summary:
        st.markdown(f"**Layout strategy:** {layout.summary}")

    if layout.issues:
        with st.expander("Issues & warnings", expanded=not layout.fits):
            show_issues(layout.issues)

    try:
        eq_safe = _sanitize_equipment(eq)
        # Use model_validate with dicts to avoid Pydantic v2 class-identity errors
        # that occur when the same module is loaded under two different import paths
        # (e.g. `models` vs `server.models` on Streamlit Cloud flat deployments).
        export_req = ExportRequest.model_validate({
            "floor_plan": fp.model_dump(),
            "equipment": [e.model_dump() for e in eq_safe],
            "layout": layout.model_dump(),
        })
    except Exception as exc:
        st.error(f"Could not build export request: {exc}")
        st.stop()
    bg_bytes = st.session_state.get("drawing_bg_bytes")
    bg_name = st.session_state.get("drawing_bg_name", "")

    room_bounds = st.session_state.get("room_bounds_pct")

    # Use overlay renderer when we have the original drawing; PDF falls back automatically
    if bg_bytes and not bg_name.lower().endswith(".pdf"):
        png_bytes = render_layout_on_drawing(export_req, bg_bytes, room_bounds)
        caption = "Equipment test-fit overlaid on uploaded floor plan"
    else:
        png_bytes = render_layout_png(export_req)
        caption = "Equipment test-fit floor plan"

    st.image(Image.open(io.BytesIO(png_bytes)), caption=caption, use_container_width=True)

    # Also offer the diagrammatic version as an alternative
    if bg_bytes and not bg_name.lower().endswith(".pdf"):
        with st.expander("Also show diagrammatic layout"):
            diag_bytes = render_layout_png(export_req)
            st.image(Image.open(io.BytesIO(diag_bytes)), use_container_width=True)

    st.download_button(
        "Download floor plan (PNG)",
        data=png_bytes,
        file_name="cte-layout.png",
        mime="image/png",
    )

    with st.expander("Placement details"):
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "instance": p.instance_id,
                        "equipment": p.equipment_id,
                        "zone": p.zone_id,
                        "x_ft": p.x_ft,
                        "y_ft": p.y_ft,
                        "rotation": p.rotation,
                        "wall": p.wall_side,
                    }
                    for p in layout.placements
                ]
            ),
            use_container_width=True,
        )
