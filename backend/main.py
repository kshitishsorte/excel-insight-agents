"""
FastAPI entrypoint.

Serves the JSON API + WebSockets and, in production mode, the built React app
(frontend/dist) so the whole thing runs as a single process on one port.

Run:
  dev   :  uvicorn backend.main:app --reload      (+ `npm run dev` in frontend/)
  prod  :  npm run build (in frontend/), then      uvicorn backend.main:app
"""

from __future__ import annotations

import os
import sys

# The tested modules (config, agents, pipeline, reporting, utils) were MOVED into
# backend/ unchanged and still import each other by top-level name. Put backend/
# on sys.path so `import config`, `from agents import ...` etc. resolve here.
_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

import asyncio  # noqa: E402

from fastapi import FastAPI, UploadFile, File, HTTPException, WebSocket  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse, Response, FileResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from state.project_store import store  # noqa: E402
from ws import project_socket  # noqa: E402
from agents import base  # noqa: E402
from voice import speech  # noqa: E402

app = FastAPI(title="Excel Insight Agents")

# Dev: the Vite dev server (5173) proxies /api and /ws, so same-origin. CORS here
# is a belt-and-braces fallback if the frontend is served from another origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class CreateProject(BaseModel):
    name: str | None = None


class RenameProject(BaseModel):
    name: str


# --- health ------------------------------------------------------------------
@app.get("/api/health")
def health():
    ok, msg = base.check_server()
    return {"ollama_ok": ok, "detail": msg}


@app.get("/api/voice/status")
def voice_status():
    ok, detail = speech.available()
    return {"ok": ok, "detail": detail}


@app.post("/api/voice/warmup")
async def voice_warmup():
    """Load the STT/TTS models (downloading them once if needed). Called when the
    user first enables voice, so the first spoken turn isn't slow."""
    loop = asyncio.get_running_loop()
    ok = await loop.run_in_executor(None, speech.warm_up)
    _, detail = speech.available()
    return {"ok": ok, "detail": detail}


# --- projects ----------------------------------------------------------------
@app.post("/api/projects")
def create_project(body: CreateProject):
    p = store.create(body.name)
    return {"id": p.id, "name": p.name}


@app.get("/api/projects")
def list_projects():
    return [p.to_summary() for p in store.list()]


@app.get("/api/projects/{pid}")
def get_project(pid: str):
    p = store.get(pid)
    if not p:
        raise HTTPException(404, "Project not found")
    return p.to_full()


@app.patch("/api/projects/{pid}")
def rename_project(pid: str, body: RenameProject):
    p = store.get(pid)
    if not p:
        raise HTTPException(404, "Project not found")
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "Name cannot be empty")
    p.name = name[:120]
    return p.to_summary()


@app.delete("/api/projects/{pid}")
def delete_project(pid: str):
    if not store.delete(pid):
        raise HTTPException(404, "Project not found")
    return {"deleted": pid}


@app.post("/api/projects/{pid}/upload")
async def upload(pid: str, file: UploadFile = File(...)):
    p = store.get(pid)
    if not p:
        raise HTTPException(404, "Project not found")
    if not (file.filename or "").lower().endswith((".xlsx", ".xls")):
        raise HTTPException(400, "Please upload an .xlsx or .xls file.")
    data = await file.read()
    p.filename = file.filename
    p.report = None
    p.error = None
    # Kick off the pipeline as a background task (queued if one is already running).
    asyncio.create_task(project_socket.run_pipeline_task(pid, data, file.filename))
    return {"status": "accepted", "filename": file.filename}


@app.get("/api/projects/{pid}/download/cleaned")
def download_cleaned(pid: str):
    p = store.get(pid)
    if not p or not p.cleaned_xlsx:
        raise HTTPException(404, "No cleaned file available")
    return Response(
        content=p.cleaned_xlsx,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="cleaned_data.xlsx"'},
    )


@app.get("/api/projects/{pid}/download/report")
def download_report(pid: str):
    p = store.get(pid)
    if not p or not p.report_html:
        raise HTTPException(404, "No report available")
    return Response(
        content=p.report_html,
        media_type="text/html",
        headers={"Content-Disposition": 'attachment; filename="report.html"'},
    )


# --- websocket ---------------------------------------------------------------
@app.websocket("/ws/projects/{pid}")
async def ws_projects(websocket: WebSocket, pid: str):
    await project_socket.websocket_endpoint(websocket, pid)


# --- static frontend (production single-process mode) ------------------------
_DIST = os.path.join(os.path.dirname(_BACKEND_DIR), "frontend", "dist")
if os.path.isdir(_DIST):
    _assets = os.path.join(_DIST, "assets")
    if os.path.isdir(_assets):
        app.mount("/assets", StaticFiles(directory=_assets), name="assets")

    # SPA fallback: unknown non-API paths return the built index.html.
    @app.get("/{full_path:path}")
    def spa(full_path: str):
        candidate = os.path.join(_DIST, full_path)
        if full_path and os.path.isfile(candidate):
            return FileResponse(candidate)
        return FileResponse(os.path.join(_DIST, "index.html"))
else:
    @app.get("/")
    def dev_root():
        return JSONResponse(
            {"message": "Backend up. Frontend not built — run `npm run dev` in frontend/ "
                        "or `npm run build` for single-process mode."}
        )
