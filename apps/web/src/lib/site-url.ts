// The canonical public origin. NEXT_PUBLIC_SITE_URL overrides it, but the Vercel
// project builds from apps/web and never reads the root vercel.json that sets it:
// live 2026-09-26, og:url and robots.txt named the per-deployment host, share links
// and JSON-LD pointed at sabiscore.com (which does not resolve), and Google sign-in
// on a pinned host skipped the canonical redirect. So the default is the canonical
// alias, never VERCEL_URL (one deployment's host) and never an unresolved domain.
export const CANONICAL_SITE_URL = "https://sabiscore.vercel.app";

export function siteUrl(): string {
  return (process.env.NEXT_PUBLIC_SITE_URL?.trim() || CANONICAL_SITE_URL).replace(/\/+$/, "");
}
