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
    from server.renderer import render_layout_png
else:
    sys.path.insert(0, str(ROOT))
    from config import resolve_gemini_api_key
    from csv_parser import equipment_to_dataframe, parse_equipment_file
    from equipment_ai import smart_parse_equipment
    from floorplan_vision import analyze_floor_plan_drawing
    from layout_engine import generate_layout
    from models import EquipmentItem, EquipmentZone, ExportRequest, FloorPlan, Opening
    from renderer import render_layout_png

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


def load_sample_floor_plan() -> dict:
    return json.loads((TEMPLATES / "sample-floor-plan.json").read_text())


def load_sample_equipment_bytes() -> bytes:
    return (TEMPLATES / "sample-equipment.csv").read_bytes()


def load_sample_equipment_xlsx_bytes() -> bytes:
    buf = io.BytesIO()
    pd.read_csv(io.BytesIO(load_sample_equipment_bytes())).to_excel(buf, index=False, engine="openpyxl")
    return buf.getvalue()


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
    st.download_button(
        "Download sample floor plan (JSON)",
        data=(TEMPLATES / "sample-floor-plan.json").read_bytes(),
        file_name="sample-floor-plan.json",
        mime="application/json",
    )
    st.download_button(
        "Download sample equipment (CSV)",
        data=load_sample_equipment_bytes(),
        file_name="sample-equipment.csv",
        mime="text/csv",
    )
    st.download_button(
        "Download sample equipment (Excel)",
        data=load_sample_equipment_xlsx_bytes(),
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
                            fp, notes = analyze_floor_plan_drawing(
                                st.session_state["drawing_bytes"],
                                st.session_state["drawing_name"],
                                api_key,
                                reading_instructions,
                            )
                            st.session_state["drawing_floor_plan"] = fp
                            st.session_state["drawing_analysis_notes"] = notes
                            st.session_state["drawing_filename"] = drawing_file.name
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
                with st.spinner("Analyzing spreadsheet with Gemini…"):
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
            equipment = parse_equipment_file(io.BytesIO(load_sample_equipment_bytes()), "sample-equipment.csv")
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
        layout = generate_layout(floor_plan, equipment, api_key or "")

    st.session_state["layout_result"] = layout
    st.session_state["layout_floor_plan"] = floor_plan
    st.session_state["layout_equipment"] = equipment

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

    png_bytes = render_layout_png(ExportRequest(floor_plan=fp, equipment=eq, layout=layout))
    st.image(Image.open(io.BytesIO(png_bytes)), caption="Equipment test-fit floor plan", use_container_width=True)

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
