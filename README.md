# CTE Equipment Space Planner

A **Streamlit** app for test-fitting CTE (Career & Technical Education) equipment in a blank classroom floor plan. Define the space, upload an equipment spreadsheet, and generate a layout that respects clearances, adjacencies, circulation, and wall/window/door constraints.

## Features

- **Floor plan input** — Visual editor for room dimensions, doors, windows, and equipment zones, or upload JSON
- **Equipment spreadsheet** — CSV or Excel (`.xlsx`) with dimensions, clearances, wall preferences, and adjacency rules
- **AI-powered layout** — Uses Google Gemini to produce an intelligent test-fit placement
- **Validation** — Checks clearance overlaps, zone boundaries, adjacency, and fit
- **Space analysis** — Flags when equipment won't fit and estimates additional square footage needed
- **Visual output** — Floor plan PNG with equipment boxes, clearance zones, and a legend

## Deploy on Streamlit Cloud (no local install)

Run the app in your browser without Python or developer tools on your Mac.

### Step 1: Put the code on GitHub

Your repo: [github.com/bsapin1/CTE-Equipment-Space-Planner](https://github.com/bsapin1/CTE-Equipment-Space-Planner)

Upload the latest project files (especially `app.py`, `requirements.txt`, `server/`, `templates/`, `.streamlit/`) if they are not already on GitHub. You can:

- Use **GitHub Desktop** or the **github.com** website → **Upload files**, or
- Push from Terminal once git is set up

The repo root must contain `app.py` and `requirements.txt`.

### Step 2: Create the Streamlit app

1. Go to **[share.streamlit.io](https://share.streamlit.io)** and sign in with **GitHub**
2. Click **Create app**
3. Choose:
   - **Repository:** `bsapin1/CTE-Equipment-Space-Planner`
   - **Branch:** `main`
   - **Main file path:** `app.py`
4. Click **Deploy** (secrets can wait for the first deploy)

### Step 3: Add your Gemini API key

1. In the Streamlit Cloud dashboard, open your app → **Settings** (⚙️) → **Secrets**
2. Paste (replace with your real key):

```toml
GEMINI_API_KEY = "AIzaSy...your-key-here"
```

3. Click **Save** — the app will redeploy automatically

See `.streamlit/secrets.toml.example` for the template.

### Step 4: Open your app

Streamlit gives you a public URL like:

`https://cte-equipment-space-planner-xxxxx.streamlit.app`

Open that in any browser. The sidebar should show **“Using API key from Streamlit secrets.”**

### Notes

- **Do not** commit `.env` or real API keys to GitHub — use Streamlit Cloud Secrets only
- Free Streamlit Cloud apps may sleep when idle; first load after sleep can take ~30 seconds
- Sample floor plan and equipment are built into the app — click **Load sample equipment** and **Generate Test Layout**

---

## Quick Start (local)

### Prerequisites

- Python 3.10+
- A [Gemini API key](https://aistudio.google.com/apikey) (optional — fallback layout used without it)

### Install & Run

```bash
cd CTE-Equipment-Space-Planner
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

Or:

```bash
python run.py
```

Open the URL shown in the terminal — **http://localhost:8502** (port 8502 avoids a conflict with Cursor on 8501).

Enter your Gemini API key in the sidebar, or configure it in `.streamlit/secrets.toml` or `.env` (see sidebar instructions). Load the sample data or upload your own files, then click **Generate Test Layout**.

### Troubleshooting: browser keeps loading

1. **Start the server first** — Opening `localhost` in a browser does nothing unless Streamlit is running in a terminal. You should see `You can now view your Streamlit app in your browser`.
2. **Use port 8502** — Cursor often occupies port 8501. This project defaults to **8502**.
3. **Use an external terminal** — Run from Terminal.app or iTerm, not only the Cursor panel, if the page still hangs:
   ```bash
   cd ~/Projects/CTE-Equipment-Space-Planner
   source .venv/bin/activate
   streamlit run app.py
   ```
4. **Confirm it is running** — In another terminal: `curl -I http://127.0.0.1:8502` should return `HTTP/1.1 200 OK`.

### Gemini API Key

Configure **one** of these (checked in order; sidebar overrides when filled):

| Method | Location |
|--------|----------|
| Streamlit Cloud | App **Settings → Secrets** → `GEMINI_API_KEY = "AIza..."` |
| Local secrets file | `.streamlit/secrets.toml` → `gemini_api_key = "AIza..."` |
| Environment file | `.env` → `GEMINI_API_KEY=AIza...` (copy from `.env.example`) |
| Sidebar | Enter in the app (overrides files for that session) |

Do **not** commit `.streamlit/secrets.toml` or `.env` — both are gitignored.

Get a key at [Google AI Studio](https://aistudio.google.com/apikey).

## Inputs

### Floor Plan (JSON)

Coordinates are in feet; origin is the **southwest corner** of the room. `equipment_zones` define where equipment may be placed. Doors and windows sit on room walls (`north`, `south`, `east`, `west`).

See `templates/sample-floor-plan.json` for a complete example.

### Equipment List (CSV or Excel)

Same columns for both formats:

| Column | Required | Description |
|--------|----------|-------------|
| `id` | Yes | Unique equipment identifier |
| `name` | Yes | Display name |
| `width_ft` | Yes | Footprint width |
| `depth_ft` | Yes | Footprint depth |
| `qty` | No | Quantity (default 1) |
| `clearance_front_ft` | No | Front clearance (default 3) |
| `clearance_rear_ft` | No | Rear clearance (default 1) |
| `clearance_left_ft` | No | Left clearance (default 1.5) |
| `clearance_right_ft` | No | Right clearance (default 1.5) |
| `wall_preferred` | No | `yes`, `no`, or `any` |
| `adjacency` | No | Pipe- or semicolon-separated IDs of equipment to place nearby |
| `category` | No | Used for legend color grouping |
| `notes` | No | Free text |

See `templates/sample-equipment.csv` for a complete example.

## How Layout Works

1. Floor plan and equipment data are sent to **Gemini 2.5 Flash** with CTE-specific placement rules
2. Gemini returns JSON placements with positions, rotations, and wall assignments
3. The app **validates** clearances, zone boundaries, adjacencies, and fit
4. If Gemini is unavailable, a **fallback grid layout** is used
5. Results render as a PNG floor plan with legend; download from the results section

## Project Structure

```
├── app.py                  # Streamlit application
├── run.py                  # Launch helper
├── server/
│   ├── models.py           # Data models
│   ├── layout_engine.py    # Gemini + fallback layout
│   ├── validation.py       # Clearance & fit validation
│   ├── renderer.py         # PNG floor plan rendering
│   └── csv_parser.py       # Equipment CSV parsing
└── templates/
    ├── sample-floor-plan.json
    └── sample-equipment.csv
```

## License

See [LICENSE](LICENSE).
