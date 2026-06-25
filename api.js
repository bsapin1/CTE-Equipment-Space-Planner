/** API client for layout generation and export. */

export async function generateLayout(floorPlan, equipment, geminiApiKey) {
  const res = await fetch("/api/layout", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      floor_plan: floorPlan,
      equipment,
      gemini_api_key: geminiApiKey || "",
    }),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Layout request failed (${res.status})`);
  }

  return res.json();
}

export async function exportLayoutPng(floorPlan, equipment, layout) {
  const res = await fetch("/api/export", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      floor_plan: floorPlan,
      equipment,
      layout,
    }),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Export failed (${res.status})`);
  }

  return res.blob();
}
