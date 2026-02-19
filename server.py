#!/usr/bin/env python3
"""
Ask Ubuntu - FastAPI + WebSocket backend for the Electron GUI
"""

import asyncio
import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from chat_engine import (
    ChatEngine,
    DEFAULT_MODEL_NAME,
    DEFAULT_EMBED_MODEL,
    ensure_model_available,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Module-level engine singleton; set during startup
engine: ChatEngine = None
_engine_ready: bool = False
_engine_error: str = ""

# Download progress state (broadcast to WebSocket clients)
_download_status: str = ""       # e.g. "downloading", "complete", ""
_download_model: str = ""        # model name being downloaded
_download_completed: int = 0
_download_total: int = 0
_ws_clients: set = set()         # connected WebSocket instances


async def _broadcast_download_progress():
    """Send current download progress to all connected WebSocket clients."""
    msg = {
        "type": "download_progress",
        "model": _download_model,
        "status": _download_status,
        "completed": _download_completed,
        "total": _download_total,
    }
    for client in list(_ws_clients):
        try:
            await client.send_json(msg)
        except Exception:
            pass


def _make_progress_callback(model_name: str, loop: asyncio.AbstractEventLoop):
    """Return a sync callback that updates global state and schedules WS broadcasts."""
    def _on_progress(status: str, completed: int, total: int):
        global _download_status, _download_model, _download_completed, _download_total
        _download_status = status
        _download_model = model_name
        _download_completed = completed
        _download_total = total
        asyncio.run_coroutine_threadsafe(_broadcast_download_progress(), loop)
    return _on_progress


async def _init_engine():
    """Initialize the chat engine in a background thread."""
    global engine, _engine_ready, _engine_error, _download_status
    loop = asyncio.get_running_loop()
    try:
        # Ensure models are available (blocking HTTP calls, with progress)
        cb = _make_progress_callback(DEFAULT_MODEL_NAME, loop)
        ok, msg = await asyncio.to_thread(ensure_model_available, DEFAULT_MODEL_NAME, cb)
        if not ok:
            _engine_error = msg
            logger.error(f"Chat model unavailable: {msg}")
            return

        cb = _make_progress_callback(DEFAULT_EMBED_MODEL, loop)
        ok, msg = await asyncio.to_thread(ensure_model_available, DEFAULT_EMBED_MODEL, cb)
        if not ok:
            _engine_error = msg
            logger.error(f"Embed model unavailable: {msg}")
            return

        _download_status = ""

        engine = ChatEngine(
            model_name=DEFAULT_MODEL_NAME,
            embed_model=DEFAULT_EMBED_MODEL,
            use_rag=True,
            debug=False,
        )
        await asyncio.to_thread(engine.initialize)
        _engine_ready = True
        logger.info("Chat engine initialized successfully")
    except Exception as e:
        _engine_error = str(e)
        logger.error(f"Engine initialization failed: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(_init_engine())
    yield


app = FastAPI(title="Ask Ubuntu Server", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    resp = {
        "status": "ok",
        "ready": _engine_ready,
        "error": _engine_error if _engine_error else None,
    }
    if _download_status and _download_status != "complete":
        resp["downloading"] = {
            "model": _download_model,
            "status": _download_status,
            "completed": _download_completed,
            "total": _download_total,
        }
    return resp


@app.get("/system-info")
async def system_info():
    if not _engine_ready:
        return {"fields": []}
    fields = await asyncio.to_thread(engine.get_neofetch_fields)
    return {"fields": fields}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    _ws_clients.add(ws)
    client = ws.client
    logger.info(f"WebSocket connected: {client}")
    try:
        while True:
            raw = await ws.receive_text()

            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await ws.send_json({"type": "error", "message": "Invalid JSON"})
                continue

            if not _engine_ready:
                await ws.send_json({
                    "type": "error",
                    "message": _engine_error or "Engine not ready yet. Please wait.",
                })
                continue

            msg_type = data.get("type")

            try:
                if msg_type == "clear":
                    engine.clear()
                    await ws.send_json({"type": "cleared"})

                elif msg_type == "chat":
                    message = data.get("message", "").strip()
                    if not message:
                        continue

                    logger.info(f"Chat request: {message[:80]!r}")
                    result = await asyncio.to_thread(engine.chat, message)
                    logger.info(f"Chat done, tool_calls={len(result['tool_calls'])}, "
                                f"response_len={len(result['response'])}")

                    if result["tool_calls"]:
                        await ws.send_json({
                            "type": "tool_calls",
                            "calls": result["tool_calls"],
                        })

                    await ws.send_json({
                        "type": "response",
                        "text": result["response"],
                    })

                else:
                    await ws.send_json({
                        "type": "error",
                        "message": f"Unknown message type: {msg_type}",
                    })

            except Exception as e:
                logger.error(f"Error handling message: {e}", exc_info=True)
                try:
                    await ws.send_json({"type": "error", "message": str(e)})
                except Exception:
                    pass

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {client}")
    except Exception as e:
        logger.error(f"WebSocket connection error: {e}", exc_info=True)
    finally:
        _ws_clients.discard(ws)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8765)
