from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[2]
FILES_TO_SCAN = [
    ROOT / ".env.example",
    ROOT / ".env.production.example",
    ROOT / ".env.v4.example",
    ROOT / "backend" / ".env.example",
    ROOT / "apps" / "web" / ".env.example",
    ROOT / "apps" / "web" / "vercel.json",
]

PUBLIC_SECRET_PATTERN = re.compile(
    r"NEXT_PUBLIC_[A-Z0-9_]*(?:KEY|TOKEN|SECRET)", re.IGNORECASE
)
ASSIGNED_SECRET_PATTERN = re.compile(
    r"^[ \t]*(?:FOOTBALL_DATA_API_KEY|API_FOOTBALL_API_KEY|API_FOOTBALL_KEY|SPORTMONKS_API_TOKEN|SPORTMONKS_API_KEY|THE_ODDS_API_KEY|ODDS_API_KEY)[ \t]*=[ \t]*([^\r\n]*)[ \t]*$",
    re.MULTILINE,
)
SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"^[ \t]*(?:DATABASE_URL|REDIS_URL|SECRET_KEY|DB_PASSWORD|CRON_SECRET)[ \t]*=[ \t]*([^\r\n]*)[ \t]*$",
    re.MULTILINE,
)
REALISTIC_SECRET_PATTERNS = [
    re.compile(r"redis://[^:\s]+:[^@\s]{12,}@", re.IGNORECASE),
    re.compile(r"postgres(?:ql)?://[^:\s]+:[^@\s]{12,}@", re.IGNORECASE),
    re.compile(
        r"(?i)(?:api[_-]?key|token|secret|password)\s*[:=]\s*['\"][A-Za-z0-9_\-]{24,}['\"]"
    ),
]
SECRET_SURFACE_FILES = [
    ROOT / ".env.example",
    ROOT / ".env.production.example",
    ROOT / "backend" / ".env.example",
    ROOT / "backend" / "scripts" / "setup.sh",
    ROOT / "backend" / "scripts" / "init_db.py",
    ROOT / "apps" / "web" / ".env.example",
    ROOT / "apps" / "web" / "vercel.json",
]


def test_env_examples_do_not_expose_browser_provider_secrets():
    retired_espn_key_name = "ESPN" + "_API_KEY"
    for path in FILES_TO_SCAN:
        text = path.read_text(encoding="utf-8")

        assert retired_espn_key_name not in text
        assert PUBLIC_SECRET_PATTERN.search(text) is None


def test_provider_keys_in_examples_are_empty_or_placeholders():
    for path in FILES_TO_SCAN:
        text = path.read_text(encoding="utf-8")

        for match in ASSIGNED_SECRET_PATTERN.finditer(text):
            value = match.group(1).strip().strip('"').strip("'")
            assert value in {"", "your_key_here", "CHANGE_ME"}


def test_sensitive_connection_examples_are_empty_or_local_placeholders():
    allowed = {
        "",
        "CHANGE_ME",
        "CHANGE_ME_SECURE_PASSWORD",
        "your-secret-key-here",
        "your-cron-secret-here",
    }
    for path in SECRET_SURFACE_FILES:
        text = path.read_text(encoding="utf-8")
        for match in SECRET_ASSIGNMENT_PATTERN.finditer(text):
            value = match.group(1).strip().strip('"').strip("'")
            assert value in allowed or "localhost" in value or "127.0.0.1" in value, (
                f"Secret-like assignment must be blank or local-only in {path.relative_to(ROOT)}"
            )


def test_tracked_setup_surfaces_do_not_contain_realistic_secret_literals():
    for path in SECRET_SURFACE_FILES:
        text = path.read_text(encoding="utf-8")
        for pattern in REALISTIC_SECRET_PATTERNS:
            assert pattern.search(text) is None, (
                f"Potential secret literal found in {path.relative_to(ROOT)}"
            )


def test_gitleaks_workflow_is_configured_with_redaction_and_full_history():
    workflow = ROOT / ".github" / "workflows" / "secret-scan.yml"
    config = ROOT / ".gitleaks.toml"
    workflow_text = workflow.read_text(encoding="utf-8")

    assert config.exists()
    assert "gitleaks/gitleaks-action" in workflow_text
    assert "fetch-depth: 0" in workflow_text
    assert "--redact" in workflow_text


def test_vercel_config_is_valid_json():
    import json

    text = (ROOT / "apps" / "web" / "vercel.json").read_text(encoding="utf-8")
    json.loads(text)


def test_web_source_has_no_direct_provider_or_tfjs_imports():
    forbidden = [
        "api.football-data.org",
        "api.the-odds-api.com",
        "oddsportal.com",
        "@tensorflow/tfjs",
    ]

    web_src = ROOT / "apps" / "web" / "src"
    for path in web_src.rglob("*"):
        if not path.is_file() or path.suffix not in {".ts", ".tsx", ".js", ".jsx"}:
            continue
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text, f"{token} found in {path.relative_to(ROOT)}"


def test_tracked_files_do_not_define_espn_api_key_variable():
    try:
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return

    retired_espn_key_name = "ESPN" + "_API_KEY"
    # .md excluded: docs/skill checklists legitimately instruct reviewers to grep
    # for this retired name, which isn't a declaration risk like code/config is.
    for rel_path in result.stdout.splitlines():
        path = ROOT / rel_path
        if not path.is_file() or path.suffix.lower() not in {
            ".py",
            ".ts",
            ".tsx",
            ".js",
            ".jsx",
            ".json",
            ".yml",
            ".yaml",
            ".env",
            ".example",
            ".sh",
            ".ps1",
        }:
            continue
        if any(part in {"node_modules", ".venv", ".git"} for part in path.parts):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        assert retired_espn_key_name not in text, (
            f"Retired ESPN key variable found in {rel_path}"
        )
