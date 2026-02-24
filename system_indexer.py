#!/usr/bin/env python3
"""
System Indexer - Collects system information for context-aware assistance
"""

import json
import subprocess
import platform
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

console = Console()


class SystemIndexer:
    """Collects and caches system information"""

    def __init__(self, cache_dir: Path = None):
        self.cache_dir = cache_dir or Path.home() / ".cache" / "ask-ubuntu"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.cache_dir / "system_info.json"
        self.system_info: Dict = {}

    def load_or_collect(self, force_refresh: bool = False) -> Dict:
        """Load cached system info or collect new"""
        if not force_refresh and self.cache_file.exists():
            try:
                with open(self.cache_file, "r") as f:
                    self.system_info = json.load(f)
                    # Check if cache is less than 1 hour old
                    cached_time = datetime.fromisoformat(
                        self.system_info.get("collected_at", "2000-01-01")
                    )
                    age_hours = (datetime.now() - cached_time).total_seconds() / 3600
                    if age_hours < 1:
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
                "os": self._get_os_info(),
                "desktop": self._get_desktop_info(),
                "packages": self._get_package_info(),
                "services": self._get_services_info(),
                "hardware": self._get_hardware_info(),
            }

            progress.update(task, completed=True)

        # Save to cache
        with open(self.cache_file, "w") as f:
            json.dump(self.system_info, f, indent=2)

        console.print("✓ System information collected", style="green")
        return self.system_info

    def _get_os_info(self) -> Dict:
        """Get OS and kernel information"""
        info = {}

        try:
            # Ubuntu version
            result = subprocess.run(
                ["lsb_release", "-a"], capture_output=True, text=True, timeout=2
            )
            if result.returncode == 0:
                for line in result.stdout.split("\n"):
                    if "Description:" in line:
                        info["ubuntu_version"] = line.split(":", 1)[1].strip()
                    elif "Release:" in line:
                        info["ubuntu_release"] = line.split(":", 1)[1].strip()
                    elif "Codename:" in line:
                        info["codename"] = line.split(":", 1)[1].strip()
        except:
            pass

        try:
            info["kernel"] = platform.release()
            info["architecture"] = platform.machine()
        except:
            pass

        return info

    def _get_desktop_info(self) -> Dict:
        """Get desktop environment information"""
        info = {}

        try:
            import os

            info["desktop_session"] = os.environ.get("XDG_CURRENT_DESKTOP", "")
            info["session_type"] = os.environ.get(
                "XDG_SESSION_TYPE", ""
            )  # wayland or x11
            info["shell"] = os.environ.get("SHELL", "").split("/")[-1]
        except:
            pass

        return info

    def _get_package_info(self) -> Dict:
        """Get installed package information"""
        info = {
            "apt_packages": [],
            "snap_packages": [],
            "total_apt": 0,
            "total_snap": 0,
            "available_snaps": [],
            "available_apt": [],
        }

        # Get snap packages (fast and commonly queried)
        try:
            result = subprocess.run(
                ["snap", "list"], capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                lines = result.stdout.strip().split("\n")[1:]  # Skip header
                info["snap_packages"] = [
                    {"name": line.split()[0], "version": line.split()[1]}
                    for line in lines
                    if line
                ]
                info["total_snap"] = len(info["snap_packages"])
        except:
            pass

        # Get available snaps from cache
        try:
            snap_names_file = Path("/var/cache/snapd/names")
            if snap_names_file.exists():
                with open(snap_names_file, "r") as f:
                    info["available_snaps"] = [
                        line.strip() for line in f if line.strip()
                    ]
        except:
            pass

        # Get installed and available apt packages via python-apt
        try:
            import apt
            cache = apt.Cache()
            info["apt_packages"] = sorted(
                pkg.name for pkg in cache if pkg.is_installed
            )
            info["total_apt"] = len(info["apt_packages"])
            info["available_apt"] = sorted(pkg.name for pkg in cache)
        except Exception:
            pass

        # Fallback: count installed deb packages via dpkg-query if python-apt unavailable
        if not info["total_apt"]:
            try:
                result = subprocess.run(
                    ["dpkg-query", "-f", ".\n", "-W"],
                    capture_output=True, text=True, timeout=10,
                )
                if result.returncode == 0:
                    info["total_apt"] = result.stdout.count(".")
            except Exception:
                pass

        return info

    def _get_services_info(self) -> Dict:
        """Get information about key system services"""
        info = {
            "snap_active": False,
            "docker_active": False,
            "ssh_active": False,
        }

        services = ["snapd", "docker", "ssh"]
        for service in services:
            try:
                result = subprocess.run(
                    ["systemctl", "is-active", service],
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                info[f"{service}_active"] = (
                    result.returncode == 0 and result.stdout.strip() == "active"
                )
            except:
                pass

        return info

    def _get_hardware_info(self) -> Dict:
        """Get basic hardware information"""
        info = {}

        try:
            # CPU info
            with open("/proc/cpuinfo", "r") as f:
                lines = f.readlines()
                for line in lines:
                    if "model name" in line:
                        info["cpu"] = line.split(":", 1)[1].strip()
                        break
                info["cpu_cores"] = len([l for l in lines if l.startswith("processor")])
        except:
            pass

        try:
            # Memory info
            with open("/proc/meminfo", "r") as f:
                for line in f:
                    if "MemTotal" in line:
                        mem_kb = int(line.split()[1])
                        info["memory_gb"] = round(mem_kb / (1024 * 1024), 1)
                        break
        except:
            pass

        try:
            # Disk space
            result = subprocess.run(
                ["df", "-h", "/"], capture_output=True, text=True, timeout=2
            )
            if result.returncode == 0:
                lines = result.stdout.strip().split("\n")
                if len(lines) > 1:
                    parts = lines[1].split()
                    info["disk_total"] = parts[1]
                    info["disk_used"] = parts[2]
                    info["disk_available"] = parts[3]
                    if len(parts) > 4:
                        info["disk_percent"] = parts[4]
        except:
            pass

        return info

    # ── Neofetch-style helpers ────────────────────────────────────────────────

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
        """Get machine vendor + product name from DMI."""
        try:
            vendor = Path("/sys/class/dmi/id/sys_vendor").read_text().strip()
            product = Path("/sys/class/dmi/id/product_name").read_text().strip()
            # Drop vendor prefix if it's already in the product name
            if product.startswith(vendor):
                return product
            return f"{vendor} {product}".strip()
        except Exception:
            return ""

    def _get_gpu(self) -> str:
        """Best-effort GPU detection via lspci."""
        try:
            result = subprocess.run(
                ["lspci"], capture_output=True, text=True, timeout=3
            )
            if result.returncode != 0:
                return ""
            for line in result.stdout.splitlines():
                low = line.lower()
                if any(k in low for k in ("vga", "3d controller", "display controller")):
                    # "00:02.0 VGA compatible controller: Intel Iris Xe Graphics (rev 01)"
                    desc = line.split(":", 2)[-1].strip()
                    desc = desc.split("(rev")[0].strip()
                    return desc[:60]
        except Exception:
            pass
        return ""

    def _get_used_memory_gb(self) -> Optional[float]:
        """Read current used RAM from /proc/meminfo (always live)."""
        try:
            meminfo = {}
            with open("/proc/meminfo", "r") as f:
                for line in f:
                    k, v = line.split(":", 1)
                    meminfo[k.strip()] = int(v.split()[0])
            total_kb = meminfo.get("MemTotal", 0)
            avail_kb = meminfo.get("MemAvailable", 0)
            used_kb = total_kb - avail_kb
            return round(used_kb / (1024 * 1024), 1)
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

        def add(label, value):
            if value:
                fields.append({"label": label, "value": value})

        # OS
        ver = os_info.get("ubuntu_version", "")
        arch = os_info.get("architecture", "")
        add("OS", f"{ver} {arch}".strip())

        # Host
        add("Host", self._get_host())

        # Kernel
        add("Kernel", os_info.get("kernel", ""))

        # Uptime (live)
        add("Uptime", self._get_uptime())

        # Shell
        add("Shell", desktop.get("shell", ""))

        # Desktop environment
        de = desktop.get("desktop_session", "")
        session = desktop.get("session_type", "")
        if de:
            # "ubuntu:GNOME" → "GNOME"; "Unity" is Ubuntu's legacy id for GNOME
            if ":" in de:
                de = de.split(":")[-1]
            if de.lower() == "unity":
                de = "GNOME"
            add("DE", f"{de} ({session.capitalize()})" if session else de)

        # CPU — clean up verbose model strings
        cpu = hw.get("cpu", "")
        cores = hw.get("cpu_cores", 0)
        if cpu:
            cpu = re.sub(r"\(R\)|\(TM\)|CPU\s+", " ", cpu)
            cpu = re.sub(r"\s+@\s+[\d.]+\s*GHz", "", cpu)
            cpu = re.sub(r"\s+", " ", cpu).strip()
        if cpu or cores:
            add("CPU", f"{cpu} ({cores})" if (cpu and cores) else cpu or f"{cores} cores")

        # GPU
        add("GPU", self._get_gpu())

        # Memory (used / total, live)
        total_gb = hw.get("memory_gb")
        if total_gb:
            used_gb = self._get_used_memory_gb()
            if used_gb is not None:
                add("Memory", f"{used_gb} used / {total_gb} GB")
            else:
                add("Memory", f"{total_gb} GB total")

        # Disk
        disk_used  = hw.get("disk_used", "")
        disk_total = hw.get("disk_total", "")
        disk_pct   = hw.get("disk_percent", "")
        if disk_used and disk_total:
            val = f"{disk_used} used / {disk_total}"
            if disk_pct:
                val += f" ({disk_pct})"
            add("Disk", val)

        # Packages (counts only, separate rows for deb and snap)
        # Deb count: query live via dpkg-query (fast, bypasses stale cache)
        deb_n = 0
        try:
            result = subprocess.run(
                ["dpkg-query", "-f", ".\n", "-W"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                deb_n = result.stdout.count(".")
        except Exception:
            pass
        if not deb_n:
            deb_n = packages.get("total_apt", 0)

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

        # OS Info
        os_info = self.system_info.get("os", {})
        if os_info.get("ubuntu_version"):
            lines.append(
                f"OS: {os_info['ubuntu_version']} ({os_info.get('architecture', 'unknown')})"
            )
        if os_info.get("kernel"):
            lines.append(f"Kernel: {os_info['kernel']}")

        # Desktop
        desktop = self.system_info.get("desktop", {})
        if desktop.get("desktop_session"):
            session_type = desktop.get("session_type", "")
            lines.append(
                f"Desktop: {desktop['desktop_session']}"
                + (f" ({session_type})" if session_type else "")
            )
        if desktop.get("shell"):
            lines.append(f"Shell: {desktop['shell']}")

        # Packages
        packages = self.system_info.get("packages", {})
        if packages.get("total_snap"):
            lines.append(f"Snap packages: {packages['total_snap']} installed")
            snap_list = [
                f"{pkg['name']} ({pkg['version']})"
                for pkg in packages.get("snap_packages", [])
            ]
            if snap_list:
                lines.append(f"Installed snaps: {', '.join(snap_list[:20])}"
                             + (" ..." if len(snap_list) > 20 else ""))

        if packages.get("total_apt"):
            lines.append(f"Apt packages installed: {packages['total_apt']} (use check_apt tool for specific packages)")

        # Available packages — counts only; use tools for specific lookups
        available_snaps = packages.get("available_snaps", [])
        if available_snaps:
            lines.append(f"Snap store packages available: {len(available_snaps)} (use check_snap tool to query)")

        # Services
        services = self.system_info.get("services", {})
        active_services = [k.replace("_active", "") for k, v in services.items() if v]
        if active_services:
            lines.append(f"Active services: {', '.join(active_services)}")

        # Hardware
        hw = self.system_info.get("hardware", {})
        if hw.get("memory_gb"):
            lines.append(f"RAM: {hw['memory_gb']} GB")
        if hw.get("cpu_cores"):
            lines.append(f"CPU: {hw['cpu_cores']} cores")

        return "\n".join(lines)

    def is_snap_available(self, package_name: str) -> bool:
        """Check if a package is available as a snap"""
        if not self.system_info:
            self.load_or_collect()

        available_snaps = self.system_info.get("packages", {}).get(
            "available_snaps", []
        )
        return package_name in available_snaps

    def is_snap_installed(self, package_name: str) -> bool:
        """Check if a snap package is installed"""
        if not self.system_info:
            self.load_or_collect()

        snap_packages = self.system_info.get("packages", {}).get("snap_packages", [])
        return any(pkg["name"] == package_name for pkg in snap_packages)

    def is_apt_available(self, package_name: str) -> bool:
        """Check if a package is available in the apt cache"""
        if not self.system_info:
            self.load_or_collect()

        available_apt = self.system_info.get("packages", {}).get("available_apt", [])
        return package_name in available_apt

    def is_apt_installed(self, package_name: str) -> bool:
        """Check if a debian package is installed"""
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
