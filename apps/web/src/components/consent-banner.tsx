/* eslint-disable jsx-a11y/aria-proptypes */
"use client";

import { useState, useEffect, useCallback } from "react";
import { Shield, AlertTriangle } from "lucide-react";

import { CONSENT_STORAGE_KEY, CONSENT_VERSION } from "@/lib/consent";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ConsentPreferences {
  necessary: boolean; // Always true
  analytics: boolean;
  marketing: boolean;
  personalization: boolean;
  ageVerified: boolean;
  responsibleGambling: boolean;
  timestamp: string;
  version: string;
}

const AGE_GATE_STORAGE_KEY = "sabiscore_age_gate_accepted_v1";

// ---------------------------------------------------------------------------
// Hook: useConsent
// ---------------------------------------------------------------------------

export function useConsent() {
  const [consent, setConsent] = useState<ConsentPreferences | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const stored = localStorage.getItem(CONSENT_STORAGE_KEY);
    if (stored) {
      try {
        const parsed = JSON.parse(stored) as ConsentPreferences;
        // Check version - if outdated, require re-consent
        if (parsed.version === CONSENT_VERSION) {
          setConsent(parsed);
        }
      } catch {
        // Invalid stored consent
      }
    }
    setIsLoading(false);
  }, []);

  const saveConsent = useCallback((prefs: Omit<ConsentPreferences, "timestamp" | "version">) => {
    const fullConsent: ConsentPreferences = {
      ...prefs,
      timestamp: new Date().toISOString(),
      version: CONSENT_VERSION,
    };
    localStorage.setItem(CONSENT_STORAGE_KEY, JSON.stringify(fullConsent));
    setConsent(fullConsent);
  }, []);

  const clearConsent = useCallback(() => {
    localStorage.removeItem(CONSENT_STORAGE_KEY);
    localStorage.removeItem(AGE_GATE_STORAGE_KEY);
    setConsent(null);
  }, []);

  const hasConsented = consent !== null && consent.ageVerified && consent.responsibleGambling;

  return { consent, saveConsent, clearConsent, isLoading, hasConsented };
}

// ---------------------------------------------------------------------------
// ConsentBanner Component
// ---------------------------------------------------------------------------

interface ConsentBannerProps {
  onConsentGiven?: (consent: ConsentPreferences) => void;
}

export function ConsentBanner({ onConsentGiven }: ConsentBannerProps) {
  const { saveConsent, isLoading, hasConsented } = useConsent();

  if (isLoading || hasConsented) {
    return null;
  }

  // v11 U14: one consent step. The age gate used to be followed by a bottom
  // cookie banner that covered the market table at 360 px, and its analytics,
  // marketing and personalization toggles were read by nothing. There is no
  // advertising, and the only optional processing is first-party usage counts.
  const accept = (analytics: boolean) => {
    const prefs = {
      necessary: true,
      analytics,
      marketing: false,
      personalization: true,
      ageVerified: true,
      responsibleGambling: true,
    };
    saveConsent(prefs);
    onConsentGiven?.(prefs as ConsentPreferences);
  };

  return (
    <div
      // m-auto on the card, not items-center here: a flex-centred child taller
      // than a 360 px viewport is clipped at the top and cannot be scrolled to.
      className="fixed inset-0 z-[100] flex overflow-y-auto bg-black/80 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="age-gate-title"
      aria-describedby="age-gate-desc"
    >
        <div className="m-auto w-full max-w-md animate-in fade-in slide-in-from-bottom-4 duration-300">
          <div className="rounded-2xl border border-amber-500/30 bg-gradient-to-b from-slate-900 to-slate-950 p-6 shadow-2xl">
            {/* Header */}
            <div className="mb-6 flex items-center justify-center gap-3">
              <AlertTriangle className="h-8 w-8 text-amber-400" />
              <h2 id="age-gate-title" className="text-xl font-bold text-white">Age Verification Required</h2>
            </div>

            {/* Content */}
            <div className="mb-6 space-y-4 text-center">
              <p id="age-gate-desc" className="text-slate-300">
                SabiScore provides sports predictions that may be used for betting purposes.
              </p>
              <div className="rounded-lg border border-amber-500/20 bg-amber-500/10 p-4">
                <p className="font-semibold text-amber-300">
                  You must be 18 years or older to use this service.
                </p>
                <p className="mt-2 text-sm text-amber-200/70">
                  By continuing, you confirm you are of legal gambling age in your jurisdiction.
                </p>
              </div>
            </div>

            {/* Responsible Gambling Acknowledgment */}
            <div className="mb-6 rounded-lg border border-slate-700 bg-slate-800/50 p-4">
              <h3 className="mb-2 flex items-center gap-2 font-semibold text-slate-200">
                <Shield className="h-4 w-4 text-emerald-400" />
                Responsible Gambling
              </h3>
              <ul className="space-y-1 text-sm text-slate-400">
                <li>• Only bet what you can afford to lose</li>
                <li>• Predictions are estimates, not guarantees</li>
                <li>• Set limits and take breaks</li>
              </ul>
              <div className="mt-3 flex gap-2 text-xs">
                <a
                  href="https://www.begambleaware.org"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-emerald-400 hover:underline"
                >
                  BeGambleAware.org
                </a>
                <span className="text-slate-600">|</span>
                <a
                  href="https://www.gamcare.org.uk"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-emerald-400 hover:underline"
                >
                  GamCare
                </a>
              </div>
            </div>

            <p className="mb-4 text-xs leading-relaxed text-slate-400">
              SabiScore counts anonymous page events on its own servers to improve the product. There is
              no advertising. You can decline and still use everything.
            </p>

            {/* Actions */}
            <div className="flex flex-col gap-3">
              <button
                onClick={() => accept(true)}
                className="w-full rounded-lg bg-gradient-to-r from-emerald-600 to-emerald-500 px-6 py-3 font-semibold text-white shadow-lg transition hover:from-emerald-500 hover:to-emerald-400"
              >
                I am 18+ · allow anonymous usage counts
              </button>
              <button
                onClick={() => accept(false)}
                className="w-full rounded-lg border border-slate-600 bg-slate-800 px-6 py-3 font-semibold text-slate-200 transition hover:bg-slate-700"
              >
                I am 18+ · essential only
              </button>
              <button
                onClick={() => (window.location.href = "https://www.begambleaware.org")}
                className="w-full px-6 py-2 text-sm text-slate-400 underline transition hover:text-slate-300"
              >
                I am under 18 / Exit
              </button>
            </div>
          </div>
        </div>
      </div>
  );
}

// ---------------------------------------------------------------------------
// ConsentProvider - Wrap app with this to conditionally block content
// ---------------------------------------------------------------------------

interface ConsentProviderProps {
  children: React.ReactNode;
  requireConsent?: boolean;
}

export function ConsentProvider({ children, requireConsent = true }: ConsentProviderProps) {
  const { hasConsented, isLoading } = useConsent();

  // Show loading state briefly
  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-950">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-emerald-500 border-t-transparent" />
      </div>
    );
  }

  return (
    <>
      {children}
      {requireConsent && !hasConsented && <ConsentBanner />}
    </>
  );
}

export default ConsentBanner;
