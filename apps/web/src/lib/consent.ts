// The stored consent record, shared by the consent gate and the analytics
// tracker. Until 2026-09-26 the tracker never read it, so a visitor who chose
// "Essential Only" was still counted.
export const CONSENT_STORAGE_KEY = "sabiscore_consent_v1";
export const CONSENT_VERSION = "1.0.0";

// Opt-in: no stored choice, an unreadable one, or an old version all mean no.
export function analyticsConsented(): boolean {
  try {
    const stored = JSON.parse(localStorage.getItem(CONSENT_STORAGE_KEY) ?? "null");
    return stored?.version === CONSENT_VERSION && stored?.analytics === true;
  } catch {
    return false;
  }
}
