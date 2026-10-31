"""Parsing tests against recorded /proc files (controlled inputs, not live readings)."""

import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from sentineleye_agent.collector import (
    CollectionError,
    Collector,
    CpuTimes,
    clean_hostname,
    cpu_percent,
    read_cpu_times,
    read_disk,
    read_memory,
    read_os,
    read_uptime,
    validate_sample,
)

FIXTURES = Path(__file__).parent / "fixtures"


def fake_statvfs(blocks=1000, bfree=400, bavail=350, frsize=4096):
    return lambda path: SimpleNamespace(f_blocks=blocks, f_bfree=bfree, f_bavail=bavail, f_frsize=frsize)


def test_cpu_times_use_the_aggregate_line():
    times = read_cpu_times(FIXTURES / "proc")
    # idle = idle + iowait; total = first eight fields
    assert times == CpuTimes(idle=3699 + 23, total=4705 + 356 + 584 + 3699 + 23 + 23 + 0 + 0)


def test_cpu_percent_from_two_samples():
    assert cpu_percent(CpuTimes(idle=100, total=200), CpuTimes(idle=150, total=400)) == 75.0
    assert cpu_percent(CpuTimes(idle=0, total=100), CpuTimes(idle=100, total=200)) == 0.0
    with pytest.raises(CollectionError):
        cpu_percent(CpuTimes(idle=10, total=100), CpuTimes(idle=10, total=100))


def test_memory_uses_memavailable():
    memory = read_memory(FIXTURES / "proc")
    total, available = 8040392 * 1024, 3015148 * 1024
    assert memory["total_bytes"] == total
    assert memory["available_bytes"] == available
    assert memory["used_bytes"] == total - available
    assert memory["percent"] == round((total - available) / total * 100, 2)


def test_memory_without_memavailable_is_an_error(tmp_path):
    (tmp_path / "meminfo").write_text("MemTotal: 1000 kB\nMemFree: 10 kB\n")
    with pytest.raises(CollectionError, match="MemAvailable"):
        read_memory(tmp_path)


def test_disk_matches_df_formula():
    disk = read_disk("/", fake_statvfs())
    assert disk["total_bytes"] == 1000 * 4096
    assert disk["used_bytes"] == 600 * 4096
    assert disk["available_bytes"] == 350 * 4096
    assert disk["percent"] == round(600 / (600 + 350) * 100, 2)


def test_uptime_and_os_release():
    assert read_uptime(FIXTURES / "proc") == 12345.67
    os_info = read_os(FIXTURES / "etc")
    assert os_info["name"] == "Ubuntu"
    assert os_info["version"] == "24.04"
    assert os_info["kernel"] == os.uname().release


def test_missing_os_release_falls_back(tmp_path):
    assert read_os(tmp_path)["name"] == "Linux"


def test_hostname_is_cleaned():
    assert clean_hostname("web 01.example.com") == "web-01.example.com"
    assert clean_hostname("***") == "unknown-host"


def test_collector_produces_a_valid_sample(tmp_path):
    proc = tmp_path / "proc"
    shutil.copytree(FIXTURES / "proc", proc)
    collector = Collector(proc_root=proc, etc_root=FIXTURES / "etc", statvfs=fake_statvfs(), first_sample_seconds=0)

    # First call samples twice; simulate the counters moving between the two reads
    original = read_cpu_times(proc)
    reads = iter([original, CpuTimes(idle=original.idle + 50, total=original.total + 200)])
    import sentineleye_agent.collector as module

    real = module.read_cpu_times
    module.read_cpu_times = lambda _proc: next(reads)
    try:
        sample = collector.collect(server_id=7)
    finally:
        module.read_cpu_times = real

    assert sample["server_id"] == 7
    assert sample["cpu_percent"] == 75.0
    assert sample["collected_at"].endswith("+00:00")
    validate_sample(sample)


def test_validation_rejects_impossible_values():
    good = {
        "cpu_percent": 10,
        "uptime_seconds": 1,
        "memory": {"total_bytes": 10, "used_bytes": 5, "available_bytes": 5, "percent": 50},
        "disk": {"total_bytes": 10, "used_bytes": 5, "available_bytes": 5, "percent": 50},
    }
    validate_sample(good)
    for mutate in (
        lambda s: s.update(cpu_percent=101),
        lambda s: s["memory"].update(used_bytes=11),
        lambda s: s["disk"].update(total_bytes=0),
        lambda s: s.update(uptime_seconds=-1),
    ):
        bad = {**good, "memory": dict(good["memory"]), "disk": dict(good["disk"])}
        mutate(bad)
        with pytest.raises(CollectionError):
            validate_sample(bad)


def test_unsupported_platform_is_reported(tmp_path):
    with pytest.raises(CollectionError, match="Linux only"):
        Collector(proc_root=tmp_path).check_supported()
