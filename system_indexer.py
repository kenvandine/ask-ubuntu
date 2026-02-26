#!/usr/bin/env python3
"""
System Indexer - Collects system information for context-aware assistance

Snap-confinement notes
─────────────────────
• snap / snapd queries  → snapd REST API via Unix socket /run/snapd.socket
                          (desktop-launch interface: /v2/snaps, /v2/snaps/{name})
• snap store queries    → api.snapcraft.io REST API (network interface)
• apt / dpkg queries    → read /var/lib/dpkg/status and /var/lib/apt/lists
                          The system-files interface only adds AppArmor rules;
                          it sets up NO bind mounts.  Inside a strict snap the
                          /var/lib/ tree comes from the (empty) core24 squashfs,
                          so /var/lib/dpkg etc. are invisible.
                          Fix: point system-files at the hostfs paths and use
                          /var/lib/snapd/hostfs/var/lib/... in code when $SNAP
                          is set — hostfs is always a visible bind mount of the
                          real host root inside every snap.
• OS version            → read /var/lib/snapd/hostfs/etc/os-release (snap) or /etc/os-release
• GPU info              → lspci staged in snap (hardware-observe interface)
• Service detection     → scan /proc/*/comm (system-observe interface)
• Disk info             → os.statvfs() – no external command needed
"""

import http.client
import json
import os
import platform
import socket as _socket
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import requests as _requests
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

console = Console()


# ── Snap-aware paths ───────────────────────────────────────────────────────────

def _snap_cache_dir() -> Path:
    """Return snap-aware cache directory ($SNAP_USER_COMMON/cache or ~/.cache/ask-ubuntu)."""
    snap_common = os.environ.get("SNAP_USER_COMMON")
    if snap_common:
        d = Path(snap_common) / "cache"
    else:
        d = Path.home() / ".cache" / "ask-ubuntu"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── snapd REST API helpers ─────────────────────────────────────────────────────

# desktop-launch interface exposes /run/snapd-snap.socket (limited API).
# snapd-control uses /run/snapd.socket (full API, not auto-connectable).
_SNAPD_SOCKET = (
    "/run/snapd-snap.socket"
    if os.environ.get("SNAP")
    else "/run/snapd.socket"
)


def _snapd_get(path: str) -> Optional[dict]:
    """
    Make a GET request to the snapd REST API via Unix socket.
    Requires the snapd-control snap interface to be connected.
    """
    class _UnixHTTPConnection(http.client.HTTPConnection):
        def __init__(self, socket_path: str) -> None:
            super().__init__("localhost")
            self._socket_path = socket_path

        def connect(self) -> None:
            self.sock = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
            self.sock.connect(self._socket_path)

    try:
        conn = _UnixHTTPConnection(_SNAPD_SOCKET)
        conn.request("GET", path, headers={"Host": "localhost"})
        response = conn.getresponse()
        data = json.loads(response.read().decode())
        conn.close()
        return data
    except Exception:
        return None


# ── dpkg / apt helpers ─────────────────────────────────────────────────────────
# Inside a strict snap, /var/lib/ comes from the core24 squashfs and is empty.
# system-files only adds AppArmor rules (no bind mounts), so /var/lib/dpkg etc.
# are invisible inside the snap.  The system-files plugs therefore point at the
# hostfs paths and we mirror that here: /var/lib/snapd/hostfs is always a
# bind-mount of the real host root visible inside every snap.
_HOSTFS = "/var/lib/snapd/hostfs" if os.environ.get("SNAP") else ""
_DPKG_STATUS = f"{_HOSTFS}/var/lib/dpkg/status"
_APT_LISTS_DIR = f"{_HOSTFS}/var/lib/apt/lists"


def _read_dpkg_installed() -> List[str]:
    """
    Parse /var/lib/dpkg/status and return names of installed packages.
    Requires system-files-dpkg interface (read /var/lib/dpkg).
    """
    installed: List[str] = []
    try:
        current: Dict[str, str] = {}
        with open(_DPKG_STATUS, "r", encoding="utf-8", errors="ignore") as f:
            for raw_line in f:
                line = raw_line.rstrip("\n")
                if not line:
                    # End of a stanza
                    if "installed" in current.get("Status", "") and current.get("Package"):
                        installed.append(current["Package"])
                    current = {}
                elif line[0] in (" ", "\t"):
                    pass  # continuation line – skip
                elif ":" in line:
                    key, _, value = line.partition(": ")
                    current[key] = value
        # Handle a trailing stanza with no final blank line
        if "installed" in current.get("Status", "") and current.get("Package"):
            installed.append(current["Package"])
    except (FileNotFoundError, PermissionError):
        pass
    return sorted(installed)


def _is_in_apt_lists(package_name: str) -> bool:
    """
    Check if a package exists in apt list files.
    Requires system-files-dpkg interface (read /var/lib/apt/lists).
    This is O(n) per list file so is only used for live tool-call lookups,
    not during bulk indexing.
    """
    needle = f"Package: {package_name}\n"
    try:
        for list_file in Path(_APT_LISTS_DIR).glob("*_Packages"):
            try:
                with open(list_file, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        if line == needle:
                            return True
            except (PermissionError, OSError):
                continue
    except (PermissionError, OSError):
        pass
    return False


# ── Snap Store REST API ────────────────────────────────────────────────────────

_SNAP_STORE_URL = "https://api.snapcraft.io/v2/snaps/info/{name}"

# Map platform.machine() → snap store architecture name
_ARCH_MAP = {
    "x86_64": "amd64",
    "aarch64": "arm64",
    "armv7l": "armhf",
    "i686": "i386",
    "s390x": "s390x",
    "ppc64le": "ppc64el",
    "riscv64": "riscv64",
}


def _snap_store_info(package_name: str) -> Optional[dict]:
    """
    Query the Snap Store REST API for snap information.
    Returns the parsed JSON response or None on failure.
    Requires the network interface.
    """
    arch = _ARCH_MAP.get(platform.machine(), "amd64")
    try:
        resp = _requests.get(
            _SNAP_STORE_URL.format(name=package_name),
            params={"architecture": arch},
            headers={
                "Snap-Device-Series": "16",
                "User-Agent": "ask-ubuntu/1.0",
            },
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


def _store_channel_version(store_info: dict, tracking_channel: str = "latest/stable") -> Optional[str]:
    """
    Extract the version for a given tracking channel from a store info response.
    tracking_channel is in the form "track/risk" e.g. "latest/stable".
    """
    parts = tracking_channel.split("/", 1)
    track = parts[0] if len(parts) >= 1 else "latest"
    risk  = parts[1] if len(parts) >= 2 else "stable"

    # Honour the snap's declared default-track if the caller used "latest"
    default_track = store_info.get("default-track") or "latest"
    if track == "latest":
        track = default_track

    for entry in store_info.get("channel-map", []):
        ch = entry.get("channel", {})
        if ch.get("track") == track and ch.get("risk") == risk:
            return entry.get("version") or None

    # Fallback: return the stable version from any track
    for entry in store_info.get("channel-map", []):
        if entry.get("channel", {}).get("risk") == "stable":
            return entry.get("version") or None

    return None


# ── PCI sysfs constants for GPU fallback ──────────────────────────────────────

_PCI_VENDORS = {
    "0x8086": "Intel",
    "0x10de": "NVIDIA",
    "0x1002": "AMD",
    "0x1a03": "ASPEED",
    "0x15ad": "VMware",
    "0x1234": "QEMU/Bochs",
}


class SystemIndexer:
    """Collects and caches system information"""

    def __init__(self, cache_dir: Path = None):
        self.cache_dir = cache_dir or _snap_cache_dir()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.cache_dir / "system_info.json"
        self.system_info: Dict = {}

    def load_or_collect(self, force_refresh: bool = False) -> Dict:
        """Load cached system info or collect new"""
        if not force_refresh and self.cache_file.exists():
            try:
                with open(self.cache_file, "r") as f:
                    self.system_info = json.load(f)
                    cached_time = datetime.fromisoformat(
                        self.system_info.get("collected_at", "2000-01-01")
                    )
                    age_hours = (datetime.now() - cached_time).total_seconds() / 3600
                    # Also invalidate when the snap has been updated since the
                    # cache was written (SNAP_REVISION changes on every install).
                    current_revision = os.environ.get("SNAP_REVISION", "")
                    cached_revision = self.system_info.get("snap_revision", "")
                    revision_changed = (
                        current_revision and current_revision != cached_revision
                    )
                    if age_hours < 1 and not revision_changed:
                        return self.system_info
            except Exception as e:
                console.print(f"⚠️  Failed to load cache: {e}", style="dim yellow")

        return self.collect_system_info()

    def collect_system_info(self) -> Dict:
        """Collect comprehensive system information"""
        console.print("🔍 Collecting system information...", style="#E95420")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Gathering system details...", total=None)

            self.system_info = {
                "collected_at": datetime.now().isoformat(),
                "snap_revision": os.environ.get("SNAP_REVISION", ""),
                "os": self._get_os_info(),
                "desktop": self._get_desktop_info(),
                "packages": self._get_package_info(),
                "services": self._get_services_info(),
                "hardware": self._get_hardware_info(),
                "storage": self._get_storage_detail(),
                "memory": self._get_memory_detail(),
                "processes": self._get_top_processes(),
                "network": self._get_network_detail(),
                "cpu_detail": self._get_cpu_detail(),
                "gpu_detail": self._get_gpu_detail(),
                "power": self._get_power_info(),
            }

            progress.update(task, completed=True)

        with open(self.cache_file, "w") as f:
            json.dump(self.system_info, f, indent=2)

        console.print("✓ System information collected", style="green")
        return self.system_info

    def _get_os_info(self) -> Dict:
        """Get OS and kernel information from os-release (no subprocess)."""
        info: Dict[str, str] = {}

        # When running in a snap, read the host's os-release; otherwise /etc
        os_release_path = (
            "/var/lib/snapd/hostfs/etc/os-release"
            if os.environ.get("SNAP")
            else "/etc/os-release"
        )
        try:
            os_release: Dict[str, str] = {}
            with open(os_release_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if "=" in line:
                        key, _, value = line.partition("=")
                        os_release[key] = value.strip('"')
            info["ubuntu_version"] = os_release.get("PRETTY_NAME", "")
            info["ubuntu_release"] = os_release.get("VERSION_ID", "")
            info["codename"] = os_release.get("VERSION_CODENAME", "")
        except Exception:
            pass

        try:
            info["kernel"] = platform.release()
            info["architecture"] = platform.machine()
        except Exception:
            pass

        return info

    def _get_desktop_info(self) -> Dict:
        """Get desktop environment information from environment variables."""
        info: Dict[str, str] = {}
        try:
            info["desktop_session"] = os.environ.get("XDG_CURRENT_DESKTOP", "")
            info["session_type"] = os.environ.get("XDG_SESSION_TYPE", "")
            info["shell"] = os.environ.get("SHELL", "").split("/")[-1]
        except Exception:
            pass
        return info

    def _get_package_info(self) -> Dict:
        """
        Get installed package information.

        snap list  → snapd REST API via /run/snapd.socket (snapd-control interface)
        apt/dpkg   → read /var/lib/dpkg/status (system-files-dpkg interface)
        """
        info: Dict = {
            "apt_packages": [],
            "snap_packages": [],
            "total_apt": 0,
            "total_snap": 0,
            "available_snaps": [],   # kept empty; live lookups go via snapd API
            "available_apt": [],     # kept empty; live lookups scan apt lists
        }

        # ── Snap packages via snapd REST API ──────────────────────────────────
        data = _snapd_get("/v2/snaps")
        if data and data.get("status") == "OK":
            snaps = data.get("result", [])
            info["snap_packages"] = [
                {"name": s["name"], "version": s.get("version", "")}
                for s in snaps
                if s.get("name")
            ]
            info["total_snap"] = len(info["snap_packages"])

        # ── Apt packages via /var/lib/dpkg/status ────────────────────────────
        installed = _read_dpkg_installed()
        info["apt_packages"] = installed
        info["total_apt"] = len(installed)

        return info

    def _get_services_info(self) -> Dict:
        """
        Detect running daemons by finding direct systemd children (PPID=1)
        in /proc.  systemctl cannot reach D-Bus in strict snap confinement.
        Requires system-observe interface.

        Also cross-references running process names against installed snap
        names (via /v2/snaps) to identify active snap services.
        """
        info: Dict = {"active": [], "failed": [], "snap_services": {}}

        # PPID=1 scan — only direct systemd children are daemons/services
        ppid1: set = set()
        try:
            for pid_dir in Path("/proc").iterdir():
                if not pid_dir.name.isdigit():
                    continue
                try:
                    status_text = (pid_dir / "status").read_text()
                    ppid = comm = None
                    for line in status_text.splitlines():
                        if line.startswith("PPid:"):
                            ppid = int(line.split()[1])
                        elif line.startswith("Name:"):
                            comm = line.split()[1]
                    if ppid == 1 and comm:
                        ppid1.add(comm)
                except (PermissionError, FileNotFoundError, OSError):
                    continue
        except Exception:
            pass
        info["active"] = sorted(ppid1)

        # Identify snap services: for each installed snap, find running
        # processes whose name starts with or equals the snap name.
        # (e.g. snap "lemonade" → process "lemonade-server")
        snap_data = _snapd_get("/v2/snaps")
        if snap_data and snap_data.get("status") == "OK":
            for snap in snap_data.get("result", []):
                snap_name = snap.get("name", "")
                if not snap_name:
                    continue
                matches = [
                    p for p in ppid1
                    if p == snap_name or p.startswith(snap_name + "-")
                    or p.startswith(snap_name + "_")
                ]
                if matches:
                    info["snap_services"][snap_name] = matches

        # Failed services cannot be detected without D-Bus access.
        return info

    def _get_hardware_info(self) -> Dict:
        """Get basic hardware information without external commands."""
        info: Dict = {}

        # CPU via /proc/cpuinfo
        try:
            with open("/proc/cpuinfo", "r") as f:
                lines = f.readlines()
            for line in lines:
                if "model name" in line:
                    info["cpu"] = line.split(":", 1)[1].strip()
                    break
            info["cpu_cores"] = len([l for l in lines if l.startswith("processor")])
        except Exception:
            pass

        # Memory via /proc/meminfo
        try:
            with open("/proc/meminfo", "r") as f:
                for line in f:
                    if "MemTotal" in line:
                        mem_kb = int(line.split()[1])
                        info["memory_gb"] = round(mem_kb / (1024 * 1024), 1)
                        break
        except Exception:
            pass

        # Disk via os.statvfs() – no external command needed
        try:
            stat = os.statvfs("/")
            block = stat.f_frsize
            total = stat.f_blocks * block
            free = stat.f_bavail * block
            used = (stat.f_blocks - stat.f_bfree) * block

            def _hsize(b: int) -> str:
                for unit in ("B", "K", "M", "G", "T"):
                    if abs(b) < 1024:
                        return f"{b:.1f}{unit}"
                    b = int(b / 1024)
                return f"{b:.1f}P"

            info["disk_total"] = _hsize(total)
            info["disk_used"] = _hsize(used)
            info["disk_available"] = _hsize(free)
            info["disk_percent"] = f"{int(used / total * 100) if total else 0}%"
        except Exception:
            pass

        return info

    # ── Storage topology ───────────────────────────────────────────────────────

    def _get_storage_detail(self) -> Dict:
        """
        Collect detailed storage topology:
        • Physical drives (type, model, size) from /sys/class/block
        • LVM / LUKS detection from dm-* devices
        • Software RAID from /proc/mdstat (system-observe)
        • zram devices
        • All real mount points with fs type, disk usage, key options (/proc/mounts)
        • Active swap devices (/proc/swaps — mount-observe)
        • Persistent mount config (/etc/fstab — mount-observe)
        • EFI vs BIOS detection
        """
        info: Dict = {
            "drives": [],
            "lvm": False,
            "luks": False,
            "raid": None,
            "zram": [],
            "mounts": [],
            "swap": [],
            "efi": False,
            "fstab_entries": [],
        }

        # ── Physical drives ────────────────────────────────────────────────────
        _SKIP_PREFIXES = ("loop", "dm-", "md", "ram", "zram", "sr")
        block_base = Path("/sys/class/block")
        if block_base.exists():
            for dev_link in sorted(block_base.iterdir()):
                name = dev_link.name
                if any(name.startswith(p) for p in _SKIP_PREFIXES):
                    continue
                # Only top-level drives (no partitions: sda not sda1, nvme0n1 not nvme0n1p1)
                if any(c.isdigit() for c in name):
                    import re as _re
                    if _re.search(
                        r'(sd[a-z]+\d+|nvme\d+n\d+p\d+|mmcblk\d+p\d+|hd[a-z]+\d+|vd[a-z]+\d+)',
                        name,
                    ):
                        continue
                try:
                    dev = dev_link.resolve()
                    rotational_path = dev / "queue" / "rotational"
                    size_path = dev / "size"

                    rotational = None
                    if rotational_path.exists():
                        rotational = rotational_path.read_text().strip() == "1"

                    size_sectors = 0
                    if size_path.exists():
                        size_sectors = int(size_path.read_text().strip())
                    size_gb = round(size_sectors * 512 / 1e9, 1)

                    # Drive type
                    if name.startswith("nvme"):
                        drive_type = "NVMe SSD"
                    elif name.startswith("mmcblk"):
                        drive_type = "eMMC/SD"
                    elif name.startswith("vd"):
                        drive_type = "Virtual disk"
                    elif rotational is True:
                        drive_type = "HDD"
                    elif rotational is False:
                        drive_type = "SSD"
                    else:
                        drive_type = "Unknown"

                    # Model string
                    model = ""
                    for model_path in [
                        dev / "device" / "model",
                        Path(f"/sys/class/nvme/{name}/model") if name.startswith("nvme") else Path("/dev/null"),
                    ]:
                        if model_path.exists():
                            try:
                                model = model_path.read_text().strip()
                                break
                            except Exception:
                                pass

                    if size_gb > 0:
                        info["drives"].append({
                            "name": name,
                            "type": drive_type,
                            "model": model,
                            "size_gb": size_gb,
                        })
                except Exception:
                    pass

            # ── LVM / LUKS via dm-* ───────────────────────────────────────────
            for dev_link in block_base.iterdir():
                if not dev_link.name.startswith("dm-"):
                    continue
                try:
                    dm_name_path = dev_link.resolve() / "dm" / "name"
                    if dm_name_path.exists():
                        dm_name = dm_name_path.read_text().strip()
                        if dm_name.endswith("_crypt") or "crypt" in dm_name:
                            info["luks"] = True
                        else:
                            info["lvm"] = True
                except Exception:
                    pass

            # ── zram devices ──────────────────────────────────────────────────
            for dev_link in block_base.iterdir():
                if not dev_link.name.startswith("zram"):
                    continue
                try:
                    dev = dev_link.resolve()
                    disksize = int((dev / "disksize").read_text().strip())
                    mem_used = 0
                    mem_used_path = dev / "mm_stat"
                    if mem_used_path.exists():
                        # mm_stat: orig_data_size compr_data_size mem_used_total ...
                        parts = mem_used_path.read_text().split()
                        if len(parts) >= 3:
                            mem_used = int(parts[2])
                    info["zram"].append({
                        "name": dev_link.name,
                        "size_gb": round(disksize / 1e9, 1),
                        "mem_used_mb": round(mem_used / 1e6, 0),
                    })
                except Exception:
                    pass

        # ── Software RAID (/proc/mdstat — system-observe) ─────────────────────
        try:
            mdstat = Path("/proc/mdstat").read_text()
            arrays = []
            current: Dict = {}
            for line in mdstat.splitlines():
                if line.startswith("md"):
                    parts = line.split()
                    current = {"name": parts[0], "status": "unknown", "members": []}
                    if len(parts) >= 4:
                        current["level"] = parts[3]  # raid1, raid5, etc.
                        current["members"] = [p.split("[")[0] for p in parts[4:]]
                elif "[" in line and ("_" in line or "U" in line) and current:
                    # State line: [2/2] [UU] or [2/1] [U_]
                    import re as _re
                    m = _re.search(r'\[([U_]+)\]', line)
                    if m:
                        state = m.group(1)
                        current["state"] = state
                        current["degraded"] = "_" in state
                    if current.get("name"):
                        arrays.append(current)
                        current = {}
            if arrays:
                info["raid"] = {"arrays": arrays}
        except Exception:
            pass

        # ── Mount points (/proc/mounts — mount-observe) ───────────────────────
        _REAL_FS = {
            "ext2", "ext3", "ext4", "btrfs", "xfs", "jfs", "reiserfs",
            "vfat", "exfat", "ntfs", "ntfs3", "hfsplus",
            "nfs", "nfs4", "cifs", "smb3", "sshfs", "fuse.sshfs",
            "overlay", "zfs", "f2fs", "nilfs2",
        }
        _NOTABLE_TMPFS = {"/tmp", "/dev/shm", "/run/user"}
        try:
            for line in Path("/proc/mounts").read_text().splitlines():
                parts = line.split()
                if len(parts) < 4:
                    continue
                source, mountpoint, fstype, options_str = parts[0], parts[1], parts[2], parts[3]
                is_real = fstype in _REAL_FS
                is_notable_tmpfs = fstype == "tmpfs" and any(
                    mountpoint == p or mountpoint.startswith(p + "/")
                    for p in _NOTABLE_TMPFS
                )
                if not (is_real or is_notable_tmpfs):
                    continue

                entry: Dict = {
                    "source": source,
                    "mountpoint": mountpoint,
                    "fstype": fstype,
                    "options": [],
                    "size_gb": None,
                    "used_gb": None,
                    "used_pct": None,
                }

                # Key options worth surfacing
                opts = options_str.split(",")
                notable_opts = [o for o in opts if o in (
                    "ro", "noatime", "relatime", "nodiratime",
                    "compress", "compress-force", "errors=remount-ro",
                ) or o.startswith("compress")]
                entry["options"] = notable_opts

                # Disk usage
                try:
                    st = os.statvfs(mountpoint)
                    total = st.f_blocks * st.f_frsize
                    used = (st.f_blocks - st.f_bfree) * st.f_frsize
                    entry["size_gb"] = round(total / 1e9, 1)
                    entry["used_gb"] = round(used / 1e9, 1)
                    entry["used_pct"] = int(used / total * 100) if total else 0
                except Exception:
                    pass

                info["mounts"].append(entry)
        except Exception:
            pass

        # ── Swap devices (/proc/swaps — mount-observe) ────────────────────────
        try:
            lines = Path("/proc/swaps").read_text().splitlines()
            for line in lines[1:]:  # skip header
                parts = line.split()
                if len(parts) >= 4:
                    size_kb = int(parts[2])
                    used_kb = int(parts[3])
                    info["swap"].append({
                        "device": parts[0],
                        "type": parts[1],
                        "size_gb": round(size_kb / 1e6, 1),
                        "used_gb": round(used_kb / 1e6, 1),
                        "used_pct": int(used_kb / size_kb * 100) if size_kb else 0,
                    })
        except Exception:
            pass

        # ── fstab (/etc/fstab — mount-observe) ────────────────────────────────
        try:
            for line in Path("/etc/fstab").read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split()
                if len(parts) >= 3:
                    info["fstab_entries"].append({
                        "source": parts[0],
                        "mountpoint": parts[1],
                        "fstype": parts[2],
                    })
        except Exception:
            pass

        # ── EFI detection ─────────────────────────────────────────────────────
        info["efi"] = Path("/sys/firmware/efi").exists()

        return info

    # ── Memory detail ──────────────────────────────────────────────────────────

    def _get_memory_detail(self) -> Dict:
        """
        Full /proc/meminfo breakdown plus PSI memory pressure and swappiness.
        All sources readable with system-observe.
        """
        info: Dict = {}

        # Full meminfo parse
        meminfo: Dict[str, int] = {}
        try:
            for line in Path("/proc/meminfo").read_text().splitlines():
                if ":" in line:
                    key, _, val = line.partition(":")
                    try:
                        meminfo[key.strip()] = int(val.split()[0])
                    except (ValueError, IndexError):
                        pass
        except Exception:
            pass

        def _gb(kb: int) -> float:
            return round(kb / 1e6, 2)

        total_kb = meminfo.get("MemTotal", 0)
        avail_kb = meminfo.get("MemAvailable", 0)
        cached_kb = meminfo.get("Cached", 0) + meminfo.get("Buffers", 0)
        swap_total_kb = meminfo.get("SwapTotal", 0)
        swap_free_kb = meminfo.get("SwapFree", 0)
        swap_used_kb = swap_total_kb - swap_free_kb

        info["total_gb"] = _gb(total_kb)
        info["available_gb"] = _gb(avail_kb)
        info["used_gb"] = _gb(total_kb - avail_kb)
        info["used_pct"] = int((total_kb - avail_kb) / total_kb * 100) if total_kb else 0
        info["cache_gb"] = _gb(cached_kb)
        info["shmem_gb"] = _gb(meminfo.get("Shmem", 0))
        info["sreclaimable_gb"] = _gb(meminfo.get("SReclaimable", 0))
        info["dirty_mb"] = round(meminfo.get("Dirty", 0) / 1024, 1)
        info["hugepages_total"] = meminfo.get("HugePages_Total", 0)
        info["swap_total_gb"] = _gb(swap_total_kb)
        info["swap_used_gb"] = _gb(swap_used_kb)
        info["swap_used_pct"] = int(swap_used_kb / swap_total_kb * 100) if swap_total_kb else 0
        info["swap_cached_kb"] = meminfo.get("SwapCached", 0)
        info["zswap_kb"] = meminfo.get("Zswap", 0)

        # PSI memory pressure (/proc/pressure/memory — system-observe)
        try:
            psi_text = Path("/proc/pressure/memory").read_text()
            for line in psi_text.splitlines():
                parts = dict(kv.split("=") for kv in line.split() if "=" in kv)
                if line.startswith("some"):
                    info["pressure_some_avg10"] = float(parts.get("avg10", 0))
                elif line.startswith("full"):
                    info["pressure_full_avg10"] = float(parts.get("avg10", 0))
        except Exception:
            pass

        # Swappiness (/proc/sys/vm/swappiness — system-observe)
        try:
            info["swappiness"] = int(Path("/proc/sys/vm/swappiness").read_text().strip())
        except Exception:
            pass

        return info

    # ── Process intelligence ───────────────────────────────────────────────────

    def _get_top_processes(self) -> Dict:
        """
        Top resource consumers from /proc — readable with system-observe.
        Walks /proc once to collect RSS, CPU ticks, I/O, state, and OOM score.
        """
        info: Dict = {
            "top_rss": [],
            "top_cpu": [],
            "top_io_write": [],
            "zombie_count": 0,
            "dstate_count": 0,
            "dstate_names": [],
            "high_oom": [],
            "load_1": 0.0,
            "load_5": 0.0,
            "load_15": 0.0,
            "load_per_cpu": 0.0,
            "running_count": 0,
            "cpu_pressure_some": 0.0,
            "io_pressure_some": 0.0,
        }

        # System uptime in jiffies (for lifetime CPU%)
        try:
            uptime_s = float(Path("/proc/uptime").read_text().split()[0])
        except Exception:
            uptime_s = 1.0
        try:
            hz = os.sysconf(os.sysconf_names["SC_CLK_TCK"])
        except Exception:
            hz = 100
        uptime_ticks = uptime_s * hz

        processes: list = []

        for pid_dir in Path("/proc").iterdir():
            if not pid_dir.name.isdigit():
                continue
            try:
                pid = int(pid_dir.name)
                status_text = (pid_dir / "status").read_text()
                status: Dict[str, str] = {}
                for line in status_text.splitlines():
                    if ":" in line:
                        k, _, v = line.partition(":")
                        status[k.strip()] = v.strip()

                name = status.get("Name", "")
                state = status.get("State", "")[:1]
                rss_kb = int(status.get("VmRSS", "0 kB").split()[0])
                swap_kb = int(status.get("VmSwap", "0 kB").split()[0])
                threads = int(status.get("Threads", "1"))

                if state == "Z":
                    info["zombie_count"] += 1
                    continue
                if state == "D":
                    info["dstate_count"] += 1
                    info["dstate_names"].append(name)

                # CPU ticks from /proc/[pid]/stat
                cpu_pct = 0.0
                try:
                    stat_parts = (pid_dir / "stat").read_text().split()
                    utime = int(stat_parts[13])
                    stime = int(stat_parts[14])
                    starttime = int(stat_parts[21])
                    total_ticks = utime + stime
                    proc_elapsed = uptime_ticks - starttime
                    if proc_elapsed > 0:
                        cpu_pct = round(total_ticks / proc_elapsed * 100, 1)
                except Exception:
                    pass

                # Write bytes from /proc/[pid]/io
                write_bytes = 0
                try:
                    for io_line in (pid_dir / "io").read_text().splitlines():
                        if io_line.startswith("write_bytes:"):
                            write_bytes = int(io_line.split()[1])
                            break
                except Exception:
                    pass

                # OOM score
                oom_score = 0
                try:
                    oom_score = int((pid_dir / "oom_score").read_text().strip())
                except Exception:
                    pass

                # Short cmdline for display
                try:
                    cmdline_raw = (pid_dir / "cmdline").read_bytes()
                    cmdline = cmdline_raw.replace(b"\x00", b" ").decode("utf-8", errors="replace").strip()
                    cmdline = cmdline[:120]
                except Exception:
                    cmdline = name

                processes.append({
                    "pid": pid,
                    "name": name,
                    "state": state,
                    "rss_mb": round(rss_kb / 1024, 1),
                    "swap_mb": round(swap_kb / 1024, 1),
                    "threads": threads,
                    "cpu_pct": cpu_pct,
                    "write_mb": round(write_bytes / 1e6, 1),
                    "oom_score": oom_score,
                    "cmdline": cmdline,
                })
            except (PermissionError, FileNotFoundError, ProcessLookupError):
                continue
            except Exception:
                continue

        # Top RSS
        info["top_rss"] = sorted(processes, key=lambda p: p["rss_mb"], reverse=True)[:10]

        # Top CPU
        info["top_cpu"] = sorted(processes, key=lambda p: p["cpu_pct"], reverse=True)[:5]

        # Top I/O writers
        info["top_io_write"] = sorted(processes, key=lambda p: p["write_mb"], reverse=True)[:3]

        # High OOM score (>= 500)
        info["high_oom"] = sorted(
            [p for p in processes if p["oom_score"] >= 500],
            key=lambda p: p["oom_score"], reverse=True,
        )[:3]

        # Load average
        try:
            parts = Path("/proc/loadavg").read_text().split()
            info["load_1"] = float(parts[0])
            info["load_5"] = float(parts[1])
            info["load_15"] = float(parts[2])
            info["running_count"] = int(parts[3].split("/")[0])
            cpu_count = len([
                d for d in Path("/sys/devices/system/cpu").iterdir()
                if d.name.startswith("cpu") and d.name[3:].isdigit()
            ]) or 1
            info["load_per_cpu"] = round(info["load_1"] / cpu_count, 2)
        except Exception:
            pass

        # PSI CPU and I/O pressure
        for resource in ("cpu", "io"):
            try:
                psi_text = Path(f"/proc/pressure/{resource}").read_text()
                for line in psi_text.splitlines():
                    if line.startswith("some"):
                        parts = dict(kv.split("=") for kv in line.split() if "=" in kv)
                        info[f"{resource}_pressure_some"] = float(parts.get("avg10", 0))
                        break
            except Exception:
                pass

        return info

    # ── Network interface topology ─────────────────────────────────────────────

    def _get_network_detail(self) -> Dict:
        """
        Network interface classification from /sys/class/net (hardware-observe).
        Note: IP addresses and connection counts need network-observe (not in snap).
        """
        interfaces = []
        net_base = Path("/sys/class/net")
        if not net_base.exists():
            return {"interfaces": interfaces}

        _VPN_PREFIXES = ("tun", "tap", "wg", "vpn", "ipsec", "ppp")
        _CONTAINER_PREFIXES = ("docker", "lxc", "lxd", "virbr", "veth", "br-")

        for iface_link in sorted(net_base.iterdir()):
            name = iface_link.name
            try:
                iface = iface_link.resolve()

                def _read(fname: str) -> str:
                    try:
                        return (iface / fname).read_text().strip()
                    except Exception:
                        return ""

                iface_type = _read("type")
                operstate = _read("operstate")
                speed_str = _read("speed")
                mac = _read("address")
                speed = int(speed_str) if speed_str.lstrip("-").isdigit() else None

                is_loopback = iface_type == "772"
                is_wifi = (iface / "wireless").exists() or iface_type == "801"
                is_bridge = (iface / "bridge").exists()
                is_bonding = (iface / "bonding").exists()
                is_vpn = any(name.startswith(p) for p in _VPN_PREFIXES)
                is_container = any(name.startswith(p) for p in _CONTAINER_PREFIXES)

                if is_loopback:
                    continue  # not useful in context

                interfaces.append({
                    "name": name,
                    "operstate": operstate,
                    "speed_mbps": speed if speed and speed > 0 else None,
                    "mac": mac,
                    "is_wifi": is_wifi,
                    "is_bridge": is_bridge,
                    "is_bonding": is_bonding,
                    "is_vpn": is_vpn,
                    "is_container_bridge": is_container,
                })
            except Exception:
                pass

        return {"interfaces": interfaces}

    # ── CPU detail ─────────────────────────────────────────────────────────────

    def _get_cpu_detail(self) -> Dict:
        """
        CPU topology, frequency scaling, and thermal zones.
        All from /sys/devices/system/cpu/ and /sys/class/thermal/ (hardware-observe).
        """
        info: Dict = {}

        cpu_base = Path("/sys/devices/system/cpu")

        # Logical CPU count
        try:
            present = (cpu_base / "present").read_text().strip()
            # Format: "0-31" or "0,1,2"
            if "-" in present:
                lo, hi = present.split("-")
                info["logical_cpus"] = int(hi) - int(lo) + 1
            else:
                info["logical_cpus"] = len(present.split(","))
        except Exception:
            info["logical_cpus"] = self.system_info.get("hardware", {}).get("cpu_cores", 1)

        # Topology from cpu0
        try:
            topo = cpu_base / "cpu0" / "topology"
            # Count unique physical package IDs
            pkg_ids = set()
            core_ids = set()
            for cpu_dir in cpu_base.iterdir():
                if not (cpu_dir.name.startswith("cpu") and cpu_dir.name[3:].isdigit()):
                    continue
                try:
                    pkg_ids.add((cpu_dir / "topology" / "physical_package_id").read_text().strip())
                    core_ids.add((
                        (cpu_dir / "topology" / "physical_package_id").read_text().strip(),
                        (cpu_dir / "topology" / "core_id").read_text().strip(),
                    ))
                except Exception:
                    pass
            info["sockets"] = len(pkg_ids) if pkg_ids else 1
            info["physical_cores"] = len(core_ids) if core_ids else info["logical_cpus"]
            info["hyperthreading"] = info["logical_cpus"] > info["physical_cores"]
        except Exception:
            pass

        # L3 cache size
        try:
            for index_dir in sorted((cpu_base / "cpu0" / "cache").iterdir()):
                try:
                    level = (index_dir / "level").read_text().strip()
                    if level == "3":
                        size_str = (index_dir / "size").read_text().strip()
                        # size_str like "32768K" or "32M"
                        if size_str.endswith("K"):
                            info["l3_cache_kb"] = int(size_str[:-1])
                        elif size_str.endswith("M"):
                            info["l3_cache_kb"] = int(size_str[:-1]) * 1024
                        break
                except Exception:
                    pass
        except Exception:
            pass

        # Frequency scaling (cpu0 as representative)
        try:
            cpufreq = cpu_base / "cpu0" / "cpufreq"
            if cpufreq.exists():
                def _read_cpufreq(fname: str) -> str:
                    try:
                        return (cpufreq / fname).read_text().strip()
                    except Exception:
                        return ""

                info["governor"] = _read_cpufreq("scaling_governor")
                info["freq_driver"] = _read_cpufreq("scaling_driver")
                cur = _read_cpufreq("scaling_cur_freq")
                max_ = _read_cpufreq("scaling_max_freq")
                min_ = _read_cpufreq("scaling_min_freq")
                if cur.isdigit():
                    info["cur_freq_mhz"] = round(int(cur) / 1000)
                if max_.isdigit():
                    info["max_freq_mhz"] = round(int(max_) / 1000)
                if min_.isdigit():
                    info["min_freq_mhz"] = round(int(min_) / 1000)
        except Exception:
            pass

        # Thermal zones (hardware-observe covers /sys/class/thermal/**)
        hot_zones = []
        try:
            for tz in sorted(Path("/sys/class/thermal").iterdir()):
                if not tz.name.startswith("thermal_zone"):
                    continue
                try:
                    tz_real = tz.resolve()
                    tz_type = (tz_real / "type").read_text().strip()
                    temp_mc = int((tz_real / "temp").read_text().strip())
                    temp_c = temp_mc / 1000
                    if temp_c >= 60:
                        hot_zones.append({"type": tz_type, "temp_c": round(temp_c, 1)})
                except Exception:
                    pass
        except Exception:
            pass
        info["hot_zones"] = hot_zones

        # Virtualisation (check cpuinfo flags and hypervisor sysfs)
        info["is_vm"] = False
        try:
            cpuinfo = Path("/proc/cpuinfo").read_text()
            if "hypervisor" in cpuinfo:
                info["is_vm"] = True
        except Exception:
            pass
        if not info["is_vm"]:
            try:
                if Path("/sys/hypervisor/type").exists():
                    info["is_vm"] = True
            except Exception:
                pass

        return info

    # ── GPU detail (AMD) ───────────────────────────────────────────────────────

    def _get_gpu_detail(self) -> Dict:
        """
        AMD GPU metrics from /sys/class/drm/ (hardware-observe).

        Collects per-card:
        • gpu_busy_percent  — shader/compute engine utilisation
        • VRAM used/total   — dedicated GPU memory (small on APUs)
        • GTT used/total    — system RAM currently mapped to GPU (large on APUs)
        • Edge temperature  — from hwmon
        • Package power (W) — PPT/power1_average from hwmon
        • GFXCLK (MHz)     — shader clock from hwmon freq1_input

        All paths fall under /sys/class/drm/** and /sys/class/*/hwmon/**,
        both covered by hardware-observe's /sys/{class,devices}/** rule.
        """
        cards = []
        drm_base = Path("/sys/class/drm")
        if not drm_base.exists():
            return {"cards": cards}

        for card_link in sorted(drm_base.iterdir()):
            name = card_link.name
            # Top-level cards only (card0, card1 …), not connectors (card1-DP-1)
            if not (name.startswith("card") and name[4:].isdigit()):
                continue
            try:
                device = card_link.resolve() / "device"

                def _rd(p) -> str:
                    try:
                        return Path(p).read_text().strip()
                    except Exception:
                        return ""

                busy_path = device / "gpu_busy_percent"
                if not busy_path.exists():
                    continue  # not an amdgpu device

                card_info: Dict = {"card": name}

                busy = _rd(busy_path)
                if busy.isdigit():
                    card_info["busy_pct"] = int(busy)

                # VRAM (dedicated GPU memory)
                for key, field in (
                    ("vram_total_mb", "mem_info_vram_total"),
                    ("vram_used_mb",  "mem_info_vram_used"),
                ):
                    val = _rd(device / field)
                    if val.isdigit():
                        card_info[key] = round(int(val) / 1e6)

                # GTT (system RAM pages mapped for GPU — critical on APUs)
                for key, field in (
                    ("gtt_total_gb", "mem_info_gtt_total"),
                    ("gtt_used_gb",  "mem_info_gtt_used"),
                ):
                    val = _rd(device / field)
                    if val.isdigit():
                        card_info[key] = round(int(val) / 1e9, 1)

                # hwmon: temperature, power, clock
                hwmon_base = device / "hwmon"
                if hwmon_base.exists():
                    for hwmon_dir in sorted(hwmon_base.iterdir()):
                        hw = hwmon_dir.resolve()
                        temp = _rd(hw / "temp1_input")
                        if temp.lstrip("-").isdigit():
                            card_info["temp_c"] = round(int(temp) / 1000, 1)
                        power = _rd(hw / "power1_average") or _rd(hw / "power1_input")
                        if power.isdigit():
                            card_info["power_w"] = round(int(power) / 1e6, 1)
                        freq = _rd(hw / "freq1_input")
                        if freq.isdigit():
                            card_info["sclk_mhz"] = round(int(freq) / 1e6)
                        break  # first hwmon is sufficient

                cards.append(card_info)
            except Exception:
                continue

        return {"cards": cards}

    # ── Power and form factor ──────────────────────────────────────────────────

    def _get_power_info(self) -> Dict:
        """
        Battery state, AC adapter, and chassis type.
        From /sys/class/power_supply/ and /sys/class/dmi/id/ (hardware-observe).
        """
        info: Dict = {
            "chassis_type": None,
            "form_factor": "unknown",
            "battery_present": False,
            "battery_pct": None,
            "battery_status": None,
            "battery_health_pct": None,
            "ac_online": None,
        }

        # Chassis type from DMI
        try:
            ct = int(Path("/sys/class/dmi/id/chassis_type").read_text().strip())
            info["chassis_type"] = ct
            # https://www.dmtf.org/sites/default/files/standards/documents/DSP0134_3.6.0.pdf
            if ct in (8, 9, 10, 11, 14):
                info["form_factor"] = "laptop"
            elif ct in (3, 4, 5, 6, 7, 15, 16, 35, 36):
                info["form_factor"] = "desktop"
            elif ct in (17, 23, 24, 25, 28, 29):
                info["form_factor"] = "server"
            elif ct == 13:
                info["form_factor"] = "all-in-one"
        except Exception:
            pass

        psu_base = Path("/sys/class/power_supply")
        if not psu_base.exists():
            return info

        for psu in psu_base.iterdir():
            try:
                psu_real = psu.resolve()
                psu_type = (psu_real / "type").read_text().strip() if (psu_real / "type").exists() else ""
            except Exception:
                continue

            if psu_type == "Battery":
                info["battery_present"] = True
                if info["form_factor"] == "unknown":
                    info["form_factor"] = "laptop"
                try:
                    info["battery_pct"] = int((psu_real / "capacity").read_text().strip())
                except Exception:
                    pass
                try:
                    info["battery_status"] = (psu_real / "status").read_text().strip()
                except Exception:
                    pass
                # Battery wear: energy_full / energy_full_design
                try:
                    ef = int((psu_real / "energy_full").read_text().strip())
                    efd = int((psu_real / "energy_full_design").read_text().strip())
                    if efd > 0:
                        info["battery_health_pct"] = round(ef / efd * 100)
                except Exception:
                    pass

            elif psu_type == "Mains":
                try:
                    info["ac_online"] = (psu_real / "online").read_text().strip() == "1"
                except Exception:
                    pass

        # If no battery was found and chassis is unknown, assume desktop
        if not info["battery_present"] and info["form_factor"] == "unknown":
            if info["ac_online"] is True:
                info["form_factor"] = "desktop"

        return info

    # ── Neofetch-style helpers ─────────────────────────────────────────────────

    def _get_uptime(self) -> str:
        """Read current uptime from /proc/uptime (always live)."""
        try:
            with open("/proc/uptime", "r") as f:
                seconds = int(float(f.read().split()[0]))
            days = seconds // 86400
            hours = (seconds % 86400) // 3600
            mins = (seconds % 3600) // 60
            parts = []
            if days:
                parts.append(f"{days}d")
            if hours:
                parts.append(f"{hours}h")
            parts.append(f"{mins}m")
            return " ".join(parts)
        except Exception:
            return ""

    def _get_host(self) -> str:
        """Get machine vendor + product name from DMI sysfs (hardware-observe)."""
        try:
            vendor = Path("/sys/class/dmi/id/sys_vendor").read_text().strip()
            product = Path("/sys/class/dmi/id/product_name").read_text().strip()
            if product.startswith(vendor):
                return product
            return f"{vendor} {product}".strip()
        except Exception:
            return ""

    def _get_gpu(self) -> str:
        """
        GPU detection via staged lspci (pciutils) with snap-aware IDs path.
        Falls back to reading /sys/bus/pci/devices/ directly.
        Requires hardware-observe interface.
        """
        # Try lspci first (staged in snap or available on host)
        try:
            cmd = ["lspci"]
            snap = os.environ.get("SNAP")
            if snap:
                pci_ids = os.path.join(snap, "usr/share/misc/pci.ids")
                if os.path.exists(pci_ids):
                    cmd.extend(["-i", pci_ids])
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    low = line.lower()
                    if any(k in low for k in ("vga", "3d controller", "display controller")):
                        desc = line.split(":", 2)[-1].strip()
                        return desc.split("(rev")[0].strip()[:60]
        except Exception:
            pass

        # Fallback: PCI sysfs (/sys/bus/pci/devices/ via hardware-observe)
        try:
            pci_base = Path("/sys/bus/pci/devices")
            if pci_base.exists():
                for dev in sorted(pci_base.iterdir()):
                    try:
                        class_file = dev / "class"
                        if not class_file.exists():
                            continue
                        pci_class = int(class_file.read_text().strip(), 16)
                        if (pci_class >> 16) != 0x03:  # not a display class
                            continue
                        vendor_hex = (dev / "vendor").read_text().strip().lower()
                        vendor_name = _PCI_VENDORS.get(vendor_hex, vendor_hex)
                        uevent_file = dev / "uevent"
                        if uevent_file.exists():
                            for ln in uevent_file.read_text().splitlines():
                                if ln.startswith("DRIVER="):
                                    driver = ln.split("=", 1)[1]
                                    if driver:
                                        return f"{vendor_name} ({driver})"[:60]
                        return f"{vendor_name} GPU"[:60]
                    except Exception:
                        continue
        except Exception:
            pass

        return ""

    def _get_used_memory_gb(self) -> Optional[float]:
        """Read current used RAM from /proc/meminfo (always live)."""
        try:
            meminfo: Dict[str, int] = {}
            with open("/proc/meminfo", "r") as f:
                for line in f:
                    k, v = line.split(":", 1)
                    meminfo[k.strip()] = int(v.split()[0])
            total_kb = meminfo.get("MemTotal", 0)
            avail_kb = meminfo.get("MemAvailable", 0)
            return round((total_kb - avail_kb) / (1024 * 1024), 1)
        except Exception:
            return None

    def get_live_stats(self) -> str:
        """
        Re-read all volatile system metrics and return a fresh formatted summary.

        Re-collects: GPU, memory, processes, CPU freq/thermals, mount disk usage.
        Static data (packages, services, drives) is NOT re-read — it doesn't change.
        The refreshed values are also written back into self.system_info so the
        caller can subsequently call get_context_summary() with fresh data.

        Use this as the handler for the get_system_stats LLM tool call.
        """
        if not self.system_info:
            self.load_or_collect()

        # Re-read volatile sections
        mem    = self._get_memory_detail()
        procs  = self._get_top_processes()
        gpu    = self._get_gpu_detail()
        cpu    = self._get_cpu_detail()

        # Refresh disk usage on existing mount entries (cheap statvfs)
        storage = self.system_info.get("storage", {})
        for m in storage.get("mounts", []):
            try:
                st = os.statvfs(m["mountpoint"])
                total = st.f_blocks * st.f_frsize
                used  = (st.f_blocks - st.f_bfree) * st.f_frsize
                m["size_gb"]  = round(total / 1e9, 1)
                m["used_gb"]  = round(used  / 1e9, 1)
                m["used_pct"] = int(used / total * 100) if total else 0
            except Exception:
                pass

        # Write back so get_context_summary() reflects fresh values
        self.system_info["memory"]     = mem
        self.system_info["processes"]  = procs
        self.system_info["gpu_detail"] = gpu
        self.system_info["cpu_detail"] = cpu

        lines = ["=== Live System Stats ==="]

        # ── Memory ────────────────────────────────────────────────────────────
        total = mem.get("total_gb", 0)
        used  = mem.get("used_gb", 0)
        pct   = mem.get("used_pct", 0)
        cache = mem.get("cache_gb", 0)
        if total:
            mem_line = f"Memory: {used}G / {total}G used ({pct}%)"
            if cache > 0.1:
                mem_line += f", {cache}G reclaimable cache"
            lines.append(mem_line)
        swap_total = mem.get("swap_total_gb", 0)
        swap_used  = mem.get("swap_used_gb", 0)
        swap_pct   = mem.get("swap_used_pct", 0)
        if swap_total:
            lines.append(f"Swap: {swap_used}G / {swap_total}G used ({swap_pct}%)")
        psi_some = mem.get("pressure_some_avg10", 0)
        if psi_some >= 5:
            lines.append(f"Memory pressure: {psi_some:.1f}% (10s avg, HIGH)")

        # ── GPU ───────────────────────────────────────────────────────────────
        for card in gpu.get("cards", []):
            gpu_parts = []
            if card.get("busy_pct") is not None:
                gpu_parts.append(f"{card['busy_pct']}% busy")
            if card.get("sclk_mhz"):
                gpu_parts.append(f"{card['sclk_mhz']} MHz")
            if card.get("power_w"):
                gpu_parts.append(f"{card['power_w']}W")
            if card.get("temp_c"):
                gpu_parts.append(f"{card['temp_c']}°C")
            if gpu_parts:
                lines.append(f"GPU ({card['card']}): {', '.join(gpu_parts)}")
            if card.get("vram_total_mb"):
                vram_used  = card.get("vram_used_mb", 0)
                vram_total = card["vram_total_mb"]
                lines.append(f"  VRAM: {vram_used}MB / {vram_total}MB used")
            if card.get("gtt_total_gb"):
                gtt_used  = card.get("gtt_used_gb", 0)
                gtt_total = card["gtt_total_gb"]
                pct_gtt = int(gtt_used / gtt_total * 100) if gtt_total else 0
                lines.append(
                    f"  GTT (sys RAM→GPU): {gtt_used}G / {gtt_total}G used ({pct_gtt}%)"
                )

        # ── CPU freq / thermals ───────────────────────────────────────────────
        governor  = cpu.get("governor", "")
        cur_mhz   = cpu.get("cur_freq_mhz")
        max_mhz   = cpu.get("max_freq_mhz")
        hot_zones = cpu.get("hot_zones", [])
        if cur_mhz:
            freq_str = f"CPU freq: {cur_mhz} MHz"
            if max_mhz:
                freq_str += f" / {max_mhz} MHz max"
            if governor:
                freq_str += f" ({governor})"
            lines.append(freq_str)
        if hot_zones:
            zone_strs = [f"{z['type']} {z['temp_c']}°C" for z in hot_zones]
            lines.append(f"Thermal alert: {', '.join(zone_strs)}")

        # ── Processes ─────────────────────────────────────────────────────────
        load_1   = procs.get("load_1", 0)
        load_5   = procs.get("load_5", 0)
        load_15  = procs.get("load_15", 0)
        load_per = procs.get("load_per_cpu", 0)
        if load_1:
            load_str = f"Load: {load_1} / {load_5} / {load_15} (1/5/15 min)"
            if load_per > 0.7:
                load_str += f" — {load_per:.2f}/CPU (HIGH)"
            lines.append(load_str)

        zombie = procs.get("zombie_count", 0)
        dstate = procs.get("dstate_count", 0)
        dnames = procs.get("dstate_names", [])
        if zombie:
            lines.append(f"Zombie processes: {zombie}")
        if dstate:
            dname_str = f" ({', '.join(dnames[:3])})" if dnames else ""
            lines.append(f"D-state (blocked) processes: {dstate}{dname_str}")

        top_rss = procs.get("top_rss", [])
        if top_rss:
            rss_strs = [f"{p['name']} {p['rss_mb']}MB" for p in top_rss[:5]]
            lines.append(f"Top RSS: {', '.join(rss_strs)}")

        high_oom = procs.get("high_oom", [])
        if high_oom:
            oom_strs = [f"{p['name']} (score {p['oom_score']})" for p in high_oom]
            lines.append(f"High OOM risk: {', '.join(oom_strs)}")

        cpu_psi = procs.get("cpu_pressure_some", 0)
        io_psi  = procs.get("io_pressure_some", 0)
        if cpu_psi >= 5 or io_psi >= 5:
            psi_parts = []
            if cpu_psi >= 5:
                psi_parts.append(f"CPU={cpu_psi:.1f}%")
            if io_psi >= 5:
                psi_parts.append(f"IO={io_psi:.1f}%")
            lines.append(f"Resource pressure (10s avg): {', '.join(psi_parts)}")

        # ── Disk usage ────────────────────────────────────────────────────────
        real_mounts = [
            m for m in storage.get("mounts", [])
            if m.get("size_gb") is not None and m.get("fstype") != "tmpfs"
        ]
        if real_mounts:
            lines.append("Disk usage:")
            for m in real_mounts:
                lines.append(
                    f"  {m['mountpoint']:<20} {m['size_gb']}G total, "
                    f"{m.get('used_gb', 0)}G used ({m.get('used_pct', 0)}%)"
                )

        return "\n".join(lines)

    def get_neofetch_fields(self) -> list:
        """Return system info as a list of {label, value} dicts for the sidebar."""
        if not self.system_info:
            self.load_or_collect()

        import re
        fields = []
        os_info    = self.system_info.get("os", {})
        desktop    = self.system_info.get("desktop", {})
        hw         = self.system_info.get("hardware", {})
        packages   = self.system_info.get("packages", {})
        cpu_detail = self.system_info.get("cpu_detail", {})
        power      = self.system_info.get("power", {})
        storage    = self.system_info.get("storage", {})
        mem_detail = self.system_info.get("memory", {})

        def add(label: str, value) -> None:
            if value:
                fields.append({"label": label, "value": value})

        ver  = os_info.get("ubuntu_version", "")
        arch = os_info.get("architecture", "")
        add("OS", f"{ver} {arch}".strip())
        add("Host", self._get_host())

        form_factor = power.get("form_factor", "")
        if form_factor and form_factor != "unknown":
            add("Type", form_factor.capitalize())

        add("Kernel", os_info.get("kernel", ""))
        add("Uptime", self._get_uptime())
        add("Shell", desktop.get("shell", ""))

        de = desktop.get("desktop_session", "")
        session = desktop.get("session_type", "")
        if de:
            if ":" in de:
                de = de.split(":")[-1]
            if de.lower() == "unity":
                de = "GNOME"
            add("DE", f"{de} ({session.capitalize()})" if session else de)

        cpu = hw.get("cpu", "")
        logical = cpu_detail.get("logical_cpus") or hw.get("cpu_cores", 0)
        governor = cpu_detail.get("governor", "")
        if cpu:
            cpu = re.sub(r"\(R\)|\(TM\)|CPU\s+", " ", cpu)
            cpu = re.sub(r"\s+@\s+[\d.]+\s*GHz", "", cpu)
            cpu = re.sub(r"\s+", " ", cpu).strip()
        cpu_val = f"{cpu} ({logical})" if (cpu and logical) else cpu or (f"{logical} cores" if logical else "")
        if governor:
            cpu_val = f"{cpu_val} [{governor}]" if cpu_val else f"[{governor}]"
        if cpu_val:
            add("CPU", cpu_val)

        add("GPU", self._get_gpu())
        gpu_detail = self.system_info.get("gpu_detail", {})
        for card in gpu_detail.get("cards", []):
            if card.get("gtt_total_gb"):
                gtt_used = card.get("gtt_used_gb", 0)
                gtt_total = card["gtt_total_gb"]
                pct = int(gtt_used / gtt_total * 100) if gtt_total else 0
                add("GPU GTT", f"{gtt_used}G / {gtt_total}G ({pct}%)")
            elif card.get("vram_total_mb"):
                vram_used = card.get("vram_used_mb", 0)
                vram_total = card["vram_total_mb"]
                pct = int(vram_used / vram_total * 100) if vram_total else 0
                add("GPU VRAM", f"{vram_used}MB / {vram_total}MB ({pct}%)")

        # Memory from detail or fallback
        if mem_detail.get("total_gb"):
            used = mem_detail.get("used_gb", 0)
            total = mem_detail["total_gb"]
            pct = mem_detail.get("used_pct", 0)
            add("Memory", f"{used}G / {total}G ({pct}%)")
        elif hw.get("memory_gb"):
            used_gb = self._get_used_memory_gb()
            total_gb = hw["memory_gb"]
            if used_gb is not None:
                add("Memory", f"{used_gb} used / {total_gb} GB")
            else:
                add("Memory", f"{total_gb} GB total")

        # Per-mount disk usage from storage detail (real filesystems only)
        mounts = [
            m for m in storage.get("mounts", [])
            if m.get("size_gb") is not None and m.get("fstype") != "tmpfs"
        ]
        if mounts:
            for m in mounts:
                size = m["size_gb"]
                used_g = m.get("used_gb", 0)
                pct = m.get("used_pct", 0)
                add(f"Disk ({m['mountpoint']})", f"{used_g}G / {size}G ({pct}%)")
        else:
            # Fallback to root-only from hw
            disk_used  = hw.get("disk_used", "")
            disk_total = hw.get("disk_total", "")
            disk_pct   = hw.get("disk_percent", "")
            if disk_used and disk_total:
                val = f"{disk_used} used / {disk_total}"
                if disk_pct:
                    val += f" ({disk_pct})"
                add("Disk", val)

        # Battery (laptops only)
        if power.get("battery_present"):
            pct = power.get("battery_pct")
            status = power.get("battery_status", "")
            health = power.get("battery_health_pct")
            bat_val = f"{pct}% ({status})" if pct is not None else status
            if health and health < 80:
                bat_val += f", health {health}%"
            add("Battery", bat_val)

        # Thermal zones (only if at least one is hot)
        hot_zones = cpu_detail.get("hot_zones", [])
        if hot_zones:
            zone_strs = [f"{z['type']} {z['temp_c']}°C" for z in hot_zones[:3]]
            add("Temps", ", ".join(zone_strs))

        # Deb package count – live query from dpkg status
        deb_n = len(_read_dpkg_installed()) or packages.get("total_apt", 0)
        snap_n = packages.get("total_snap", 0)
        if deb_n:
            add("Deb pkgs", str(deb_n))
        if snap_n:
            add("Snap pkgs", str(snap_n))

        return fields

    def get_context_summary(self) -> str:
        """Generate a concise summary for LLM context"""
        if not self.system_info:
            self.load_or_collect()

        import re as _re
        lines = []

        os_info = self.system_info.get("os", {})
        if os_info.get("ubuntu_version"):
            lines.append(
                f"OS: {os_info['ubuntu_version']} ({os_info.get('architecture', 'unknown')})"
            )
        if os_info.get("kernel"):
            lines.append(f"Kernel: {os_info['kernel']}")

        desktop = self.system_info.get("desktop", {})
        if desktop.get("desktop_session"):
            session_type = desktop.get("session_type", "")
            lines.append(
                f"Desktop: {desktop['desktop_session']}"
                + (f" ({session_type})" if session_type else "")
            )
        if desktop.get("shell"):
            lines.append(f"Shell: {desktop['shell']}")

        packages = self.system_info.get("packages", {})
        if packages.get("total_snap"):
            lines.append(f"Snap packages: {packages['total_snap']} installed")
            snap_list = [
                f"{pkg['name']} ({pkg['version']})"
                for pkg in packages.get("snap_packages", [])
            ]
            if snap_list:
                lines.append(
                    f"Installed snaps: {', '.join(snap_list[:20])}"
                    + (" ..." if len(snap_list) > 20 else "")
                )

        if packages.get("total_apt"):
            lines.append(
                f"Apt packages installed: {packages['total_apt']} "
                "(use check_apt tool for specific packages)"
            )

        services = self.system_info.get("services", {})
        failed = services.get("failed", [])
        active_procs = set(services.get("active", []))
        snap_services = services.get("snap_services", {})
        if failed:
            lines.append(f"Failed services: {', '.join(failed)}")
        # Notable system daemons users commonly ask about
        _notable = [
            "snapd", "dockerd", "sshd", "NetworkManager", "systemd-resolved",
            "cups", "bluetoothd", "gdm3", "lightdm", "apache2", "nginx",
            "mysql", "mariadb", "postgresql", "redis-server", "mongod",
            "pipewire", "pulseaudio", "avahi-daemon", "openvpn", "wpa_supplicant",
        ]
        running_notable = [s for s in _notable if s in active_procs]
        if running_notable:
            lines.append(f"Running system services: {', '.join(running_notable)}")
        if snap_services:
            parts = [
                f"{snap} ({', '.join(procs)})"
                for snap, procs in snap_services.items()
            ]
            lines.append(f"Running snap services: {', '.join(parts)}")

        # ── Form factor / power ───────────────────────────────────────────────
        power = self.system_info.get("power", {})
        form_factor = power.get("form_factor", "")
        if form_factor and form_factor != "unknown":
            lines.append(f"Form factor: {form_factor}")
        if power.get("battery_present"):
            pct = power.get("battery_pct")
            status = power.get("battery_status", "")
            health = power.get("battery_health_pct")
            bat_str = f"Battery: {pct}% ({status})" if pct is not None else f"Battery: {status}"
            if health and health < 80:
                bat_str += f", health {health}% (degraded)"
            elif health:
                bat_str += f", health {health}%"
            lines.append(bat_str)

        # ── CPU detail ────────────────────────────────────────────────────────
        hw = self.system_info.get("hardware", {})
        cpu_detail = self.system_info.get("cpu_detail", {})
        cpu_name = hw.get("cpu", "")
        logical = cpu_detail.get("logical_cpus") or hw.get("cpu_cores", 0)
        phys = cpu_detail.get("physical_cores")
        sockets = cpu_detail.get("sockets", 1)
        ht = cpu_detail.get("hyperthreading")
        governor = cpu_detail.get("governor", "")
        is_vm = cpu_detail.get("is_vm", False)

        cpu_parts = []
        if cpu_name:
            cpu_clean = _re.sub(r"\(R\)|\(TM\)|CPU\s+", " ", cpu_name)
            cpu_clean = _re.sub(r"\s+@\s+[\d.]+\s*GHz", "", cpu_clean)
            cpu_clean = _re.sub(r"\s+", " ", cpu_clean).strip()
            cpu_parts.append(cpu_clean)
        topo_parts = []
        if logical:
            topo_parts.append(f"{logical} logical")
        if phys and phys != logical:
            topo_parts.append(f"{phys} physical")
        if sockets > 1:
            topo_parts.append(f"{sockets} sockets")
        if topo_parts:
            cpu_parts.append(f"({', '.join(topo_parts)})")
        if ht:
            cpu_parts.append("HT")
        if governor:
            cpu_parts.append(f"governor={governor}")
        if is_vm:
            cpu_parts.append("VM")
        if cpu_parts:
            lines.append(f"CPU: {' '.join(cpu_parts)}")

        l3 = cpu_detail.get("l3_cache_kb")
        if l3:
            lines.append(f"L3 cache: {l3 // 1024} MB" if l3 >= 1024 else f"L3 cache: {l3} KB")

        hot_zones = cpu_detail.get("hot_zones", [])
        if hot_zones:
            zone_strs = [f"{z['type']} {z['temp_c']}°C" for z in hot_zones]
            lines.append(f"Thermal alert: {', '.join(zone_strs)}")

        gpu_name = self._get_gpu()
        if gpu_name:
            lines.append(f"GPU: {gpu_name}")
        gpu_detail = self.system_info.get("gpu_detail", {})
        for card in gpu_detail.get("cards", []):
            parts = []
            if card.get("busy_pct") is not None:
                parts.append(f"{card['busy_pct']}% busy")
            if card.get("sclk_mhz"):
                parts.append(f"{card['sclk_mhz']} MHz")
            if card.get("power_w"):
                parts.append(f"{card['power_w']}W")
            if card.get("temp_c"):
                parts.append(f"{card['temp_c']}°C")
            if card.get("vram_total_mb"):
                vram_used = card.get("vram_used_mb", 0)
                vram_total = card["vram_total_mb"]
                parts.append(f"VRAM {vram_used}/{vram_total}MB")
            if card.get("gtt_total_gb"):
                gtt_used = card.get("gtt_used_gb", 0)
                gtt_total = card["gtt_total_gb"]
                parts.append(f"GTT {gtt_used}/{gtt_total}G")
            if parts:
                lines.append(f"  GPU stats: {', '.join(parts)}")

        # ── Memory ────────────────────────────────────────────────────────────
        mem = self.system_info.get("memory", {})
        if mem:
            total = mem.get("total_gb") or hw.get("memory_gb", 0)
            used = mem.get("used_gb", 0)
            pct = mem.get("used_pct", 0)
            cache = mem.get("cache_gb", 0)
            swap_total = mem.get("swap_total_gb", 0)
            swap_used = mem.get("swap_used_gb", 0)
            swap_pct = mem.get("swap_used_pct", 0)
            if total:
                mem_line = f"Memory: {used}G / {total}G used ({pct}%)"
                if cache > 0.1:
                    mem_line += f", {cache}G reclaimable cache"
                lines.append(mem_line)
            if swap_total:
                lines.append(f"Swap: {swap_used}G / {swap_total}G used ({swap_pct}%)")
            psi_some = mem.get("pressure_some_avg10", 0)
            psi_full = mem.get("pressure_full_avg10", 0)
            if psi_some >= 5:
                lines.append(
                    f"Memory pressure: some={psi_some:.1f}% full={psi_full:.1f}% (10s avg, HIGH)"
                )
            swappiness = mem.get("swappiness")
            if swappiness is not None:
                lines.append(f"vm.swappiness: {swappiness}")
        elif hw.get("memory_gb"):
            lines.append(f"RAM: {hw['memory_gb']} GB")

        # ── Storage ───────────────────────────────────────────────────────────
        storage = self.system_info.get("storage", {})
        if storage:
            drives = storage.get("drives", [])
            if drives:
                drive_strs = []
                for d in drives:
                    s = f"{d['name']} ({d['type']}, {d['size_gb']}G"
                    if d.get("model"):
                        s += f", {d['model']}"
                    s += ")"
                    drive_strs.append(s)
                flags = []
                if storage.get("lvm"):
                    flags.append("LVM")
                if storage.get("luks"):
                    flags.append("LUKS")
                if storage.get("efi"):
                    flags.append("EFI")
                drive_line = f"Drives: {', '.join(drive_strs)}"
                if flags:
                    drive_line += f" [{', '.join(flags)}]"
                lines.append(drive_line)

            raid = storage.get("raid")
            if raid:
                arr_strs = []
                for arr in raid.get("arrays", []):
                    s = f"{arr['name']} {arr.get('level', '')} [{arr.get('state', '')}]"
                    if arr.get("degraded"):
                        s += " DEGRADED"
                    arr_strs.append(s)
                if arr_strs:
                    lines.append(f"RAID: {', '.join(arr_strs)}")

            mounts = [
                m for m in storage.get("mounts", [])
                if m.get("size_gb") is not None and m.get("fstype") != "tmpfs"
            ]
            if mounts:
                lines.append("Mounts:")
                for m in mounts:
                    opts = f" [{','.join(m['options'])}]" if m.get("options") else ""
                    lines.append(
                        f"  {m['mountpoint']:<20} {m['fstype']:<8} "
                        f"{m['size_gb']}G total, {m.get('used_gb', 0)}G used "
                        f"({m.get('used_pct', 0)}%){opts}"
                    )

            for sw in storage.get("swap", []):
                lines.append(
                    f"Swap device: {sw['device']} {sw['size_gb']}G ({sw['used_pct']}% used)"
                )
            for z in storage.get("zram", []):
                lines.append(
                    f"zram: {z['name']} {z['size_gb']}G ({z['mem_used_mb']}MB memory used)"
                )

        # ── Process intelligence ──────────────────────────────────────────────
        procs = self.system_info.get("processes", {})
        if procs:
            load_1 = procs.get("load_1", 0)
            load_5 = procs.get("load_5", 0)
            load_15 = procs.get("load_15", 0)
            load_per_cpu = procs.get("load_per_cpu", 0)
            if load_1:
                load_str = f"Load average: {load_1} {load_5} {load_15} (1/5/15 min)"
                if load_per_cpu > 0.7:
                    load_str += f" — {load_per_cpu:.2f} per CPU (HIGH)"
                lines.append(load_str)

            zombie = procs.get("zombie_count", 0)
            dstate = procs.get("dstate_count", 0)
            dnames = procs.get("dstate_names", [])
            if zombie:
                lines.append(f"Zombie processes: {zombie}")
            if dstate:
                dname_str = f" ({', '.join(dnames[:3])})" if dnames else ""
                lines.append(f"D-state (blocked) processes: {dstate}{dname_str}")

            top_rss = procs.get("top_rss", [])
            if top_rss:
                rss_strs = [f"{p['name']} {p['rss_mb']}MB" for p in top_rss[:5]]
                lines.append(f"Top RSS: {', '.join(rss_strs)}")

            high_oom = procs.get("high_oom", [])
            if high_oom:
                oom_strs = [f"{p['name']} (score {p['oom_score']})" for p in high_oom]
                lines.append(f"High OOM risk: {', '.join(oom_strs)}")

            cpu_psi = procs.get("cpu_pressure_some", 0)
            io_psi = procs.get("io_pressure_some", 0)
            if cpu_psi >= 5 or io_psi >= 5:
                psi_parts = []
                if cpu_psi >= 5:
                    psi_parts.append(f"CPU={cpu_psi:.1f}%")
                if io_psi >= 5:
                    psi_parts.append(f"IO={io_psi:.1f}%")
                lines.append(f"Resource pressure (10s avg): {', '.join(psi_parts)}")

        # ── Network ───────────────────────────────────────────────────────────
        network = self.system_info.get("network", {})
        ifaces = network.get("interfaces", [])
        active_ifaces = [
            i for i in ifaces
            if i.get("operstate") == "up" and not i.get("is_container_bridge")
        ]
        if active_ifaces:
            iface_parts = []
            for i in active_ifaces:
                kind = "wifi" if i["is_wifi"] else ("VPN" if i["is_vpn"] else "ethernet")
                s = f"{i['name']} ({kind}"
                if i.get("speed_mbps"):
                    s += f", {i['speed_mbps']}Mbps"
                s += ")"
                iface_parts.append(s)
            lines.append(f"Network interfaces: {', '.join(iface_parts)}")

        return "\n".join(lines)

    # ── Live lookup helpers (used by chat_engine tool calls) ──────────────────

    def get_snap_store_version(self, package_name: str) -> Optional[str]:
        """
        Return the version available in the store for the snap's tracking channel.

        For installed snaps: reads the tracking channel from the local snapd
        response (/v2/snaps/{name} via desktop-launch) then queries the online
        Snap Store for the version in that channel.

        For uninstalled snaps: queries the Snap Store directly and returns the
        latest/stable version.
        """
        tracking = "latest/stable"

        # For installed snaps, read the tracking channel from local snapd
        local = _snapd_get(f"/v2/snaps/{package_name}")
        if local and local.get("status-code") == 200:
            tracking = local["result"].get("tracking-channel", "latest/stable")

        store_info = _snap_store_info(package_name)
        if store_info:
            return _store_channel_version(store_info, tracking)
        return None

    def is_snap_available(self, package_name: str) -> bool:
        """Check if a snap exists in the Snap Store (works for installed and uninstalled snaps)."""
        return _snap_store_info(package_name) is not None

    def is_snap_installed(self, package_name: str) -> bool:
        """
        Check if a snap is installed via snapd REST API (live query).
        Falls back to the in-memory cache if the socket is unavailable.
        """
        data = _snapd_get(f"/v2/snaps/{package_name}")
        if data is not None:
            return data.get("status-code") == 200
        # Fall back to cache
        snap_packages = self.system_info.get("packages", {}).get("snap_packages", [])
        return any(pkg["name"] == package_name for pkg in snap_packages)

    def is_apt_available(self, package_name: str) -> bool:
        """
        Check if a package is available in apt by scanning apt list files.
        Requires system-files-dpkg interface.
        """
        # Check in-memory cache first (populated at startup from dpkg status)
        available_apt = self.system_info.get("packages", {}).get("available_apt", [])
        if available_apt:
            return package_name in available_apt
        # Live scan of apt lists
        return _is_in_apt_lists(package_name)

    def get_running_daemons(self) -> List[str]:
        """Return all current PPID=1 process names (live /proc scan)."""
        ppid1: set = set()
        try:
            for pid_dir in Path("/proc").iterdir():
                if not pid_dir.name.isdigit():
                    continue
                try:
                    status_text = (pid_dir / "status").read_text()
                    ppid = comm = None
                    for line in status_text.splitlines():
                        if line.startswith("PPid:"):
                            ppid = int(line.split()[1])
                        elif line.startswith("Name:"):
                            comm = line.split()[1]
                    if ppid == 1 and comm:
                        ppid1.add(comm)
                except (PermissionError, FileNotFoundError, OSError):
                    continue
        except Exception:
            pass
        return sorted(ppid1)

    def check_service_status(self, service_name: str) -> Dict:
        """
        Check if a daemon is running by scanning PPID=1 processes in /proc.
        systemctl cannot reach D-Bus in strict snap confinement.
        Tries the given name, namedaemon form, and de-daemonised form
        (e.g. ssh→sshd, sshd→ssh).
        """
        base = service_name.removesuffix(".service")
        candidates = {base, base + "d", base.rstrip("d")}

        running = self.get_running_daemons()
        found = next((p for p in running if p in candidates), None)

        return {
            "active_state": "active" if found else "inactive",
            "process_name": found or base,
            "note": (
                "Detected via /proc scan. "
                "For enabled/disabled state run: "
                f"systemctl is-enabled {service_name}"
            ),
        }

    def list_failed_services(self) -> List[str]:
        """
        Failed services cannot be detected from /proc (they are not running).
        D-Bus access (blocked in snap confinement) would be required.
        """
        return []

    def is_apt_installed(self, package_name: str) -> bool:
        """Check if a debian package is installed (uses in-memory cache)."""
        if not self.system_info:
            self.load_or_collect()
        apt_packages = self.system_info.get("packages", {}).get("apt_packages", [])
        return package_name in apt_packages

    def get_hardware_tier(self):
        """
        Categorizes hardware into 4 tiers for model optimization.
        Tiers: high_end, mid_intel, balanced_amd, legacy
        """
        cpu_info = ""
        try:
            # Get CPU model name on Linux
            cpu_info = subprocess.check_output("grep 'model name' /proc/cpuinfo | head -1", shell=True).decode().lower()
        except Exception:
            import platform
            cpu_info = platform.processor().lower()

        # Get Total RAM in GB
        total_ram_gb = 0
        try:
            with open('/proc/meminfo', 'r') as f:
                for line in f:
                    if "MemTotal" in line:
                        total_ram_gb = int(line.split()[1]) / (1024 * 1024)
                        break
        except Exception:
            total_ram_gb = 8 # Default assumption

        # Tier Logic [Inference]
        if "strix" in cpu_info or "ryzen ai" in cpu_info:
            return "high_end"
        elif "intel" in cpu_info and ("ultra" in cpu_info or "core i" in cpu_info):
            return "mid_intel"
        elif "amd" in cpu_info and total_ram_gb >= 16:
            return "balanced_amd"
        else:
            return "legacy"


def main():
    """Test the system indexer"""
    indexer = SystemIndexer()
    info = indexer.collect_system_info()

    console.print("\n📊 System Information:", style="#E95420 bold")
    console.print(json.dumps(info, indent=2))

    console.print("\n📋 Context Summary:", style="#E95420 bold")
    console.print(indexer.get_context_summary())


if __name__ == "__main__":
    main()
