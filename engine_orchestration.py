"""
Shared engine orchestration helpers for CLI and Electron backend.
"""

from dataclasses import dataclass
from typing import Callable, Optional

from chat_engine import (
    ChatEngine,
    DEFAULT_MODEL_NAME,
    DEFAULT_EMBED_MODEL,
    LLM_TIER_MAP,
    EMBED_TIER_MAP,
    ensure_model_available,
    detect_npu_flm_model,
    load_last_model,
    save_last_model,
)
from remote_providers import get_configured_providers
from remote_providers import get_provider_info, PROVIDER_PRESETS
from system_indexer import SystemIndexer


@dataclass
class LocalModelSelection:
    chat_model: str
    embed_model: str
    source: str  # requested | saved | npu_flm | tier


@dataclass
class ProviderStartupSelection:
    provider_id: str
    provider_name: str
    base_url: str
    api_key: str
    model_id: str


def resolve_local_models(
    requested_model: Optional[str] = None,
    requested_embed_model: Optional[str] = None,
) -> LocalModelSelection:
    """Resolve startup local models: requested -> saved -> NPU+FLM -> tier."""
    if requested_model:
        return LocalModelSelection(
            chat_model=requested_model,
            embed_model=requested_embed_model or DEFAULT_EMBED_MODEL,
            source="requested",
        )

    saved_model = load_last_model()
    if saved_model:
        return LocalModelSelection(
            chat_model=saved_model,
            embed_model=requested_embed_model or DEFAULT_EMBED_MODEL,
            source="saved",
        )

    npu_flm = detect_npu_flm_model()
    if npu_flm:
        return LocalModelSelection(
            chat_model=npu_flm,
            embed_model=requested_embed_model or DEFAULT_EMBED_MODEL,
            source="npu_flm",
        )

    tier = SystemIndexer().get_hardware_tier()
    return LocalModelSelection(
        chat_model=LLM_TIER_MAP.get(tier, DEFAULT_MODEL_NAME),
        embed_model=requested_embed_model or EMBED_TIER_MAP.get(tier, DEFAULT_EMBED_MODEL),
        source="tier",
    )


def resolve_explicit_provider_startup(
    provider_id: str,
    model_override: Optional[str] = None,
    api_key_override: Optional[str] = None,
) -> tuple[Optional[ProviderStartupSelection], Optional[dict]]:
    """
    Resolve explicit --provider startup selection.
    Returns (selection, error) where error is a structured dict.
    """
    provider = get_provider_info(provider_id)

    if provider is None and provider_id not in PROVIDER_PRESETS:
        return None, {"code": "unknown_provider", "known": ", ".join(PROVIDER_PRESETS.keys())}

    if provider is None:
        preset = PROVIDER_PRESETS[provider_id]
        api_key = api_key_override or ""
        if not api_key:
            return None, {"code": "no_api_key", "env_var": preset["env_var"]}
        base_url = preset["base_url"]
        provider_name = preset["name"]
        models = preset["models"]
    else:
        api_key = api_key_override or provider["api_key"]
        base_url = provider["base_url"]
        provider_name = provider["name"]
        models = provider.get("models", [])

    if model_override:
        model_id = model_override
    elif models:
        model_id = models[0]["id"]
    else:
        return None, {"code": "no_models"}

    return ProviderStartupSelection(
        provider_id=provider_id,
        provider_name=provider_name,
        base_url=base_url,
        api_key=api_key,
        model_id=model_id,
    ), None


def pick_remote_fallback(preferred_model: str) -> tuple[Optional[dict], Optional[str]]:
    """Return the first configured provider and its fallback model, if available."""
    providers = get_configured_providers()
    if not providers:
        return None, None
    provider = providers[0]
    fallback_model = provider["models"][0]["id"] if provider.get("models") else preferred_model
    return provider, fallback_model


def ensure_local_models_available(
    chat_model: str,
    embed_model: str,
    progress_callback_factory: Optional[Callable[[str], Optional[Callable[[str, int, int], None]]]] = None,
) -> tuple[bool, str]:
    """Ensure chat + embedding models are available through Lemonade."""
    cb = progress_callback_factory(chat_model) if progress_callback_factory else None
    ok, msg = ensure_model_available(chat_model, progress_callback=cb)
    if not ok:
        return False, msg

    cb = progress_callback_factory(embed_model) if progress_callback_factory else None
    ok, msg = ensure_model_available(embed_model, progress_callback=cb)
    if not ok:
        return False, msg

    return True, ""


def switch_engine_model(
    current_engine: Optional[ChatEngine],
    new_model: str,
    provider: Optional[dict] = None,
    progress_callback: Optional[Callable[[str, int, int], None]] = None,
    defer_rag: bool = False,
) -> tuple[Optional[ChatEngine], Optional[str]]:
    """
    Build and initialize a new ChatEngine for model switch.
    Returns (engine, error_message).
    """
    debug = current_engine.debug if current_engine else False

    if provider:
        new_engine = ChatEngine(
            model_name=new_model,
            use_rag=False,
            debug=debug,
            provider_base_url=provider["base_url"],
            provider_api_key=provider["api_key"],
        )
        try:
            new_engine.initialize(defer_rag=defer_rag)
            return new_engine, None
        except Exception as e:
            return None, str(e)

    ok, msg = ensure_model_available(new_model, progress_callback=progress_callback)
    if not ok:
        return None, msg

    embed_model = current_engine.embed_model if current_engine else DEFAULT_EMBED_MODEL
    use_rag = (current_engine.use_rag if current_engine and not current_engine.is_remote else True)
    new_engine = ChatEngine(
        model_name=new_model,
        embed_model=embed_model,
        use_rag=use_rag,
        debug=debug,
    )
    try:
        new_engine.initialize(defer_rag=defer_rag)
        save_last_model(new_model)
        return new_engine, None
    except Exception as e:
        return None, str(e)
