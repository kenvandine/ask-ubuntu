#!/usr/bin/env python3
"""
Ask Ubuntu - FastAPI + WebSocket backend for the Electron GUI
"""

import asyncio
import base64
import json
import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from chat_engine import (
    ChatEngine,
    ensure_model_available,
    get_chat_models,
    create_client,
    unload_model,
)
from remote_providers import (
    get_configured_providers,
    get_provider_info,
    save_provider,
    delete_provider,
    PROVIDER_PRESETS,
)
from engine_orchestration import (
    resolve_local_models,
    pick_remote_fallback,
    switch_engine_model,
)
import i18n

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Module-level engine singleton; set during startup
engine: ChatEngine = None
_engine_ready: bool = False
_engine_error: str = ""

# Download progress state (broadcast to WebSocket clients)
_download_status: str = ""  # e.g. "downloading", "complete", ""
_download_model: str = ""  # model name being downloaded
_download_completed: int = 0
_download_total: int = 0
_ws_clients: set = set()  # connected WebSocket instances
_tts_model_candidates = tuple(
    dict.fromkeys(
        [
            os.environ.get("ASK_UBUNTU_TTS_MODEL", "kokorro-v1"),
            "kokorro-v1",
            "kokoro-v1",
        ]
    )
)
_openai_style_voices = {
    "alloy",
    "ash",
    "coral",
    "echo",
    "fable",
    "onyx",
    "nova",
    "sage",
    "shimmer",
}
_tts_voice = os.environ.get("ASK_UBUNTU_TTS_VOICE", "af_heart")
_tts_ready_models: set[str] = set()
_our_loaded_models: set[str] = set()  # models we loaded (to unload only ours)
_post_init_task: asyncio.Task | None = None
_boot_t0 = time.perf_counter()


def _boot_ms() -> int:
    return int((time.perf_counter() - _boot_t0) * 1000)


def _detect_audio_mime(audio_bytes: bytes) -> str:
    if len(audio_bytes) >= 3 and audio_bytes[:3] == b"ID3":
        return "audio/mpeg"
    if len(audio_bytes) >= 2 and audio_bytes[:2] == b"\xff\xfb":
        return "audio/mpeg"
    if (
        len(audio_bytes) >= 12
        and audio_bytes[:4] == b"RIFF"
        and audio_bytes[8:12] == b"WAVE"
    ):
        return "audio/wav"
    if len(audio_bytes) >= 4 and audio_bytes[:4] == b"OggS":
        return "audio/ogg"
    if len(audio_bytes) >= 4 and audio_bytes[:4] == b"fLaC":
        return "audio/flac"
    return "application/octet-stream"


def _extract_audio_bytes(audio_resp) -> bytes:
    """
    Handle both raw-binary responses and JSON/base64 payloads.
    """
    if hasattr(audio_resp, "read"):
        raw = audio_resp.read()
    elif hasattr(audio_resp, "content"):
        raw = audio_resp.content
    elif isinstance(audio_resp, (bytes, bytearray)):
        raw = bytes(audio_resp)
    else:
        raise RuntimeError("Unexpected TTS response type")

    if not raw:
        return b""

    # Some providers/proxies may return JSON with base64-encoded audio.
    if raw[:1] in (b"{", b"["):
        try:
            payload = json.loads(raw.decode("utf-8"))
            if isinstance(payload, dict):
                for key in ("audio", "data", "b64_json"):
                    val = payload.get(key)
                    if isinstance(val, str) and val:
                        try:
                            return base64.b64decode(val)
                        except Exception:
                            pass
        except Exception:
            pass

    return raw


def _synthesize_tts_bytes(
    text: str, model_hint: str = "", voice_hint: str = ""
) -> tuple[bytes, str, str]:
    """
    Generate speech audio via Lemonade's OpenAI-compatible audio API.
    Returns (audio_bytes, model_name_used, media_type).
    """
    client = create_client()
    candidates = []
    if model_hint:
        candidates.append(model_hint)
    candidates.extend(_tts_model_candidates)
    # Preserve order while de-duplicating.
    ordered = tuple(dict.fromkeys(candidates))
    last_err = None

    for model_name in ordered:
        if model_name not in _tts_ready_models:
            ok, _ = ensure_model_available(model_name)
            if not ok:
                continue
            _tts_ready_models.add(model_name)
        effective_voice = (voice_hint or _tts_voice).strip() or _tts_voice
        if "kokoro" in model_name.lower() and effective_voice in _openai_style_voices:
            # Migrate old OpenAI-style voice defaults for Kokoro models.
            effective_voice = "af_heart"

        voices_to_try = [effective_voice]
        if "kokoro" in model_name.lower() and effective_voice != "af_heart":
            voices_to_try.append("af_heart")

        for voice_name in voices_to_try:
            try:
                audio_resp = client.audio.speech.create(
                    model=model_name,
                    voice=voice_name,
                    input=text,
                    response_format="wav",
                )
                audio_bytes = _extract_audio_bytes(audio_resp)
                if not audio_bytes:
                    raise RuntimeError("Empty TTS audio output")
                _our_loaded_models.add(model_name)
                return audio_bytes, model_name, _detect_audio_mime(audio_bytes)
            except Exception as e:
                last_err = e
                continue

    raise RuntimeError(
        f"Unable to synthesize audio with available TTS models: {last_err}"
    )


def _unload_our_models() -> None:
    """Unload only the models that we loaded, leaving other apps' models alone."""
    for model_name in list(_our_loaded_models):
        unload_model(model_name)
    _our_loaded_models.clear()


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


def _cancel_post_init_task() -> None:
    global _post_init_task
    if _post_init_task and not _post_init_task.done():
        _post_init_task.cancel()
    _post_init_task = None


async def _finish_local_engine_setup(engine_ref: ChatEngine, embed_model: str) -> None:
    """Complete local embed model pull + RAG indexing after core startup."""
    global _download_status, _engine_error
    loop = asyncio.get_running_loop()
    try:
        logger.info(
            f"[boot] +{_boot_ms()}ms phase2.embed.pull.start model={embed_model}"
        )
        cb = _make_progress_callback(embed_model, loop)
        ok, msg = await asyncio.to_thread(ensure_model_available, embed_model, cb)
        _download_status = ""
        if not ok:
            logger.warning(f"Embedding model unavailable for background init: {msg}")
            if engine is engine_ref:
                engine_ref.use_rag = False
            return
        if engine is not engine_ref:
            return
        logger.info(f"[boot] +{_boot_ms()}ms phase2.rag.index.start")
        await asyncio.to_thread(engine_ref.load_rag_index)
        # Unload the embedding model now that the RAG index is built so it
        # doesn't compete with the chat model for GPU compute.
        await asyncio.to_thread(unload_model, embed_model)
        if engine_ref.use_rag and engine_ref.rag_indexer:
            logger.info(f"[boot] +{_boot_ms()}ms phase2.rag.ready embed={embed_model}")
    except asyncio.CancelledError:
        logger.info("Background local setup cancelled")
    except Exception as e:
        logger.error(f"Background local setup failed: {e}")
        if engine is engine_ref:
            _engine_error = str(e)


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
    global engine, _engine_ready, _engine_error, _download_status, _post_init_task
    loop = asyncio.get_running_loop()
    try:
        logger.info(f"[boot] +{_boot_ms()}ms init.start")
        requested_model = os.environ.get("ASK_UBUNTU_MODEL")
        selection = await asyncio.to_thread(resolve_local_models, requested_model, None)
        chat_model = selection.chat_model
        embed_model = selection.embed_model
        logger.info(
            f"[boot] +{_boot_ms()}ms models.resolved chat={chat_model} embed={embed_model} source={selection.source}"
        )

        # Phase 1: Ensure chat model + initialize core engine for fast readiness.
        try:
            logger.info(
                f"[boot] +{_boot_ms()}ms phase1.chat.pull.start model={chat_model}"
            )
            cb = _make_progress_callback(chat_model, loop)
            ok, msg = await asyncio.to_thread(ensure_model_available, chat_model, cb)
            if not ok:
                raise RuntimeError(msg)
            lemonade_ok = True
            logger.info(
                f"[boot] +{_boot_ms()}ms phase1.chat.pull.ready model={chat_model}"
            )
        except (ConnectionError, RuntimeError) as e:
            lemonade_error = str(e)
            lemonade_ok = False
            logger.warning(
                f"Lemonade unavailable: {lemonade_error}. Trying remote fallback."
            )

        if lemonade_ok:
            _download_status = ""
            engine = ChatEngine(
                model_name=chat_model,
                embed_model=embed_model,
                use_rag=True,
                debug=False,
            )
            logger.info(f"[boot] +{_boot_ms()}ms phase1.engine.init.start")
            await asyncio.to_thread(engine.initialize, True)
            _engine_ready = True
            _our_loaded_models.add(chat_model)
            _cancel_post_init_task()
            # Phase 2: Pull embed model + build RAG index in background.
            _post_init_task = asyncio.create_task(
                _finish_local_engine_setup(engine, embed_model)
            )
            logger.info(f"[boot] +{_boot_ms()}ms ready.core chat={chat_model}")
        else:
            # Try remote fallback
            p, fallback_model = await asyncio.to_thread(
                pick_remote_fallback, chat_model
            )
            if p:
                logger.info(
                    f"[boot] +{_boot_ms()}ms fallback.remote.start provider={p['id']} model={fallback_model}"
                )
                switched_engine, err = await asyncio.to_thread(
                    switch_engine_model,
                    None,
                    fallback_model,
                    p,
                )
                if err:
                    _engine_error = err
                    logger.error(f"Remote fallback failed: {err}")
                    return
                engine = switched_engine
                _engine_ready = True
                _cancel_post_init_task()
                logger.info(
                    f"[boot] +{_boot_ms()}ms ready.remote provider={p['id']} model={fallback_model}"
                )
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
    # Unload only the models we loaded on shutdown
    if _our_loaded_models:
        logger.info("Server shutting down, unloading our models")
        _unload_our_models()


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


@app.post("/unload-models")
async def unload_models_endpoint():
    """Unload only the models we loaded from lemonade to free memory."""
    if not _our_loaded_models:
        return {"ok": True}
    await asyncio.to_thread(_unload_our_models)
    logger.info("Models unloaded via /unload-models endpoint")
    return {"ok": True}


@app.get("/system-info")
async def system_info():
    if not _engine_ready:
        return {"fields": []}
    fields = await asyncio.to_thread(engine.get_neofetch_fields)
    return {"fields": fields}


@app.post("/tts")
async def text_to_speech(body: dict):
    """
    Synthesize assistant text to spoken audio.
    Uses kokorro-v1 by default (with kokoro-v1 fallback).
    """
    text = (body.get("text") or "").strip()
    model_hint = (body.get("model") or "").strip()
    voice_hint = (body.get("voice") or "").strip()
    if not text:
        return JSONResponse(status_code=400, content={"error": "text required"})

    # Keep payload bounded for latency and backend limits.
    if len(text) > 8000:
        text = text[:8000]

    try:
        audio_bytes, model_used, media_type = await asyncio.to_thread(
            _synthesize_tts_bytes, text, model_hint, voice_hint
        )
        logger.info(
            "TTS generated: model=%s voice=%s bytes=%d mime=%s",
            model_used,
            voice_hint or _tts_voice,
            len(audio_bytes),
            media_type,
        )
        return Response(
            content=audio_bytes,
            media_type=media_type,
            headers={
                "X-TTS-Model": model_used,
                "X-TTS-Voice": voice_hint or _tts_voice,
            },
        )
    except Exception as e:
        logger.error(f"TTS generation failed: {e}")
        return JSONResponse(status_code=502, content={"error": str(e)})


async def _change_model(new_model: str, provider_id: str = None) -> tuple:
    """
    Pull the model if needed then reinitialize the engine.
    When provider_id is set, switches to a remote provider (no Lemonade pull needed).
    Returns (success: bool, message: str).
    Broadcasts download_progress via WebSocket during pull.
    """
    global engine, _engine_ready, _engine_error, _download_status, _post_init_task

    _engine_ready = False
    loop = asyncio.get_running_loop()
    _cancel_post_init_task()

    try:
        if provider_id:
            # Remote provider — no need to pull from Lemonade
            provider = await asyncio.to_thread(get_provider_info, provider_id)
            if not provider:
                msg = f"Remote provider '{provider_id}' not configured"
                _engine_error = msg
                _engine_ready = bool(engine)
                return False, msg

            new_engine, err = await asyncio.to_thread(
                switch_engine_model,
                engine,
                new_model,
                provider,
            )
            if err:
                _engine_error = err
                _engine_ready = bool(engine)
                return False, err
            # Switching to remote — unload our local models
            await asyncio.to_thread(_unload_our_models)
            engine = new_engine
            _engine_ready = True
            _engine_error = ""
            logger.info(f"Switched to remote model: {provider_id}/{new_model}")
            return True, new_model
        else:
            # Local Lemonade model — unload old model before loading new one
            old_models = set(_our_loaded_models)
            cb = _make_progress_callback(new_model, loop)
            new_engine, err = await asyncio.to_thread(
                switch_engine_model,
                engine,
                new_model,
                None,
                cb,
                True,
            )
            if err:
                _engine_error = err
                logger.error(f"Model unavailable: {err}")
                return False, err

            # Unload the previous chat model (embed model may stay if unchanged)
            for m in old_models:
                if m != new_model and m != new_engine.embed_model:
                    unload_model(m)
                    _our_loaded_models.discard(m)

            _download_status = ""
            engine = new_engine
            _engine_ready = True
            _engine_error = ""
            _our_loaded_models.add(new_model)
            _post_init_task = asyncio.create_task(
                _finish_local_engine_setup(engine, engine.embed_model)
            )
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
                await ws.send_json(
                    {"type": "error", "message": i18n.t("server.invalid_json")}
                )
                continue

            if not _engine_ready:
                # Allow change_model even when engine is not ready (e.g. after a failed init)
                if data.get("type") != "change_model":
                    await ws.send_json(
                        {
                            "type": "error",
                            "message": _engine_error or i18n.t("server.not_ready"),
                        }
                    )
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
                        tts_buf = ""

                        def _extract_sentences(buf: str):
                            out = []
                            cur = ""
                            for ch in buf:
                                cur += ch
                                if ch in ".!?\n":
                                    seg = cur.strip()
                                    if seg:
                                        out.append(seg)
                                    cur = ""
                            return out, cur

                        try:
                            loop = asyncio.get_running_loop()

                            def _thread_delta(delta_text: str):
                                nonlocal tts_buf
                                try:
                                    asyncio.run_coroutine_threadsafe(
                                        ws.send_json(
                                            {
                                                "type": "response_delta",
                                                "text": delta_text,
                                            }
                                        ),
                                        loop,
                                    )
                                    tts_buf += delta_text
                                    segs, rest = _extract_sentences(tts_buf)
                                    tts_buf = rest
                                    for seg in segs:
                                        if len(seg) < 3:
                                            continue
                                        asyncio.run_coroutine_threadsafe(
                                            ws.send_json(
                                                {"type": "tts_text", "text": seg}
                                            ),
                                            loop,
                                        )
                                except Exception:
                                    pass

                            result = await asyncio.to_thread(
                                engine.chat, msg, _thread_delta
                            )
                            logger.info(
                                f"Chat done, tool_calls={len(result['tool_calls'])}, "
                                f"response_len={len(result['response'])}, "
                                f"aborted={result.get('aborted')}"
                            )
                            if result.get("aborted"):
                                return
                            # Flush any trailing text that didn't end in sentence punctuation.
                            tail = tts_buf.strip()
                            if tail:
                                await ws.send_json({"type": "tts_text", "text": tail})
                            if result["tool_calls"]:
                                await ws.send_json(
                                    {
                                        "type": "tool_calls",
                                        "calls": result["tool_calls"],
                                    }
                                )
                            await ws.send_json(
                                {
                                    "type": "response",
                                    "text": result["response"],
                                }
                            )
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
                        await ws.send_json(
                            {
                                "type": "error",
                                "message": i18n.t("server.no_model_specified"),
                            }
                        )
                        continue

                    await ws.send_json({"type": "model_changing", "model": new_model})
                    ok, result_msg = await _change_model(
                        new_model, provider_id=provider_id
                    )
                    if ok:
                        await ws.send_json(
                            {"type": "model_changed", "model": new_model}
                        )
                    else:
                        await ws.send_json({"type": "error", "message": result_msg})

                else:
                    await ws.send_json(
                        {
                            "type": "error",
                            "message": i18n.t("server.unknown_type", type=msg_type),
                        }
                    )

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
