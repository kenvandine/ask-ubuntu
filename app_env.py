"""
Shared environment/path helpers for Ask Ubuntu.
"""

import os
from pathlib import Path
from typing import Mapping, Optional

APP_SNAP_NAME_PREFIX = "ask-ubuntu"
APP_DIRNAME = "ask-ubuntu"


def in_ask_ubuntu_snap(env: Optional[Mapping[str, str]] = None) -> bool:
    """Return True only when running inside the Ask Ubuntu snap."""
    e = env or os.environ
    snap = e.get("SNAP", "")
    snap_name = e.get("SNAP_NAME", "")
    return bool(
        snap
        and (
            snap_name.startswith(APP_SNAP_NAME_PREFIX)
            or f"/{APP_SNAP_NAME_PREFIX}/" in snap
        )
    )


def snap_root(env: Optional[Mapping[str, str]] = None) -> Optional[Path]:
    """Return snap root path when in Ask Ubuntu snap, else None."""
    e = env or os.environ
    if not in_ask_ubuntu_snap(e):
        return None
    snap = e.get("SNAP")
    return Path(snap) if snap else None


def snap_user_common(env: Optional[Mapping[str, str]] = None) -> Optional[Path]:
    """Return SNAP_USER_COMMON when in Ask Ubuntu snap, else None."""
    e = env or os.environ
    if not in_ask_ubuntu_snap(e):
        return None
    val = e.get("SNAP_USER_COMMON")
    return Path(val) if val else None


def snap_user_data(env: Optional[Mapping[str, str]] = None) -> Optional[Path]:
    """Return SNAP_USER_DATA when in Ask Ubuntu snap, else None."""
    e = env or os.environ
    if not in_ask_ubuntu_snap(e):
        return None
    val = e.get("SNAP_USER_DATA")
    return Path(val) if val else None


def app_cache_dir(env: Optional[Mapping[str, str]] = None) -> Path:
    """Return Ask Ubuntu cache dir (snap-aware), creating it if needed."""
    base = snap_user_common(env)
    d = (base / "cache") if base else (Path.home() / ".cache" / APP_DIRNAME)
    d.mkdir(parents=True, exist_ok=True)
    return d


def app_config_dir(env: Optional[Mapping[str, str]] = None) -> Path:
    """Return Ask Ubuntu config dir (snap-aware), creating it if needed."""
    base = snap_user_data(env)
    d = (base / "config") if base else (Path.home() / ".config" / APP_DIRNAME)
    d.mkdir(parents=True, exist_ok=True)
    return d
