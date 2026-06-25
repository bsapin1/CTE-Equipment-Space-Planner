"""Render layout to PNG using Pillow."""

from __future__ import annotations

import io
from typing import TYPE_CHECKING

from PIL import Image, ImageDraw, ImageFont

from .models import EquipmentItem, ExportRequest, FloorPlan, Placement
from .validation import _clearance_rect, _equipment_rect, _rotated_dims

if TYPE_CHECKING:
    from .models import EquipmentZone

SCALE = 12  # pixels per foot
MARGIN = 60
LEGEND_WIDTH = 280
COLORS = [
    "#4A90D9",
    "#50C878",
    "#E67E22",
    "#9B59B6",
    "#E74C3C",
    "#1ABC9C",
    "#F39C12",
    "#34495E",
    "#16A085",
    "#C0392B",
]


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in (
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "arial.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def render_layout_png(req: ExportRequest) -> bytes:
    fp = req.floor_plan
    eq_by_id = {e.id: e for e in req.equipment}
    zone_by_id = {z.id: z for z in fp.equipment_zones}

    room_w = int(fp.width_ft * SCALE)
    room_h = int(fp.depth_ft * SCALE)
    canvas_w = MARGIN * 2 + room_w + LEGEND_WIDTH
    canvas_h = MARGIN * 2 + room_h + 80

    img = Image.new("RGB", (canvas_w, canvas_h), "#F8F9FA")
    draw = ImageDraw.Draw(img)
    font = _load_font(12)
    font_sm = _load_font(10)
    font_lg = _load_font(16)

    ox, oy = MARGIN, MARGIN + 40

    draw.text((MARGIN, 12), fp.name, fill="#1a1a2e", font=font_lg)
    draw.text(
        (MARGIN, 32),
        f"Room: {fp.width_ft}' × {fp.depth_ft}'  |  Test-fit layout",
        fill="#666",
        font=font_sm,
    )

    # Room outline
    draw.rectangle([ox, oy, ox + room_w, oy + room_h], outline="#333", width=2, fill="#FFFFFF")

    # Equipment zones
    for zone in fp.equipment_zones:
        zx = ox + int(zone.x_ft * SCALE)
        zy = oy + room_h - int((zone.y_ft + zone.depth_ft) * SCALE)
        zw = int(zone.width_ft * SCALE)
        zh = int(zone.depth_ft * SCALE)
        draw.rectangle([zx, zy, zx + zw, zy + zh], outline="#888", width=1, fill="#EEF2FF")
        label = zone.label or zone.id
        draw.text((zx + 4, zy + 4), label, fill="#555", font=font_sm)

    # Doors & windows on room perimeter
    for door in fp.doors:
        _draw_opening(draw, ox, oy, room_w, room_h, door.wall, door.offset_ft, door.width_ft, "#8B4513", "D")
    for win in fp.windows:
        _draw_opening(draw, ox, oy, room_w, room_h, win.wall, win.offset_ft, win.width_ft, "#87CEEB", "W")

    # Color map for legend
    color_map: dict[str, str] = {}
    categories = sorted({eq_by_id[p.equipment_id].category for p in req.layout.placements if p.equipment_id in eq_by_id})
    for i, cat in enumerate(categories):
        color_map[cat] = COLORS[i % len(COLORS)]

    # Placements
    for p in req.layout.placements:
        item = eq_by_id.get(p.equipment_id)
        zone = zone_by_id.get(p.zone_id)
        if not item or not zone:
            continue

        eq_rect = _equipment_rect(p, item, zone)
        px = ox + int(eq_rect.x * SCALE)
        py = oy + room_h - int((eq_rect.y + eq_rect.h) * SCALE)
        pw = int(eq_rect.w * SCALE)
        ph = int(eq_rect.h * SCALE)

        color = color_map.get(item.category, COLORS[0])
        draw.rectangle([px, py, px + pw, py + ph], fill=color, outline="#222", width=1)

        label = p.instance_id
        draw.text((px + 2, py + 2), label, fill="#FFF", font=font_sm)

        # Clearance dashed outline
        clr = _clearance_rect(p, item, zone)
        cx = ox + int(clr.x * SCALE)
        cy = oy + room_h - int((clr.y + clr.h) * SCALE)
        cw = int(clr.w * SCALE)
        ch = int(clr.h * SCALE)
        draw.rectangle([cx, cy, cx + cw, cy + ch], outline="#CCC", width=1)

    # Legend
    lx = ox + room_w + 20
    ly = oy
    draw.text((lx, ly), "Legend", fill="#1a1a2e", font=font)
    ly += 22

    seen: set[str] = set()
    for p in req.layout.placements:
        item = eq_by_id.get(p.equipment_id)
        if not item or p.instance_id in seen:
            continue
        seen.add(p.instance_id)
        color = color_map.get(item.category, COLORS[0])
        w, d = _rotated_dims(item, p.rotation)
        draw.rectangle([lx, ly, lx + 14, ly + 14], fill=color, outline="#222")
        draw.text(
            (lx + 20, ly),
            f"{p.instance_id}: {item.name} ({w:.0f}'×{d:.0f}')",
            fill="#333",
            font=font_sm,
        )
        ly += 18

    # Status banner
    status_y = oy + room_h + 16
    if req.layout.fits:
        status = f"✓ Layout fits  |  Zone utilization: {req.layout.zone_utilization_pct:.0f}%"
        color = "#2E7D32"
    else:
        status = f"✗ Space insufficient  |  ~{req.layout.additional_sqft_needed:.0f} additional sq ft needed"
        color = "#C62828"
    draw.text((MARGIN, status_y), status, fill=color, font=font)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _draw_opening(
    draw: ImageDraw.ImageDraw,
    ox: int,
    oy: int,
    room_w: int,
    room_h: int,
    wall: str,
    offset_ft: float,
    width_ft: float,
    color: str,
    label: str,
) -> None:
    off = int(offset_ft * SCALE)
    wid = int(width_ft * SCALE)
    font = _load_font(9)

    if wall == "south":
        x1, y1, x2, y2 = ox + off, oy + room_h - 4, ox + off + wid, oy + room_h
    elif wall == "north":
        x1, y1, x2, y2 = ox + off, oy, ox + off + wid, oy + 4
    elif wall == "west":
        x1, y1, x2, y2 = ox, oy + room_h - off - wid, ox + 4, oy + room_h - off
    else:  # east
        x1, y1, x2, y2 = ox + room_w - 4, oy + room_h - off - wid, ox + room_w, oy + room_h - off

    draw.rectangle([x1, y1, x2, y2], fill=color)
    draw.text((x1, y1 - 12), label, fill=color, font=font)
