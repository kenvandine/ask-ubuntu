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
        except:
            pass

        return info

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
                lines.append(f"Installed snaps: {', '.join(snap_list)}")

        if packages.get("apt_packages"):
            lines.append(f"Installed apt packages ({packages['total_apt']} total): {', '.join(packages['apt_packages'])}")

        # Available packages
        available_snaps = packages.get("available_snaps", [])
        if available_snaps:
            lines.append(f"Available snaps in store ({len(available_snaps)} total): {', '.join(available_snaps)}")

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
