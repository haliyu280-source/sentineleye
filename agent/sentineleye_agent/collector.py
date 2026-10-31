"""Reads live system metrics from Linux kernel interfaces (/proc) and statvfs.

The proc root and statvfs function are injectable so the parsing can be tested against
recorded /proc files on any platform.
"""

import os
import re
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import __version__


class CollectionError(RuntimeError):
    pass


@dataclass(frozen=True)
class CpuTimes:
    idle: int
    total: int


def read_cpu_times(proc: Path) -> CpuTimes:
    for line in (proc / "stat").read_text().splitlines():
        if line.startswith("cpu "):
            fields = [int(v) for v in line.split()[1:]]
            if len(fields) < 4:
                break
            # user nice system idle iowait irq softirq steal; guest time is already counted in user
            busy_and_idle = fields[:8]
            idle = fields[3] + (fields[4] if len(fields) > 4 else 0)
            return CpuTimes(idle=idle, total=sum(busy_and_idle))
    raise CollectionError("Could not find the aggregate cpu line in /proc/stat")


def cpu_percent(before: CpuTimes, after: CpuTimes) -> float:
    total = after.total - before.total
    idle = after.idle - before.idle
    if total <= 0 or idle < 0:
        raise CollectionError("CPU counters did not advance between samples")
    return round(min(max((1 - idle / total) * 100, 0.0), 100.0), 2)


def read_memory(proc: Path) -> dict:
    info: dict[str, int] = {}
    for line in (proc / "meminfo").read_text().splitlines():
        key, _, rest = line.partition(":")
        parts = rest.split()
        if parts:
            info[key] = int(parts[0]) * 1024  # values are in KiB
    try:
        total = info["MemTotal"]
        available = info["MemAvailable"]  # kernel >= 3.14
    except KeyError as missing:
        raise CollectionError(f"/proc/meminfo has no {missing.args[0]}") from None
    used = total - available
    return {
        "total_bytes": total,
        "used_bytes": used,
        "available_bytes": available,
        "percent": round(used / total * 100, 2),
    }


def read_disk(path: str, statvfs: Callable = os.statvfs) -> dict:
    st = statvfs(path)
    total = st.f_blocks * st.f_frsize
    available = st.f_bavail * st.f_frsize  # space usable by unprivileged users, as df reports
    used = (st.f_blocks - st.f_bfree) * st.f_frsize
    if total <= 0:
        raise CollectionError(f"Filesystem at {path} reports zero size")
    # Same formula as df: used / (used + available)
    percent = used / (used + available) * 100 if used + available else 0.0
    return {
        "mount": path,
        "total_bytes": total,
        "used_bytes": used,
        "available_bytes": available,
        "percent": round(percent, 2),
    }


def read_uptime(proc: Path) -> float:
    return float((proc / "uptime").read_text().split()[0])


def read_os(etc: Path) -> dict:
    release: dict[str, str] = {}
    try:
        for line in (etc / "os-release").read_text().splitlines():
            key, sep, value = line.partition("=")
            if sep:
                release[key] = value.strip().strip('"')
    except FileNotFoundError:
        pass
    return {
        "name": release.get("NAME", "Linux")[:100],
        "version": release.get("VERSION_ID", release.get("VERSION", ""))[:100],
        "kernel": os.uname().release[:100],
    }


def clean_hostname(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "-", name)[:255].strip("-")
    return cleaned or "unknown-host"


class Collector:
    """Keeps the previous CPU counters so each cycle measures CPU over the whole interval."""

    def __init__(self, disk_path: str = "/", proc_root: str = "/proc", etc_root: str = "/etc",
                 statvfs: Callable = os.statvfs, first_sample_seconds: float = 1.0):
        self.proc = Path(proc_root)
        self.etc = Path(etc_root)
        self.disk_path = disk_path
        self.statvfs = statvfs
        self.first_sample_seconds = first_sample_seconds
        self._last_cpu: CpuTimes | None = None

    def check_supported(self) -> None:
        if not (self.proc / "stat").exists():
            raise CollectionError("This agent supports Linux only (no /proc/stat found)")

    def collect(self, server_id: int) -> dict:
        if self._last_cpu is None:
            self._last_cpu = read_cpu_times(self.proc)
            time.sleep(self.first_sample_seconds)
        current = read_cpu_times(self.proc)
        cpu = cpu_percent(self._last_cpu, current)
        self._last_cpu = current

        return {
            "server_id": server_id,
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "hostname": clean_hostname(socket.gethostname()),
            "agent_version": __version__,
            "os": read_os(self.etc),
            "uptime_seconds": round(read_uptime(self.proc), 2),
            "cpu_percent": cpu,
            "memory": read_memory(self.proc),
            "disk": read_disk(self.disk_path, self.statvfs),
        }


def validate_sample(sample: dict) -> None:
    """Catch impossible readings before they leave the machine."""
    if not 0 <= sample["cpu_percent"] <= 100:
        raise CollectionError(f"CPU percent out of range: {sample['cpu_percent']}")
    for section in ("memory", "disk"):
        part = sample[section]
        if part["total_bytes"] <= 0:
            raise CollectionError(f"{section} total is not positive")
        if part["used_bytes"] > part["total_bytes"] or part["available_bytes"] > part["total_bytes"]:
            raise CollectionError(f"{section} used/available exceeds total")
        if not 0 <= part["percent"] <= 100:
            raise CollectionError(f"{section} percent out of range: {part['percent']}")
    if sample["uptime_seconds"] < 0:
        raise CollectionError("Negative uptime")
