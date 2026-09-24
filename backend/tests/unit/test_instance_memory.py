"""docs/DEBT.md item 152: /health reports the container's memory, never the host's.

psutil.virtual_memory() reads the host; on Render's free plan it reported 113 GB
available for a single-worker instance. The instance figure comes from cgroups.
"""

from __future__ import annotations

from src.api.endpoints import monitoring


def _files(tmp_path, current: str | None, limit: str | None):
    cur, lim = tmp_path / "memory.current", tmp_path / "memory.max"
    if current is not None:
        cur.write_text(current)
    if limit is not None:
        lim.write_text(limit)
    return ((str(cur), str(lim)),)


def test_cgroup_limit_and_headroom(tmp_path, monkeypatch):
    mb = 1024 * 1024
    monkeypatch.setattr(
        monitoring, "_CGROUP_MEMORY_FILES", _files(tmp_path, str(400 * mb), str(512 * mb))
    )
    memory = monitoring._instance_memory()
    assert memory["cgroup_current_mb"] == 400
    assert memory["cgroup_limit_mb"] == 512
    assert memory["headroom_mb"] == 112
    assert memory["process_rss_mb"] > 0


def test_unlimited_cgroup_reports_no_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(
        monitoring, "_CGROUP_MEMORY_FILES", _files(tmp_path, str(1024 * 1024), "max")
    )
    memory = monitoring._instance_memory()
    assert memory["cgroup_limit_mb"] is None
    assert memory["headroom_mb"] is None


def test_no_cgroup_never_substitutes_host_memory(tmp_path, monkeypatch):
    monkeypatch.setattr(monitoring, "_CGROUP_MEMORY_FILES", _files(tmp_path, None, None))
    memory = monitoring._instance_memory()
    assert memory["cgroup_current_mb"] is None
    assert memory["cgroup_limit_mb"] is None
    assert memory["headroom_mb"] is None
