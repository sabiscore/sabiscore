# Operator Action Pack (One Page)

Date: 2026-09-22  
Scope: Execute Phase A systematically for DEBT items 118, 28, 16, and 85.

## How to use this page

1. Run each item top to bottom.
2. Paste outputs/screenshots into the item evidence block in docs/DEBT.md.
3. Mark status only after evidence is captured.

---

## Item 118 — ADR-0011 per-fixture disclosure decision (operator decision)

Objective: decide whether fixtures panel should default to prediction-backed payloads.

Decision options:

- Option A: keep `include_predictions=false` default (bounded DB read).
- Option B: allow prediction-backed default panel (higher inference/cost, wider disclosure scope).

Copy/paste checklist:

- [ ] Confirm current production behavior:
  - `GET /api/upcoming?limit=5` returns `predictions: null`, `staking_authorization: null`.
- [ ] Choose Option A or Option B explicitly.
- [ ] Record decision owner, timestamp, and rationale in docs/DEBT.md item 118.
- [ ] If Option B is chosen, open an implementation task that includes load/cost impact verification.

Evidence template to paste into docs/DEBT.md item 118:

```
Decision: OPTION_[A|B]
Authorized by: <name/role>
Timestamp (UTC): <yyyy-mm-ddThh:mm:ssZ>
Rationale: <one paragraph>
Observed current payload sample: <request/response summary>
Follow-up ticket/PR: <link>
```

---

## Item 28 — S3 IAM 403 (operator-only)

Objective: clear `s3_authorization_failed` for evidence storage writer path.

Known context:

- Bucket: `sabiscore-artifacts-prod-uswest2`
- Region: `us-west-2`
- Principal: `sabiscore-render-evidence-writer`

Copy/paste checklist:

- [ ] In AWS IAM console, verify policy attachment for the writer principal.
- [ ] In S3 console, verify bucket policy/object ownership does not block writer principal.
- [ ] Confirm writer scope includes required prefixes: `raw/*`, `processed/*`, `manifests/*`.
- [ ] Re-run probe from repo root:

```powershell
pnpm --filter @sabiscore/scraper storage:probe
```

- [ ] Save probe output and close item 28 only if `ok: true`.

Evidence template to paste into docs/DEBT.md item 28:

```
IAM change summary: <policy/bucket settings changed>
Principal: sabiscore-render-evidence-writer
Bucket: sabiscore-artifacts-prod-uswest2
Probe command: pnpm --filter @sabiscore/scraper storage:probe
Probe result: <full JSON or key fields>
Timestamp (UTC): <yyyy-mm-ddThh:mm:ssZ>
```

---

## Item 16 — Infra gate closure (historical secrets + CI dispatch lock)

Objective: close remaining release-infra residuals with auditable proof.

Copy/paste checklist:

- [ ] Confirm GitHub Actions dispatch lock is cleared with runner-backed execution:

```powershell
gh run list --branch master --limit 5
```

- [ ] For latest failed/successful run IDs, verify real runner and non-zero steps:

```powershell
gh api repos/sabiscore/sabiscore/actions/runs/<RUN_ID>/jobs
```

- [ ] Re-run historical secret scan proof (history mode):

```powershell
gitleaks detect --source . --report-format json --report-path artifacts/gitleaks-history.json
```

- [ ] Attach credential-owner revocation evidence for historical fingerprints.

Evidence template to paste into docs/DEBT.md item 16:

```
Actions dispatch status: <cleared|locked>
Run IDs checked: <ids>
Runner evidence: <runner_name + step count snippets>
Gitleaks history result: <summary count + report path>
Credential revocation evidence: <links/screenshots/owner attestation>
Timestamp (UTC): <yyyy-mm-ddThh:mm:ssZ>
```

---

## Item 85 — Alias health (resolved-monitoring)

Objective: keep alias parity checks reliable and detect regressions fast.

Copy/paste checklist:

- [ ] Probe canonical working frontend alias health endpoint.
- [ ] Verify backend/frontend SHA parity on release checks.
- [ ] Keep fallback alias documented in case of routing anomaly recurrence.

Suggested probe sequence:

```powershell
curl https://web-oversabis-projects.vercel.app/api/health
curl https://sabiscore-api-bav1.onrender.com/health
```

- [ ] If alias regression reappears, reopen item 85 with timestamped evidence.

Evidence template to paste into docs/DEBT.md item 85 (monitor run):

```
Frontend alias checked: <url>
Backend health checked: <url>
SHA parity: <frontend_sha vs backend_sha>
Result: <healthy|regressed>
Timestamp (UTC): <yyyy-mm-ddThh:mm:ssZ>
```

---

## Execution Snapshot (2026-09-22)

Use this section only as a quick reference for the most recent run; authoritative status still lives in `docs/DEBT.md`.

- Item 16 (run list): latest `master` runs observed as `completed/success` for
  canonical workflows (`35671911694`, `35671911700`, `35671911778`,
  `35671911696`, `35668060261`).
- Item 16 (runner evidence): run `35671911696` jobs reported non-empty runners
  and non-zero steps (example: backend job `runner=GitHub Actions 1000008272`,
  `steps=18`).
- Item 16 (history scan): `gitleaks detect --source . --report-format json --report-path artifacts/gitleaks-history.json`
  reported `leaks found: 2` after scanning 668 commits (40.88 MB).
- Item 28 rerun output:

```json
{ "ok": false, "error_code": "s3_write_failed", "http_status": null }
```

  Interpret this with prerequisite checks: if `SABISCORE_ARTIFACT_BUCKET` is
  unset locally, the probe result is non-diagnostic for IAM/root-cause status.
- Item 85 parity check: frontend alias health returned `sha=6f15c04`,
  `backendStatus=ok`, backend health returned `sha=6b9b48b`, `status=healthy`.

---

## Phase completion rule

Phase A is complete only when:

- Item 118 has an explicit operator decision recorded.
- Item 28 has a passing storage probe with evidence.
- Item 16 has current dispatch + historical-secret proof captured.
- Item 85 has current parity-monitor evidence (or a reopened issue with proof).
