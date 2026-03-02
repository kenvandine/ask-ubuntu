#!/usr/bin/env python3
"""
Ask Ubuntu - FastAPI + WebSocket backend for the Electron GUI
"""

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from chat_engine import (
    ChatEngine,
    DEFAULT_MODEL_NAME,
    DEFAULT_EMBED_MODEL,
    LLM_TIER_MAP,
    EMBED_TIER_MAP,
    ensure_model_available,
    detect_npu_flm_model,
    get_chat_models,
    save_last_model,
    load_last_model,
)
from remote_providers import (
    get_configured_providers,
    get_provider_info,
    save_provider,
    delete_provider,
    PROVIDER_PRESETS,
)
from system_indexer import SystemIndexer
import i18n

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
        # Determine models: env var override → last saved → NPU+FLM → tier
        requested_model = os.environ.get("ASK_UBUNTU_MODEL")
        if requested_model:
            chat_model = requested_model
            embed_model = DEFAULT_EMBED_MODEL
            logger.info(f"Using model from ASK_UBUNTU_MODEL env var: {chat_model}")
        else:
            saved_model = load_last_model()
            if saved_model:
                chat_model = saved_model
                embed_model = DEFAULT_EMBED_MODEL
                logger.info(f"Resuming last model: {chat_model}")
            else:
                npu_flm_model = await asyncio.to_thread(detect_npu_flm_model)
                if npu_flm_model:
                    chat_model = npu_flm_model
                    embed_model = DEFAULT_EMBED_MODEL
                    logger.info(f"NPU+FLM detected: using {chat_model}")
                else:
                    si = SystemIndexer()
                    tier = si.get_hardware_tier()
                    chat_model = LLM_TIER_MAP.get(tier, DEFAULT_MODEL_NAME)
                    embed_model = EMBED_TIER_MAP.get(tier, DEFAULT_EMBED_MODEL)
                    logger.info(f"Hardware tier '{tier}': chat={chat_model}, embed={embed_model}")

        # Ensure models are available (blocking HTTP calls, with progress)
        lemonade_ok = True
        try:
            cb = _make_progress_callback(chat_model, loop)
            ok, msg = await asyncio.to_thread(ensure_model_available, chat_model, cb)
            if not ok:
                raise RuntimeError(msg)

            cb = _make_progress_callback(embed_model, loop)
            ok, msg = await asyncio.to_thread(ensure_model_available, embed_model, cb)
            if not ok:
                raise RuntimeError(msg)
        except (ConnectionError, RuntimeError) as e:
            lemonade_ok = False
            lemonade_error = str(e)
            logger.warning(f"Lemonade unavailable: {lemonade_error}. Trying remote fallback.")

        if lemonade_ok:
            _download_status = ""
            engine = ChatEngine(
                model_name=chat_model,
                embed_model=embed_model,
                use_rag=True,
                debug=False,
            )
            await asyncio.to_thread(engine.initialize)
            _engine_ready = True
            logger.info(f"Chat engine initialized with model: {chat_model}")
        else:
            # Try remote fallback
            providers = await asyncio.to_thread(get_configured_providers)
            if providers:
                p = providers[0]
                fallback_model = p["models"][0]["id"] if p.get("models") else chat_model
                logger.info(f"Falling back to remote provider '{p['id']}', model '{fallback_model}'")
                engine = ChatEngine(
                    model_name=fallback_model,
                    use_rag=False,
                    provider_base_url=p["base_url"],
                    provider_api_key=p["api_key"],
                )
                await asyncio.to_thread(engine.initialize)
                _engine_ready = True
                logger.info(f"Remote fallback engine initialized: {p['id']}/{fallback_model}")
            else:
                _engine_error = lemonade_error
                logger.error(f"No remote fallback available: {lemonade_error}")
    except Exception as e:
        _engine_error = str(e)
        logger.error(f"Engine initialization failed: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    i18n.init()
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


@app.get("/models")
async def list_models():
    """Return prioritized chat models from lemonade plus the current active model."""
    current = engine.model_name if engine else None
    models = await asyncio.to_thread(get_chat_models, current)
    return {"models": models, "current_model": current}


@app.get("/remote-providers")
async def list_remote_providers():
    """Return configured remote providers and their available models."""
    providers = await asyncio.to_thread(get_configured_providers)
    return {"providers": providers, "presets": list(PROVIDER_PRESETS.keys())}


@app.post("/remote-providers")
async def save_remote_provider(body: dict):
    """Save or update a provider config (api_key, optional base_url/name)."""
    provider_id = body.get("id")
    api_key = body.get("api_key", "")
    base_url = body.get("base_url")
    name = body.get("name")
    if not provider_id:
        return JSONResponse(status_code=400, content={"error": "id required"})
    await asyncio.to_thread(save_provider, provider_id, api_key, base_url, name)
    return {"ok": True}


@app.delete("/remote-providers/{provider_id}")
async def delete_remote_provider(provider_id: str):
    """Remove a provider from config."""
    await asyncio.to_thread(delete_provider, provider_id)
    return {"ok": True}


@app.get("/remote-providers/{provider_id}/models")
async def discover_remote_provider_models(provider_id: str):
    """Discover models by querying the provider's OpenAI-compatible /models endpoint."""
    provider = await asyncio.to_thread(get_provider_info, provider_id)
    if not provider:
        return JSONResponse(status_code=404, content={"error": "Provider not found"})

    def _fetch():
        from chat_engine import create_client
        client = create_client(provider["base_url"], provider["api_key"])
        page = client.models.list()
        return [{"id": m.id, "name": m.id} for m in page.data]

    try:
        models = await asyncio.to_thread(_fetch)
        return {"models": models}
    except Exception as e:
        return JSONResponse(status_code=502, content={"error": str(e)})


@app.get("/system-info")
async def system_info():
    if not _engine_ready:
        return {"fields": []}
    fields = await asyncio.to_thread(engine.get_neofetch_fields)
    return {"fields": fields}


async def _change_model(new_model: str, provider_id: str = None) -> tuple:
    """
    Pull the model if needed then reinitialize the engine.
    When provider_id is set, switches to a remote provider (no Lemonade pull needed).
    Returns (success: bool, message: str).
    Broadcasts download_progress via WebSocket during pull.
    """
    global engine, _engine_ready, _engine_error, _download_status

    _engine_ready = False
    loop = asyncio.get_running_loop()

    try:
        if provider_id:
            # Remote provider — no need to pull from Lemonade
            provider = await asyncio.to_thread(get_provider_info, provider_id)
            if not provider:
                msg = f"Remote provider '{provider_id}' not configured"
                _engine_error = msg
                _engine_ready = bool(engine)
                return False, msg

            debug = engine.debug if engine else False
            new_engine = ChatEngine(
                model_name=new_model,
                use_rag=False,
                debug=debug,
                provider_base_url=provider["base_url"],
                provider_api_key=provider["api_key"],
            )
            await asyncio.to_thread(new_engine.initialize)
            engine = new_engine
            _engine_ready = True
            _engine_error = ""
            logger.info(f"Switched to remote model: {provider_id}/{new_model}")
            return True, new_model
        else:
            # Local Lemonade model
            cb = _make_progress_callback(new_model, loop)
            ok, msg = await asyncio.to_thread(ensure_model_available, new_model, cb)
            if not ok:
                _engine_error = msg
                logger.error(f"Model unavailable: {msg}")
                return False, msg

            _download_status = ""

            # Preserve current embed model and settings
            embed_model = engine.embed_model if engine else DEFAULT_EMBED_MODEL
            use_rag = (engine.use_rag if engine and not engine.is_remote else True)
            debug = engine.debug if engine else False

            new_engine = ChatEngine(
                model_name=new_model,
                embed_model=embed_model,
                use_rag=use_rag,
                debug=debug,
            )
            await asyncio.to_thread(new_engine.initialize)
            engine = new_engine
            _engine_ready = True
            _engine_error = ""
            save_last_model(new_model)
            logger.info(f"Model changed to: {new_model}")
            return True, new_model

    except Exception as e:
        _engine_error = str(e)
        _engine_ready = bool(engine)  # restore ready if old engine still exists
        logger.error(f"Model change failed: {e}")
        return False, str(e)


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    _ws_clients.add(ws)
    client = ws.client
    logger.info(f"WebSocket connected: {client}")
    _chat_task = None
    try:
        while True:
            raw = await ws.receive_text()

            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await ws.send_json({"type": "error", "message": i18n.t('server.invalid_json')})
                continue

            if not _engine_ready:
                # Allow change_model even when engine is not ready (e.g. after a failed init)
                if data.get("type") != "change_model":
                    await ws.send_json({
                        "type": "error",
                        "message": _engine_error or i18n.t('server.not_ready'),
                    })
                    continue

            msg_type = data.get("type")

            try:
                if msg_type == "clear":
                    engine.clear()
                    await ws.send_json({"type": "cleared"})

                elif msg_type == "rewind":
                    engine.rewind(data.get("index", 0))
                    # No broadcast needed — the GUI already rewound its own DOM

                elif msg_type == "abort":
                    engine.abort()
                    await ws.send_json({"type": "aborted"})

                elif msg_type == "chat":
                    message = data.get("message", "").strip()
                    if not message:
                        continue

                    logger.info(f"Chat request: {message[:80]!r}")

                    async def _run_chat(msg=message):
                        try:
                            result = await asyncio.to_thread(engine.chat, msg)
                            logger.info(f"Chat done, tool_calls={len(result['tool_calls'])}, "
                                        f"response_len={len(result['response'])}, "
                                        f"aborted={result.get('aborted')}")
                            if result.get("aborted"):
                                return
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
                            logger.error(f"Error in chat task: {e}", exc_info=True)
                            try:
                                await ws.send_json({"type": "error", "message": str(e)})
                            except Exception:
                                pass

                    _chat_task = asyncio.create_task(_run_chat())

                elif msg_type == "change_model":
                    new_model = data.get("model", "").strip()
                    provider_id = data.get("provider")
                    if not new_model:
                        await ws.send_json({"type": "error", "message": "No model specified"})
                        continue

                    await ws.send_json({"type": "model_changing", "model": new_model})
                    ok, result_msg = await _change_model(new_model, provider_id=provider_id)
                    if ok:
                        await ws.send_json({"type": "model_changed", "model": new_model})
                    else:
                        await ws.send_json({"type": "error", "message": result_msg})

                else:
                    await ws.send_json({
                        "type": "error",
                        "message": i18n.t('server.unknown_type', type=msg_type),
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
