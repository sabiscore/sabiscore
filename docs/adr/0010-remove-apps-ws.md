# 0010 — Remove `apps/ws` (OG-02)

**Status:** Accepted, operator-approved 2026-09-13 · implemented 2026-09-13

## Context

`PRODUCTION_EXECUTIVE_DIRECTIVE.md` §25 (P11) names the WebSocket build-vs-
remove question explicitly: *"if `apps/ws` is a stub, do not represent it as
production real-time infrastructure. Evaluate build versus removal, choose
the smallest architecture satisfying the product, require OG-02, and create
an ADR."* This is that evaluation and that ADR.

`apps/ws` was a standalone FastAPI service (`Dockerfile`, `main.py`,
`requirements.txt`) with exactly one endpoint:

```python
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            # Echo for now; replace with real-time logic
            await websocket.send_text(f"Echo: {data}")
    except WebSocketDisconnect:
        pass
```

It imported and constructed a `redis.Redis` client but never called any
method on it — dead on arrival, not a partially-built feature. Evidence
gathered before the decision:

- **Not deployed.** `render.yaml` (SabiScore's actual production target) has
  zero references to `apps/ws`, `sabiscore-ws`, `WS_PORT`, or a `ws` service
  of any kind.
- **Not canonical.** `CLAUDE.md`'s own "SABISCORE CANONICAL PRODUCTION SHAPE"
  names exactly three production-authorised entrypoints —
  `backend/src/api/main.py`, `apps/web`, `apps/scraper` — and states
  "Never reference `apps/api` or `frontend/` in production scripts, CI, or
  runbooks" for the *other* two known-legacy surfaces; `apps/ws` was never
  even added to that list to begin with.
- **Not consumed.** A repo-wide search of `apps/web/src` for `new
  WebSocket(` / `ws://` / `wss://` found zero client-side connections to
  anything.
- **Redundant with real, already-shipped infrastructure.** `backend/src/api/
  websocket.py` — inside the one FastAPI service that *is* canonical — is a
  substantially more complete real-time layer: a `ConnectionManager`, a
  mounted `/ws/edge/{match_id}` route (`app.include_router(ws_router, ...)`
  in `main.py:520`), Redis pub/sub subscription for match events, polling
  loops for xG and odds, and an edge-alert broadcast via `EdgeDetector`. Where
  `apps/ws` echoed text, this module already does the real thing.
- **Only remaining consumer of the idea was a comment.** `apps/web`'s
  `/api/revalidate` route carried a docstring claiming it is "called by
  WebSocket layer when goals/odds change" — true in spirit, but the actual
  caller is `backend/src/api/websocket.py`'s `trigger_isr_revalidation()`,
  never `apps/ws`. The comment is corrected, not removed, since the backend
  callback is real code, even though (see Consequences) it is currently inert
  in production.
- `docker-compose.prod.yml` provisioned `apps/ws` with 4 replicas — a
  self-hosted deployment shape that was never adopted (Render + Vercel is the
  actual, extensively-documented production target); this made the stub look
  more load-bearing on paper than it ever was in practice.

## Decision

Remove `apps/ws` outright rather than build it out. "Smallest architecture
satisfying the product" favors deleting a redundant, unconsumed duplicate
over investing further in a second real-time service when a more complete
one already exists, is deployed, and is wired into the one canonical backend.

Removed:

- `apps/ws/` (directory, 3 tracked files + local `__pycache__`)
- `pnpm-workspace.yaml`'s `apps/ws` package entry
- `docker-compose.prod.yml`'s `ws:` service block (4-replica deploy spec,
  ports, Redis dependency)
- `turbo.json`'s `NEXT_PUBLIC_WS_URL` from `globalEnv` (nothing read it —
  confirmed zero references anywhere in `apps/web/src` after the directory
  search above)

Corrected, not removed: the `/api/revalidate` route's docstring, which now
names the real caller and the reason it does not currently fire in
production (see Consequences and `docs/DEBT.md`).

Not touched by this ADR, on purpose: `apps/api/` and `frontend/` are
separately-named legacy surfaces in `CLAUDE.md`'s own table. Both were
confirmed absent from every CI workflow, Docker file, and `pnpm-
workspace.yaml` during this same investigation (their removal-from-config
action item is already done), but the directories themselves still exist on
disk — `apps/api/` even carries its own `LEGACY_ARCHIVED` marker file. Fully
deleting either is a bigger, separate call (OG-11, irreversible architecture
deletion) than the WebSocket-specific OG-02 this ADR resolves, and neither
was authorized in this pass.

## Consequences

- No production behavior changes. `apps/ws` was never deployed, so nothing
  that was working stops working.
- `backend/src/api/websocket.py` remains the one real-time layer, and this
  ADR does not change its behavior. Investigating it to write this ADR
  surfaced that it is currently **dormant end-to-end**: `NEXT_URL` /
  `REVALIDATE_SECRET` are unset in `render.yaml`, so `trigger_isr_
  revalidation()`'s own fail-closed guard skips every call; and nothing in
  the codebase publishes to the `match_events:{match_id}` Redis channel it
  subscribes to, so even a connected client would receive an initial
  "connected" acknowledgment and then silence. This is a real, separate
  finding — not fixed here, since turning it on is a product decision (does
  SabiScore want live push, and who produces the match events?), not a
  WebSocket-infrastructure cleanup. Recorded in `docs/DEBT.md`.
- Anyone reintroducing real-time push should extend `backend/src/api/
  websocket.py` (the one already wired into the canonical backend) rather
  than starting a second standalone service.
