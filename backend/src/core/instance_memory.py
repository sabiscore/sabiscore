"""The container's memory, read from cgroups (never the host's).

Shared by /health and the prediction-capture history, so the 9 Oct capture
burst can be judged on the same working-set and anon figures /health reports
(directive v11 M1, M2).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

try:
    import psutil
except ImportError:  # pragma: no cover - depends on optional system package
    psutil = None  # type: ignore[assignment]


# (usage, limit, stat file, reclaimable-cache key in that stat file)
CGROUP_MEMORY_FILES = (
    (
        "/sys/fs/cgroup/memory.current",
        "/sys/fs/cgroup/memory.max",
        "/sys/fs/cgroup/memory.stat",
        "inactive_file",
    ),  # cgroup v2
    (
        "/sys/fs/cgroup/memory/memory.usage_in_bytes",
        "/sys/fs/cgroup/memory/memory.limit_in_bytes",
        "/sys/fs/cgroup/memory/memory.stat",
        "total_inactive_file",
    ),  # cgroup v1
)
# memory.stat keys that split the working set into process memory (anon, not
# reclaimable) and active page cache (reclaimable under pressure). Live
# 2026-09-26 the working set sat 39 MB above RSS and /health could not say why.
CGROUP_BREAKDOWN_KEYS = {
    "inactive_file": ("anon", "active_file"),
    "total_inactive_file": ("total_rss", "total_active_file"),
}


def _read_cgroup_bytes(path: str) -> int | None:
    try:
        raw = Path(path).read_text().strip()
    except OSError:
        return None
    if not raw.isdigit():  # v2 writes "max" for no limit
        return None
    value = int(raw)
    return value if value < 1 << 60 else None  # v1 "unlimited" sentinel


def _read_cgroup_stat(path: str, key: str) -> int | None:
    try:
        for line in Path(path).read_text().splitlines():
            name, _, value = line.partition(" ")
            if name == key and value.strip().isdigit():
                return int(value)
    except OSError:
        pass
    return None


def instance_memory() -> Dict[str, Any]:
    """Memory of this container, not the host.

    psutil.virtual_memory() reads the host: on Render's free plan it reported
    113 GB available for a single-worker instance (docs/DEBT.md item 152).
    None where the platform does not expose a figure; never a host substitute.

    Headroom is measured against the working set (usage minus inactive file
    cache, the figure Docker and Kubernetes use), not raw usage. Raw usage
    counts page cache the kernel reclaims under pressure: live on 2026-09-25 it
    sat at 507/512 MB, with RSS at 381 MB, until the kernel dropped it to 381 MB.
    Headroom from raw usage flagged /health "degraded" on a healthy instance.
    """
    current = limit = inactive = anon = active_file = None
    for current_path, limit_path, stat_path, cache_key in CGROUP_MEMORY_FILES:
        current = _read_cgroup_bytes(current_path)
        if current is not None:
            limit = _read_cgroup_bytes(limit_path)
            inactive = _read_cgroup_stat(stat_path, cache_key)
            anon_key, active_key = CGROUP_BREAKDOWN_KEYS.get(cache_key, ("", ""))
            anon = _read_cgroup_stat(stat_path, anon_key)
            active_file = _read_cgroup_stat(stat_path, active_key)
            break
    working_set = max(0, current - (inactive or 0)) if current is not None else None
    mb = 1024 * 1024
    return {
        "process_rss_mb": psutil.Process().memory_info().rss // mb if psutil else None,
        "cgroup_current_mb": current // mb if current is not None else None,
        "cgroup_working_set_mb": working_set // mb if working_set is not None else None,
        "cgroup_limit_mb": limit // mb if limit is not None else None,
        "cgroup_anon_mb": anon // mb if anon is not None else None,
        "cgroup_active_file_mb": active_file // mb if active_file is not None else None,
        "headroom_mb": (limit - working_set) // mb
        if working_set is not None and limit is not None
        else None,
    }
