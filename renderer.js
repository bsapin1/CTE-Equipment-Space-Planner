/** Client-side canvas renderer for floor plan preview. */

const SCALE = 12;
const MARGIN = 50;
const LEGEND_W = 240;
const COLORS = [
  "#4A90D9", "#50C878", "#E67E22", "#9B59B6", "#E74C3C",
  "#1ABC9C", "#F39C12", "#34495E", "#16A085", "#C0392B",
];

function rotatedDims(item, rotation) {
  return rotation === 90 || rotation === 270
    ? [item.depth_ft, item.width_ft]
    : [item.width_ft, item.depth_ft];
}

function equipmentRect(p, item, zone) {
  const [w, d] = rotatedDims(item, p.rotation);
  return { x: zone.x_ft + p.x_ft, y: zone.y_ft + p.y_ft, w, h: d };
}

function clearanceRect(p, item, zone) {
  const [w, d] = rotatedDims(item, p.rotation);
  return {
    x: zone.x_ft + p.x_ft - item.clearance_left_ft,
    y: zone.y_ft + p.y_ft - item.clearance_rear_ft,
    w: w + item.clearance_left_ft + item.clearance_right_ft,
    h: d + item.clearance_rear_ft + item.clearance_front_ft,
  };
}

function drawOpening(ctx, ox, oy, roomW, roomH, wall, offsetFt, widthFt, color, label) {
  const off = offsetFt * SCALE;
  const wid = widthFt * SCALE;
  ctx.fillStyle = color;

  let x, y, w, h;
  if (wall === "south") { x = ox + off; y = oy + roomH - 5; w = wid; h = 5; }
  else if (wall === "north") { x = ox + off; y = oy; w = wid; h = 5; }
  else if (wall === "west") { x = ox; y = oy + roomH - off - wid; w = 5; h = wid; }
  else { x = ox + roomW - 5; y = oy + roomH - off - wid; w = 5; h = wid; }

  ctx.fillRect(x, y, w, h);
  ctx.fillStyle = color;
  ctx.font = "10px sans-serif";
  ctx.fillText(label, x, y - 3);
}

export function renderToCanvas(canvas, floorPlan, equipment, layout) {
  const eqById = Object.fromEntries(equipment.map((e) => [e.id, e]));
  const zoneById = Object.fromEntries(floorPlan.equipment_zones.map((z) => [z.id, z]));

  const roomW = floorPlan.width_ft * SCALE;
  const roomH = floorPlan.depth_ft * SCALE;
  canvas.width = MARGIN * 2 + roomW + LEGEND_W;
  canvas.height = MARGIN * 2 + roomH + 60;

  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "#F8F9FA";
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  const ox = MARGIN;
  const oy = MARGIN + 30;

  ctx.fillStyle = "#1a1a2e";
  ctx.font = "bold 15px sans-serif";
  ctx.fillText(floorPlan.name, MARGIN, 22);
  ctx.fillStyle = "#666";
  ctx.font = "11px sans-serif";
  ctx.fillText(
    `Room: ${floorPlan.width_ft}' × ${floorPlan.depth_ft}'  |  Test-fit layout`,
    MARGIN,
    38
  );

  ctx.fillStyle = "#FFF";
  ctx.strokeStyle = "#333";
  ctx.lineWidth = 2;
  ctx.fillRect(ox, oy, roomW, roomH);
  ctx.strokeRect(ox, oy, roomW, roomH);

  for (const zone of floorPlan.equipment_zones) {
    const zx = ox + zone.x_ft * SCALE;
    const zy = oy + roomH - (zone.y_ft + zone.depth_ft) * SCALE;
    const zw = zone.width_ft * SCALE;
    const zh = zone.depth_ft * SCALE;
    ctx.fillStyle = "#EEF2FF";
    ctx.fillRect(zx, zy, zw, zh);
    ctx.strokeStyle = "#888";
    ctx.lineWidth = 1;
    ctx.strokeRect(zx, zy, zw, zh);
    ctx.fillStyle = "#555";
    ctx.font = "10px sans-serif";
    ctx.fillText(zone.label || zone.id, zx + 4, zy + 14);
  }

  for (const door of floorPlan.doors || []) {
    drawOpening(ctx, ox, oy, roomW, roomH, door.wall, door.offset_ft, door.width_ft, "#8B4513", "D");
  }
  for (const win of floorPlan.windows || []) {
    drawOpening(ctx, ox, oy, roomW, roomH, win.wall, win.offset_ft, win.width_ft, "#87CEEB", "W");
  }

  const categories = [...new Set(
    layout.placements.map((p) => eqById[p.equipment_id]?.category).filter(Boolean)
  )].sort();
  const colorMap = Object.fromEntries(categories.map((c, i) => [c, COLORS[i % COLORS.length]]));

  for (const p of layout.placements) {
    const item = eqById[p.equipment_id];
    const zone = zoneById[p.zone_id];
    if (!item || !zone) continue;

    const clr = clearanceRect(p, item, zone);
    const cx = ox + clr.x * SCALE;
    const cy = oy + roomH - (clr.y + clr.h) * SCALE;
    ctx.strokeStyle = "#CCC";
    ctx.lineWidth = 1;
    ctx.strokeRect(cx, cy, clr.w * SCALE, clr.h * SCALE);

    const eq = equipmentRect(p, item, zone);
    const px = ox + eq.x * SCALE;
    const py = oy + roomH - (eq.y + eq.h) * SCALE;
    const pw = eq.w * SCALE;
    const ph = eq.h * SCALE;

    ctx.fillStyle = colorMap[item.category] || COLORS[0];
    ctx.fillRect(px, py, pw, ph);
    ctx.strokeStyle = "#222";
    ctx.strokeRect(px, py, pw, ph);

    ctx.fillStyle = "#FFF";
    ctx.font = "10px sans-serif";
    ctx.fillText(p.instance_id, px + 3, py + 13);
  }

  const lx = ox + roomW + 16;
  let ly = oy;
  ctx.fillStyle = "#1a1a2e";
  ctx.font = "bold 12px sans-serif";
  ctx.fillText("Legend", lx, ly + 12);
  ly += 24;

  const seen = new Set();
  for (const p of layout.placements) {
    if (seen.has(p.instance_id)) continue;
    seen.add(p.instance_id);
    const item = eqById[p.equipment_id];
    if (!item) continue;
    const [w, d] = rotatedDims(item, p.rotation);
    ctx.fillStyle = colorMap[item.category] || COLORS[0];
    ctx.fillRect(lx, ly, 12, 12);
    ctx.strokeStyle = "#222";
    ctx.strokeRect(lx, ly, 12, 12);
    ctx.fillStyle = "#333";
    ctx.font = "10px sans-serif";
    ctx.fillText(`${p.instance_id}: ${item.name} (${w.toFixed(0)}'×${d.toFixed(0)}')`, lx + 18, ly + 10);
    ly += 16;
  }

  const statusY = oy + roomH + 20;
  if (layout.fits) {
    ctx.fillStyle = "#059669";
    ctx.fillText(`✓ Layout fits  |  Zone utilization: ${layout.zone_utilization_pct}%`, MARGIN, statusY);
  } else {
    ctx.fillStyle = "#DC2626";
    ctx.fillText(
      `✗ Space insufficient  |  ~${layout.additional_sqft_needed} additional sq ft needed`,
      MARGIN,
      statusY
    );
  }

  return canvas.toDataURL("image/png");
}

export function downloadDataUrl(dataUrl, filename) {
  const a = document.createElement("a");
  a.href = dataUrl;
  a.download = filename;
  a.click();
}
