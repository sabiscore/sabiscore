# SabiScore Brand Architecture — Implementation Guide

This upgrade applies the three-part SabiScore identity directly to the production Next.js workspace without changing prediction, provider, market, health, or model contracts.

## Architecture applied

### 1. SabiSignal — master identity

`SabiSignalMark` is the canonical product mark. Its continuous S-curve represents observations flowing through inference into a forecast; the lime terminal node is the forecast output. The mark deliberately avoids literal football, gauge, shield, betting-slip, or AI-brain imagery.

The primary lockup is `SabiScoreBrand`. The sidebar uses the descriptor **Predictive intelligence** rather than the environment-like phrase **Production analytics**. Runtime/environment status remains the responsibility of the existing platform-health UI.

The supplied 512px master SVG has been surgically adapted rather than copied verbatim into every surface: the quantitative grid is removed from the favicon because it aliases at small sizes; the predictive path, obsidian field, signal gradient, origin node, terminal forecast node, and restrained depth treatment are retained. Inline navigation uses crisp, filter-free geometry for rendering performance.

### 2. Prediction Matrix — model language

`PredictionMatrix` is a secondary, decorative model primitive. It is applied to model metadata surfaces only. The highlighted cyan cell means **selected forecast/output**, not confidence or model health.

### 3. The Edge — market language

`EdgeSignal` is reserved for UI states where SabiScore already has an evidence-backed positive market edge. It is currently used only in the existing value-bet badge path, preserving all existing edge gates and thresholds.

## Files

- `apps/web/src/components/brand/sabiscore-brand.tsx` — canonical inline mark and wordmark lockup.
- `apps/web/src/components/brand/prediction-matrix.tsx` — secondary model/feature primitive.
- `apps/web/src/components/brand/edge-signal.tsx` — market-edge primitive.
- `apps/web/src/app/layout.tsx` — desktop/mobile shell branding and palette integration.
- `apps/web/src/components/mobile-nav.tsx` — canonical mobile-drawer lockup.
- `apps/web/src/components/match-intelligence-card.tsx` — evidence-gated Edge glyph in the existing value-bet badge.
- `apps/web/src/components/model-metadata-panel.tsx` — Prediction Matrix watermark on model metadata cards.
- `apps/web/src/app/globals.css` — centralized brand tokens and component primitives.
- `apps/web/public/icon.svg` — production favicon/PWA SabiSignal icon using the refined master SVG treatment.
- `apps/web/src/app/apple-icon.tsx` — generated Apple/PWA icon aligned with the refined SabiSignal treatment.

## Brand tokens

The canonical identity tokens are deliberately isolated from outcome/conviction colors:

```css
--brand-mint: #3ce4aa;
--brand-prediction: #29cff3;
--brand-forecast: #c4ff4d;
--brand-wordmark: #f6f8f7;
--brand-muted: #829590;
--brand-nav: #06140f;
--brand-elevated: #091c16;
--brand-inactive: #244139;
```

The lime forecast node is a mark-level semantic: it denotes the terminal forecast/output in the logo. It must not be reused as a probability-strength, value-bet, readiness, or success signal in product data UI.

## Local implementation

From the repository root:

```powershell
corepack enable
corepack prepare pnpm@11.8.0 --activate
pnpm install --frozen-lockfile
pnpm --filter @sabiscore/web typecheck
pnpm --filter @sabiscore/web test
pnpm --filter @sabiscore/web build
```

If your environment already has the repository's pnpm version installed, skip the `corepack prepare` command.

Run the web app:

```powershell
pnpm --filter @sabiscore/web dev
```

Open `http://localhost:3000` and verify the following:

1. Sidebar: SabiSignal mark + `SabiScore` + `PREDICTIVE INTELLIGENCE`.
2. Mobile header: compact SabiSignal icon; no generic gauge is used as the brand mark.
3. Mobile drawer: same canonical SabiScore lockup as desktop.
4. Browser/PWA icon: obsidian SabiSignal with mint-to-lime predictive signal and distinct lime forecast node.
5. Apple/PWA icon: same geometry and semantic hierarchy as the browser icon.
6. Model metadata surfaces: subtle matrix watermark; cyan cell does not replace actual model-status text.
7. Value-bet cards: Edge glyph appears only when the pre-existing `isValueBet` gate is true.
8. No changes to prediction probabilities, edge thresholds, Kelly sizing, provider state, health contracts, API routes, or backend authority.

## Production deployment

Before deployment:

```powershell
pnpm --filter @sabiscore/web typecheck
pnpm --filter @sabiscore/web test
pnpm --filter @sabiscore/web build
```

Then deploy through the repository's existing Vercel workflow. Because `apps/web/public/icon.svg` is referenced by Next metadata and `manifest.json`, no new environment variable or CDN configuration is required.

After deployment, hard-refresh once or clear the site's cached favicon/PWA metadata if the browser still shows the previous icon. Existing service-worker/browser favicon caches can outlive a normal page refresh.

## Extension rules

- Use `SabiSignalMark` for favicon-adjacent, loading, navigation, authentication, and master-brand surfaces.
- Use `PredictionMatrix` for model, feature, ensemble, calibration, or inference surfaces only.
- Use `EdgeSignal` only when backend evidence already confirms a positive/value market state.
- Never use the lime forecast node as a generic success indicator; existing emerald readiness/success semantics remain authoritative.
- Never use the logo's terminal node to imply probability confidence.
- Do not place literal footballs, shields, gauges, speedometers, betting slips, or AI-brain imagery back into the master identity.

## Validation note

The change is limited to brand rendering and documentation. The production PR should still run the repository's normal frontend typecheck, tests, and build before deployment. The icon SVG is deliberately effect-light at 48px/inline sizes while the standalone 512px asset retains a restrained glow and gradient for richer browser/PWA presentation.
