import { generateLayout, exportLayoutPng } from "./api.js";
import {
  applyFloorPlanToEditor,
  buildFloorPlanFromEditor,
  getActiveFloorPlan,
  loadSampleFloorPlan,
} from "./floorplan.js";
import {
  loadSampleEquipment,
  parseCsv,
  renderEquipmentPreview,
} from "./equipment.js";
import { downloadDataUrl, renderToCanvas } from "./renderer.js";

const STORAGE_KEY = "cte-planner-gemini-key";

let equipment = [];
let currentFloorPlan = null;
let currentLayout = null;
let activeTab = "editor";

function $(id) {
  return document.getElementById(id);
}

function setStatus(text, type = "idle") {
  const el = $("status");
  el.textContent = text;
  el.className = `status ${type}`;
}

function renderIssues(issues) {
  const el = $("issues");
  if (!issues?.length) {
    el.innerHTML = "";
    return;
  }
  el.innerHTML = issues
    .map(
      (i) =>
        `<div class="issue ${i.severity}">${i.severity.toUpperCase()}: ${i.message}</div>`
    )
    .join("");
}

function getActiveTab() {
  return document.querySelector(".tab.active")?.dataset.tab || "editor";
}

async function init() {
  const savedKey = localStorage.getItem(STORAGE_KEY);
  if (savedKey) $("gemini-key").value = savedKey;

  $("gemini-key").addEventListener("change", (e) => {
    localStorage.setItem(STORAGE_KEY, e.target.value.trim());
  });

  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
      document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
      tab.classList.add("active");
      activeTab = tab.dataset.tab;
      $(`tab-${activeTab}`).classList.add("active");
    });
  });

  $("load-sample-floor").addEventListener("click", async () => {
    const fp = await loadSampleFloorPlan();
    applyFloorPlanToEditor(fp);
    currentFloorPlan = fp;
  });

  $("floor-json-file").addEventListener("change", async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const text = await file.text();
    $("floor-json").value = text;
    activeTab = "json";
    document.querySelector('[data-tab="json"]').click();
  });

  $("equipment-file").addEventListener("change", async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      equipment = parseCsv(await file.text());
      renderEquipmentPreview(equipment, $("equipment-preview"));
    } catch (err) {
      setStatus(err.message, "error");
    }
  });

  $("generate-btn").addEventListener("click", onGenerate);

  $("download-png").addEventListener("click", () => {
    if (!currentLayout || !currentFloorPlan) return;
    const dataUrl = renderToCanvas(
      $("preview-canvas"),
      currentFloorPlan,
      equipment,
      currentLayout
    );
    downloadDataUrl(dataUrl, "cte-layout.png");
  });

  $("download-server-png").addEventListener("click", async () => {
    if (!currentLayout || !currentFloorPlan) return;
    try {
      const blob = await exportLayoutPng(currentFloorPlan, equipment, currentLayout);
      const url = URL.createObjectURL(blob);
      downloadDataUrl(url, "cte-layout.png");
      URL.revokeObjectURL(url);
    } catch (err) {
      setStatus(err.message, "error");
    }
  });

  // Pre-load samples for quick demo
  try {
    const [fp, eq] = await Promise.all([loadSampleFloorPlan(), loadSampleEquipment()]);
    applyFloorPlanToEditor(fp);
    currentFloorPlan = fp;
    equipment = eq;
    renderEquipmentPreview(equipment, $("equipment-preview"));
  } catch {
    // samples optional if server not running
  }
}

async function onGenerate() {
  try {
    activeTab = getActiveTab();
    currentFloorPlan = getActiveFloorPlan(activeTab);

    if (!equipment.length) {
      equipment = await loadSampleEquipment();
      renderEquipmentPreview(equipment, $("equipment-preview"));
    }

    setStatus("Generating layout with Gemini...", "loading");
    $("summary").textContent = "";
    renderIssues([]);
    $("download-png").disabled = true;
    $("download-server-png").disabled = true;

    const apiKey = $("gemini-key").value.trim();
    localStorage.setItem(STORAGE_KEY, apiKey);

    currentLayout = await generateLayout(currentFloorPlan, equipment, apiKey);

    renderToCanvas($("preview-canvas"), currentFloorPlan, equipment, currentLayout);

    if (currentLayout.fits) {
      setStatus(
        `Layout fits — ${currentLayout.zone_utilization_pct}% zone utilization`,
        "success"
      );
    } else {
      setStatus(
        `Space insufficient — ~${currentLayout.additional_sqft_needed} additional sq ft needed`,
        "error"
      );
    }

    $("summary").textContent = currentLayout.summary || "";
    renderIssues(currentLayout.issues);
    $("download-png").disabled = false;
    $("download-server-png").disabled = false;
  } catch (err) {
    setStatus(err.message, "error");
  }
}

init();
