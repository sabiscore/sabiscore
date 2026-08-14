"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  BarChart3,
  CheckCircle2,
  Clock,
  Database,
  FileSearch,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import { ProviderMeter } from "@/components/ProviderMeter";
import { ResponsibleGamblingBanner } from "@/components/ui/ResponsibleGamblingTooltip";
import { ResearchModeBanner } from "@/components/research-mode-banner";
import type {
  FixtureEvidenceResponse,
  FixtureSummary,
  ManualOddsSnapshotRequest,
  MatchAnalysisResult,
  MarketEvaluation,
  ProviderOddsCandidate,
  Verdict,
} from "@/lib/betting-intelligence-api";
import {
  APIError,
  analyzeFixture,
  getEnginePolicy,
  getFixtureEvidence,
  getProviderOddsCandidates,
  getUpcomingFixtures,
  refreshFixtureEvidence,
  submitManualOddsSnapshot,
} from "@/lib/betting-intelligence-api";
import { describeEvidenceCode } from "@/lib/full-analysis-contract";
import { VERDICT_TOKENS } from "@/lib/verdict-tokens";

const COMPETITIONS = ["EPL", "LA_LIGA", "SERIE_A", "BUNDESLIGA", "LIGUE_1", "EREDIVISIE", "UCL"];

const VERDICT_LABEL: Record<Verdict, { label: string; action: string; tone: string }> = {
  HIGH_CONVICTION: {
    label: VERDICT_TOKENS.HIGH_CONVICTION.label,
    action: "RESEARCH SIGNAL — STAKING DISABLED",
    tone: VERDICT_TOKENS.HIGH_CONVICTION.tone,
  },
  ACTIONABLE: {
    label: VERDICT_TOKENS.ACTIONABLE.label,
    action: "RESEARCH SIGNAL — STAKING DISABLED",
    tone: VERDICT_TOKENS.ACTIONABLE.tone,
  },
  SPECULATIVE: {
    label: "Watchlist Signal",
    action: "WATCHLIST ONLY",
    tone: VERDICT_TOKENS.SPECULATIVE.tone,
  },
  HOLD: {
    label: "Monitor Closely",
    action: "WAIT FOR MORE EVIDENCE",
    tone: VERDICT_TOKENS.HOLD.tone,
  },
  PARTIAL: {
    label: "Incomplete Data",
    action: "MORE EVIDENCE REQUIRED",
    tone: VERDICT_TOKENS.PARTIAL.tone,
  },
  NO_BET: {
    label: "Skip This Match",
    action: "PASS",
    tone: VERDICT_TOKENS.NO_BET.tone,
  },
};

const fmtPct = (value?: number | null, digits = 1) =>
  value == null || !Number.isFinite(value) ? "Unavailable" : `${(value * 100).toFixed(digits)}%`;

const fmtPp = (value?: number | null, digits = 2) =>
  value == null || !Number.isFinite(value) ? "Unavailable" : `${value > 0 ? "+" : ""}${value.toFixed(digits)}pp`;

const fmtOdds = (value?: number | null) =>
  value == null || !Number.isFinite(value) ? "Unavailable" : value.toFixed(2);

const fmtDate = (value?: string | null) =>
  value ? new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value)) : "Kickoff unavailable";

const recordNumber = (record: Record<string, unknown> | null | undefined, key: string) => {
  const value = record?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
};

function userFacingError(error: unknown, fallback: string): string {
  if (error instanceof APIError && [408, 503, 504].includes(error.status)) {
    return "Intelligence service is unavailable or exceeded its deadline. No recommendation was produced; retry shortly.";
  }
  return fallback;
}

interface OddsForm {
  bookmaker: string;
  home: string;
  draw: string;
  away: string;
  observedAt: string;
  sourceLabel: string;
  sourceUrl: string;
  confirmed: boolean;
}

const defaultOddsForm = (): OddsForm => {
  const now = new Date();
  now.setSeconds(0, 0);
  return {
    bookmaker: "",
    home: "",
    draw: "",
    away: "",
    observedAt: now.toISOString().slice(0, 16),
    sourceLabel: "",
    sourceUrl: "",
    confirmed: false,
  };
};

function statusText(evidence?: FixtureEvidenceResponse | null) {
  if (!evidence) return "Select a fixture to retrieve evidence.";
  if (Object.values(evidence.source_status).some((statusValue) => statusValue === "CONFLICTING")) {
    return "Source conflict detected. The engine will fail closed until the conflict is resolved.";
  }
  if (Object.values(evidence.source_status).some((statusValue) => statusValue === "STALE")) {
    return "Stale evidence detected. Refresh the affected source before evaluation.";
  }
  if (evidence.data_gaps.length > 0) return "Evidence is incomplete. The engine will fail closed.";
  return "Evidence bundle is complete enough for value analysis.";
}

function stateBadge(
  evidence: FixtureEvidenceResponse | null,
  result: MatchAnalysisResult | null,
): { label: string; tone: string; detail: string } {
  if (result?.verdict === "NO_BET") {
    return { label: "NO_BET", tone: "pass", detail: "Verified evidence is available, but no current 1X2 outcome offers positive value." };
  }
  if (result?.verdict === "PARTIAL") {
    return { label: "PARTIAL", tone: "partial", detail: "Critical evidence is missing, stale, or conflicting. Stake remains pass." };
  }
  if (result?.analysis_mode === "FORECAST_ONLY") {
    return { label: "FORECAST ONLY", tone: "neutral", detail: "Model context can be reviewed, but market value is not executable without a verified price." };
  }
  if (evidence && Object.values(evidence.source_status).some((statusValue) => statusValue === "CONFLICTING")) {
    return { label: "SOURCE CONFLICT", tone: "partial", detail: "Two required sources disagree. Resolve the conflict before analysis." };
  }
  if (evidence && Object.values(evidence.source_status).some((statusValue) => statusValue === "STALE")) {
    return { label: "STALE DATA", tone: "watch", detail: "Refresh the stale evidence source before relying on the verdict." };
  }
  if (evidence?.data_gaps.length) {
    return { label: "PARTIAL", tone: "partial", detail: "Evidence gaps are present. The backend will return a pass stake." };
  }
  if (result) {
    return { label: VERDICT_LABEL[result.verdict].action, tone: VERDICT_LABEL[result.verdict].tone, detail: result.explanation };
  }
  return { label: "FORECAST ONLY", tone: "neutral", detail: "Retrieve evidence, then submit one coherent odds snapshot before value analysis." };
}

function nextActionText(
  evidence: FixtureEvidenceResponse | null,
  result: MatchAnalysisResult | null,
): string {
  if (result?.verdict === "NO_BET") return "Pass. Refresh prices only if the market moves materially.";
  if (result?.verdict === "HOLD") return "Wait for lineups or refreshed non-critical evidence before reassessment.";
  if (result?.verdict === "PARTIAL") return "Resolve the listed data gaps, then rerun analysis.";
  if (result?.verdict === "ACTIONABLE" || result?.verdict === "HIGH_CONVICTION") {
    return "Review the signal as research only; staking remains disabled until model certification passes.";
  }
  if (result?.verdict === "SPECULATIVE") return "Keep on watchlist only; do not treat this state as execution permission.";
  if (evidence?.data_gaps.some((gap) => gap.includes("coherent_1x2_market_snapshot"))) {
    return "Enter one confirmed bookmaker 1X2 snapshot to unlock market math.";
  }
  if (evidence?.data_gaps.length) return "Review evidence gaps before running analysis.";
  return "Retrieve evidence, confirm odds, then run analysis.";
}

function Timeline({ evidence }: { evidence: FixtureEvidenceResponse | null }) {
  const rows = evidence?.retrieval_timeline ?? [
    { step: "fixture", status: "WAITING", source: "database" },
    { step: "model", status: "WAITING", source: "predictions" },
    { step: "market", status: "WAITING", source: "manual odds snapshot" },
  ];

  return (
    <section className="bi-panel">
      <div className="bi-panel-title"><Clock size={16} /> Evidence Retrieval Timeline</div>
      <div className="bi-timeline">
        {rows.map((row) => (
          <div className="bi-timeline-row" key={String(row.step)}>
            <span className={`bi-dot ${String(row.status).toLowerCase()}`} />
            <span>{String(row.step).replace(/_/g, " ")}</span>
            <strong>{String(row.status)}</strong>
            <small>{String(row.source ?? "source unavailable")}</small>
          </div>
        ))}
      </div>
    </section>
  );
}

function ReadinessRail({ evidence }: { evidence: FixtureEvidenceResponse | null }) {
  const rows = evidence?.readiness ?? [
    { stage: "Fixture identity", state: "WAITING", source: "database" },
    { stage: "Team metrics", state: "WAITING", source: "model features" },
    { stage: "Availability", state: "WAITING", source: "provider gateway" },
    { stage: "Lineup", state: "WAITING", source: "provider gateway" },
    { stage: "Model", state: "WAITING", source: "SabiScore backend" },
    { stage: "Market", state: "WAITING", source: "bookmaker snapshot" },
    { stage: "Risk gate", state: "WAITING", source: "strict engine" },
  ];

  return (
    <section className="bi-panel">
      <div className="bi-panel-title"><ShieldCheck size={16} /> Evidence Readiness</div>
      <div className="bi-rail">
        {rows.map((row) => (
          <div className="bi-rail-row" key={String(row.stage)}>
            <span className={`bi-dot ${String(row.state).toLowerCase()}`} />
            <div>
              <strong>{String(row.stage)}</strong>
              <small>{String(row.source ?? "source unavailable")} {row.timestamp ? `| ${fmtDate(String(row.timestamp))}` : ""}</small>
              {row.reason ? <small className="bi-risk">{String(row.reason)}</small> : null}
            </div>
            <span className="bi-state">{String(row.state)}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

function OutcomeTable({ rows }: { rows?: MarketEvaluation[] | null }) {
  return (
    <section className="bi-panel">
      <div className="bi-panel-title"><BarChart3 size={16} /> All-Outcome Audit</div>
      {rows && rows.length > 0 ? (
        <div className="bi-table-wrap">
          <div className="bi-table" role="table" aria-label="All outcome market audit">
            <div className="bi-tr bi-th" role="row">
              <span>Outcome</span><span>Model</span><span>Fair market<em className="bi-gloss">De-vigged, overround removed</em></span><span>Odds</span><span>Edge<em className="bi-gloss">Model vs fair</em></span><span>EV<em className="bi-gloss">Avg. unit return</em></span>
            </div>
            {rows.map((row) => (
              <div className="bi-tr" role="row" key={row.market_label}>
                <span>{row.market_label.replace("_ML", "")}</span>
                <span>{fmtPct(row.model_probability)}</span>
                <span>{fmtPct(row.fair_market_probability)}</span>
                <span>{fmtOdds(row.market_odds)}</span>
                <span className={row.edge > 0 ? "bi-good" : "bi-risk"}>{fmtPp(row.edge_pct)}</span>
                <span className={row.expected_value > 0 ? "bi-good" : "bi-risk"}>
                  {Number.isFinite(row.expected_value) ? `${row.expected_value > 0 ? "+" : ""}${row.expected_value.toFixed(4)}` : "Unavailable"}
                </span>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <p className="bi-muted">No coherent market snapshot is available. Submit one bookmaker 1X2 snapshot to unlock the audit.</p>
      )}
    </section>
  );
}

export function BettingIntelligenceDashboard() {
  const [competition, setCompetition] = useState("EPL");
  const [fixtures, setFixtures] = useState<FixtureSummary[]>([]);
  const [selectedFixtureId, setSelectedFixtureId] = useState<string>("");
  const [evidence, setEvidence] = useState<FixtureEvidenceResponse | null>(null);
  const [result, setResult] = useState<MatchAnalysisResult | null>(null);
  const [teamQuery, setTeamQuery] = useState("");
  const [dateFilter, setDateFilter] = useState("");
  const [oddsCandidates, setOddsCandidates] = useState<ProviderOddsCandidate[]>([]);
  const [sourceDrawerOpen, setSourceDrawerOpen] = useState(false);
  const [oddsForm, setOddsForm] = useState<OddsForm>(() => defaultOddsForm());
  const [policy, setPolicy] = useState<string>("4.2pp edge threshold");
  const [loading, setLoading] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const selectedFixture = useMemo(
    () => fixtures.find((fixture) => fixture.fixture_id === selectedFixtureId) ?? null,
    [fixtures, selectedFixtureId],
  );
  const visibleFixtures = useMemo(() => {
    const q = teamQuery.trim().toLowerCase();
    return fixtures.filter((fixture) => {
      const teamMatches = !q
        || fixture.home_team.toLowerCase().includes(q)
        || fixture.away_team.toLowerCase().includes(q);
      const dateMatches = !dateFilter
        || fixture.kickoff_utc.slice(0, 10) === dateFilter;
      return teamMatches && dateMatches;
    });
  }, [dateFilter, fixtures, teamQuery]);
  const parsedOdds = useMemo(
    () => ({
      home: Number(oddsForm.home),
      draw: Number(oddsForm.draw),
      away: Number(oddsForm.away),
    }),
    [oddsForm.away, oddsForm.draw, oddsForm.home],
  );
  const oddsFormValid = Boolean(
    selectedFixtureId
    && oddsForm.bookmaker.trim().length >= 2
    && Number.isFinite(parsedOdds.home)
    && parsedOdds.home > 1
    && Number.isFinite(parsedOdds.draw)
    && parsedOdds.draw > 1
    && Number.isFinite(parsedOdds.away)
    && parsedOdds.away > 1
    && oddsForm.observedAt
    && oddsForm.confirmed,
  );

  const loadFixtures = useCallback(async (preserveSelection = false) => {
    setLoading("fixtures");
    setError(null);
    try {
      const payload = await getUpcomingFixtures(competition);
      setFixtures(payload.fixtures);
      setSelectedFixtureId((current) => {
        if (preserveSelection && payload.fixtures.some((fixture) => fixture.fixture_id === current)) {
          return current;
        }
        return payload.fixtures[0]?.fixture_id ?? "";
      });
      setEvidence(null);
      setResult(null);
      setOddsCandidates([]);
      if (payload.fixtures.length === 0) {
        setError("No verified fixtures are available for this competition yet.");
      }
    } catch (err: unknown) {
      setFixtures([]);
      setSelectedFixtureId("");
      setEvidence(null);
      setResult(null);
      setOddsCandidates([]);
      setError(userFacingError(err, "Could not load verified fixtures."));
    } finally {
      setLoading(null);
    }
  }, [competition]);

  useEffect(() => {
    void loadFixtures(false);
  }, [loadFixtures]);

  const activeLoading = loading !== null;

  useEffect(() => {
    setOddsCandidates([]);
    setOddsForm(defaultOddsForm());
  }, [selectedFixtureId]);

  useEffect(() => {
    if (!selectedFixtureId) {
      setEvidence(null);
      setResult(null);
    }
  }, [selectedFixtureId]);

  useEffect(() => {
    let cancelled = false;
    getEnginePolicy()
      .then((payload) => {
        if (!cancelled) {
          setPolicy(`${payload.policy.min_actionable_edge_pp.toFixed(1)}pp edge threshold`);
        }
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  const loadEvidence = async () => {
    if (!selectedFixtureId) return;
    setLoading("evidence");
    setError(null);
    setResult(null);
    try {
      setEvidence(await getFixtureEvidence(selectedFixtureId));
    } catch (err: unknown) {
      setError(userFacingError(err, "Evidence retrieval failed. No recommendation was produced."));
    } finally {
      setLoading(null);
    }
  };

  const runAnalysis = async () => {
    if (!selectedFixtureId) return;
    setLoading("analysis");
    setError(null);
    try {
      const response = await analyzeFixture(selectedFixtureId);
      setResult(response);
      setEvidence(await getFixtureEvidence(selectedFixtureId).catch(() => evidence));
    } catch (err: unknown) {
      setError(userFacingError(err, "Analysis failed. No recommendation was produced."));
    } finally {
      setLoading(null);
    }
  };

  const refreshEvidence = async () => {
    if (!selectedFixtureId) return;
    setLoading("refresh");
    setError(null);
    try {
      await refreshFixtureEvidence(selectedFixtureId, "PREMATCH_STANDARD");
      setEvidence(await getFixtureEvidence(selectedFixtureId));
    } catch (err: unknown) {
      setError(userFacingError(err, "Evidence refresh failed."));
    } finally {
      setLoading(null);
    }
  };

  const loadOddsCandidates = async () => {
    if (!selectedFixtureId) return;
    setLoading("odds-candidates");
    setError(null);
    try {
      const payload = await getProviderOddsCandidates(selectedFixtureId);
      setOddsCandidates(payload.candidates);
      if (payload.candidates.length === 0) {
        setError("No backend bookmaker snapshots are available. Manual entry is required.");
      }
    } catch (err: unknown) {
      setError(userFacingError(err, "Could not load bookmaker snapshots."));
    } finally {
      setLoading(null);
    }
  };

  const previewCandidate = (candidate: ProviderOddsCandidate) => {
    setOddsForm((current) => ({
      ...current,
      bookmaker: candidate.bookmaker,
      home: String(candidate.home_odds),
      draw: String(candidate.draw_odds),
      away: String(candidate.away_odds),
      observedAt: new Date(candidate.captured_at).toISOString().slice(0, 16),
      sourceLabel: `${candidate.provider} | ${candidate.bookmaker}`,
      confirmed: false,
    }));
  };

  const submitOdds = async (event: FormEvent) => {
    event.preventDefault();
    if (!selectedFixtureId) return;
    const payload: ManualOddsSnapshotRequest = {
      bookmaker: oddsForm.bookmaker.trim(),
      home_odds: parsedOdds.home,
      draw_odds: parsedOdds.draw,
      away_odds: parsedOdds.away,
      observed_at: new Date(oddsForm.observedAt).toISOString(),
      source_label: oddsForm.sourceLabel.trim() || null,
      source_url: oddsForm.sourceUrl.trim() || null,
      user_confirmed: oddsForm.confirmed,
    };
    setLoading("odds");
    setError(null);
    try {
      await submitManualOddsSnapshot(selectedFixtureId, payload);
      setOddsForm(defaultOddsForm());
      setEvidence(await getFixtureEvidence(selectedFixtureId));
      setResult(await analyzeFixture(selectedFixtureId));
    } catch (err: unknown) {
      setError(userFacingError(err, "Odds snapshot was rejected."));
    } finally {
      setLoading(null);
    }
  };

  const cfg = result ? VERDICT_LABEL[result.verdict] : null;
  const currentState = stateBadge(evidence, result);
  const nextAction = nextActionText(evidence, result);

  return (
    <div className="bi-root">
      <style>{`
        .bi-root{min-height:100vh;background:#08100f;color:#eef7f2;font-family:Inter,system-ui,sans-serif}
        .bi-shell{max-width:1200px;margin:0 auto;padding:24px}
        .bi-top{display:flex;align-items:flex-end;justify-content:space-between;gap:16px;margin-bottom:18px}
        .bi-title{font-size:28px;font-weight:800;margin:0;letter-spacing:0}
        .bi-sub{color:#9fb3aa;margin:6px 0 0;max-width:720px}
        .bi-grid{display:grid;grid-template-columns:340px 1fr;gap:16px;align-items:start}
        .bi-panel{border:1px solid rgba(255,255,255,.11);background:#0f1b18;border-radius:8px;padding:16px;box-shadow:0 18px 60px rgba(0,0,0,.22)}
        .bi-panel-title{display:flex;gap:8px;align-items:center;font-size:13px;font-weight:800;text-transform:uppercase;letter-spacing:0;color:#cfe5dc;margin-bottom:12px}
        .bi-select,.bi-input{width:100%;border:1px solid rgba(255,255,255,.14);background:#101f1b;color:#f5fffb;border-radius:6px;padding:10px;font-size:14px}
        .bi-select:focus-visible,.bi-input:focus-visible,.bi-btn:focus-visible,.bi-fixture:focus-visible{outline:2px solid #9eeec8;outline-offset:2px}
        .bi-label{display:block;color:#9fb3aa;font-size:12px;font-weight:700;margin:12px 0 6px}
        .bi-fixture{width:100%;text-align:left;border:1px solid rgba(255,255,255,.1);background:#10231e;color:#eef7f2;border-radius:7px;padding:12px;margin-bottom:8px;cursor:pointer}
        .bi-fixture[aria-current=true]{border-color:#39d98a;background:#123126}
        .bi-fixture strong{display:block;font-size:14px;margin-bottom:4px}
        .bi-fixture small,.bi-muted{color:#9fb3aa}
        .bi-actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:12px}
        .bi-btn{display:inline-flex;align-items:center;gap:7px;border:0;border-radius:7px;background:#39d98a;color:#07120f;font-weight:800;padding:10px 13px;cursor:pointer}
        .bi-btn.secondary{background:#d7e5df;color:#10201b}
        .bi-btn.ghost{background:transparent;border:1px solid rgba(255,255,255,.16);color:#e8f5ef}
        .bi-btn:disabled{opacity:.45;cursor:not-allowed}
        .bi-main{display:grid;gap:16px}
        .bi-status{display:flex;align-items:center;justify-content:space-between;gap:16px;border:1px solid rgba(255,255,255,.11);background:linear-gradient(135deg,#10251f,#111a20);border-radius:8px;padding:18px}
        .bi-verdict{display:inline-flex;gap:8px;align-items:center;padding:8px 10px;border-radius:6px;font-weight:900}
        .bi-verdict.positive{background:hsl(var(--conviction-actionable)/.12);color:hsl(var(--conviction-actionable))}.bi-verdict.watch{background:hsl(var(--conviction-speculative)/.12);color:hsl(var(--conviction-speculative))}.bi-verdict.neutral{background:hsl(var(--conviction-hold)/.12);color:hsl(var(--conviction-hold))}.bi-verdict.partial{background:hsl(var(--conviction-partial)/.12);color:hsl(var(--conviction-partial))}.bi-verdict.pass{background:hsl(var(--signal-danger)/.12);color:hsl(var(--signal-danger))}
        .bi-metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}
        .bi-metric{border:1px solid rgba(255,255,255,.1);border-radius:7px;padding:12px;background:#0c1714}
        .bi-metric span{display:block;color:#9fb3aa;font-size:11px;text-transform:uppercase;font-weight:800}
        .bi-metric strong{display:block;margin-top:5px;font-size:18px}
        .bi-two{display:grid;grid-template-columns:1fr 1fr;gap:16px}
        .bi-list{display:grid;gap:8px;margin:0;padding:0;list-style:none}.bi-list li{border-left:3px solid #39d98a;padding:8px 10px;background:#0c1714;border-radius:4px}
        .bi-list.risk li{border-left-color:#ffd76b}.bi-list.gap li{border-left-color:#d8b8ff}
        .bi-table-wrap{overflow-x:auto;padding-bottom:2px}.bi-table{display:grid;gap:6px;min-width:680px}.bi-tr{display:grid;grid-template-columns:1fr 1fr 1fr .8fr .8fr .8fr;gap:8px;align-items:center;border-bottom:1px solid rgba(255,255,255,.07);padding:9px 0;font-size:13px}.bi-th{color:#9fb3aa;font-weight:900;text-transform:uppercase;font-size:11px}
        .bi-good{color:hsl(var(--signal-positive))}.bi-risk{color:hsl(var(--signal-danger))}
        .bi-timeline{display:grid;gap:10px}.bi-timeline-row{display:grid;grid-template-columns:14px 1fr auto;gap:10px;align-items:center}.bi-timeline-row small{grid-column:2 / 4;color:#9fb3aa}.bi-dot{width:10px;height:10px;border-radius:50%;background:#71827b}.bi-dot.verified,.bi-dot.success{background:#39d98a}.bi-dot.data_gap,.bi-dot.waiting{background:#d8b8ff}.bi-dot.stale{background:#ffd76b}.bi-dot.conflicting{background:#ffb5bd}
        .bi-rail{display:grid;gap:8px}.bi-rail-row{display:grid;grid-template-columns:14px 1fr auto;gap:10px;align-items:start;border-bottom:1px solid rgba(255,255,255,.07);padding:8px 0}.bi-rail-row strong{display:block}.bi-rail-row small{display:block;color:#9fb3aa;margin-top:2px}.bi-state{font-size:11px;font-weight:900;color:#cfe5dc}
        .bi-candidates{display:grid;gap:8px;margin-top:10px}.bi-candidate{display:flex;justify-content:space-between;gap:10px;align-items:center;border:1px solid rgba(255,255,255,.12);background:#0c1714;border-radius:7px;padding:10px}
        .bi-filters{display:grid;grid-template-columns:1fr 1fr;gap:10px}
        .bi-form-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}.bi-confirm{display:flex;gap:8px;align-items:flex-start;margin-top:12px;color:#cfe5dc;font-size:13px}
        .bi-error{display:flex;gap:8px;align-items:center;border:1px solid rgba(255,181,189,.3);background:#2a1518;color:#ffd9de;border-radius:7px;padding:10px;margin-top:12px}
        .bi-next-action{margin:8px 0 0;color:#d8f5e7;font-weight:800}
        .bi-note{border:1px solid rgba(255,255,255,.11);background:#0c1714;border-radius:7px;padding:12px;color:#cfe5dc}
        @media(max-width:900px){.bi-grid,.bi-two{grid-template-columns:1fr}.bi-metrics{grid-template-columns:1fr 1fr}.bi-top,.bi-status{align-items:flex-start;flex-direction:column}.bi-form-grid{grid-template-columns:1fr}}
        @media(max-width:560px){.bi-shell{padding:16px}.bi-metrics{grid-template-columns:1fr}.bi-title{font-size:24px}.bi-actions{flex-direction:column}.bi-btn{width:100%;justify-content:center}}
        .bi-gloss{display:block;font-size:10px;opacity:0.6;margin-top:2px;font-weight:400;text-transform:none}
        .bi-gap-summary{cursor:pointer;list-style:none;padding:8px 0;color:#9fb3aa;font-size:12px}
      `}</style>
      <div className="bi-shell">
        <ResearchModeBanner className="mb-5" />
        <header className="bi-top">
          <div>
            <h1 className="bi-title">Betting Intelligence</h1>
            <p className="bi-sub">Evidence-first value analysis. The backend owns probabilities, market math, verdicts, and stake policy.</p>
          </div>
          <div className="bi-note"><ShieldCheck size={16} /> {policy}</div>
        </header>

        <div className="bi-grid">
          <aside className="bi-panel">
            <div className="bi-panel-title"><Database size={16} /> Fixture Discovery</div>
            <label className="bi-label" htmlFor="competition">Competition</label>
            <select id="competition" className="bi-select" value={competition} onChange={(e) => setCompetition(e.target.value)}>
              {COMPETITIONS.map((item) => <option value={item} key={item}>{item}</option>)}
            </select>
            <div className="bi-filters">
              <label className="bi-label">Team
                <input className="bi-input" aria-label="Search fixtures by team" value={teamQuery} onChange={(e) => setTeamQuery(e.target.value)} placeholder="Search team" />
              </label>
              <label className="bi-label">Date
                <input className="bi-input" aria-label="Filter fixtures by date" type="date" value={dateFilter} onChange={(e) => setDateFilter(e.target.value)} />
              </label>
            </div>
            <div className="bi-actions">
              <button className="bi-btn ghost" type="button" disabled={activeLoading} onClick={() => void loadFixtures(true)}>
                <RefreshCw size={14} /> {loading === "fixtures" ? "Refreshing" : "Refresh"}
              </button>
            </div>
            <label className="bi-label">Verified Fixtures</label>
            {loading === "fixtures" && <p className="bi-muted">Loading fixtures...</p>}
            {!loading && visibleFixtures.length === 0 && <p className="bi-muted">No upcoming fixtures found for these filters.</p>}
            {visibleFixtures.map((fixture) => (
              <button
                className="bi-fixture"
                key={fixture.fixture_id}
                aria-current={fixture.fixture_id === selectedFixtureId}
                type="button"
                onClick={() => {
                  setSelectedFixtureId(fixture.fixture_id);
                  setEvidence(null);
                  setResult(null);
                }}
              >
                <strong>{fixture.home_team} vs {fixture.away_team}</strong>
                <small>{fmtDate(fixture.kickoff_utc)} | {fixture.odds_status.replace(/_/g, " ")}</small>
              </button>
            ))}
            <div className="bi-actions">
              <button className="bi-btn" type="button" disabled={!selectedFixtureId || activeLoading} onClick={loadEvidence}>
                <FileSearch size={14} /> Retrieve Evidence
              </button>
              <button className="bi-btn ghost" type="button" disabled={!selectedFixtureId || activeLoading} onClick={refreshEvidence}>
                <RefreshCw size={14} /> Refresh Evidence
              </button>
              <button className="bi-btn secondary" type="button" disabled={!selectedFixtureId || activeLoading} onClick={runAnalysis}>
                Analyze
              </button>
            </div>
            {error && <div className="bi-error"><AlertTriangle size={16} /> {error}</div>}
          </aside>

          {/* div not main: app/layout.tsx's root <main id="main-content"> is
              already this page's sole <main> landmark — a second one here
              is a duplicate-landmark a11y violation. .bi-main styling is
              class-based, so this is a no-op visually. */}
          <div className="bi-main">
            <section className="bi-status" aria-live="polite">
              <div>
                <div className="bi-panel-title"><CheckCircle2 size={16} /> Current State</div>
                <strong>{selectedFixture ? `${selectedFixture.home_team} vs ${selectedFixture.away_team}` : "No fixture selected"}</strong>
                <p className="bi-muted">{statusText(evidence)}</p>
                <p className="bi-muted">{currentState.detail}</p>
                <p className="bi-next-action">{nextAction}</p>
              </div>
              {cfg ? <span className={`bi-verdict ${currentState.tone}`}>{cfg.label}: {cfg.action}</span> : <span className={`bi-verdict ${currentState.tone}`}>{currentState.label}</span>}
            </section>

            {result && (
              <section className="bi-panel">
                <div className="bi-panel-title"><BarChart3 size={16} /> Model Versus Market</div>
                <div className="bi-metrics">
                  <div className="bi-metric"><span>Best Market</span><strong>{result.best_market?.replace("_ML", "") ?? "Unavailable"}</strong></div>
                  <div className="bi-metric"><span>Edge<em className="bi-gloss">Model prob. minus fair implied</em></span><strong>{fmtPp(result.edge_percentage_points)}</strong></div>
                  <div className="bi-metric"><span>Expected Value<em className="bi-gloss">Avg. return per unit staked</em></span><strong>{result.expected_value == null ? "Unavailable" : result.expected_value.toFixed(4)}</strong></div>
                  <div className="bi-metric"><span>Stake</span><strong>Disabled</strong></div>
                  <div className="bi-metric"><span>Stake permission</span><strong>Not permitted — uncertified generation</strong></div>
                  <div className="bi-metric"><span>Confidence</span><strong>{result.confidence ?? "Unavailable"}</strong></div>
                  <div className="bi-metric"><span>Minimum acceptable odds</span><strong>{fmtOdds(result.minimum_acceptable_odds)}</strong></div>
                </div>
                <p className="bi-muted">{result.explanation}</p>
              </section>
            )}

            <div className="bi-two">
              <Timeline evidence={evidence} />
              <ReadinessRail evidence={evidence} />
            </div>

            <ProviderMeter />

            <div className="bi-two">
              <section className="bi-panel">
                <div className="bi-panel-title"><ShieldCheck size={16} /> Evidence Passport</div>
                {evidence ? (
                  <>
                    <div className="bi-metrics">
                      <div className="bi-metric"><span>Model</span><strong>{evidence.source_status.model}</strong></div>
                      <div className="bi-metric"><span>Market</span><strong>{evidence.source_status.market}</strong></div>
                      <div className="bi-metric"><span>Team Metrics</span><strong>{evidence.source_status.team_metrics}</strong></div>
                      <div className="bi-metric"><span>Availability</span><strong>{evidence.source_status.availability}</strong></div>
                      <div className="bi-metric"><span>Model age</span><strong>{recordNumber(evidence.freshness, "model_features_seconds") == null ? "Unknown" : `${recordNumber(evidence.freshness, "model_features_seconds")}s`}</strong></div>
                      <div className="bi-metric"><span>Market age</span><strong>{recordNumber(evidence.freshness, "market_seconds") == null ? "Unknown" : `${recordNumber(evidence.freshness, "market_seconds")}s`}</strong></div>
                      <div className="bi-metric"><span>Epistemic uncertainty</span><strong>{fmtPct(recordNumber(evidence.model ?? null, "epistemic_uncertainty"))}</strong></div>
                      <div className="bi-metric"><span>Aleatoric uncertainty</span><strong>{fmtPct(recordNumber(evidence.model ?? null, "aleatoric_uncertainty"))}</strong></div>
                    </div>
                    {evidence.data_gaps.length > 0 && (
                      evidence.data_gaps.length > 5 ? (
                        <details>
                          <summary className="bi-gap-summary">{evidence.data_gaps.length} fields pending — show all ▸</summary>
                          <ul className="bi-list gap">
                            {evidence.data_gaps.map((gap) => <li key={gap}>{gap.replace(/_/g, " ")}</li>)}
                          </ul>
                        </details>
                      ) : (
                        <ul className="bi-list gap">
                          {evidence.data_gaps.map((gap) => <li key={gap}>{gap.replace(/_/g, " ")}</li>)}
                        </ul>
                      )
                    )}
                  </>
                ) : <p className="bi-muted">Evidence has not been retrieved yet.</p>}
              </section>
              <section className="bi-panel">
                <div className="bi-panel-title">Compare Sources</div>
                <button className="bi-btn ghost" type="button" onClick={() => setSourceDrawerOpen((value) => !value)}>
                  {sourceDrawerOpen ? "Hide" : "Show"} source comparison
                </button>
                {sourceDrawerOpen && evidence?.source_comparison?.length ? (
                  <div className="bi-candidates">
                    {evidence.source_comparison.map((row) => (
                      <div className="bi-candidate" key={`${String(row.field)}-${String(row.selected_source)}`}>
                        <span>
                          <strong>{String(row.field)}</strong>
                          <small className="bi-muted">{String(row.reason ?? "No selection reason")}</small>
                        </span>
                        <span className="bi-state">{String(row.status)}</span>
                      </div>
                    ))}
                  </div>
                ) : <p className="bi-muted">Source comparison appears after evidence retrieval.</p>}
              </section>
            </div>

            <section className="bi-panel">
              <div className="bi-panel-title"><Database size={16} /> Manual Odds Snapshot</div>
              <div className="bi-actions">
                <button className="bi-btn ghost" type="button" disabled={!selectedFixtureId || activeLoading} onClick={loadOddsCandidates}>
                  Auto-fill market
                </button>
              </div>
              {oddsCandidates.length > 0 && (
                <div className="bi-candidates">
                  {oddsCandidates.map((candidate) => (
                    <div className="bi-candidate" key={`${candidate.bookmaker}-${candidate.captured_at}`}>
                      <span>
                        <strong>{candidate.bookmaker}</strong>
                        <small className="bi-muted">H {fmtOdds(candidate.home_odds)} D {fmtOdds(candidate.draw_odds)} A {fmtOdds(candidate.away_odds)} | {fmtDate(candidate.captured_at)}</small>
                      </span>
                      <button className="bi-btn secondary" type="button" onClick={() => previewCandidate(candidate)}>Preview</button>
                    </div>
                  ))}
                </div>
              )}
              <form onSubmit={submitOdds}>
                <label className="bi-label">Bookmaker<input className="bi-input" value={oddsForm.bookmaker} onChange={(e) => setOddsForm((f) => ({ ...f, bookmaker: e.target.value }))} required /></label>
                <div className="bi-form-grid">
                  <label className="bi-label">Home odds<input className="bi-input" type="number" min="1.01" step="0.01" value={oddsForm.home} onChange={(e) => setOddsForm((f) => ({ ...f, home: e.target.value }))} required /></label>
                  <label className="bi-label">Draw odds<input className="bi-input" type="number" min="1.01" step="0.01" value={oddsForm.draw} onChange={(e) => setOddsForm((f) => ({ ...f, draw: e.target.value }))} required /></label>
                  <label className="bi-label">Away odds<input className="bi-input" type="number" min="1.01" step="0.01" value={oddsForm.away} onChange={(e) => setOddsForm((f) => ({ ...f, away: e.target.value }))} required /></label>
                </div>
                <label className="bi-label">Observed timestamp<input className="bi-input" type="datetime-local" value={oddsForm.observedAt} onChange={(e) => setOddsForm((f) => ({ ...f, observedAt: e.target.value }))} required /></label>
                <label className="bi-label">Source label or page reference<input className="bi-input" value={oddsForm.sourceLabel} onChange={(e) => setOddsForm((f) => ({ ...f, sourceLabel: e.target.value }))} /></label>
                <label className="bi-label">Optional URL label<input className="bi-input" type="url" value={oddsForm.sourceUrl} onChange={(e) => setOddsForm((f) => ({ ...f, sourceUrl: e.target.value }))} /></label>
                <div className="bi-note" style={{ marginTop: 12 }}>
                  Confirmation preview: {oddsForm.bookmaker || "Bookmaker unavailable"} | H {fmtOdds(parsedOdds.home)} D {fmtOdds(parsedOdds.draw)} A {fmtOdds(parsedOdds.away)}
                </div>
                <label className="bi-confirm">
                  <input type="checkbox" checked={oddsForm.confirmed} onChange={(e) => setOddsForm((f) => ({ ...f, confirmed: e.target.checked }))} />
                  I confirm these three prices are from one bookmaker and one fixture snapshot.
                </label>
                <div className="bi-actions">
                  <button className="bi-btn" type="submit" disabled={!oddsFormValid || activeLoading}>Submit Snapshot</button>
                </div>
              </form>
            </section>

            <OutcomeTable rows={result?.all_market_evaluations} />

            <ResponsibleGamblingBanner />

            {result && (
              <div className="bi-two">
                <section className="bi-panel">
                  <div className="bi-panel-title">Drivers</div>
                  <ul className="bi-list">{(result.drivers.length ? result.drivers : ["No verified drivers above display threshold."]).map((item) => <li key={item}>{item}</li>)}</ul>
                </section>
                <section className="bi-panel">
                  <div className="bi-panel-title">Risks And Invalidation</div>
                  <ul className="bi-list risk">{[...result.risks, ...result.invalidation_conditions].map((item) => <li key={item}>{item}</li>)}</ul>
                </section>
              </div>
            )}

            {result && (result.critical_gaps?.length || result.advisory_gaps?.length || result.conflicts?.length) ? (
              <div className="bi-two">
                {result.critical_gaps?.length ? (
                  <section className="bi-panel border-[hsl(var(--signal-danger)/0.45)]">
                    <div className="bi-panel-title text-[hsl(var(--signal-danger))]">
                      <AlertTriangle size={14} /> Blocking Gaps — execution paused
                    </div>
                    <ul className="bi-list gap">
                      {result.critical_gaps.map((gap) => <li key={gap}>{describeEvidenceCode(gap)}</li>)}
                    </ul>
                  </section>
                ) : null}
                {(result.advisory_gaps?.length || result.conflicts?.length) ? (
                  <section className="bi-panel border-[hsl(var(--signal-warning)/0.45)]">
                    <div className="bi-panel-title text-[hsl(var(--signal-warning))]">
                      Advisory
                    </div>
                    {result.advisory_gaps?.length ? (
                      <ul className="bi-list gap">
                        {result.advisory_gaps.map((gap) => <li key={gap}>{describeEvidenceCode(gap)}</li>)}
                      </ul>
                    ) : null}
                    {result.conflicts?.length ? (
                      <ul className="bi-list risk" style={{ marginTop: 8 }}>
                        {result.conflicts.map((c) => <li key={c}>{describeEvidenceCode(c)}</li>)}
                      </ul>
                    ) : null}
                  </section>
                ) : null}
              </div>
            ) : null}

            {result?.calculation_audit && (
              <section className="bi-panel">
                <div className="bi-panel-title">Price Window</div>
                <div className="bi-metrics">
                  <div className="bi-metric"><span>Breakeven</span><strong>{fmtOdds(result.calculation_audit.breakeven_odds)}</strong></div>
                  <div className="bi-metric"><span>Target EV</span><strong>{fmtOdds(result.calculation_audit.minimum_odds_for_target_ev)}</strong></div>
                  <div className="bi-metric"><span>Edge Preserving</span><strong>{fmtOdds(result.calculation_audit.edge_preserving_minimum_odds)}</strong></div>
                  <div className="bi-metric"><span>Method</span><strong>{result.minimum_acceptable_odds_method?.replace(/_/g, " ") ?? "Unavailable"}</strong></div>
                </div>
              </section>
            )}

            <section className="bi-panel">
              <div className="bi-panel-title"><AlertTriangle size={16} /> Responsible Use</div>
              <p className="bi-muted">This interface provides statistical analysis only. A pass, hold, or partial verdict is an intentional safety state. Never treat model output as assured return.</p>
            </section>
          </div>
        </div>
      </div>
    </div>
  );
}
