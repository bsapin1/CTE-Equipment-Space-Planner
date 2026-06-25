"""FastAPI application for CTE Equipment Space Planner."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from .layout_engine import generate_layout
from .models import ExportRequest, LayoutRequest, LayoutResult
from .renderer import render_layout_png

APP_DIR = Path(__file__).resolve().parent
ROOT = APP_DIR.parent
STATIC = ROOT / "static"

app = FastAPI(title="CTE Equipment Space Planner", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/layout", response_model=LayoutResult)
async def create_layout(req: LayoutRequest) -> LayoutResult:
    if not req.equipment:
        raise HTTPException(status_code=400, detail="Equipment list is empty")
    if not req.floor_plan.equipment_zones:
        raise HTTPException(status_code=400, detail="Floor plan has no equipment zones")
    return generate_layout(req.floor_plan, req.equipment, req.gemini_api_key)


@app.post("/api/export")
async def export_png(req: ExportRequest) -> Response:
    try:
        png = render_layout_png(req)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return Response(content=png, media_type="image/png")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
app.mount("/templates", StaticFiles(directory=ROOT / "templates"), name="templates")
