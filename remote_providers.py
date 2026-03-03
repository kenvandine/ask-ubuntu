#!/usr/bin/env python3
"""
Remote provider configuration for Ask Ubuntu.
Supports OpenAI-compatible providers: Anthropic, OpenAI, Gemini, and custom.
"""

import json
import os
from pathlib import Path
from typing import Optional

PROVIDER_PRESETS = {
    "anthropic": {
        "name": "Anthropic",
        "base_url": "https://api.anthropic.com/v1",
        "env_var": "ANTHROPIC_API_KEY",
        "models": [
            {"id": "claude-opus-4-6", "name": "Claude Opus 4.6"},
            {"id": "claude-sonnet-4-6", "name": "Claude Sonnet 4.6"},
            {"id": "claude-haiku-4-5-20251001", "name": "Claude Haiku 4.5"},
        ],
    },
    "openai": {
        "name": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "env_var": "OPENAI_API_KEY",
        "models": [
            {"id": "gpt-4o", "name": "GPT-4o"},
            {"id": "gpt-4o-mini", "name": "GPT-4o Mini"},
            {"id": "o3-mini", "name": "o3-mini"},
        ],
    },
    "gemini": {
        "name": "Google Gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "env_var": "GEMINI_API_KEY",
        "models": [
            {"id": "gemini-2.0-flash", "name": "Gemini 2.0 Flash"},
            {"id": "gemini-2.5-pro-preview-03-25", "name": "Gemini 2.5 Pro"},
            {"id": "gemini-1.5-pro", "name": "Gemini 1.5 Pro"},
        ],
    },
}


def _config_path() -> Path:
    """Return the snap-aware config path for remote_providers.json."""
    snap_user_data = os.environ.get("SNAP_USER_DATA")
    if snap_user_data:
        config_dir = Path(snap_user_data) / "config"
    else:
        config_dir = Path.home() / ".config" / "ask-ubuntu"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "remote_providers.json"


def load_remote_config() -> dict:
    """Load the remote providers config file. Returns empty config on error."""
    path = _config_path()
    if not path.exists():
        return {"providers": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"providers": []}


def save_remote_config(config: dict) -> None:
    """Save the remote providers config to disk."""
    path = _config_path()
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")


def get_configured_providers() -> list:
    """
    Return providers that have a resolvable API key (env var or config file).
    Each entry: {id, name, base_url, api_key, models: [{id, name}]}
    """
    config = load_remote_config()
    config_by_id = {p["id"]: p for p in config.get("providers", [])}

    result = []

    # Check preset providers (env vars first, then config file)
    for provider_id, preset in PROVIDER_PRESETS.items():
        env_key = os.environ.get(preset["env_var"], "").strip()
        stored = config_by_id.get(provider_id, {})
        stored_key = stored.get("api_key", "").strip()

        api_key = env_key or stored_key
        if not api_key:
            continue

        result.append({
            "id": provider_id,
            "name": preset["name"],
            "base_url": preset["base_url"],
            "api_key": api_key,
            "models": preset["models"],
            "from_env": bool(env_key),
        })

    # Custom providers (only from config file, not presets)
    for p in config.get("providers", []):
        pid = p.get("id", "")
        if pid in PROVIDER_PRESETS:
            continue  # already handled above
        api_key = p.get("api_key", "").strip()
        if not api_key:
            continue
        result.append({
            "id": pid,
            "name": p.get("name", pid),
            "base_url": p.get("base_url", ""),
            "api_key": api_key,
            "models": p.get("models", []),
            "from_env": False,
        })

    return result


def get_provider_info(provider_id: str) -> Optional[dict]:
    """Return info for a single configured provider, or None if not configured."""
    for p in get_configured_providers():
        if p["id"] == provider_id:
            return p
    return None


def save_provider(
    provider_id: str,
    api_key: str,
    base_url: str = None,
    name: str = None,
    models: list = None,
) -> None:
    """Save or update a provider in the config file."""
    config = load_remote_config()
    providers = config.get("providers", [])

    # Find existing entry or create new one
    for p in providers:
        if p["id"] == provider_id:
            p["api_key"] = api_key
            if base_url is not None:
                p["base_url"] = base_url
            if name is not None:
                p["name"] = name
            if models is not None:
                p["models"] = models
            break
    else:
        entry: dict = {"id": provider_id, "api_key": api_key}
        if base_url is not None:
            entry["base_url"] = base_url
        if name is not None:
            entry["name"] = name
        if models is not None:
            entry["models"] = models
        providers.append(entry)

    config["providers"] = providers
    save_remote_config(config)


def delete_provider(provider_id: str) -> None:
    """Remove a provider from the config file."""
    config = load_remote_config()
    config["providers"] = [
        p for p in config.get("providers", []) if p.get("id") != provider_id
    ]
    save_remote_config(config)


def discover_provider_models(provider: dict) -> list:
    """
    Try to fetch the model list from a provider's OpenAI-compatible /models endpoint.
    Returns a list of {id, name} dicts, or [] on any failure.
    """
    try:
        from openai import OpenAI
        client = OpenAI(
            base_url=provider.get("base_url"),
            api_key=provider.get("api_key") or "none",
        )
        page = client.models.list()
        return [{"id": m.id, "name": m.id} for m in page.data]
    except Exception:
        return []
