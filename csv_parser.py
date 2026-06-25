"""Parse equipment spreadsheets (CSV or Excel) into EquipmentItem models."""

from __future__ import annotations

from typing import BinaryIO

import pandas as pd

try:
    from .models import EquipmentItem
except ImportError:
    from models import EquipmentItem

REQUIRED = {"id", "name", "width_ft", "depth_ft"}
EXCEL_EXTENSIONS = (".xlsx", ".xlsm")


def _normalize_row(row: dict) -> EquipmentItem:
    keys = {k.lower().strip(): v for k, v in row.items()}
    missing = REQUIRED - set(keys)
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(sorted(missing))}")

    adj_raw = keys.get("adjacency", "")
    if pd.isna(adj_raw) or adj_raw == "":
        adjacency: list[str] = []
    else:
        adjacency = [s.strip() for s in str(adj_raw).replace("|", ";").split(";") if s.strip()]

    wall = str(keys.get("wall_preferred", "any")).lower().strip()
    if wall not in ("yes", "no", "any"):
        wall = "any"

    def _float(key: str, default: float) -> float:
        val = keys.get(key, default)
        if pd.isna(val) or val == "":
            return default
        return float(val)

    def _int(key: str, default: int) -> int:
        val = keys.get(key, default)
        if pd.isna(val) or val == "":
            return default
        return int(val)

    return EquipmentItem(
        id=str(keys["id"]).strip(),
        name=str(keys["name"]).strip(),
        width_ft=float(keys["width_ft"]),
        depth_ft=float(keys["depth_ft"]),
        qty=_int("qty", 1),
        clearance_front_ft=_float("clearance_front_ft", 3.0),
        clearance_rear_ft=_float("clearance_rear_ft", 1.0),
        clearance_left_ft=_float("clearance_left_ft", 1.5),
        clearance_right_ft=_float("clearance_right_ft", 1.5),
        wall_preferred=wall,  # type: ignore[arg-type]
        adjacency=adjacency,
        category=str(keys.get("category", "general") or "general").strip(),
        notes=str(keys.get("notes", "") or "").strip(),
    )


def _dataframe_to_equipment(df: pd.DataFrame) -> list[EquipmentItem]:
    df.columns = [str(c).lower().strip() for c in df.columns]
    if df.empty:
        raise ValueError("Equipment spreadsheet has no data rows")
    return [_normalize_row(row) for row in df.to_dict(orient="records")]


def parse_equipment_file(source: str | BinaryIO, filename: str | None = None) -> list[EquipmentItem]:
    """Parse equipment from CSV or Excel (.xlsx, .xlsm, .xls)."""
    name = (filename or "").lower()
    if name.endswith(EXCEL_EXTENSIONS):
        df = pd.read_excel(source)
    else:
        df = pd.read_csv(source)
    return _dataframe_to_equipment(df)


def parse_equipment_csv(source: str | BinaryIO) -> list[EquipmentItem]:
    return parse_equipment_file(source)


def equipment_to_dataframe(equipment: list[EquipmentItem]) -> pd.DataFrame:
    rows = []
    for e in equipment:
        rows.append(
            {
                "id": e.id,
                "name": e.name,
                "width_ft": e.width_ft,
                "depth_ft": e.depth_ft,
                "qty": e.qty,
                "clearance_front_ft": e.clearance_front_ft,
                "clearance_rear_ft": e.clearance_rear_ft,
                "clearance_left_ft": e.clearance_left_ft,
                "clearance_right_ft": e.clearance_right_ft,
                "wall_preferred": e.wall_preferred,
                "adjacency": "|".join(e.adjacency),
                "category": e.category,
                "notes": e.notes,
            }
        )
    return pd.DataFrame(rows)
