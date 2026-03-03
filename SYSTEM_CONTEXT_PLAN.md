# System Context Enrichment Plan

Goal: give the LLM a complete, accurate picture of the user's system so it can
provide high-quality, specific guidance rather than generic advice.

## Interface access map

| Interface | Key paths unlocked |
|---|---|
| `hardware-observe` | `/sys/{block,bus,class,devices,firmware}/{,**}` → covers block devices, net interfaces, thermal, power supply, CPU topology, DMI, NVMe, PCI |
| `system-observe` | `/proc/*/stat`, `statm`, `status`, `cmdline`, `io`, `oom_score`, `smaps_rollup`; `/proc/diskstats`, `mdstat`, `stat`, `vmstat`, `pressure/*`, `swappiness`, `slabinfo`; `/sys/fs/{btrfs,ext4}/**`; `/proc/spl/kstat/zfs/**`; DBus → systemd `ListUnits`/`GetUnit` |
| `mount-observe` | `/proc/mounts`, `/proc/swaps`, `/etc/fstab`, `/etc/mtab`, `/sys/devices/*/block/**`, ZFS arcstats |
| `network-observe` | NOT in snap — not needed for sysfs interface info |
| `hardware-observe` (net) | `/sys/class/net/**` → names, operstate, speed, type, MAC, wireless/bridge/bonding detection |

**Network clarification**: `/sys/class/net/**` is covered by `hardware-observe`'s
broad `/sys/{...class...}/{,**}` rule. IP addresses, TCP connection counts, and
traffic stats live in `/proc/[pid]/net/**` which requires `network-observe` (not
currently in the snap). We collect what we can from sysfs.

---

## 1. Storage topology

**Interface**: `hardware-observe` + `mount-observe`

### Drive classification (`/sys/class/block/`)
- `{dev}/queue/rotational` → 0 = SSD/NVMe, 1 = HDD
- `{dev}/device/model` → SATA drive model string
- `/sys/class/nvme/nvme*/model` → NVMe model
- `{dev}/size` → size in 512-byte sectors
- Device name prefix: `nvme*` = NVMe, `sd*` = SATA/USB, `vd*` = virtual, `mmcblk*` = eMMC/SD card
- Exclude: `loop*`, `dm-*`, `md*`, `ram*`, `zram*`

### LVM / device-mapper (`/sys/class/block/dm-*/`)
- `dm/name` file → mapper name reveals purpose:
  - `ubuntu--vg-ubuntu--lv` pattern → LVM logical volume
  - `*_crypt` → LUKS encrypted device
  - `mpatha` etc. → multipath
- Presence of any `dm-*` → device mapper in use

### Software RAID (`/proc/mdstat`)
- Already readable via `system-observe`
- Parse: personalities, array names, member drives, state (`[UUU]` vs `[UU_]` = degraded)
- Degraded RAID = high-priority warning in context

### Zswap / zram (`/sys/class/block/zram*`)
- `disksize` → configured size
- `mem_used_total` → actual compressed memory used
- Presence → Ubuntu's default compressed swap is active

### All mount points (`/proc/mounts` via `mount-observe`)
- Parse all mounts, filter to real filesystems
- **Keep**: ext4, btrfs, xfs, vfat, exfat, ntfs, nfs*, cifs, fuse.*, overlay, zfs, tmpfs (user-visible ones like /tmp, /dev/shm)
- **Drop**: devtmpfs, sysfs, proc, cgroup*, devpts, securityfs, efivarfs, debugfs, bpf, configfs, pstore, autofs
- Per mount: source device, mount point, filesystem type, key options (ro, noatime, compress=, errors=)
- Cross-reference device → drive type from block classification above

### Per-mount disk usage
- `os.statvfs()` on every real mount point (already done for `/`, expand to all)
- Flag mounts > 85% full for special mention in context

### Swap devices (`/proc/swaps` via `mount-observe`)
- All active swap: partition path, size, usage
- Distinguishes: partition swap vs swap file vs zram

### fstab (`/etc/fstab` via `mount-observe`)
- Shows intended layout: reveals if `/home` is separate, what UUIDs map to what, `noatime` etc.
- Useful for "how do I resize my partition" (need to know the layout)

### EFI vs BIOS
- `/sys/firmware/efi/` exists → EFI system (changes bootloader commands entirely)
- Via `hardware-observe`

### Filesystem-specific info (`system-observe`)
- `/sys/fs/ext4/{dev}/errors_count` → ext4 filesystem errors
- `/sys/fs/btrfs/{uuid}/` → btrfs device stats, balance status
- `/proc/spl/kstat/zfs/{pool}/` → ZFS pool health

**Guidance improvements**: "How do I extend my volume?" (LVM vs partition vs ZFS), TRIM advice
(SSD only), defrag advice (never ext4/btrfs, periodic xfs_fsr), "my disk is slow" diagnosis,
degraded RAID warning, LUKS unlock help.

---

## 2. Memory detail

**Interface**: `system-observe` (already have)

### Full `/proc/meminfo` parse
Currently only reads `MemTotal`. Add:

| Field | Meaning | Usage |
|---|---|---|
| `MemAvailable` | Real usable free memory | "You have X GB actually free" |
| `Buffers` | Block device read-ahead cache | Reclaimable |
| `Cached` | Page cache | Reclaimable, explains "high memory use" |
| `SwapTotal` / `SwapFree` | Swap configured/available | Swap management advice |
| `SwapCached` | Data in both RAM and swap | Non-zero = swap actively used |
| `Shmem` | Shared memory / tmpfs | Docker, browsers, tmpfs mounts |
| `SReclaimable` | Reclaimable kernel slab | Can be freed under pressure |
| `SUnreclaim` | Non-reclaimable slab | Kernel overhead |
| `Dirty` | Waiting to be written to disk | Large value + slow disk = data loss risk |
| `HugePages_Total` / `Free` | Huge page pool | Database tuning (Postgres, etc.) |

### Derived metrics
- `mem_used_pct = (MemTotal - MemAvailable) / MemTotal * 100`
- `swap_used_pct = (SwapTotal - SwapFree) / SwapTotal * 100` (if SwapTotal > 0)
- `cache_pct = (Buffers + Cached) / MemTotal * 100` — helps explain apparent high usage

### PSI memory pressure (`/proc/pressure/memory` via `system-observe`)
- `some avg10` / `full avg10` — fraction of time tasks stalled on memory in last 10s
- Non-zero `full` → system is memory-bound right now

### Swappiness (`/proc/sys/vm/swappiness` via `system-observe`)
- Default 60 on desktop, 200 on zram systems
- Useful context for swap tuning advice

**Guidance improvements**: Explain "my RAM is full" (cache is normal, available is what matters),
swap configuration advice, huge page tuning for databases.

---

## 3. Process intelligence

**Interface**: `system-observe` (already have)

### Top memory consumers
- Walk `/proc/[0-9]*/status` — read `VmRSS`, `VmSwap`, `Name`, `State`, `Threads`
- Walk `/proc/[0-9]*/smaps_rollup` — read `Rss`, `Pss`, `Private_Dirty` (more accurate)
- Walk `/proc/[0-9]*/cmdline` — full command line for identification
- Sort by RSS, keep top 10
- Also flag any process with non-zero `VmSwap` (swapped-out processes)

### Top CPU consumers
- `/proc/[0-9]*/stat` field 14 (`utime`) + 15 (`stime`) = total ticks
- `/proc/stat` line `cpu` field 1+2+3 = total system ticks elapsed (for percentage)
- Read once at startup, compute lifetime CPU% per process (no sleep needed)
- Keep top 5 by CPU%

### Problem process detection
- **Zombies**: State `Z` in `/proc/[pid]/status` — count them; more than 0 is notable
- **D-state**: State `D` (uninterruptible sleep) — indicates I/O block; flag which processes + their cmdlines
- **High OOM score**: `/proc/[pid]/oom_score` > 500 — top 3 candidates for OOM killer

### Per-process I/O (`/proc/[pid]/io` via `system-observe`)
- `read_bytes`, `write_bytes` — lifetime totals
- High writers worth flagging for disk I/O questions

### System-wide load (`/proc/loadavg`)
- 1min, 5min, 15min averages
- `load_per_cpu = load_1min / cpu_count` — normalised load > 1.0 = overloaded
- Running processes count (field 4 numerator)

### PSI (`/proc/pressure/{cpu,io,memory}` via `system-observe`)
- `some avg10` and `full avg10` for all three resources
- These are the clearest signal of actual resource contention

### Thread counts
- From `/proc/[pid]/status` `Threads:` field alongside top processes
- 500-thread Java process vs 5-thread native daemon = very different tuning advice

**Guidance improvements**: "What's eating my RAM/CPU?", OOM killer prediction,
"why is my disk light always on?", zombie parent identification.

---

## 4. Network interface topology

**Interface**: `hardware-observe` (covers `/sys/class/net/**`)

**Note**: IP addresses and connection counts need `network-observe` (not in snap).
Sysfs gives topology; that's enough for most guidance questions.

### Per-interface classification
For each entry in `/sys/class/net/`:
- `operstate` → up/down/unknown/dormant
- `type` → 1=ethernet, 772=loopback, 801=wifi (also check `wireless/` subdir)
- `speed` → Mbps (-1 = no carrier / not applicable for wifi while associated)
- `address` → MAC address
- Subdirectory `wireless/` → wifi interface
- Subdirectory `bridge/` → software bridge (docker0, lxdbr0, virbr0)
- Subdirectory `bonding/` → bonded/teamed interface
- Interface name heuristics: `wg*` = WireGuard, `tun*`/`tap*` = VPN tunnel,
  `veth*` = container veth pair, `docker*`/`lxc*`/`virbr*` = VM/container bridge

### What this enables
- "Why can't I connect?" → is the right interface actually up?
- "I have LXD/Docker" → detect bridges automatically
- "How do I configure my VPN?" → detect existing WireGuard/OpenVPN tunnels
- Desktop vs server → server likely has no wifi interface

**Guidance improvements**: Interface-specific networking advice, VPN presence detection,
container bridge identification, "ethernet is down but wifi is up" diagnosis.

---

## 5. CPU detail

**Interface**: `hardware-observe`

### Topology (`/sys/devices/system/cpu/`)
- `cpu/present` → total logical CPU count (already have from cpuinfo, more reliable here)
- `cpu0/topology/physical_package_id` — unique count = socket count
- `cpu0/topology/core_id` + `thread_siblings` count → detect hyperthreading
- `cpu0/cache/index*/` → L1d, L1i, L2, L3 sizes and types

### Frequency scaling (`/sys/devices/system/cpu/cpu0/cpufreq/`)
- `scaling_governor` → powersave / performance / schedutil / ondemand / conservative
- `scaling_driver` → amd-pstate / intel_pstate / acpi-cpufreq (affects tuning options)
- `scaling_cur_freq` → current frequency in kHz
- `scaling_max_freq` → configured maximum
- `scaling_min_freq` → configured minimum
- If `cur_freq` << `max_freq` sustained → likely thermal throttling

### Thermal zones (`/sys/class/thermal/thermal_zone*/`)
- `type` → zone type (x86_pkg_temp, acpitz, iwlwifi_1, etc.)
- `temp` → millidegrees C → divide by 1000
- Flag any zone > 85°C

### PSI CPU pressure (`/proc/pressure/cpu` via `system-observe`)
- `some avg10` → fraction of time at least one task was runnable but waiting
- Complements load average with a more accurate contention signal

### Virtualisation detection
- `hardware-observe` includes `systemd-detect-virt` execution permission
- Can also read: `/proc/cpuinfo` flags (hypervisor bit), `/sys/hypervisor/type`
- Relevant: VM → don't recommend CPU governor changes, nested virt considerations

**Guidance improvements**: `make -j N` recommendations (physical cores, not logical),
governor change advice ("switch to performance for compilation"), thermal throttle diagnosis,
VM-aware advice (no governor, no TRIM on virtual disks).

---

## 6. Power & form factor

**Interface**: `hardware-observe`

### Battery (`/sys/class/power_supply/BAT*/`)
- `capacity` → charge percentage (0-100)
- `status` → Charging / Discharging / Full / Not charging / Unknown
- `health` → Good / Degraded / Overheat / Dead
- `energy_now` / `energy_full` → compute actual current capacity
- `energy_full` / `energy_full_design` → battery wear level (%)
- `technology` → Li-ion, Li-poly, NiMH

### AC adapter (`/sys/class/power_supply/AC*/` or `ACAD/`)
- `online` → 1 = plugged in, 0 = on battery

### Chassis type (`/sys/class/dmi/id/chassis_type`)
- 3 = Desktop, 8/9/10 = Laptop/Notebook/Portable, 14 = All-in-one
- 11 = Handheld, 17 = Rack mount server, 23 = Blade server

### Derived form factor
- `battery_present AND chassis_type IN (8,9,10)` → laptop
- `NOT battery_present OR chassis_type IN (3,17,23)` → desktop/server

**Guidance improvements**: "My laptop is slow on battery" (governor = powersave),
hibernate/suspend advice (only relevant for laptops), battery health reporting,
power management tuning, server-specific advice (no suspend, no battery management).

---

## 7. systemd service status improvement

**Interface**: `system-observe` (DBus access to systemd)

The current PPID=1 scan is a rough approximation. `system-observe` grants:
```
dbus send bus=system path=/org/freedesktop/systemd1
    interface=org.freedesktop.systemd1.Manager
    member={GetUnit,ListUnits}
```

### With ListUnits we get for each unit:
- Unit name (e.g. `docker.service`)
- Load state: loaded / not-found / masked
- Active state: active / inactive / failed / activating / deactivating
- Sub-state: running / dead / exited / waiting / start / stop etc.
- Description string

This replaces the PPID=1 heuristic with exact systemd state, including:
- Properly detecting **failed** services (currently impossible with /proc scan)
- One-shot services that ran and exited (sub-state: exited, not running)
- Services that are activating/deactivating

**Requires**: `dbus-python` or `dasbus` staged in snap, or use `gdbus` binary.
Alternative: use the systemd private D-Bus socket if accessible.

---

## 8. Implementation order

1. **Storage topology** — highest guidance value, many common questions
2. **Memory detail** — full meminfo + PSI + swappiness
3. **Process intelligence** — top RSS/CPU, zombies, D-state, PSI
4. **Network topology** — sysfs only (no network-observe needed)
5. **CPU detail** — topology, governor, thermal
6. **Power & form factor** — battery, chassis type, derived form factor
7. **Service status via DBus** — replaces PPID=1 heuristic (requires dbus dependency)

---

## New `system_info` structure

```python
{
    "collected_at": "...",
    "snap_revision": "...",
    "os": { ... },          # existing
    "desktop": { ... },     # existing
    "packages": { ... },    # existing
    "services": { ... },    # existing — improve with DBus in step 7
    "hardware": { ... },    # existing — extend with chassis_type, efi_boot
    # NEW:
    "storage": {
        "drives": [...],        # physical drives with type/model/size
        "lvm": bool,            # LVM in use
        "luks": bool,           # LUKS encryption in use
        "raid": {...},          # mdraid state if present
        "zram": [...],          # zram devices if present
        "mounts": [...],        # real mount points with fs type, usage, options
        "swap": [...],          # active swap devices from /proc/swaps
        "efi": bool,            # EFI system
        "fstab_mounts": [...],  # persistent mount config from /etc/fstab
    },
    "memory": {
        "total_gb": float,
        "available_gb": float,
        "used_pct": int,
        "cache_gb": float,
        "swap_total_gb": float,
        "swap_used_gb": float,
        "swap_used_pct": int,
        "shmem_gb": float,
        "dirty_mb": int,
        "hugepages_total": int,
        "swappiness": int,
        "pressure": { "some_avg10": float, "full_avg10": float },
    },
    "processes": {
        "top_rss": [...],        # top 10 by RSS: name, pid, rss_mb, swap_mb, cmdline
        "top_cpu": [...],        # top 5 by CPU%: name, pid, cpu_pct, cmdline
        "top_io_write": [...],   # top 3 by write_bytes: name, pid, write_mb, cmdline
        "zombie_count": int,
        "dstate_count": int,
        "dstate_names": [...],   # names of D-state processes
        "high_oom": [...],       # top 3 by oom_score > 500
        "load_1": float,
        "load_5": float,
        "load_15": float,
        "load_per_cpu": float,
        "running_count": int,
        "cpu_pressure": { "some_avg10": float, "full_avg10": float },
        "io_pressure": { "some_avg10": float, "full_avg10": float },
    },
    "network": {
        "interfaces": [...],  # name, type, operstate, speed, mac, is_wifi, is_bridge, is_vpn
    },
    "cpu_detail": {
        "logical_cpus": int,
        "physical_cores": int,
        "sockets": int,
        "hyperthreading": bool,
        "l3_cache_kb": int,
        "governor": str,
        "driver": str,
        "cur_freq_mhz": int,
        "max_freq_mhz": int,
        "hot_zones": [...],    # thermal zones > 60°C: type, temp_c
        "is_vm": bool,
    },
    "power": {
        "chassis_type": int,
        "form_factor": str,   # "laptop" / "desktop" / "server" / "unknown"
        "battery_present": bool,
        "battery_pct": int,
        "battery_status": str,
        "battery_health_pct": int,
        "ac_online": bool,
    },
}
```

## Context summary additions

```
Storage: 2x NVMe SSD — nvme0n1 (Samsung 970 EVO, 500G), nvme1n1 (WD Blue, 1T)
  /        ext4   450G   89G used  (20%)   ← nvme0n1p2 [LUKS]
  /home    ext4   930G  234G used  (25%)   ← nvme1n1p1
  Swap: 8G partition on nvme0n1p3 (0% used), zram0 4G compressed
  EFI boot, no LVM, no RAID
Memory: 27G / 128G used (21%) — 61G reclaimable cache, 8G swap free
  Top RSS: gnome-shell 510M, firefox 490M, code 380M
  Swap: 0% used, swappiness=60, no memory pressure
Load: 1.25 (32 CPUs → 4% busy), 0 zombies, 0 D-state
  CPU pressure: 2.1% | I/O pressure: 0.3%
CPU: 32 threads / 16 cores / 1 socket, HT enabled, L3 56MB
  Governor: performance (amd-pstate), 3.8GHz cur / 5.1GHz max
  Thermal: pkg 57°C (normal)
Network: wifi up (wlp192s0), ethernet down, lxdbr0 bridge (LXD), wg0 WireGuard VPN
Power: Desktop, AC only
```
