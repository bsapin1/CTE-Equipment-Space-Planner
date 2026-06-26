"""Render layout to PNG using Pillow.

Equipment is drawn in the style shown in the reference sketch:
  - Solid rectangle  = equipment footprint
  - Dashed rectangle = clearance envelope (one dashed side per clearance direction)
  - Number centered in solid rectangle → keyed to legend
"""

from __future__ import annotations

import io
import math
from typing import TYPE_CHECKING

from PIL import Image, ImageDraw, ImageFont

try:
    from .models import EquipmentItem, ExportRequest, FloorPlan, Placement
    from .validation import _clearance_rect, _equipment_rect, _rotated_dims
except ImportError:
    from models import EquipmentItem, ExportRequest, FloorPlan, Placement
    from validation import _clearance_rect, _equipment_rect, _rotated_dims

if TYPE_CHECKING:
    pass

SCALE = 14          # pixels per foot (blank renderer)
MARGIN = 60
LEGEND_WIDTH = 460

# All linework is black and white
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
GRAY  = (100, 100, 100)


# ---------------------------------------------------------------------------
# Font helpers
# ---------------------------------------------------------------------------

def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in (
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Supplemental/ArialBD.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "arial.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _load_font_bold(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in (
        "/System/Library/Fonts/Supplemental/ArialBD.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return _load_font(size)


# ---------------------------------------------------------------------------
# Drawing primitives
# ---------------------------------------------------------------------------

def _dashed_line(
    draw: ImageDraw.ImageDraw,
    x0: float, y0: float, x1: float, y1: float,
    fill,
    width: int = 1,
    dash: int = 6,
    gap: int = 4,
) -> None:
    """Draw a dashed line from (x0,y0) to (x1,y1)."""
    length = math.hypot(x1 - x0, y1 - y0)
    if length < 1:
        return
    ux, uy = (x1 - x0) / length, (y1 - y0) / length
    pos = 0.0
    on = True
    while pos < length:
        seg = dash if on else gap
        end = min(pos + seg, length)
        if on:
            sx, sy = x0 + ux * pos, y0 + uy * pos
            ex, ey = x0 + ux * end, y0 + uy * end
            draw.line([(sx, sy), (ex, ey)], fill=fill, width=width)
        pos = end
        on = not on


def _dashed_rect(
    draw: ImageDraw.ImageDraw,
    x: int, y: int, w: int, h: int,
    fill,
    width: int = 1,
    dash: int = 6,
    gap: int = 4,
) -> None:
    """Draw a dashed-line rectangle."""
    _dashed_line(draw, x,     y,     x + w, y,     fill, width, dash, gap)
    _dashed_line(draw, x + w, y,     x + w, y + h, fill, width, dash, gap)
    _dashed_line(draw, x + w, y + h, x,     y + h, fill, width, dash, gap)
    _dashed_line(draw, x,     y + h, x,     y,     fill, width, dash, gap)


def _clamp_rect(
    x: int, y: int, w: int, h: int,
    min_x: int, min_y: int, max_x: int, max_y: int,
) -> tuple[int, int, int, int]:
    """Clamp a rectangle so it stays within [min_x..max_x, min_y..max_y].
    Returns (x, y, w, h) with w/h reduced as needed (minimum 1 each).
    """
    x2 = min(x + w, max_x)
    y2 = min(y + h, max_y)
    x  = max(x, min_x)
    y  = max(y, min_y)
    return x, y, max(1, x2 - x), max(1, y2 - y)


def _centered_text(
    draw: ImageDraw.ImageDraw,
    cx: float, cy: float,
    text: str,
    font,
    fill,
    outline_fill=None,
) -> None:
    """Draw text centered on (cx, cy), with optional 1px dark outline for readability."""
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx, ty = int(cx - tw / 2), int(cy - th / 2)
    if outline_fill:
        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            draw.text((tx + dx, ty + dy), text, font=font, fill=outline_fill)
    draw.text((tx, ty), text, font=font, fill=fill)


def _draw_equipment_symbol(
    draw: ImageDraw.ImageDraw,
    ex: int, ey: int, ew: int, eh: int,   # equipment rect in pixels
    cx: int, cy: int, cw: int, ch: int,   # clearance rect in pixels
    number: str,
    font_num,
    line_width: int = 2,
) -> None:
    """Draw one equipment symbol (black and white):
    - White fill + solid black border = equipment footprint
    - Dashed black lines = clearance envelope
    - Number centered in equipment box
    """
    # Clearance envelope — dashed black rect
    _dashed_rect(draw, cx, cy, cw, ch, fill=BLACK, width=line_width, dash=6, gap=4)

    # Equipment footprint — white fill + solid black border
    draw.rectangle([ex, ey, ex + ew, ey + eh], fill=WHITE, outline=BLACK, width=line_width)

    # Number centered inside equipment box
    _centered_text(draw, ex + ew / 2, ey + eh / 2, number, font_num, fill=BLACK)


# ---------------------------------------------------------------------------
# Number map: assign a sequential integer to every placement
# ---------------------------------------------------------------------------

def _make_number_map(placements: list[Placement]) -> dict[str, int]:
    """Map instance_id → sequential integer (1-based)."""
    return {p.instance_id: i + 1 for i, p in enumerate(placements)}


# ---------------------------------------------------------------------------
# Legend
# ---------------------------------------------------------------------------

def _draw_legend_panel(
    draw: ImageDraw.ImageDraw,
    placements: list[Placement],
    eq_by_id: dict[str, EquipmentItem],
    number_map: dict[str, int],
    lx: int, ly: int,
    fits: bool,
    utilization: float,
    extra_sqft: float,
    fp_name: str = "",
    fp_dims: str = "",
) -> None:
    font_title = _load_font_bold(24)
    font = _load_font(20)
    font_sm = _load_font(19)
    font_num = _load_font_bold(19)

    if fp_name:
        draw.text((lx, ly), fp_name, fill=BLACK, font=font_title)
        ly += 30
    if fp_dims:
        draw.text((lx, ly), fp_dims, fill=GRAY, font=font_sm)
        ly += 26

    draw.text((lx, ly), "KEY", fill=BLACK, font=font_title)
    ly += 34

    box = 30
    for p in placements:
        item = eq_by_id.get(p.equipment_id)
        if not item:
            continue
        num = str(number_map.get(p.instance_id, "?"))
        w, d = _rotated_dims(item, p.rotation)

        # Mini B&W equipment symbol
        draw.rectangle([lx, ly, lx + box, ly + box], fill=WHITE, outline=BLACK, width=2)
        _centered_text(draw, lx + box / 2, ly + box / 2, num, font_num, fill=BLACK)

        label = f"{num}. {item.name}  ({w:.0f}' × {d:.0f}')"
        draw.text((lx + box + 10, ly + (box - 18) // 2), label, fill=BLACK, font=font_sm)
        ly += box + 10

    ly += 10
    draw.line([(lx, ly), (lx + LEGEND_WIDTH - 20, ly)], fill=GRAY, width=1)
    ly += 10

    if fits:
        draw.text((lx, ly), f"Layout fits  |  Zone util: {utilization:.0f}%", fill=BLACK, font=font)
    else:
        draw.text((lx, ly), f"Need ~{extra_sqft:.0f} more sq ft", fill=BLACK, font=font)


# ---------------------------------------------------------------------------
# Door / window openings
# ---------------------------------------------------------------------------

def _door_zone_ft(door, room_w_ft: float, room_d_ft: float, depth_ft: float) -> tuple[float, float, float, float]:
    """Return (x, y, w, h) in feet for a door's no-go zone (swing arc or overhead travel path)."""
    off = door.offset_ft
    wid = door.width_ft
    if door.wall == "south":
        return off, 0.0, wid, depth_ft
    if door.wall == "north":
        return off, room_d_ft - depth_ft, wid, depth_ft
    if door.wall == "west":
        return 0.0, room_d_ft - off - wid, depth_ft, wid
    # east
    return room_w_ft - depth_ft, room_d_ft - off - wid, depth_ft, wid


def _draw_door(
    draw: ImageDraw.ImageDraw,
    ox: int, oy: int, room_w: int, room_h: int,
    door,  # Opening model
    scale: int = SCALE,
) -> None:
    """Draw a door with its type-specific clearance zone indicator."""
    wall = door.wall
    off = int(door.offset_ft * scale)
    wid = int(door.width_ft * scale)
    door_type = getattr(door, "door_type", "swing")
    font = _load_font(9)

    # Door opening marker on the wall (solid color fill)
    if wall == "south":
        wx1, wy1, wx2, wy2 = ox + off, oy + room_h - 4, ox + off + wid, oy + room_h
    elif wall == "north":
        wx1, wy1, wx2, wy2 = ox + off, oy, ox + off + wid, oy + 4
    elif wall == "west":
        wx1, wy1, wx2, wy2 = ox, oy + room_h - off - wid, ox + 4, oy + room_h - off
    else:
        wx1, wy1, wx2, wy2 = ox + room_w - 4, oy + room_h - off - wid, ox + room_w, oy + room_h - off

    draw.rectangle([wx1, wy1, wx2, wy2], fill="#8B4513")
    draw.text((wx1, wy1 - 12), "D", fill="#8B4513", font=font)

    if door_type == "swing":
        sc = getattr(door, "swing_clearance_ft", 0.0)
        eff = sc if sc > 0 else door.width_ft
        arc_px = int(eff * scale)
        if arc_px < 2:
            return
        # Swing arc zone — light hatch using dashed rect
        if wall == "south":
            zx, zy, zw, zh = ox + off, oy + room_h - arc_px, wid, arc_px
        elif wall == "north":
            zx, zy, zw, zh = ox + off, oy, wid, arc_px
        elif wall == "west":
            zx, zy, zw, zh = ox, oy + room_h - off - wid, arc_px, wid
        else:
            zx, zy, zw, zh = ox + room_w - arc_px, oy + room_h - off - wid, arc_px, wid
        _dashed_rect(draw, zx, zy, zw, zh, fill=(139, 69, 19, 200), width=1, dash=4, gap=3)

    elif door_type == "overhead":
        travel_px = wid  # travel depth = door width
        # Overhead travel zone — dashed with different color
        if wall == "south":
            zx, zy, zw, zh = ox + off, oy + room_h - travel_px, wid, travel_px
        elif wall == "north":
            zx, zy, zw, zh = ox + off, oy, wid, travel_px
        elif wall == "west":
            zx, zy, zw, zh = ox, oy + room_h - off - wid, travel_px, wid
        else:
            zx, zy, zw, zh = ox + room_w - travel_px, oy + room_h - off - wid, travel_px, wid
        _dashed_rect(draw, zx, zy, zw, zh, fill=(180, 60, 0, 220), width=2, dash=8, gap=4)
        draw.text((zx + 2, zy + 2), "OH", fill="#B43C00", font=font)


def _draw_opening(
    draw: ImageDraw.ImageDraw,
    ox: int, oy: int, room_w: int, room_h: int,
    wall: str, offset_ft: float, width_ft: float,
    color: str, label: str,
    scale: int = SCALE,
) -> None:
    off = int(offset_ft * scale)
    wid = int(width_ft * scale)
    font = _load_font(9)

    if wall == "south":
        x1, y1, x2, y2 = ox + off, oy + room_h - 4, ox + off + wid, oy + room_h
    elif wall == "north":
        x1, y1, x2, y2 = ox + off, oy, ox + off + wid, oy + 4
    elif wall == "west":
        x1, y1, x2, y2 = ox, oy + room_h - off - wid, ox + 4, oy + room_h - off
    else:
        x1, y1, x2, y2 = ox + room_w - 4, oy + room_h - off - wid, ox + room_w, oy + room_h - off

    draw.rectangle([x1, y1, x2, y2], fill=color)
    draw.text((x1, y1 - 12), label, fill=color, font=font)


# ---------------------------------------------------------------------------
# Blank renderer
# ---------------------------------------------------------------------------

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
    font_lg = _load_font(16)
    font_sm = _load_font(10)

    ox, oy = MARGIN, MARGIN + 40

    draw.text((MARGIN, 12), fp.name, fill="#1a1a2e", font=font_lg)
    draw.text(
        (MARGIN, 32),
        f"Room: {fp.width_ft:.0f}' × {fp.depth_ft:.0f}'  |  Test-fit layout",
        fill="#666",
        font=font_sm,
    )

    # Room outline
    draw.rectangle([ox, oy, ox + room_w, oy + room_h], outline="#333333", width=2, fill="#FFFFFF")

    # Equipment zones
    for zone in fp.equipment_zones:
        zx = ox + int(zone.x_ft * SCALE)
        zy = oy + room_h - int((zone.y_ft + zone.depth_ft) * SCALE)
        zw = int(zone.width_ft * SCALE)
        zh = int(zone.depth_ft * SCALE)
        draw.rectangle([zx, zy, zx + zw, zy + zh], outline="#AAAAAA", width=1, fill="#F0F4FF")
        draw.text((zx + 4, zy + 4), zone.label or zone.id, fill="#666666", font=font_sm)

    # Doors (with swing arcs / overhead zones) & windows
    for door in fp.doors:
        _draw_door(draw, ox, oy, room_w, room_h, door, SCALE)
    for win in fp.windows:
        _draw_opening(draw, ox, oy, room_w, room_h, win.wall, win.offset_ft, win.width_ft, "#3B82F6", "W")

    number_map = _make_number_map(req.layout.placements)
    font_num = _load_font_bold(max(11, int(SCALE * 1.4)))

    # Room pixel bounds for clamping
    room_px_x0, room_px_y0 = ox, oy
    room_px_x1, room_px_y1 = ox + room_w, oy + room_h

    for p in req.layout.placements:
        item = eq_by_id.get(p.equipment_id)
        zone = zone_by_id.get(p.zone_id)
        if not item or not zone:
            continue

        eq_rect = _equipment_rect(p, item, zone)
        ex = ox + int(eq_rect.x * SCALE)
        ey = oy + room_h - int((eq_rect.y + eq_rect.h) * SCALE)
        ew = max(4, int(eq_rect.w * SCALE))
        eh = max(4, int(eq_rect.h * SCALE))

        clr = _clearance_rect(p, item, zone)
        cx = ox + int(clr.x * SCALE)
        cy = oy + room_h - int((clr.y + clr.h) * SCALE)
        cw = max(4, int(clr.w * SCALE))
        ch = max(4, int(clr.h * SCALE))

        # Clamp clearance to room bounds
        cx, cy, cw, ch = _clamp_rect(cx, cy, cw, ch, room_px_x0, room_px_y0, room_px_x1, room_px_y1)

        num = str(number_map[p.instance_id])
        _draw_equipment_symbol(draw, ex, ey, ew, eh, cx, cy, cw, ch, num, font_num)

    # Legend
    lx = ox + room_w + 18
    _draw_legend_panel(
        draw, req.layout.placements, eq_by_id, number_map,
        lx=lx, ly=oy,
        fits=req.layout.fits,
        utilization=req.layout.zone_utilization_pct,
        extra_sqft=req.layout.additional_sqft_needed,
    )

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Drawing overlay renderer
# ---------------------------------------------------------------------------

def render_layout_on_drawing(
    req: ExportRequest,
    drawing_bytes: bytes,
    room_bounds_pct: dict | None = None,
) -> bytes:
    """Overlay equipment symbols onto the original floor plan image."""
    fp = req.floor_plan
    bounds = room_bounds_pct or {"left": 0.0, "top": 0.0, "right": 1.0, "bottom": 1.0}

    try:
        bg = Image.open(io.BytesIO(drawing_bytes)).convert("RGBA")
    except Exception:
        return render_layout_png(req)

    img_w, img_h = bg.size

    rpx_left = bounds["left"] * img_w
    rpx_top  = bounds["top"]  * img_h
    rpx_w    = (bounds["right"]  - bounds["left"]) * img_w
    rpx_h    = (bounds["bottom"] - bounds["top"])  * img_h
    scale_x  = rpx_w / fp.width_ft
    scale_y  = rpx_h / fp.depth_ft

    def ft_to_px(x_ft, y_ft, w_ft, h_ft):
        px = int(rpx_left + x_ft * scale_x)
        py = int(rpx_top  + rpx_h - (y_ft + h_ft) * scale_y)
        pw = max(4, int(w_ft * scale_x))
        ph = max(4, int(h_ft * scale_y))
        return px, py, pw, ph

    canvas_w = img_w + LEGEND_WIDTH
    canvas_h = max(img_h, 200)
    canvas = Image.new("RGBA", (canvas_w, canvas_h), (248, 249, 250, 255))
    canvas.paste(bg, (0, 0))

    overlay = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    draw_ov = ImageDraw.Draw(overlay)

    eq_by_id   = {e.id: e for e in req.equipment}
    zone_by_id = {z.id: z for z in fp.equipment_zones}
    number_map = _make_number_map(req.layout.placements)

    # Scale-aware line width and font
    pix_per_ft = (scale_x + scale_y) / 2
    line_w = max(2, int(pix_per_ft * 0.12))
    font_num = _load_font_bold(max(11, int(pix_per_ft * 0.75)))

    # Room pixel region bounds (for clamping clearances)
    room_px_x0 = int(rpx_left)
    room_px_y0 = int(rpx_top)
    room_px_x1 = int(rpx_left + rpx_w)
    room_px_y1 = int(rpx_top  + rpx_h)

    # Draw door swing arcs and overhead door travel zones on the overlay (dark dashed)
    for door in fp.doors:
        door_type = getattr(door, "door_type", "swing")
        if door_type == "swing":
            sc = getattr(door, "swing_clearance_ft", 0.0)
            arc_ft = sc if sc > 0 else door.width_ft
            dx, dy, dw, dh = ft_to_px(*_door_zone_ft(door, fp.width_ft, fp.depth_ft, arc_ft))
            _dashed_rect(draw_ov, dx, dy, dw, dh, fill=(0, 0, 0, 120), width=max(1, line_w), dash=6, gap=4)
        elif door_type == "overhead":
            dx, dy, dw, dh = ft_to_px(*_door_zone_ft(door, fp.width_ft, fp.depth_ft, door.width_ft))
            _dashed_rect(draw_ov, dx, dy, dw, dh, fill=(0, 0, 0, 140), width=max(2, line_w), dash=8, gap=5)

    for p in req.layout.placements:
        item = eq_by_id.get(p.equipment_id)
        zone = zone_by_id.get(p.zone_id)
        if not item or not zone:
            continue

        eq_rect = _equipment_rect(p, item, zone)
        ex, ey, ew, eh = ft_to_px(eq_rect.x, eq_rect.y, eq_rect.w, eq_rect.h)

        clr = _clearance_rect(p, item, zone)
        cx, cy, cw, ch = ft_to_px(clr.x, clr.y, clr.w, clr.h)

        # Clamp clearance rect to room pixel bounds so it never overflows
        cx, cy, cw, ch = _clamp_rect(cx, cy, cw, ch, room_px_x0, room_px_y0, room_px_x1, room_px_y1)

        num = str(number_map[p.instance_id])

        # Dashed black clearance envelope
        _dashed_rect(draw_ov, cx, cy, cw, ch, fill=(0, 0, 0, 210),
                     width=line_w, dash=max(4, line_w * 3), gap=max(3, line_w * 2))

        # White-fill equipment box with black border
        draw_ov.rectangle([ex, ey, ex + ew, ey + eh],
                          fill=(255, 255, 255, 230), outline=(0, 0, 0, 255), width=line_w)

        # Number centered in box
        _centered_text(draw_ov, ex + ew / 2, ey + eh / 2, num, font_num,
                       fill=(0, 0, 0, 255), outline_fill=(255, 255, 255, 255))

    canvas = Image.alpha_composite(canvas, overlay)

    # Legend panel (white background strip)
    draw_main = ImageDraw.Draw(canvas)
    draw_main.rectangle([img_w, 0, canvas_w, canvas_h], fill=(255, 255, 255, 255))
    _draw_legend_panel(
        draw_main, req.layout.placements, eq_by_id, number_map,
        lx=img_w + 12, ly=16,
        fits=req.layout.fits,
        utilization=req.layout.zone_utilization_pct,
        extra_sqft=req.layout.additional_sqft_needed,
        fp_name=fp.name,
        fp_dims=f"{fp.width_ft:.0f}' × {fp.depth_ft:.0f}'  |  Test-fit overlay",
    )

    buf = io.BytesIO()
    canvas.convert("RGB").save(buf, format="PNG")
    return buf.getvalue()
