"""
WebSocket layer: one socket per project carrying pipeline progress + chat.

Server -> client events:
  {type:"status", stage, detail, round?, max_rounds?}
  {type:"message", message}          # a stored chat/status/system message
  {type:"report_ready", report}
  {type:"chat_token", token}
  {type:"chat_done"}
  {type:"error", detail}
  {type:"status_change", status}     # project lifecycle status

Client -> server events:
  {type:"chat", content}

Concurrency: only ONE pipeline runs at a time across all projects (CPU-only
machine). A second upload is marked "queued" and waits on the same lock.
"""

from __future__ import annotations

import asyncio
import io
import re
import time
import traceback

from fastapi import WebSocket, WebSocketDisconnect

import config
from agents import base, chat_agent, analysis_agent
from pipeline import orchestrator
from reporting import serialize, report_builder
from state.project_store import store
from utils import excel_io
from voice import speech

# One global lock => exactly one pipeline running at any moment.
_pipeline_lock = asyncio.Lock()
_ROUND_RE = re.compile(r"round\s+(\d+)\s*/\s*(\d+)", re.IGNORECASE)


def fmt_duration(secs: float) -> str:
    """Human-friendly duration, e.g. '47s' or '6m 32s'."""
    secs = max(0, round(secs))
    if secs < 60:
        return f"{secs}s"
    return f"{secs // 60}m {secs % 60:02d}s"


class ConnectionManager:
    def __init__(self):
        self._conns: dict[str, set[WebSocket]] = {}

    async def connect(self, pid: str, ws: WebSocket):
        await ws.accept()
        self._conns.setdefault(pid, set()).add(ws)

    def disconnect(self, pid: str, ws: WebSocket):
        conns = self._conns.get(pid)
        if conns:
            conns.discard(ws)
            if not conns:
                self._conns.pop(pid, None)

    async def broadcast(self, pid: str, event: dict):
        for ws in list(self._conns.get(pid, set())):
            try:
                await ws.send_json(event)
            except Exception:  # noqa: BLE001 - drop dead sockets silently
                self.disconnect(pid, ws)


manager = ConnectionManager()


# --- helpers to marshal worker-thread callbacks onto the event loop ----------
def _threadsafe(loop, coro):
    try:
        asyncio.run_coroutine_threadsafe(coro, loop)
    except RuntimeError:
        pass


async def _set_status(pid: str, status: str):
    p = store.get(pid)
    if p:
        p.status = status
    await manager.broadcast(pid, {"type": "status_change", "status": status})


async def _emit_status(pid, stage, detail, elapsed_s=None):
    """Store a status line as a message AND push a live status event.

    `elapsed_s` is cumulative time since the run started; the frontend derives
    each step's duration by diffing consecutive lines. Consistent live & on reload.
    """
    msg = store.add_message(pid, role="agent", content=detail, kind="status")
    if msg and elapsed_s is not None:
        msg["elapsed_s"] = round(elapsed_s, 1)

    event = {"type": "status", "stage": stage, "detail": detail}
    if elapsed_s is not None:
        event["elapsed_s"] = round(elapsed_s, 1)
    m = _ROUND_RE.search(detail)
    if m:
        event["round"] = int(m.group(1))
        event["max_rounds"] = int(m.group(2))
    await manager.broadcast(pid, event)
    if msg:
        await manager.broadcast(pid, {"type": "message", "message": msg})


# --- pipeline runner (queued, one at a time) ---------------------------------
async def run_pipeline_task(pid: str, file_bytes: bytes, filename: str):
    loop = asyncio.get_running_loop()

    # If a pipeline is already running, reflect "queued" until the lock frees.
    if _pipeline_lock.locked():
        await _set_status(pid, "queued")
        await _emit_status(pid, "queued", "Another analysis is running — queued, will start shortly…")

    async with _pipeline_lock:
        await _set_status(pid, "running")
        t0 = time.monotonic()
        try:
            df = await loop.run_in_executor(None, _load_df, file_bytes)
        except Exception as exc:  # noqa: BLE001
            await _fail(pid, f"Could not read the spreadsheet: {exc}")
            return

        def progress(stage: str, detail: str):
            _threadsafe(loop, _emit_status(pid, stage, detail, elapsed_s=time.monotonic() - t0))

        try:
            result = await loop.run_in_executor(None, orchestrator.run_pipeline, df, progress)
        except base.OllamaUnreachableError:
            await _fail(pid, "Ollama is unreachable. Start it (`ollama serve`) and re-upload.")
            return
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            await _fail(pid, f"The pipeline hit an unexpected error: {exc}")
            return

        try:
            report = await loop.run_in_executor(None, serialize.serialize_report, result)
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            await _fail(pid, f"Failed to serialize the report: {exc}")
            return

        # Build downloadable artifacts (cleaned xlsx + standalone HTML report).
        try:
            p_tmp = store.get(pid)
            if p_tmp:
                p_tmp.cleaned_xlsx = await loop.run_in_executor(
                    None, excel_io.dataframe_to_xlsx_bytes, result.cleaned_df, "cleaned"
                )
                p_tmp.report_html = await loop.run_in_executor(
                    None, report_builder.build_html_report, result
                )
                p_tmp.cleaned_df = result.cleaned_df
        except Exception:  # noqa: BLE001 - downloads are best-effort
            traceback.print_exc()

        total = time.monotonic() - t0
        report["timing"] = {"total_seconds": round(total, 1), "label": fmt_duration(total)}

        p = store.get(pid)
        if not p:
            return
        p.report = report
        await _set_status(pid, "ready")
        await manager.broadcast(pid, {"type": "report_ready", "report": report})

        sys_msg = store.add_message(
            pid, role="system", kind="system",
            content=f"Analysis complete in {fmt_duration(total)} — ask me anything about it, or check the panel.",
        )
        if sys_msg:
            await manager.broadcast(pid, {"type": "message", "message": sys_msg})


def _load_df(file_bytes: bytes):
    return excel_io.load_sheet(io.BytesIO(file_bytes), sheet_name=None)


async def _fail(pid: str, detail: str):
    p = store.get(pid)
    if p:
        p.error = detail
    await _set_status(pid, "error")
    msg = store.add_message(pid, role="system", content=detail, kind="system")
    if msg:
        await manager.broadcast(pid, {"type": "message", "message": msg})
    await manager.broadcast(pid, {"type": "error", "detail": detail})


# --- chat --------------------------------------------------------------------
_chat_busy: set[str] = set()


async def handle_chat(pid: str, content: str, brief: bool = False) -> str:
    """Run one chat turn (routing to analysis or grounded report). Returns the
    final assistant text (used by the voice loop to synthesize speech)."""
    p = store.get(pid)
    if not p:
        return ""
    content = (content or "").strip()
    if not content:
        return ""
    if not p.report:
        warn = store.add_message(
            pid, role="system", kind="system",
            content="No analysis is ready yet — upload a spreadsheet first.",
        )
        if warn:
            await manager.broadcast(pid, {"type": "message", "message": warn})
        return ""
    if pid in _chat_busy:
        return ""
    _chat_busy.add(pid)
    final_text = ""

    # Store + echo the user's message.
    user_msg = store.add_message(pid, role="user", content=content, kind="chat")
    if user_msg:
        await manager.broadcast(pid, {"type": "message", "message": user_msg})

    loop = asyncio.get_running_loop()
    context = serialize.report_context_for_chat(p.report)
    history = [m for m in p.messages if m.get("kind") == "chat" and m.get("role") in ("user", "assistant")]
    df = p.cleaned_df

    async def chat_status(detail: str):
        await manager.broadcast(pid, {"type": "chat_status", "detail": detail})

    try:
        # --- Route: does this need a real computation on the data? ------------
        routed_compute = False
        if df is not None:
            await chat_status("Reading your question…")
            schema = await loop.run_in_executor(None, analysis_agent.build_schema, df)
            mode, code0 = await loop.run_in_executor(
                None, analysis_agent.decide, content, schema, context
            )

            if mode == "compute" and code0.strip():
                routed_compute = True
                await chat_status("Running the analysis on your data…")
                ok, result, error, code = await loop.run_in_executor(
                    None, analysis_agent.compute, df, content, schema, code0
                )
                if ok:
                    analysis = {"code": code, **analysis_agent.result_payload(result)}
                    await chat_status("Summarising the result…")
                    full = await loop.run_in_executor(
                        None, _run_summary_stream, pid, content, result, loop, brief
                    )
                    msg = store.add_message(pid, role="assistant", content=full, kind="chat", analysis=analysis)
                    final_text = full
                    await manager.broadcast(pid, {"type": "chat_done"})
                    if msg:
                        await manager.broadcast(pid, {"type": "message", "message": msg})
                else:
                    analysis = {"code": code, "table": None, "value": None, "error": error}
                    answer = (
                        "I tried to compute that from the data, but the query failed "
                        f"({error}). Try naming the exact column, or rephrasing the question."
                    )
                    msg = store.add_message(pid, role="assistant", content=answer, kind="chat", analysis=analysis)
                    final_text = answer
                    await manager.broadcast(pid, {"type": "chat_done"})
                    if msg:
                        await manager.broadcast(pid, {"type": "message", "message": msg})

        # --- Otherwise: grounded answer about the report ---------------------
        if not routed_compute:
            await chat_status("Thinking…")
            full = await loop.run_in_executor(None, _run_chat_stream, pid, context, history, loop, brief)
            assistant_msg = store.add_message(pid, role="assistant", content=full, kind="chat")
            final_text = full
            await manager.broadcast(pid, {"type": "chat_done"})
            if assistant_msg:
                await manager.broadcast(pid, {"type": "message", "message": assistant_msg})
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        await manager.broadcast(pid, {"type": "error", "detail": f"Chat failed: {exc}"})
    finally:
        _chat_busy.discard(pid)
    return final_text


def _run_chat_stream(pid: str, context: str, history: list[dict], loop, brief: bool = False) -> str:
    """Runs in a worker thread; pushes tokens back onto the loop."""
    parts: list[str] = []
    for token in chat_agent.stream_answer(context, history, brief=brief):
        parts.append(token)
        _threadsafe(loop, manager.broadcast(pid, {"type": "chat_token", "token": token}))
    return "".join(parts)


def _run_summary_stream(pid: str, question: str, result, loop, brief: bool = False) -> str:
    """Stream the plain-English summary of a computed result."""
    parts: list[str] = []
    for token in analysis_agent.stream_summary(question, result, brief=brief):
        parts.append(token)
        _threadsafe(loop, manager.broadcast(pid, {"type": "chat_token", "token": token}))
    return "".join(parts)


# --- voice -------------------------------------------------------------------
async def handle_voice(pid: str, audio_b64: str):
    """One spoken turn: transcribe -> chat (with analysis) -> speak the answer."""
    import base64

    p = store.get(pid)
    if not p or not p.report:
        return
    loop = asyncio.get_running_loop()

    async def vstate(state: str):
        await manager.broadcast(pid, {"type": "voice_state", "state": state})

    try:
        audio = base64.b64decode(audio_b64)
        await vstate("transcribing")
        text = await loop.run_in_executor(None, speech.transcribe, audio)
        if not text.strip():
            await vstate("idle")
            return
        await manager.broadcast(pid, {"type": "voice_transcript", "text": text})

        await vstate("thinking")
        answer = await handle_chat(pid, text, brief=True)
        if not answer.strip():
            await vstate("idle")
            return

        await vstate("speaking")
        wav = await loop.run_in_executor(None, speech.synthesize, answer)
        import uuid as _uuid

        await manager.broadcast(
            pid,
            {
                "type": "voice_audio",
                "audio": base64.b64encode(wav).decode(),
                "id": _uuid.uuid4().hex[:10],  # unique per reply, so the client never double-plays
            },
        )
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        await manager.broadcast(pid, {"type": "error", "detail": f"Voice failed: {exc}"})
    finally:
        await vstate("idle")


# --- websocket endpoint ------------------------------------------------------
async def websocket_endpoint(websocket: WebSocket, pid: str):
    if store.get(pid) is None:
        await websocket.close(code=4004)
        return
    await manager.connect(pid, websocket)
    try:
        while True:
            data = await websocket.receive_json()
            mtype = data.get("type")
            if mtype == "chat":
                await handle_chat(pid, data.get("content", ""))
            elif mtype == "voice":
                await handle_voice(pid, data.get("audio", ""))
    except WebSocketDisconnect:
        manager.disconnect(pid, websocket)
    except Exception:  # noqa: BLE001
        manager.disconnect(pid, websocket)
