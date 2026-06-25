"""Validate equipment placements against floor plan constraints."""

from __future__ import annotations

from dataclasses import dataclass

from .models import EquipmentItem, EquipmentZone, FloorPlan, LayoutIssue, Placement


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
    room_w, room_d = floor_plan.width_ft, floor_plan.depth_ft
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


def validate_layout(
    floor_plan: FloorPlan,
    equipment: list[EquipmentItem],
    placements: list[Placement],
) -> list[LayoutIssue]:
    issues: list[LayoutIssue] = []
    eq_by_id = {e.id: e for e in equipment}
    zone_by_id = {z.id: z for z in floor_plan.equipment_zones}

    clearance_rects: list[tuple[str, Rect]] = []

    for p in placements:
        item = eq_by_id.get(p.equipment_id)
        zone = zone_by_id.get(p.zone_id)
        if not item:
            issues.append(
                LayoutIssue(
                    severity="error",
                    message=f"Unknown equipment id '{p.equipment_id}'",
                    equipment_id=p.equipment_id,
                )
            )
            continue
        if not zone:
            issues.append(
                LayoutIssue(
                    severity="error",
                    message=f"Unknown zone id '{p.zone_id}'",
                    equipment_id=p.equipment_id,
                )
            )
            continue

        eq_rect = _equipment_rect(p, item, zone)
        clr_rect = _clearance_rect(p, item, zone)
        zone_rect = _zone_rect(zone)

        if (
            eq_rect.x < zone_rect.x - 0.01
            or eq_rect.y < zone_rect.y - 0.01
            or eq_rect.x + eq_rect.w > zone_rect.x + zone_rect.w + 0.01
            or eq_rect.y + eq_rect.h > zone_rect.y + zone_rect.h + 0.01
        ):
            issues.append(
                LayoutIssue(
                    severity="error",
                    message=f"{p.instance_id} extends outside zone '{zone.label or zone.id}'",
                    equipment_id=p.equipment_id,
                )
            )

        if item.wall_preferred == "yes" and p.wall_side == "none":
            issues.append(
                LayoutIssue(
                    severity="warning",
                    message=f"{item.name} prefers wall placement but is freestanding",
                    equipment_id=p.equipment_id,
                )
            )

        if p.wall_side != "none":
            dist = _wall_distance(eq_rect, p.wall_side, floor_plan, zone)
            if dist > 0.5:
                issues.append(
                    LayoutIssue(
                        severity="warning",
                        message=f"{item.name} marked on {p.wall_side} wall but is {dist:.1f} ft away",
                        equipment_id=p.equipment_id,
                    )
                )

        clearance_rects.append((p.instance_id, clr_rect))

    for i, (id_a, rect_a) in enumerate(clearance_rects):
        for id_b, rect_b in clearance_rects[i + 1 :]:
            if rect_a.intersects(rect_b):
                issues.append(
                    LayoutIssue(
                        severity="error",
                        message=f"Clearance overlap between {id_a} and {id_b}",
                    )
                )

    placed_ids = {p.equipment_id for p in placements}
    for item in equipment:
        expected = item.qty
        actual = sum(1 for p in placements if p.equipment_id == item.id)
        if actual < expected:
            issues.append(
                LayoutIssue(
                    severity="error",
                    message=f"Only placed {actual}/{expected} of {item.name}",
                    equipment_id=item.id,
                )
            )

    for p in placements:
        item = eq_by_id.get(p.equipment_id)
        if not item or not item.adjacency:
            continue
        my_rect = _equipment_rect(p, item, zone_by_id[p.zone_id])
        for adj_id in item.adjacency:
            neighbors = [
                other
                for other in placements
                if other.equipment_id == adj_id and other.zone_id == p.zone_id
            ]
            if not neighbors:
                issues.append(
                    LayoutIssue(
                        severity="warning",
                        message=f"{item.name} should be adjacent to {adj_id} but none placed nearby",
                        equipment_id=p.equipment_id,
                    )
                )
                continue
            min_dist = min(
                _rect_gap(my_rect, _equipment_rect(n, eq_by_id[n.equipment_id], zone_by_id[n.zone_id]))
                for n in neighbors
                if n.equipment_id in eq_by_id
            )
            if min_dist > 8.0:
                issues.append(
                    LayoutIssue(
                        severity="warning",
                        message=f"{item.name} is {min_dist:.1f} ft from preferred neighbor {adj_id}",
                        equipment_id=p.equipment_id,
                    )
                )

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

    required_area = 0.0
    for item in equipment:
        footprint = (
            item.width_ft + item.clearance_left_ft + item.clearance_right_ft
        ) * (item.depth_ft + item.clearance_front_ft + item.clearance_rear_ft)
        required_area += footprint * item.qty

    utilization = min(100.0, (used_area / total_zone_area) * 100)
    shortfall = max(0.0, required_area - total_zone_area)
    fits = shortfall <= 0.0

    return fits, round(shortfall, 1), round(utilization, 1)
