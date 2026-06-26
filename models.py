"""Pydantic models for floor plan and equipment layout."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Opening(BaseModel):
    wall: Literal["north", "south", "east", "west"]
    offset_ft: float = Field(ge=0, description="Distance from west/north corner along the wall")
    width_ft: float = Field(gt=0)
    # "swing"    — hinged door with arc swinging into the room
    # "overhead" — garage/roll-up/coiling door (dashed line on plan = travel path below door)
    # "sliding"  — pocket or barn door (no arc, but track clearance needed)
    # "passage"  — opening with no door (no clearance needed beyond circulation)
    door_type: Literal["swing", "overhead", "sliding", "passage", "window"] = "swing"
    # How far the swing arc extends into the room (ft). 0 = auto-compute as width_ft.
    swing_clearance_ft: float = Field(default=0.0, ge=0)

    @property
    def effective_swing_clearance(self) -> float:
        """Swing arc depth into the room (0 → defaults to door width = 90° swing)."""
        return self.swing_clearance_ft if self.swing_clearance_ft > 0 else self.width_ft


class EquipmentZone(BaseModel):
    id: str
    label: str = ""
    x_ft: float = Field(ge=0)
    y_ft: float = Field(ge=0)
    width_ft: float = Field(gt=0)
    depth_ft: float = Field(gt=0)


class FloorPlan(BaseModel):
    name: str = "CTE Classroom"
    width_ft: float = Field(gt=0)
    depth_ft: float = Field(gt=0)
    doors: list[Opening] = Field(default_factory=list)
    windows: list[Opening] = Field(default_factory=list)
    equipment_zones: list[EquipmentZone] = Field(default_factory=list)


class EquipmentItem(BaseModel):
    id: str
    name: str
    width_ft: float = Field(gt=0)
    depth_ft: float = Field(gt=0)
    qty: int = Field(default=1, ge=1)
    clearance_front_ft: float = Field(default=3.0, ge=0)
    clearance_rear_ft: float = Field(default=1.0, ge=0)
    clearance_left_ft: float = Field(default=1.5, ge=0)
    clearance_right_ft: float = Field(default=1.5, ge=0)
    wall_preferred: Literal["any", "yes", "no"] = "any"
    adjacency: list[str] = Field(default_factory=list)
    category: str = "general"
    notes: str = ""


class Placement(BaseModel):
    instance_id: str
    equipment_id: str
    zone_id: str
    x_ft: float
    y_ft: float
    rotation: Literal[0, 90, 180, 270] = 0
    wall_side: Literal["none", "north", "south", "east", "west"] = "none"


class LayoutIssue(BaseModel):
    severity: Literal["error", "warning", "info"]
    message: str
    equipment_id: str | None = None


class LayoutResult(BaseModel):
    placements: list[Placement]
    issues: list[LayoutIssue]
    fits: bool
    additional_sqft_needed: float = 0.0
    zone_utilization_pct: float = 0.0
    summary: str = ""


class LayoutRequest(BaseModel):
    floor_plan: FloorPlan
    equipment: list[EquipmentItem]
    gemini_api_key: str


class ExportRequest(BaseModel):
    floor_plan: FloorPlan
    equipment: list[EquipmentItem]
    layout: LayoutResult
