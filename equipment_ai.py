"""Use Gemini to interpret arbitrarily-formatted equipment spreadsheets."""

from __future__ import annotations

import io
import json
import re
from typing import Any, BinaryIO

import google.generativeai as genai
import pandas as pd

try:
    from .config import DEFAULT_GEMINI_MODEL
    from .models import EquipmentItem
except ImportError:
    from config import DEFAULT_GEMINI_MODEL
    from models import EquipmentItem

# Parsing is a structured extraction task — prefer fast, non-"thinking" models first.
# gemini-2.0-flash is much faster than 2.5-flash (which spends time reasoning) and is
# more than capable of column mapping. Slower models are kept only as fallbacks.
AI_MODELS = ("gemini-2.0-flash", "gemini-1.5-flash", "gemini-2.5-flash")
EXCEL_EXTENSIONS = (".xlsx", ".xlsm")
MAX_ROWS = 200
MAX_COLS = 30
MAX_CELL_CHARS = 80
REQUEST_TIMEOUT_S = 90


def read_raw_table(source: str | BinaryIO, filename: str | None = None) -> pd.DataFrame:
    """Read a spreadsheet with no assumptions about its columns."""
    name = (filename or "").lower()
    if name.endswith(EXCEL_EXTENSIONS):
        df = pd.read_excel(source, header=None, dtype=str)
    else:
        df = pd.read_csv(source, header=None, dtype=str, skip_blank_lines=False)
    df = df.fillna("")
    return _trim_table(df)


def _trim_table(df: pd.DataFrame) -> pd.DataFrame:
    """Drop fully-empty rows/columns to keep the prompt small and fast."""
    if df.empty:
        return df
    stripped = df.map(lambda c: str(c).strip())
    non_empty_rows = stripped.apply(lambda r: any(v != "" for v in r), axis=1)
    non_empty_cols = stripped.apply(lambda c: any(v != "" for v in c), axis=0)
    trimmed = df.loc[non_empty_rows, non_empty_cols]
    return trimmed.reset_index(drop=True)


def _table_to_text(df: pd.DataFrame) -> str:
    rows = df.values.tolist()[:MAX_ROWS]
    lines = []
    for i, row in enumerate(rows):
        cells = [str(c).strip()[:MAX_CELL_CHARS] for c in row[:MAX_COLS]]
        lines.append(f"Row {i}: " + " | ".join(cells))
    text = "\n".join(lines)
    total_rows = len(df)
    if total_rows > MAX_ROWS:
        text += f"\n... ({total_rows - MAX_ROWS} more rows omitted)"
    return text


def _parse_json_response(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned)
    if fence:
        cleaned = fence.group(1).strip()
    return json.loads(cleaned)


def _build_prompt(table_text: str, user_instructions: str) -> str:
    instructions_block = ""
    if user_instructions.strip():
        instructions_block = f"""
USER INSTRUCTIONS (follow carefully when interpreting the spreadsheet):
{user_instructions.strip()}
"""

    return f"""You are a data-mapping assistant for a CTE (Career & Technical Education) classroom equipment planner.

You are given the raw contents of an equipment spreadsheet that may use ANY column names, layout, units, or ordering. Your job is to interpret it and produce a clean, normalized equipment list the planning tool can use.

{instructions_block}
RAW SPREADSHEET (each line is a row; cells separated by " | "):
{table_text}

MAPPING RULES:
1. Find the header row (it may not be the first row). Ignore title rows, blank rows, totals, and notes-only rows.
2. Map each real equipment row to these target fields:
   - id: short unique code. If none exists, generate one from the name (e.g. "Wire Feed Welder" -> "WLD-001"). Ensure uniqueness.
   - name: human-readable equipment name (required).
   - width_ft: footprint width in FEET (required).
   - depth_ft: footprint depth in FEET (required).
   - qty: integer quantity (default 1).
   - clearance_front_ft, clearance_rear_ft, clearance_left_ft, clearance_right_ft: required clearances in FEET. Use sensible CTE safety defaults if not given (front 3.0, rear 1.0, left 1.5, right 1.5).
   - wall_preferred: "yes", "no", or "any". Infer from columns like "against wall", "wall mount", "freestanding". Default "any".
   - adjacency: list of equipment ids/names this item should be near. Default [].
   - category: grouping for legend color (e.g. "welding", "cutting", "storage"). Infer from the name/type if not given. Default "general".
   - notes: any leftover relevant info. Default "".
3. UNIT CONVERSION: Convert all dimensions to FEET. If values look like inches (e.g. 30, 48) or have units like "in", "cm", "mm", "m", convert. If a column shows dimensions like "30x48" or "2'-6\"", parse them. Explain assumptions in mapping_notes.
4. If width/depth cannot be determined for a row, estimate a reasonable footprint for that equipment type and note it in mapping_notes.
5. Preserve every distinct piece of equipment. Combine duplicate rows into qty when clearly identical.

Respond with ONLY valid JSON (no markdown):
{{
  "equipment": [
    {{
      "id": "WLD-001",
      "name": "Wire Feed Welder",
      "width_ft": 2.5,
      "depth_ft": 3.5,
      "qty": 2,
      "clearance_front_ft": 3.0,
      "clearance_rear_ft": 1.0,
      "clearance_left_ft": 1.5,
      "clearance_right_ft": 1.5,
      "wall_preferred": "yes",
      "adjacency": [],
      "category": "welding",
      "notes": ""
    }}
  ],
  "mapping_notes": "How you identified columns, unit conversions, and any assumptions"
}}
"""


def _coerce_equipment(raw_items: list[dict]) -> list[EquipmentItem]:
    items: list[EquipmentItem] = []
    seen_ids: set[str] = set()

    for idx, raw in enumerate(raw_items):
        item_id = str(raw.get("id") or f"EQ-{idx + 1:03d}").strip()
        base_id = item_id
        n = 2
        while item_id in seen_ids:
            item_id = f"{base_id}-{n}"
            n += 1
        seen_ids.add(item_id)

        adjacency = raw.get("adjacency", [])
        if isinstance(adjacency, str):
            adjacency = [s.strip() for s in adjacency.replace("|", ";").split(";") if s.strip()]

        wall = str(raw.get("wall_preferred", "any")).lower().strip()
        if wall not in ("yes", "no", "any"):
            wall = "any"

        def _f(key: str, default: float) -> float:
            try:
                val = raw.get(key)
                return float(val) if val not in (None, "") else default
            except (TypeError, ValueError):
                return default

        items.append(
            EquipmentItem(
                id=item_id,
                name=str(raw.get("name") or item_id).strip(),
                width_ft=_f("width_ft", 2.0),
                depth_ft=_f("depth_ft", 2.0),
                qty=max(1, int(_f("qty", 1))),
                clearance_front_ft=_f("clearance_front_ft", 3.0),
                clearance_rear_ft=_f("clearance_rear_ft", 1.0),
                clearance_left_ft=_f("clearance_left_ft", 1.5),
                clearance_right_ft=_f("clearance_right_ft", 1.5),
                wall_preferred=wall,  # type: ignore[arg-type]
                adjacency=[str(a).strip() for a in adjacency if str(a).strip()],
                category=str(raw.get("category") or "general").strip(),
                notes=str(raw.get("notes") or "").strip(),
            )
        )

    if not items:
        raise ValueError("No equipment rows could be identified in the spreadsheet.")
    return items


def smart_parse_equipment(
    source: str | BinaryIO,
    filename: str,
    api_key: str,
    user_instructions: str = "",
) -> tuple[list[EquipmentItem], str]:
    """Return (equipment, mapping_notes) by letting Gemini interpret any format."""
    if not api_key.strip():
        raise ValueError("Gemini API key is required for smart spreadsheet parsing.")

    df = read_raw_table(source, filename)
    if df.empty:
        raise ValueError("The uploaded spreadsheet appears to be empty.")

    table_text = _table_to_text(df)
    prompt = _build_prompt(table_text, user_instructions)
    genai.configure(api_key=api_key.strip())

    generation_config = {
        "temperature": 0.1,
        "response_mime_type": "application/json",
        "max_output_tokens": 8192,
    }

    last_error: Exception | None = None
    for model_name in AI_MODELS:
        try:
            model = genai.GenerativeModel(model_name, generation_config=generation_config)
            response = model.generate_content(
                prompt,
                request_options={"timeout": REQUEST_TIMEOUT_S},
            )
            raw = _parse_json_response(response.text)
            equipment = _coerce_equipment(raw.get("equipment", []))
            notes = str(raw.get("mapping_notes", ""))
            return equipment, notes
        except Exception as exc:
            last_error = exc
            # Only fall back to another model when this one is unavailable
            # (e.g. 404 / not found / unsupported). For timeouts, quota, or
            # transient errors, retrying other models just compounds the wait.
            message = str(exc).lower()
            if any(token in message for token in ("not found", "404", "not supported", "unsupported", "permission")):
                continue
            raise RuntimeError(f"Could not interpret spreadsheet: {exc}") from exc

    raise RuntimeError(f"Could not interpret spreadsheet: {last_error}")
