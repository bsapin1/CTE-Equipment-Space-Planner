"""Render layout to PNG using Pillow."""

from __future__ import annotations

import io
from typing import TYPE_CHECKING

from PIL import Image, ImageDraw, ImageFont

try:
    from .models import EquipmentItem, ExportRequest, FloorPlan, Placement
    from .validation import _clearance_rect, _equipment_rect, _rotated_dims
except ImportError:
    from models import EquipmentItem, ExportRequest, FloorPlan, Placement
    from validation import _clearance_rect, _equipment_rect, _rotated_dims

if TYPE_CHECKING:
    from .models import EquipmentZone

SCALE = 12  # pixels per foot (blank renderer)
MARGIN = 60
LEGEND_WIDTH = 300
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
# Opacity for equipment fill drawn on top of the real drawing (0–255)
OVERLAY_ALPHA = 160


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


def _hex_to_rgba(hex_color: str, alpha: int) -> tuple[int, int, int, int]:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return r, g, b, alpha


def _build_color_map(
    placements: list[Placement],
    eq_by_id: dict[str, EquipmentItem],
) -> dict[str, str]:
    categories = sorted(
        {eq_by_id[p.equipment_id].category for p in placements if p.equipment_id in eq_by_id}
    )
    return {cat: COLORS[i % len(COLORS)] for i, cat in enumerate(categories)}


def _draw_legend(
    draw: ImageDraw.ImageDraw,
    placements: list[Placement],
    eq_by_id: dict[str, EquipmentItem],
    color_map: dict[str, str],
    lx: int,
    ly: int,
    fits: bool,
    utilization: float,
    extra_sqft: float,
) -> None:
    font = _load_font(12)
    font_sm = _load_font(10)

    draw.text((lx, ly), "Legend", fill="#1a1a2e", font=font)
    ly += 22

    seen: set[str] = set()
    for p in placements:
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
            fill="#1a1a2e",
            font=font_sm,
        )
        ly += 18

    ly += 10
    if fits:
        status = f"✓ Fits  |  Zone util: {utilization:.0f}%"
        status_color = "#2E7D32"
    else:
        status = f"✗ Need ~{extra_sqft:.0f} more sq ft"
        status_color = "#C62828"
    draw.text((lx, ly), status, fill=status_color, font=font_sm)


def render_layout_on_drawing(
    req: ExportRequest,
    drawing_bytes: bytes,
) -> bytes:
    """Overlay equipment boxes on the original uploaded floor plan image.

    Coordinate mapping assumes the drawing fills the full room extent:
      pixel_x = x_ft * (img_w / room_w_ft)
      pixel_y = img_h - (y_ft + h_ft) * (img_h / room_d_ft)   [y flipped: SW origin]

    For PDFs (not rasterisable without Ghostscript), falls back to
    render_layout_png() automatically.
    """
    fp = req.floor_plan

    # Attempt to open the drawing as an image
    try:
        bg = Image.open(io.BytesIO(drawing_bytes)).convert("RGBA")
    except Exception:
        # PDF or unreadable format — fall back to blank renderer
        return render_layout_png(req)

    img_w, img_h = bg.size

    # Scale factors: feet → pixels
    scale_x = img_w / fp.width_ft
    scale_y = img_h / fp.depth_ft

    def ft_to_px(x_ft: float, y_ft: float, w_ft: float, h_ft: float) -> tuple[int, int, int, int]:
        px = int(x_ft * scale_x)
        # Flip y: SW origin → image top-left origin
        py = int(img_h - (y_ft + h_ft) * scale_y)
        pw = max(2, int(w_ft * scale_x))
        ph = max(2, int(h_ft * scale_y))
        return px, py, pw, ph

    # Composite canvas: image on left, legend panel on right
    canvas_w = img_w + LEGEND_WIDTH
    canvas_h = img_h
    canvas = Image.new("RGBA", (canvas_w, canvas_h), (248, 249, 250, 255))
    canvas.paste(bg, (0, 0))

    # Transparent overlay for equipment boxes
    overlay = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    draw_ov = ImageDraw.Draw(overlay)

    eq_by_id = {e.id: e for e in req.equipment}
    zone_by_id = {z.id: z for z in fp.equipment_zones}
    color_map = _build_color_map(req.layout.placements, eq_by_id)

    font_sm = _load_font(10)

    for p in req.layout.placements:
        item = eq_by_id.get(p.equipment_id)
        zone = zone_by_id.get(p.zone_id)
        if not item or not zone:
            continue

        # Clearance outline
        clr = _clearance_rect(p, item, zone)
        cx, cy, cw, ch = ft_to_px(clr.x, clr.y, clr.w, clr.h)
        draw_ov.rectangle([cx, cy, cx + cw, cy + ch], outline=(180, 180, 180, 180), width=1)

        # Equipment box (semi-transparent fill)
        eq_rect = _equipment_rect(p, item, zone)
        ex, ey, ew, eh = ft_to_px(eq_rect.x, eq_rect.y, eq_rect.w, eq_rect.h)
        hex_color = color_map.get(item.category, COLORS[0])
        fill_rgba = _hex_to_rgba(hex_color, OVERLAY_ALPHA)
        outline_rgba = _hex_to_rgba(hex_color, 255)
        draw_ov.rectangle([ex, ey, ex + ew, ey + eh], fill=fill_rgba, outline=outline_rgba, width=2)

        # Label (white text, dark shadow for readability on any background)
        label = p.instance_id
        draw_ov.text((ex + 3, ey + 1), label, fill=(0, 0, 0, 200), font=font_sm)
        draw_ov.text((ex + 2, ey), label, fill=(255, 255, 255, 255), font=font_sm)

    # Merge overlay onto canvas
    canvas = Image.alpha_composite(canvas, overlay)

    # Legend panel (solid background on the right strip)
    draw_main = ImageDraw.Draw(canvas)
    lx = img_w + 12
    # Light background behind legend
    draw_main.rectangle([img_w, 0, canvas_w, canvas_h], fill=(248, 249, 250, 255))
    # Title bar
    draw_main.text((lx, 10), fp.name, fill="#1a1a2e", font=_load_font(13))
    draw_main.text(
        (lx, 28),
        f"{fp.width_ft:.0f}' × {fp.depth_ft:.0f}'  |  Test-fit overlay",
        fill="#666666",
        font=_load_font(10),
    )
    _draw_legend(
        draw_main,
        req.layout.placements,
        eq_by_id,
        color_map,
        lx=lx,
        ly=55,
        fits=req.layout.fits,
        utilization=req.layout.zone_utilization_pct,
        extra_sqft=req.layout.additional_sqft_needed,
    )

    buf = io.BytesIO()
    canvas.convert("RGB").save(buf, format="PNG")
    return buf.getvalue()
