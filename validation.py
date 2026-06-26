"""Validate equipment placements against floor plan constraints."""

from __future__ import annotations

from dataclasses import dataclass

try:
    from .models import EquipmentItem, EquipmentZone, FloorPlan, LayoutIssue, Opening, Placement
except ImportError:
    from models import EquipmentItem, EquipmentZone, FloorPlan, LayoutIssue, Opening, Placement


@dataclass
class Rect:
    x: float
    y: float
    w: float
    h: float

    @property
    def area(self) -> float:
        return self.w * self.h

    def intersects(self, other: Rect, gap: float = 0.0) -> bool:
        return not (
            self.x + self.w + gap <= other.x
            or other.x + other.w + gap <= self.x
            or self.y + self.h + gap <= other.y
            or other.y + other.h + gap <= self.y
        )


def _rotated_dims(item: EquipmentItem, rotation: int) -> tuple[float, float]:
    if rotation in (90, 270):
        return item.depth_ft, item.width_ft
    return item.width_ft, item.depth_ft


def _clearance_rect(
    placement: Placement, item: EquipmentItem, zone: EquipmentZone
) -> Rect:
    w, d = _rotated_dims(item, placement.rotation)
    return Rect(
        x=zone.x_ft + placement.x_ft - item.clearance_left_ft,
        y=zone.y_ft + placement.y_ft - item.clearance_rear_ft,
        w=w + item.clearance_left_ft + item.clearance_right_ft,
        h=d + item.clearance_rear_ft + item.clearance_front_ft,
    )


def _equipment_rect(
    placement: Placement, item: EquipmentItem, zone: EquipmentZone
) -> Rect:
    w, d = _rotated_dims(item, placement.rotation)
    return Rect(
        x=zone.x_ft + placement.x_ft,
        y=zone.y_ft + placement.y_ft,
        w=w,
        h=d,
    )


def _zone_rect(zone: EquipmentZone) -> Rect:
    return Rect(zone.x_ft, zone.y_ft, zone.width_ft, zone.depth_ft)


def _wall_distance(
    eq_rect: Rect, wall: str, floor_plan: FloorPlan, zone: EquipmentZone
) -> float:
    zone_rect = _zone_rect(zone)
    if wall == "north":
        return abs(eq_rect.y + eq_rect.h - (zone_rect.y + zone_rect.h))
    if wall == "south":
        return abs(eq_rect.y - zone_rect.y)
    if wall == "west":
        return abs(eq_rect.x - zone_rect.x)
    if wall == "east":
        return abs(eq_rect.x + eq_rect.w - (zone_rect.x + zone_rect.w))
    return float("inf")


def _swing_door_zone(door: Opening, room_w: float, room_d: float) -> Rect:
    """Return the floor rectangle occupied by a swing door's arc (in room coordinates)."""
    # effective_swing_clearance only exists on the new Opening model; fall back to width_ft
    sc = getattr(door, "swing_clearance_ft", 0.0)
    arc = sc if sc > 0 else door.width_ft
    off = door.offset_ft
    wid = door.width_ft
    if door.wall == "south":
        return Rect(x=off, y=0.0, w=wid, h=arc)
    if door.wall == "north":
        return Rect(x=off, y=room_d - arc, w=wid, h=arc)
    if door.wall == "west":
        return Rect(x=0.0, y=room_d - off - wid, w=arc, h=wid)
    # east
    return Rect(x=room_w - arc, y=room_d - off - wid, w=arc, h=wid)


def _overhead_door_zone(door: Opening, room_w: float, room_d: float) -> Rect:
    """Return the floor rectangle an overhead door travels across when opening.

    Typical overhead doors travel a depth equal to the door width (the door panel
    stacks overhead over that footprint).  We use width_ft as the travel depth.
    """
    travel = door.width_ft  # conservative: door panel depth = door width
    off = door.offset_ft
    wid = door.width_ft
    if door.wall == "south":
        return Rect(x=off, y=0.0, w=wid, h=travel)
    if door.wall == "north":
        return Rect(x=off, y=room_d - travel, w=wid, h=travel)
    if door.wall == "west":
        return Rect(x=0.0, y=room_d - off - wid, w=travel, h=wid)
    # east
    return Rect(x=room_w - travel, y=room_d - off - wid, w=travel, h=wid)


def validate_layout(
    floor_plan: FloorPlan,
    equipment: list[EquipmentItem],
    placements: list[Placement],
) -> list[LayoutIssue]:
    issues: list[LayoutIssue] = []
    eq_by_id = {e.id: e for e in equipment}
    zone_by_id = {z.id: z for z in floor_plan.equipment_zones}

    rw = floor_plan.width_ft
    rd = floor_plan.depth_ft

    # Pre-compute door constraint zones
    # Use getattr for backward compat with floor plans that lack door_type/swing_clearance_ft
    swing_zones: list[Rect] = [
        _swing_door_zone(d, rw, rd)
        for d in floor_plan.doors
        if getattr(d, "door_type", "swing") == "swing"
    ]
    overhead_zones: list[Rect] = [
        _overhead_door_zone(d, rw, rd)
        for d in floor_plan.doors
        if getattr(d, "door_type", "swing") == "overhead"
    ]

    clearance_rects: list[tuple[str, Rect]] = []

    for p in placements:
        item = eq_by_id.get(p.equipment_id)
        zone = zone_by_id.get(p.zone_id)
        if not item:
            issues.append(LayoutIssue(
                severity="error",
                message=f"Unknown equipment id '{p.equipment_id}'",
                equipment_id=p.equipment_id,
            ))
            continue
        if not zone:
            issues.append(LayoutIssue(
                severity="error",
                message=f"Unknown zone id '{p.zone_id}'",
                equipment_id=p.equipment_id,
            ))
            continue

        eq_rect = _equipment_rect(p, item, zone)
        clr_rect = _clearance_rect(p, item, zone)
        zone_rect = _zone_rect(zone)

        # Equipment must be inside its zone
        if (
            eq_rect.x < zone_rect.x - 0.01
            or eq_rect.y < zone_rect.y - 0.01
            or eq_rect.x + eq_rect.w > zone_rect.x + zone_rect.w + 0.01
            or eq_rect.y + eq_rect.h > zone_rect.y + zone_rect.h + 0.01
        ):
            issues.append(LayoutIssue(
                severity="error",
                message=f"{p.instance_id} extends outside zone '{zone.label or zone.id}'",
                equipment_id=p.equipment_id,
            ))

        # Wall preference
        if item.wall_preferred == "yes" and p.wall_side == "none":
            issues.append(LayoutIssue(
                severity="warning",
                message=f"{item.name} prefers wall placement but is freestanding",
                equipment_id=p.equipment_id,
            ))
        if p.wall_side != "none":
            dist = _wall_distance(eq_rect, p.wall_side, floor_plan, zone)
            if dist > 0.5:
                issues.append(LayoutIssue(
                    severity="warning",
                    message=f"{item.name} marked on {p.wall_side} wall but is {dist:.1f} ft away",
                    equipment_id=p.equipment_id,
                ))

        # Swing door arcs — equipment footprint must not enter
        for sz in swing_zones:
            if eq_rect.intersects(sz):
                issues.append(LayoutIssue(
                    severity="error",
                    message=f"{p.instance_id} is placed inside a swing door arc",
                    equipment_id=p.equipment_id,
                ))
                break

        # Overhead door travel path — equipment AND clearance must not enter
        for oz in overhead_zones:
            if clr_rect.intersects(oz):
                issues.append(LayoutIssue(
                    severity="error",
                    message=f"{p.instance_id} clearance encroaches on an overhead door travel path",
                    equipment_id=p.equipment_id,
                ))
                break

        clearance_rects.append((p.instance_id, clr_rect))

    # Clearance-to-clearance overlaps
    for i, (id_a, rect_a) in enumerate(clearance_rects):
        for id_b, rect_b in clearance_rects[i + 1:]:
            if rect_a.intersects(rect_b):
                issues.append(LayoutIssue(
                    severity="error",
                    message=f"Clearance overlap between {id_a} and {id_b}",
                ))

    # Quantity check
    for item in equipment:
        actual = sum(1 for p in placements if p.equipment_id == item.id)
        if actual < item.qty:
            issues.append(LayoutIssue(
                severity="error",
                message=f"Only placed {actual}/{item.qty} of {item.name}",
                equipment_id=item.id,
            ))

    # Adjacency
    for p in placements:
        item = eq_by_id.get(p.equipment_id)
        if not item or not item.adjacency:
            continue
        my_rect = _equipment_rect(p, item, zone_by_id[p.zone_id])
        for adj_id in item.adjacency:
            neighbors = [o for o in placements if o.equipment_id == adj_id and o.zone_id == p.zone_id]
            if not neighbors:
                issues.append(LayoutIssue(
                    severity="warning",
                    message=f"{item.name} should be adjacent to {adj_id} but none placed nearby",
                    equipment_id=p.equipment_id,
                ))
                continue
            min_dist = min(
                _rect_gap(my_rect, _equipment_rect(n, eq_by_id[n.equipment_id], zone_by_id[n.zone_id]))
                for n in neighbors if n.equipment_id in eq_by_id
            )
            if min_dist > 8.0:
                issues.append(LayoutIssue(
                    severity="warning",
                    message=f"{item.name} is {min_dist:.1f} ft from preferred neighbor {adj_id}",
                    equipment_id=p.equipment_id,
                ))

    return issues


def _rect_gap(a: Rect, b: Rect) -> float:
    if a.intersects(b):
        return 0.0
    dx = max(0.0, max(a.x - (b.x + b.w), b.x - (a.x + a.w)))
    dy = max(0.0, max(a.y - (b.y + b.h), b.y - (a.y + a.h)))
    return (dx**2 + dy**2) ** 0.5


def compute_fit_metrics(
    floor_plan: FloorPlan,
    equipment: list[EquipmentItem],
    placements: list[Placement],
) -> tuple[bool, float, float]:
    """Return (fits, additional_sqft_needed, zone_utilization_pct)."""
    total_zone_area = sum(z.width_ft * z.depth_ft for z in floor_plan.equipment_zones)
    if total_zone_area <= 0:
        return False, 0.0, 0.0

    eq_by_id = {e.id: e for e in equipment}
    zone_by_id = {z.id: z for z in floor_plan.equipment_zones}

    used_area = 0.0
    for p in placements:
        item = eq_by_id.get(p.equipment_id)
        zone = zone_by_id.get(p.zone_id)
        if not item or not zone:
            continue
        clr = _clearance_rect(p, item, zone)
        used_area += clr.w * clr.h

    required_area = sum(
        (e.width_ft + e.clearance_left_ft + e.clearance_right_ft)
        * (e.depth_ft + e.clearance_front_ft + e.clearance_rear_ft)
        * e.qty
        for e in equipment
    )

    utilization = min(100.0, (used_area / total_zone_area) * 100)
    shortfall = max(0.0, required_area - total_zone_area)
    fits = shortfall <= 0.0
    return fits, round(shortfall, 1), round(utilization, 1)
