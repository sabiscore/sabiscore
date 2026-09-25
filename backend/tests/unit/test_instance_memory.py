"""docs/DEBT.md item 152: /health reports the container's memory, never the host's.

psutil.virtual_memory() reads the host; on Render's free plan it reported 113 GB
available for a single-worker instance. The instance figure comes from cgroups.
"""

from __future__ import annotations

from src.api.endpoints import monitoring


def _files(tmp_path, current: str | None, limit: str | None, stat: str | None = None):
    cur, lim, st = (
        tmp_path / "memory.current",
        tmp_path / "memory.max",
        tmp_path / "memory.stat",
    )
    if current is not None:
        cur.write_text(current)
    if limit is not None:
        lim.write_text(limit)
    if stat is not None:
        st.write_text(stat)
    return ((str(cur), str(lim), str(st), "inactive_file"),)


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


def test_boto3_is_not_imported_at_startup() -> None:
    """Directive v8 S4: boto3 costs ~20 MB RSS on a 512 MB instance and only the
    S3 model-download path uses it, so importing the fetcher must not load it.
    Run in a fresh interpreter: this suite's own imports would mask it."""
    import subprocess
    import sys
    from pathlib import Path

    code = (
        "import sys; import src.core.model_fetcher; "
        "sys.exit(1 if 'boto3' in sys.modules else 0)"
    )
    backend = Path(__file__).resolve().parents[2]
    assert subprocess.run([sys.executable, "-c", code], cwd=backend).returncode == 0


def test_reclaimable_file_cache_is_not_counted_against_headroom(tmp_path, monkeypatch):
    """Live 2026-09-25: usage sat at 507/512 MB with RSS at 381 MB until the
    kernel reclaimed cache. Raw-usage headroom (5 MB) flagged a healthy
    instance degraded; the working set is what can actually be OOM-killed."""
    mb = 1024 * 1024
    stat = "".join(
        f"{name} {size * mb}\n"
        for name, size in (("anon", 381), ("inactive_file", 120), ("active_file", 6))
    )
    monkeypatch.setattr(
        monitoring,
        "_CGROUP_MEMORY_FILES",
        _files(tmp_path, str(507 * mb), str(512 * mb), stat),
    )
    memory = monitoring._instance_memory()
    assert memory["cgroup_current_mb"] == 507
    assert memory["cgroup_working_set_mb"] == 387
    assert memory["headroom_mb"] == 125
