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


async def _init_engine():
    """Initialize the chat engine in a background thread."""
    global engine, _engine_ready, _engine_error
    try:
        # Ensure models are available (blocking HTTP calls)
        ok, msg = await asyncio.to_thread(ensure_model_available, DEFAULT_MODEL_NAME)
        if not ok:
            _engine_error = msg
            logger.error(f"Chat model unavailable: {msg}")
            return

        ok, msg = await asyncio.to_thread(ensure_model_available, DEFAULT_EMBED_MODEL)
        if not ok:
            _engine_error = msg
            logger.error(f"Embed model unavailable: {msg}")
            return

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
    return {
        "status": "ok",
        "ready": _engine_ready,
        "error": _engine_error if _engine_error else None,
    }


@app.get("/system-info")
async def system_info():
    if not _engine_ready:
        return {"summary": "Engine not ready yet."}
    return {"summary": engine.get_system_info()}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    try:
        while True:
            raw = await ws.receive_text()
            data = json.loads(raw)

            if not _engine_ready:
                await ws.send_json({
                    "type": "error",
                    "message": _engine_error or "Engine not ready yet. Please wait.",
                })
                continue

            msg_type = data.get("type")

            if msg_type == "clear":
                engine.clear()
                await ws.send_json({"type": "cleared"})

            elif msg_type == "chat":
                message = data.get("message", "").strip()
                if not message:
                    continue

                try:
                    result = await asyncio.to_thread(engine.chat, message)

                    if result["tool_calls"]:
                        await ws.send_json({
                            "type": "tool_calls",
                            "calls": result["tool_calls"],
                        })

                    await ws.send_json({
                        "type": "response",
                        "text": result["response"],
                    })

                except Exception as e:
                    await ws.send_json({
                        "type": "error",
                        "message": str(e),
                    })
            else:
                await ws.send_json({
                    "type": "error",
                    "message": f"Unknown message type: {msg_type}",
                })

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"WebSocket error: {e}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8765)
