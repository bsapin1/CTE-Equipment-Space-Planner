/** Parse equipment CSV into structured objects. */

const REQUIRED = ["id", "name", "width_ft", "depth_ft"];

export function parseCsv(text) {
  const lines = text.trim().split(/\r?\n/).filter(Boolean);
  if (lines.length < 2) throw new Error("CSV must have a header row and at least one data row");

  const headers = lines[0].split(",").map((h) => h.trim().toLowerCase());
  const rows = [];

  for (let i = 1; i < lines.length; i++) {
    const values = _splitCsvLine(lines[i]);
    const row = {};
    headers.forEach((h, idx) => {
      row[h] = (values[idx] ?? "").trim();
    });
    rows.push(row);
  }

  return rows.map(normalizeEquipmentRow);
}

function _splitCsvLine(line) {
  const result = [];
  let current = "";
  let inQuotes = false;
  for (const ch of line) {
    if (ch === '"') {
      inQuotes = !inQuotes;
    } else if (ch === "," && !inQuotes) {
      result.push(current);
      current = "";
    } else {
      current += ch;
    }
  }
  result.push(current);
  return result;
}

function normalizeEquipmentRow(row) {
  for (const key of REQUIRED) {
    if (!row[key]) throw new Error(`Missing required column: ${key}`);
  }

  const adjacency = row.adjacency
    ? row.adjacency.split(/[|;]/).map((s) => s.trim()).filter(Boolean)
    : [];

  return {
    id: row.id,
    name: row.name,
    width_ft: parseFloat(row.width_ft),
    depth_ft: parseFloat(row.depth_ft),
    qty: parseInt(row.qty || "1", 10) || 1,
    clearance_front_ft: parseFloat(row.clearance_front_ft ?? "3") || 3,
    clearance_rear_ft: parseFloat(row.clearance_rear_ft ?? "1") || 1,
    clearance_left_ft: parseFloat(row.clearance_left_ft ?? "1.5") || 1.5,
    clearance_right_ft: parseFloat(row.clearance_right_ft ?? "1.5") || 1.5,
    wall_preferred: ["yes", "no", "any"].includes(row.wall_preferred)
      ? row.wall_preferred
      : "any",
    adjacency,
    category: row.category || "general",
    notes: row.notes || "",
  };
}

export function renderEquipmentPreview(equipment, container) {
  if (!equipment?.length) {
    container.innerHTML = "<p style='padding:0.5rem;color:#888'>No equipment loaded</p>";
    return;
  }

  const cols = ["id", "name", "width_ft", "depth_ft", "qty", "category"];
  let html = "<table><thead><tr>";
  cols.forEach((c) => (html += `<th>${c}</th>`));
  html += "</tr></thead><tbody>";
  equipment.forEach((e) => {
    html += "<tr>";
    cols.forEach((c) => (html += `<td>${e[c]}</td>`));
    html += "</tr>";
  });
  html += "</tbody></table>";
  container.innerHTML = html;
}

export async function loadSampleEquipment() {
  const res = await fetch("/templates/sample-equipment.csv");
  const text = await res.text();
  return parseCsv(text);
}
