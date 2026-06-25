/** Build floor plan object from visual editor or JSON. */

export function buildFloorPlanFromEditor() {
  const windows = [];
  const w1 = parseFloat(document.getElementById("win1-width").value);
  if (w1 > 0) {
    windows.push({
      wall: document.getElementById("win-wall").value,
      offset_ft: parseFloat(document.getElementById("win1-offset").value) || 0,
      width_ft: w1,
    });
  }
  const w2 = parseFloat(document.getElementById("win2-width").value);
  if (w2 > 0) {
    windows.push({
      wall: document.getElementById("win-wall").value,
      offset_ft: parseFloat(document.getElementById("win2-offset").value) || 0,
      width_ft: w2,
    });
  }

  return {
    name: document.getElementById("room-name").value || "CTE Classroom",
    width_ft: parseFloat(document.getElementById("room-width").value) || 40,
    depth_ft: parseFloat(document.getElementById("room-depth").value) || 30,
    doors: [
      {
        wall: document.getElementById("door-wall").value,
        offset_ft: parseFloat(document.getElementById("door-offset").value) || 0,
        width_ft: parseFloat(document.getElementById("door-width").value) || 3,
      },
    ],
    windows,
    equipment_zones: [
      {
        id: "zone-1",
        label: document.getElementById("zone-label").value || "Equipment Zone",
        x_ft: parseFloat(document.getElementById("zone-x").value) || 0,
        y_ft: parseFloat(document.getElementById("zone-y").value) || 0,
        width_ft: parseFloat(document.getElementById("zone-width").value) || 20,
        depth_ft: parseFloat(document.getElementById("zone-depth").value) || 15,
      },
    ],
  };
}

export function parseFloorPlanJson(text) {
  const data = JSON.parse(text);
  if (!data.width_ft || !data.depth_ft) {
    throw new Error("Floor plan JSON must include width_ft and depth_ft");
  }
  if (!data.equipment_zones?.length) {
    throw new Error("Floor plan JSON must include at least one equipment zone");
  }
  return data;
}

export async function loadSampleFloorPlan() {
  const res = await fetch("/templates/sample-floor-plan.json");
  return res.json();
}

export function applyFloorPlanToEditor(fp) {
  document.getElementById("room-name").value = fp.name || "CTE Classroom";
  document.getElementById("room-width").value = fp.width_ft;
  document.getElementById("room-depth").value = fp.depth_ft;

  if (fp.doors?.[0]) {
    document.getElementById("door-wall").value = fp.doors[0].wall;
    document.getElementById("door-offset").value = fp.doors[0].offset_ft;
    document.getElementById("door-width").value = fp.doors[0].width_ft;
  }

  if (fp.windows?.[0]) {
    document.getElementById("win-wall").value = fp.windows[0].wall;
    document.getElementById("win1-offset").value = fp.windows[0].offset_ft;
    document.getElementById("win1-width").value = fp.windows[0].width_ft;
  }
  if (fp.windows?.[1]) {
    document.getElementById("win2-offset").value = fp.windows[1].offset_ft;
    document.getElementById("win2-width").value = fp.windows[1].width_ft;
  }

  const zone = fp.equipment_zones?.[0];
  if (zone) {
    document.getElementById("zone-label").value = zone.label || zone.id;
    document.getElementById("zone-x").value = zone.x_ft;
    document.getElementById("zone-y").value = zone.y_ft;
    document.getElementById("zone-width").value = zone.width_ft;
    document.getElementById("zone-depth").value = zone.depth_ft;
  }

  document.getElementById("floor-json").value = JSON.stringify(fp, null, 2);
}

export function getActiveFloorPlan(activeTab) {
  if (activeTab === "json") {
    const text = document.getElementById("floor-json").value.trim();
    if (!text) throw new Error("Paste or upload a floor plan JSON");
    return parseFloorPlanJson(text);
  }
  return buildFloorPlanFromEditor();
}
