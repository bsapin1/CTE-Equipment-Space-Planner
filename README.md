# CTE Equipment Space Planner

A **Streamlit** app for test-fitting CTE (Career & Technical Education) equipment in a classroom floor plan. Upload a floor plan drawing and an equipment spreadsheet, and the tool generates a test-fit layout that respects clearances, adjacencies, circulation, door zones, and wall constraints.

## Features

- **Floor plan input** — Upload a drawing (JPG, PNG, PDF), use the visual editor, or upload JSON. Gemini Vision reads the drawing and extracts room dimensions, equipment zones, doors, and windows.
- **Room boundary alignment** — Sliders and direct width/depth number inputs let you precisely align the overlay with your drawing. Equipment zones scale proportionally when dimensions change.
- **Equipment spreadsheet** — CSV or Excel (`.xlsx`). **Smart parse** lets Gemini read any column layout and units; **strict columns** mode requires exact template headers.
- **AI-powered layout** — Gemini produces an intelligent test-fit respecting CTE safety rules.
- **Overlap-repair pass** — After Gemini generates positions, a local algorithm guarantees zero clearance overlaps by repositioning any conflicting item to the nearest valid spot.
- **Duplicate adjacency** — Multiple units of the same equipment type are always placed directly next to each other.
- **Wall snapping** — Equipment marked `wall_preferred = yes` is automatically snapped so the zero-clearance side sits flush against the zone boundary.
- **Door constraints** — Equipment is never placed inside a swing door arc or an overhead door travel path.
- **Validation** — Checks clearance overlaps, zone boundaries, swing/overhead door zones, adjacency, and space fit.
- **Space analysis** — Flags when equipment won't fit and estimates additional square footage needed.
- **Visual output** — Floor plan PNG overlaid on the uploaded drawing (or a blank diagram), with solid equipment rectangles, dashed clearance envelopes, sequential numbers, and a legend. All linework is black and white.
- **Download** — Export the final layout as a PNG.

---

## Deploy on Streamlit Cloud (no local install required)

Run the app in your browser without Python or developer tools.

### Step 1 — Put the code on GitHub

Your repo: [github.com/bsapin1/CTE-Equipment-Space-Planner](https://github.com/bsapin1/CTE-Equipment-Space-Planner)

Upload the latest project files to GitHub. Keep the folder structure — do **not** upload everything flat into the repo root:

```
app.py
requirements.txt
server/          ← all Python modules go here
templates/       ← sample files go here
.streamlit/
```

> If files were previously uploaded flat, the app handles both layouts automatically — but the `server/` folder is recommended for clarity.

### Step 2 — Create the Streamlit app

1. Go to **[share.streamlit.io](https://share.streamlit.io)** and sign in with GitHub
2. Click **Create app**
3. Choose:
   - **Repository:** `bsapin1/CTE-Equipment-Space-Planner`
   - **Branch:** `main`
   - **Main file path:** `app.py`
4. Click **Deploy**

### Step 3 — Add your Gemini API key

1. In the Streamlit Cloud dashboard: app → **Settings (⚙️)** → **Secrets**
2. Paste:

```toml
GEMINI_API_KEY = "AIzaSy...your-key-here"
```

3. Click **Save** — the app redeploys automatically.

### Step 4 — Open your app

Your public URL will be something like:
`https://cte-equipment-space-planner-xxxxx.streamlit.app`

The sidebar should show **"Using API key from Streamlit secrets."**

### Notes

- Do **not** commit `.env` or real API keys to GitHub — use Streamlit Cloud Secrets only.
- Free Streamlit Cloud apps sleep when idle; first load after sleep takes ~30 s.

---

## Quick Start (local)

### Prerequisites

- Python 3.10+
- A [Gemini API key](https://aistudio.google.com/apikey) (optional — a fallback grid layout is used without it)

### Install & run

```bash
cd CTE-Equipment-Space-Planner
python3 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

Or use the launch helper (defaults to port 8502):

```bash
python run.py
```

Open **http://localhost:8502** in a browser. Port 8502 avoids a conflict with Cursor IDE on 8501.

### Gemini API key

Configure **one** of these (checked in order; sidebar entry overrides all):

| Method | Where |
|--------|-------|
| Streamlit Cloud | App **Settings → Secrets** → `GEMINI_API_KEY = "AIza..."` |
| Local secrets | `.streamlit/secrets.toml` → `gemini_api_key = "AIza..."` |
| Environment file | `.env` → `GEMINI_API_KEY=AIza...` |
| Sidebar | Enter in the app sidebar (session only) |

Do **not** commit `.streamlit/secrets.toml` or `.env` — both are gitignored.

Get a key at [Google AI Studio](https://aistudio.google.com/apikey).

### Troubleshooting: browser keeps loading

1. **Start the server first** — Streamlit must be running before you open the URL.
2. **Use port 8502** — Cursor often occupies 8501. This project defaults to 8502.
3. **Confirm it is running** — `curl -I http://127.0.0.1:8502` should return `HTTP/1.1 200 OK`.

---

## Using the app

### 1. Floor Plan

Choose one of three input modes:

**Upload drawing** *(recommended)*
1. Upload a JPG or PNG floor plan.
2. Optionally add reading instructions (e.g. "North is up. Room is 100' × 80'. The open workshop is the equipment zone.").
3. Click **Analyze drawing** — Gemini Vision extracts room dimensions, zones, doors (swing vs overhead), and windows.
4. In the **"Adjust room bounds and dimensions"** expander:
   - Set the exact **room width** and **room depth** in feet (the values Gemini found can be overridden here).
   - Use the **Left / Right / Top / Bottom sliders** to align the blue boundary box with the room walls in the preview image. This ensures equipment is placed inside the correct region of the drawing.
5. Review or edit the extracted floor plan JSON if needed.

**Visual editor**
- Fill in room name, dimensions, door, windows, and equipment zone manually.

**Upload JSON**
- Paste or upload a floor plan JSON. See `templates/sample-floor-plan.json` for the schema.

### 2. Equipment List

**Smart parse (Gemini)** *(default)*
1. Upload any CSV or Excel spreadsheet — any column names, any unit system.
2. Optionally add instructions (e.g. "Dimensions are in inches. Quantity is in the 'Count' column.").
3. Click **Analyze spreadsheet**. Gemini maps columns, converts units to feet, infers clearances, and fills missing values with CTE safety defaults.
4. Review and edit the interpreted data in the table before proceeding.

**Strict columns**
- Upload a CSV or Excel file with exact headers (see table below). No AI step.

#### Equipment columns

| Column | Required | Description |
|--------|----------|-------------|
| `id` | Yes | Unique equipment code |
| `name` | Yes | Display name |
| `width_ft` | Yes | Footprint width in feet |
| `depth_ft` | Yes | Footprint depth in feet |
| `qty` | No | Quantity (default 1) |
| `clearance_front_ft` | No | Front clearance in feet (default 3.0) |
| `clearance_rear_ft` | No | Rear clearance in feet (default 1.0) |
| `clearance_left_ft` | No | Left clearance in feet (default 1.5) |
| `clearance_right_ft` | No | Right clearance in feet (default 1.5) |
| `wall_preferred` | No | `yes`, `no`, or `any` |
| `adjacency` | No | Semicolon-separated IDs of items to place nearby |
| `category` | No | Grouping for legend (e.g. "welding", "storage") |
| `notes` | No | Free text |

> **Wall placement:** If `wall_preferred = yes`, the side of the equipment with `clearance_ft = 0` is placed flush against the zone wall. The layout engine snaps this automatically.
>
> **Duplicate adjacency:** All units of the same equipment type (`qty > 1`) are always placed directly next to each other in the layout.

### 3. Layout instructions (optional)

Before clicking **Generate Test Layout**, add any extra directives — priority groupings, aisle widths, specific wall preferences, safety zones, equipment to exclude, etc.

### 4. Generate and download

Click **Generate Test Layout**. The result shows:
- Equipment overlaid on the uploaded drawing (or a blank diagram)
- Solid rectangle = equipment footprint
- Dashed lines = clearance envelope
- Number in each rectangle keyed to the legend
- Issues and warnings listed below the image
- **Download floor plan (PNG)** button

---

## How layout works

1. Floor plan and equipment data are sent to **Gemini 2.5 Flash** (falls back through `gemini-2.0-flash` and `gemini-1.5-flash`) with CTE-specific placement rules.
2. Gemini returns JSON placements with positions, rotations, and wall assignments.
3. An **overlap-repair pass** runs locally — items are sorted by clearance footprint (largest first, wall-preferred first), and any conflicting placement is moved to the nearest valid grid position. Duplicates are clustered adjacent to each other.
4. The layout is **validated** for clearance overlaps, zone boundaries, swing/overhead door zones, and total fit.
5. The result renders as a PNG with equipment symbols and legend.
6. If Gemini is unavailable, a **fallback row-packer** that respects clearances is used.

---

## Project structure

```
├── app.py                   # Streamlit application
├── run.py                   # Local launch helper (port 8502)
├── requirements.txt
├── server/
│   ├── config.py            # API key resolution
│   ├── models.py            # Pydantic data models
│   ├── layout_engine.py     # Gemini layout + overlap-repair pass
│   ├── validation.py        # Clearance & constraint validation
│   ├── renderer.py          # PNG rendering (blank + drawing overlay)
│   ├── floorplan_vision.py  # Gemini Vision — analyze uploaded drawings
│   ├── equipment_ai.py      # Gemini — smart-parse any spreadsheet format
│   └── csv_parser.py        # Strict-column CSV/Excel parser
├── templates/
│   ├── sample-floor-plan.png    # Sample floor plan image
│   ├── sample-floor-plan.json   # Sample floor plan JSON
│   └── sample-equipment.xlsx    # Sample equipment list
└── .streamlit/
    ├── config.toml
    └── secrets.toml.example
```

## License

See [LICENSE](LICENSE).
