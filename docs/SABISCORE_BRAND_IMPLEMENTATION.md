# SabiScore Brand Architecture — Implementation Guide

This upgrade applies the three-part SabiScore identity directly to the production Next.js workspace without changing prediction, provider, market, health, or model contracts.

## Architecture applied

### 1. SabiSignal — master identity

`SabiSignalMark` is the canonical product mark. Its continuous path represents observations flowing into inference; the cyan terminal node is the forecast output. It replaces the generic gauge used as the product identity in desktop and mobile navigation.

The primary lockup is `SabiScoreBrand`. The sidebar uses the descriptor **Predictive intelligence** rather than the environment-like phrase **Production analytics**. Runtime/environment status remains the responsibility of the existing platform-health UI.

### 2. Prediction Matrix — model language

`PredictionMatrix` is a secondary, decorative model primitive. It is applied to model metadata surfaces only. The highlighted cyan cell means **selected forecast/output**, not confidence or model health.

### 3. The Edge — market language

`EdgeSignal` is reserved for UI states where SabiScore already has an evidence-backed positive market edge. It is currently used only in the existing value-bet badge path, preserving all existing edge gates and thresholds.

## Files

- `apps/web/src/components/brand/sabiscore-brand.tsx` — canonical mark and wordmark lockup.
- `apps/web/src/components/brand/prediction-matrix.tsx` — secondary model/feature primitive.
- `apps/web/src/components/brand/edge-signal.tsx` — market-edge primitive.
- `apps/web/src/app/layout.tsx` — desktop/mobile shell branding and palette integration.
- `apps/web/src/components/mobile-nav.tsx` — canonical mobile-drawer lockup.
- `apps/web/src/components/match-intelligence-card.tsx` — evidence-gated Edge glyph in the existing value-bet badge.
- `apps/web/src/components/model-metadata-panel.tsx` — Prediction Matrix watermark on model metadata cards.
- `apps/web/src/app/globals.css` — centralized brand tokens and component primitives.
- `apps/web/public/icon.svg` — production favicon/PWA SabiSignal icon.
- `apps/web/src/app/apple-icon.tsx` — generated Apple/PWA icon aligned with SabiSignal.

## Brand tokens

The canonical identity tokens are deliberately isolated from outcome/conviction colors:

```css
--brand-mint: #3ce4aa;
--brand-prediction: #29cff3;
--brand-wordmark: #f6f8f7;
--brand-muted: #829590;
--brand-nav: #06140f;
--brand-elevated: #091c16;
--brand-inactive: #244139;
```

Do not reuse `--brand-prediction` to imply probability strength. Cyan is an identity/output semantic, while the existing domain tokens continue to describe conviction, readiness, warnings, and outcomes.

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
4. Browser/PWA icon: dark forest SabiSignal with mint path and cyan prediction node.
5. Model metadata surfaces: subtle matrix watermark; cyan cell does not replace actual model-status text.
6. Value-bet cards: Edge glyph appears only when the pre-existing `isValueBet` gate is true.
7. No changes to prediction probabilities, edge thresholds, Kelly sizing, provider state, health contracts, API routes, or backend authority.

## Production deployment

Before deployment:

```powershell
pnpm --filter @sabiscore/web typecheck
pnpm --filter @sabiscore/web test
pnpm --filter @sabiscore/web build
```

Then deploy through the repository's existing Vercel workflow. Because `apps/web/public/icon.svg` is referenced by both Next metadata and `manifest.json`, no new environment variable or CDN configuration is required.

After deployment, hard-refresh once or clear the site's cached favicon/PWA metadata if the browser still shows the previous icon. Existing service-worker/browser favicon caches can outlive a normal page refresh.

## Extension rules

- Use `SabiSignalMark` for favicon, loading, navigation, authentication, and master-brand surfaces.
- Use `PredictionMatrix` for model, feature, ensemble, calibration, or inference surfaces only.
- Use `EdgeSignal` only when backend evidence already confirms a positive/value market state.
- Never use the cyan terminal node as a generic success indicator; existing emerald readiness/success semantics remain authoritative.
- Do not place literal footballs, shields, gauges, speedometers, betting slips, or AI-brain imagery back into the master identity.

## Validation note

The source changes are dependency-neutral. In the analysis environment, package validation could not execute because pnpm was not locally installed and Corepack could not download the repository-pinned pnpm package due DNS/network access to the npm registry. Run the commands above in the normal development environment before production deployment.
