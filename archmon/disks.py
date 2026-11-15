"""Диски: модель, тип, размер, температура, скорость чтения и записи, разделы. Без Qt.

Всё читается без root: из /sys/block (модель, размер, тип), из hwmon (температура NVMe; у SATA, если
загружен модуль drivetemp), из psutil (скорости, разделы, заполненность). Здоровье диска (SMART)
требует root, поэтому здесь его нет.
"""
import glob
import os
import time
from dataclasses import dataclass, field
from typing import Optional

import psutil

from .helpers import read_text, to_float

SYS_BLOCK = "/sys/block"
SYS_CLASS_BLOCK = "/sys/class/block"
SKIP_PREFIXES = ("loop", "ram", "zram", "dm-", "sr", "md", "fd")   # не физические диски
SKIP_FSTYPES = {"squashfs", "overlay", "tmpfs", "devtmpfs", "efivarfs", "nsfs", "autofs"}
SKIP_MOUNT_PREFIXES = ("/snap/", "/var/lib/docker/", "/var/lib/containers/")


@dataclass
class Mount:
    device: str           # /dev/nvme0n1p2
    mountpoints: list     # все точки монтирования этого раздела (у btrfs их бывает несколько)
    fstype: str
    used: float
    total: float
    percent: float


@dataclass
class Disk:
    name: str                       # nvme0n1, sda
    model: str
    kind: str                       # NVMe, SSD, HDD, USB
    size: float                     # байты
    temp: Optional[float] = None    # °C
    mounts: list = field(default_factory=list)


@dataclass
class IoRate:
    read: float                     # байт/с
    write: float
    busy: Optional[float] = None    # % времени, когда диск был занят (как %util в iostat)


# ── Физические диски ────────────────────────────────────────────────────────
def _kind(name):
    if "/usb" in os.path.realpath(f"{SYS_BLOCK}/{name}") or read_text(f"{SYS_BLOCK}/{name}/removable") == "1":
        return "USB"
    if name.startswith("nvme"):
        return "NVMe"
    return "HDD" if read_text(f"{SYS_BLOCK}/{name}/queue/rotational") == "1" else "SSD"


def _model(name):
    model = (read_text(f"{SYS_BLOCK}/{name}/device/model") or "").strip()
    vendor = (read_text(f"{SYS_BLOCK}/{name}/device/vendor") or "").strip()
    if vendor and vendor.upper() not in ("ATA", "NVME") and not model.lower().startswith(vendor.lower()):
        model = f"{vendor} {model}".strip()
    return " ".join(model.split()) or name


def _temp(name):
    """Температура диска: NVMe отдаёт её всегда, SATA при загруженном модуле drivetemp."""
    for pattern in (f"{SYS_BLOCK}/{name}/device/hwmon*/temp1_input",
                    f"{SYS_BLOCK}/{name}/device/hwmon/hwmon*/temp1_input"):
        for path in sorted(glob.glob(pattern)):
            value = to_float(read_text(path))
            if value is not None:
                return value / 1000
    return None


def physical_disks():
    """Физические диски (без loop, zram, LVM/LUKS-обёрток и пустых картридеров)."""
    disks = []
    for path in sorted(glob.glob(f"{SYS_BLOCK}/*")):
        name = os.path.basename(path)
        if name.startswith(SKIP_PREFIXES):
            continue
        sectors = to_float(read_text(f"{path}/size"))
        if not sectors:
            continue
        disks.append(Disk(name=name, model=_model(name), kind=_kind(name), size=sectors * 512, temp=_temp(name)))
    return disks


# ── Разделы ─────────────────────────────────────────────────────────────────
def parent_disk(device):
    """Физический диск раздела: /dev/nvme0n1p2 -> nvme0n1; /dev/mapper/root (LUKS, LVM) -> диск под ним."""
    name = os.path.basename(os.path.realpath(device))
    for _ in range(8):
        base = f"{SYS_CLASS_BLOCK}/{name}"
        if not os.path.exists(base):
            return None
        slaves = sorted(os.listdir(f"{base}/slaves")) if os.path.isdir(f"{base}/slaves") else []
        if slaves:
            name = slaves[0]           # dm-0 -> nvme0n1p2 -> ...
            continue
        if os.path.exists(f"{base}/partition"):
            return os.path.basename(os.path.dirname(os.path.realpath(base)))
        return name
    return None


def mounts():
    """Смонтированные разделы, по одной записи на устройство: {имя диска или None: [Mount, …]}."""
    by_device = {}
    for part in psutil.disk_partitions(all=False):
        if part.fstype in SKIP_FSTYPES or part.fstype.startswith("fuse."):
            continue
        if part.mountpoint.startswith(SKIP_MOUNT_PREFIXES):
            continue
        by_device.setdefault(part.device, []).append(part)
    result = {}
    for device, parts in by_device.items():
        parts.sort(key=lambda p: (len(p.mountpoint), p.mountpoint))
        try:
            usage = psutil.disk_usage(parts[0].mountpoint)
        except OSError:
            continue
        mount = Mount(device=device, mountpoints=[p.mountpoint for p in parts], fstype=parts[0].fstype,
                      used=usage.used, total=usage.total, percent=usage.percent)
        result.setdefault(parent_disk(device), []).append(mount)
    for group in result.values():
        group.sort(key=lambda m: (len(m.mountpoints[0]), m.mountpoints[0]))
    return result


def read_disks():
    """Диски с их разделами. Разделы без известного диска (сетевые, ZFS…) идут отдельным «диском» other."""
    disks = physical_disks()
    by_disk = mounts()
    for disk in disks:
        disk.mounts = by_disk.pop(disk.name, [])
    orphans = [m for group in by_disk.values() for m in group]
    if orphans:
        disks.append(Disk(name="other", model="Other filesystems", kind="", size=0, mounts=orphans))
    return disks


def root_usage():
    """Заполненность корневого раздела «/» (для кольца на главной) или None."""
    try:
        return psutil.disk_usage("/")
    except OSError:
        return None


# ── Скорости ────────────────────────────────────────────────────────────────
class IoSampler:
    """Считает скорости по разнице счётчиков между двумя вызовами sample()."""

    def __init__(self):
        self.prev = {}
        self.rates = {}     # имя диска -> IoRate
        self.totals = {}    # имя диска -> счётчики psutil с момента загрузки (read_bytes, write_bytes…)

    def sample(self):
        now = time.monotonic()
        try:
            counters = psutil.disk_io_counters(perdisk=True, nowrap=True) or {}
        except (OSError, RuntimeError):
            counters = {}
        rates = {}
        for name, c in counters.items():
            prev = self.prev.get(name)
            if prev is not None:
                then, old = prev
                dt = now - then
                if dt > 0:
                    busy = None
                    if hasattr(c, "busy_time") and hasattr(old, "busy_time"):
                        busy = min(100.0, max(0.0, (c.busy_time - old.busy_time) / (dt * 1000) * 100))
                    rates[name] = IoRate(read=max(0.0, (c.read_bytes - old.read_bytes) / dt),
                                         write=max(0.0, (c.write_bytes - old.write_bytes) / dt), busy=busy)
            self.prev[name] = (now, c)
        self.rates, self.totals = rates, counters
        return rates
