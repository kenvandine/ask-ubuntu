#!/usr/bin/env python3
"""
System Indexer - Collects system information for context-aware assistance

Snap-confinement notes
─────────────────────
• snap / snapd queries  → snapd REST API via Unix socket /run/snapd.socket
                          (requires snapd-control interface)
• apt / dpkg queries    → read /var/lib/dpkg/status and /var/lib/apt/lists
                          (requires system-files-dpkg interface)
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

_SNAPD_SOCKET = "/run/snapd.socket"


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

_DPKG_STATUS = "/var/lib/dpkg/status"
_APT_LISTS_DIR = "/var/lib/apt/lists"


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
        Detect active services by scanning /proc/*/comm.
        Requires system-observe interface (read /proc).
        """
        info: Dict[str, bool] = {
            "snap_active": False,
            "docker_active": False,
            "ssh_active": False,
        }
        _service_procs = {
            "snapd": "snap_active",
            "dockerd": "docker_active",
            "sshd": "ssh_active",
        }
        try:
            proc_base = Path("/proc")
            for pid_dir in proc_base.iterdir():
                if not pid_dir.name.isdigit():
                    continue
                try:
                    comm = (pid_dir / "comm").read_text().strip()
                    if comm in _service_procs:
                        info[_service_procs[comm]] = True
                except (PermissionError, FileNotFoundError, OSError):
                    continue
        except Exception:
            pass
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

    def get_neofetch_fields(self) -> list:
        """Return system info as a list of {label, value} dicts for the sidebar."""
        if not self.system_info:
            self.load_or_collect()

        import re
        fields = []
        os_info  = self.system_info.get("os", {})
        desktop  = self.system_info.get("desktop", {})
        hw       = self.system_info.get("hardware", {})
        packages = self.system_info.get("packages", {})

        def add(label: str, value) -> None:
            if value:
                fields.append({"label": label, "value": value})

        ver  = os_info.get("ubuntu_version", "")
        arch = os_info.get("architecture", "")
        add("OS", f"{ver} {arch}".strip())
        add("Host", self._get_host())
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
        cores = hw.get("cpu_cores", 0)
        if cpu:
            cpu = re.sub(r"\(R\)|\(TM\)|CPU\s+", " ", cpu)
            cpu = re.sub(r"\s+@\s+[\d.]+\s*GHz", "", cpu)
            cpu = re.sub(r"\s+", " ", cpu).strip()
        if cpu or cores:
            add("CPU", f"{cpu} ({cores})" if (cpu and cores) else cpu or f"{cores} cores")

        add("GPU", self._get_gpu())

        total_gb = hw.get("memory_gb")
        if total_gb:
            used_gb = self._get_used_memory_gb()
            if used_gb is not None:
                add("Memory", f"{used_gb} used / {total_gb} GB")
            else:
                add("Memory", f"{total_gb} GB total")

        disk_used  = hw.get("disk_used", "")
        disk_total = hw.get("disk_total", "")
        disk_pct   = hw.get("disk_percent", "")
        if disk_used and disk_total:
            val = f"{disk_used} used / {disk_total}"
            if disk_pct:
                val += f" ({disk_pct})"
            add("Disk", val)

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
        active_services = [k.replace("_active", "") for k, v in services.items() if v]
        if active_services:
            lines.append(f"Active services: {', '.join(active_services)}")

        hw = self.system_info.get("hardware", {})
        if hw.get("memory_gb"):
            lines.append(f"RAM: {hw['memory_gb']} GB")
        if hw.get("cpu_cores"):
            lines.append(f"CPU: {hw['cpu_cores']} cores")

        return "\n".join(lines)

    # ── Live lookup helpers (used by chat_engine tool calls) ──────────────────

    def is_snap_available(self, package_name: str) -> bool:
        """
        Check if a package is available in the snap store via snapd REST API.
        Falls back to the in-memory cache if the socket is unavailable.
        """
        data = _snapd_get(f"/v2/find?name={package_name}")
        if data and data.get("status") == "OK":
            results = data.get("result", [])
            return any(s.get("name") == package_name for s in results)
        # Fall back to cache (populated from snap list at startup)
        available = self.system_info.get("packages", {}).get("available_snaps", [])
        return package_name in available

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

    def is_apt_installed(self, package_name: str) -> bool:
        """Check if a debian package is installed (uses in-memory cache)."""
        if not self.system_info:
            self.load_or_collect()
        apt_packages = self.system_info.get("packages", {}).get("apt_packages", [])
        return package_name in apt_packages


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
