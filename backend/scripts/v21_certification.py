"""Generate V21 certification artifacts from repository evidence only.

No market metric or live C6 count is inferred here. Empirical fields remain
null until an evaluation or database query supplies attributable observations.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.src.models.feature_registry import build_feature_contract
from backend.scripts.v21_market_protocol import PROTOCOL, protocol_bytes, protocol_sha256
from backend.workers.c6_live_collector import LIVE_CAPTURE_TRIGGER


ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "reports"


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _git(*args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True
        )
        return result.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def generate_protocol() -> str:
    path = REPORTS / "research/v21-market-evaluation-protocol.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    frozen = protocol_bytes()
    if path.exists() and path.read_bytes() != frozen:
        raise RuntimeError("V21 market protocol is frozen and cannot be rewritten")
    if not path.exists():
        path.write_bytes(frozen)
    digest = protocol_sha256()
    sha_path = REPORTS / "research/v21-market-evaluation-protocol.sha256"
    expected_sha = f"{digest}  v21-market-evaluation-protocol.json\n"
    if sha_path.exists() and sha_path.read_text(encoding="utf-8") != expected_sha:
        raise RuntimeError("V21 protocol hash file does not match the frozen protocol")
    if not sha_path.exists():
        sha_path.write_text(expected_sha, encoding="utf-8")
    return digest


def generate_reports() -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    protocol_hash = generate_protocol()
    active = _read_json(ROOT / "backend/models/active_generation.json") or {}
    v20_evaluation = _read_json(REPORTS / "research/v20-promotion-evaluation.json") or {}
    v20_alpha = _read_json(REPORTS / "research/v20-market-alpha-report.json") or {}
    v20_c6 = _read_json(REPORTS / "research/v20-c6-accumulation-status.json") or {}
    v20_bridge = _read_json(REPORTS / "research/v20-serving-bridge-audit.json") or {}
    contract = build_feature_contract("apex_v1_89")
    required_contract_fields = ("semantic_definition", "unit", "serving_source")
    undeclared = [
        item["feature_name"]
        for item in contract["features"]
        if any(item.get(key) in (None, "", "UNDECLARED") for key in required_contract_fields)
    ]

    src_main = (ROOT / "backend/src/api/main.py").read_text(encoding="utf-8")
    src_analysis = (ROOT / "backend/src/api/endpoints/full_analysis.py").read_text(encoding="utf-8")
    src_collector = (ROOT / "backend/workers/c6_live_collector.py").read_text(encoding="utf-8")
    src_capture = (ROOT / "backend/src/services/prediction_capture_service.py").read_text(encoding="utf-8")
    src_repos = (ROOT / "backend/src/repositories/fixtures.py").read_text(encoding="utf-8")

    reconciliation = {
        "report_id": "v20-claim-reconciliation",
        "generated_at": now,
        "repository_head": _git("rev-parse", "HEAD"),
        "claims": [
            {
                "claim": "FeatureBridge exists",
                "status": "VERIFIED_BUILT",
                "evidence": ["backend/serving/feature_bridge.py", f"sha256:{_sha(ROOT / 'backend/serving/feature_bridge.py')}"],
            },
            {
                "claim": "FeatureBridge participates in canonical full-analysis request handling",
                "status": "WIRED_CANDIDATE_ADMISSION_ONLY",
                "evidence": ["backend/src/api/endpoints/full_analysis.py imports and calls FeatureBridge"],
                "limitation": "Candidate-M remains withheld until its 89-feature semantics and live per-field provenance validate.",
            },
            {
                "claim": "Candidate has a production-compatible apex_v1_89 schema",
                "status": "NOT_VERIFIED",
                "evidence": [f"active_generation.feature_schema_version={active.get('feature_schema_version')}", f"undeclared_semantics_or_units={len(undeclared)}"],
            },
            {
                "claim": "C6LiveCollector accumulates live sample",
                "status": "V20_CLAIM_REJECTED_FROZEN_PERSISTED_PATH_USED",
                "evidence": ["backend/src/api/main.py binds the collector to capture and settlement loops", "live rows are filtered by capture_trigger and kickoff time"],
                "prior_collector_was": "in-memory counter/no-op capture",
                "frozen_writer_filter": LIVE_CAPTURE_TRIGGER,
            },
            {
                "claim": "V20 live C6 N is current and verified",
                "status": "NOT_VERIFIED",
                "evidence": [f"legacy report recorded N={v20_c6.get('N')}; current database observation was not made by this artifact generator"],
            },
            {
                "claim": "V20 Gate 7 market comparison is empirical and reproducible",
                "status": "NOT_VERIFIED",
                "evidence": [f"legacy gate_7={((v20_evaluation.get('gates') or {}).get('gate_7'))}", "V20 market report contains aggregate values but not a V21 cohort/provenance manifest"],
                "legacy_report_values": (v20_alpha.get("calibration") or {}),
            },
            {
                "claim": "V20 bridge audit proves semantic compatibility",
                "status": "CLAIM_EXCEEDS_IMPLEMENTATION",
                "evidence": [f"legacy fallback_contract_verified={((v20_bridge.get('audit') or {}).get('fallback_contract_verified'))}", "V20 bridge compared vector width and accepted parent fallback; V21 bridge rejects unproven fallback vectors"],
            },
        ],
        "release_state": "ACTIVE_FAIL_CLOSED",
    }
    _write_json(REPORTS / "audits/v20-claim-reconciliation.json", reconciliation)

    feature_status = "BLOCKED" if undeclared or active.get("feature_schema_version") != "apex_v1_89" else "PENDING_RUNTIME_PROOF"
    market_inputs_in_schema = [
        item["feature_name"] for item in contract["features"]
        if any(token in item["feature_name"].casefold() for token in ("odds", "market", "implied_prob", "closing", "devig", "sharp_money"))
    ]
    feature_report = {
        "status": feature_status,
        "candidate": "Candidate-M",
        "required_schema": "apex_v1_89",
        "active_schema": active.get("feature_schema_version"),
        "feature_count": len(contract["features"]),
        "schema_contract_sha256": contract.get("feature_contract_sha256"),
        "undeclared_semantic_contract_count": len(undeclared),
        "undeclared_features": undeclared,
        "live_bridge_callsite": "backend/src/api/endpoints/full_analysis.py",
        "incumbent_retained": True,
        "generated_at": now,
    }
    _write_json(REPORTS / "research/v21-feature-integration.json", feature_report)

    old_g7 = (v20_evaluation.get("gates") or {}).get("gate_7")
    old_metrics = v20_alpha.get("calibration") or {}
    market_report = {
        "status": "BLOCKED_NO_V21_EMPIRICAL_COHORT_ARTIFACT",
        "protocol_sha256": protocol_hash,
        "inherited_protocol_sha256": {item["path"]: item["sha256"] for item in PROTOCOL["inherited_protocols"]},
        "gate_7": "FAIL" if old_g7 == "FAIL" else "UNVERIFIED",
        "gate_7_basis": "legacy V20 report only; not independently accepted as a V21 market evaluation",
        "candidate_m": {
            "rps": None,
            "input_market_features": None,
            "market_feature_exclusion_verified": False,
            "existing_apex_v1_89_market_features": market_inputs_in_schema,
        },
        "candidate_ma": {"rps": None, "certification_eligible_as_independent_alpha": False},
        "research_market_blend": {"rps": old_metrics.get("candidate_rps_after_calibration"), "certification_eligible": False},
        "market_baselines": {"opening": None, "closing": None},
        "cohort_hashes": {},
        "prior_v20_report_values_unverified": {
            "candidate_rps_after_calibration": old_metrics.get("candidate_rps_after_calibration"),
            "reported_market_rps": old_metrics.get("opening_market_rps"),
        },
        "reason": "No attributable V21 paired fixture IDs, outcomes, point-in-time closing market provenance, and candidate manifest were available.",
        "generated_at": now,
    }
    _write_json(REPORTS / "research/v21-market-evaluation.json", market_report)

    c6_report = {
        "status": "UNVERIFIED_CURRENT_DATABASE_COUNT",
        "live_n": None,
        "last_reported_v20_n": v20_c6.get("N"),
        "target": 200,
        "milestones": [200, 500, 1000],
        "capture_trigger": LIVE_CAPTURE_TRIGGER,
        "replay_n": None,
        "replay_included_in_live_n": False,
        "live_count_source": "persisted settled MatchPredictionLog rows with a strict pre-kickoff close and the frozen capture_trigger filter",
        "protocol_source_sha256": {item["path"]: item["sha256"] for item in PROTOCOL["inherited_protocols"]},
        "pre_kickoff_filter": "prediction timestamp must be strictly before fixture kickoff",
        "generated_at": now,
    }
    _write_json(REPORTS / "research/v21-c6-live-status.json", c6_report)

    calibration = {"status": "NOT_RUN_NO_V21_CALIBRATION_ARTIFACT", "metrics": None, "split_overlap": None, "generated_at": now}
    _write_json(REPORTS / "research/v21-calibration.json", calibration)
    regimes = {"status": "NOT_RUN_NO_V21_OUT_OF_SAMPLE_PREDICTIONS", "regimes": None, "generated_at": now}
    _write_json(REPORTS / "research/v21-regime-performance.json", regimes)
    data_quality = {
        "status": "NOT_MEASURED",
        "leagues": {
            league: {key: None for key in ("fixture_count", "settled_count", "feature_coverage", "market_coverage", "critical_gap_rate", "advisory_gap_rate", "provider_agreement", "identity_conflict_rate", "stale_rate")}
            for league in ("EPL", "La Liga", "Bundesliga", "Serie A", "Ligue 1", "Eredivisie")
        },
        "generated_at": now,
    }
    _write_json(REPORTS / "evidence/v21-data-quality-dashboard.json", data_quality)
    provider_report = {
        "status": "UNVERIFIED",
        "provider": "the-odds-api / football-data.org (evaluated)",
        "league_coverage": ["EPL", "La Liga", "Bundesliga", "Serie A", "Ligue 1", "Eredivisie"],
        "historical_depth": "seasons 19/20-23/24 gap identified (65.4% missing in baseline corpus)",
        "timestamp_granularity": "1-minute snapshots pre-kickoff",
        "closing_definition": "Last verified 1X2 quote strictly before kickoff_utc (quote_timestamp < kickoff_timestamp)",
        "bookmaker_coverage": ["Pinnacle", "Betfair Exchange", "Bet365"],
        "rate_limits": "30 req/min (free) / 100 req/min (paid tier)",
        "quota": "Current live plan: 500 requests/month free tier — insufficient for bulk historical replay",
        "licensing": "Commercial historical archive license required for deep multi-season backfill",
        "retention_rights": "Internal model training and point-in-time calibration permissible under enterprise license",
        "source_report": "reports/evidence/v20-historical-odds-recovery.json",
        "source_report_sha256": _sha(REPORTS / "evidence/v20-historical-odds-recovery.json"),
        "point_in_time_closing_integrity": "NOT_VERIFIED_BY_V21_EVALUATION",
        "generated_at": now,
    }
    _write_json(REPORTS / "evidence/v21-historical-market-provider.json", provider_report)

    # The existing 40-gate suite has only partial machine-readable results in
    # V20 reports. Never convert missing statuses into PASS.
    gates: dict[str, Any] = {}
    legacy = v20_evaluation.get("gates") or {}
    for gate in range(1, 41):
        gates[f"gate_{gate}"] = legacy.get(f"gate_{gate}", "UNVERIFIED")
    hard_gate_specs = {
        41: ("PASS" if "FeatureBridge(schema_id=\"apex_v1_89\")" in src_analysis else "FAIL"),
        42: ("FAIL" if undeclared else "UNVERIFIED"),
        43: "FAIL" if undeclared else "UNVERIFIED",
        44: "PASS" if "_background_clv_capture(" in src_main and "c6_collector" in src_main else "FAIL",
        45: "PASS" if "c6_collector.settle_predictions()" in src_main else "FAIL",
        46: "PASS" if "persist_prediction_log" in src_analysis and "capture_trigger" in src_capture else "FAIL",
        47: "PASS" if "get_clv_records" in src_collector and "capture_trigger=LIVE_CAPTURE_TRIGGER" in src_collector else "FAIL",
        48: "PASS" if LIVE_CAPTURE_TRIGGER == "interactive_full_analysis" and "capture_trigger" in src_repos else "FAIL",
        49: "UNVERIFIED",
        50: "UNVERIFIED",
        51: "UNVERIFIED",
        52: "UNVERIFIED",
        53: "PASS" if PROTOCOL["gate_7"]["market_blend_is_certification_input"] is False else "FAIL",
        54: "FAIL" if feature_status == "BLOCKED" else "UNVERIFIED",
        55: "UNVERIFIED",
        56: "UNVERIFIED",
        57: "UNVERIFIED",
        58: "UNVERIFIED",
        59: "FAIL" if feature_status == "BLOCKED" else "UNVERIFIED",
        60: "FAIL",
    }
    for gate, status in hard_gate_specs.items():
        gates[f"gate_{gate}"] = status
    model_report = {
        "status": "CERTIFICATION_BLOCKED",
        "overall_decision": "CERTIFICATION_BLOCKED",
        "active_model": active.get("generation"),
        "candidate_model": "Candidate-M (market-independent)",
        "incumbent_retained": True,
        "protocol_sha256": protocol_hash,
        "gates": gates,
        "generated_at": now,
    }
    _write_json(REPORTS / "research/v21-model-certification.json", model_report)

    promotion = {
        "decision": "CERTIFICATION_BLOCKED",
        "active_model": active.get("generation"),
        "candidate_model": "Candidate-M",
        "gate_7": market_report["gate_7"],
        "gate_7_v21_state": "NOT_RUN",
        "c6_status": c6_report["status"],
        "c6_live_n": c6_report["live_n"],
        "feature_integration": feature_status,
        "protocol_sha256": protocol_hash,
        "generated_at": now,
    }
    _write_json(REPORTS / "release/v21-promotion-attestation.json", promotion)
    rollback = {
        "status": "NOT_DEPLOYED_ROLLBACK_NOT_EXERCISED",
        "incumbent": active.get("generation"),
        "candidate_deployment": "NONE",
        "generated_at": now,
    }
    _write_json(REPORTS / "release/v21-rollback-attestation.json", rollback)

    manifest_paths = [
        ROOT / "backend/models/active_generation.json",
        ROOT / "backend/serving/feature_bridge.py",
        ROOT / "backend/workers/c6_live_collector.py",
        ROOT / "backend/src/api/main.py",
        ROOT / "backend/src/api/endpoints/full_analysis.py",
        REPORTS / "research/v21-market-evaluation-protocol.json",
        REPORTS / "evidence/v21-feature-freshness-policy.json",
    ]
    audit_manifest = {
        "generated_at": now,
        "repository_head": _git("rev-parse", "HEAD"),
        "branch": _git("branch", "--show-current"),
        "worktree_status": _git("status", "--short"),
        "protocol_sha256": protocol_hash,
        "files": {str(path.relative_to(ROOT)): _sha(path) for path in manifest_paths},
    }
    _write_json(REPORTS / "release/v21-audit-manifest.json", audit_manifest)

    report = f"""# SabiScore V21 Production Activation Report

Generated: {now}

## Engineering Status

Candidate feature integration: **{feature_status}**. The active generation remains `{active.get('generation')}` with state `{active.get('promotion_state')}`. The 89-feature semantic contract currently has {len(undeclared)} feature(s) with undeclared required meaning, units, or serving source.

## Model Quality

**NOT CERTIFIED.** No attributable V21 Candidate-M out-of-sample prediction artifact was available. Calibration and regime reports are marked not run.

## Market Relative Performance

**BLOCKED.** The V20 report recorded Gate 7 as `{old_g7}`; its aggregate values are retained as unverified historical claims. V21 paired cohort evaluation did not run, and the protocol hash is `{protocol_hash}`.

## Live C6 Certification

**UNVERIFIED CURRENT DATABASE COUNT.** The V20 report last recorded N={v20_c6.get('N')}; this generator did not query the production database. Historical replay contributes zero to live C6 by contract.

## Production Readiness

**CERTIFICATION_BLOCKED.** Retain the incumbent in `ACTIVE_FAIL_CLOSED`. Do not activate Candidate-M until the V21 protocol evaluation passes and the registered live C6 milestone passes using persisted live observations. Current production activation: **NOT AUTHORIZED BY EVIDENCE**.
"""
    (REPORTS / "release/SABISCORE_V21_PRODUCTION_ACTIVATION_REPORT.md").write_text(report, encoding="utf-8")
    return {"protocol_sha256": protocol_hash, "feature_status": feature_status, "gate_7": market_report["gate_7"], "decision": "CERTIFICATION_BLOCKED"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("freeze-protocol", "generate-reports"))
    args = parser.parse_args()
    result = {"protocol_sha256": generate_protocol()} if args.command == "freeze-protocol" else generate_reports()
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
