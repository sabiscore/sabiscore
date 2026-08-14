"use client";

import { useId, useState } from 'react';
import { Info, AlertTriangle, HelpCircle } from 'lucide-react';

interface TooltipProps {
  children: React.ReactNode;
  content: string;
  type?: 'info' | 'warning' | 'help';
}

/**
 * Simple tooltip component for responsible gambling disclaimers
 */
export function Tooltip({ children, content }: TooltipProps) {
  const [isVisible, setIsVisible] = useState(false);
  const tooltipId = useId();

  return (
    <div className="relative inline-block">
      <div
        onMouseEnter={() => setIsVisible(true)}
        onMouseLeave={() => setIsVisible(false)}
        onFocus={() => setIsVisible(true)}
        onBlur={() => setIsVisible(false)}
        tabIndex={0}
        role="button"
        aria-label={content}
        aria-describedby={isVisible ? tooltipId : undefined}
        className="cursor-help"
      >
        {children}
      </div>
      {isVisible && (
        <div
          id={tooltipId}
          role="tooltip"
          className="absolute bottom-full left-1/2 z-50 mb-2 w-64 -translate-x-1/2 transform rounded-lg border border-slate-600 bg-slate-800 p-3 text-xs text-slate-300 shadow-xl"
        >
          <div className="relative">
            {content}
            <div className="absolute -bottom-2 left-1/2 h-2 w-2 -translate-x-1/2 rotate-45 border-b border-r border-slate-600 bg-slate-800" />
          </div>
        </div>
      )}
    </div>
  );
}

interface ResponsibleGamblingBannerProps {
  compact?: boolean;
}

/**
 * Responsible Gambling Banner
 * Displays important disclaimers about betting responsibly
 */
export function ResponsibleGamblingBanner({ compact = false }: ResponsibleGamblingBannerProps) {
  const [dismissed, setDismissed] = useState(false);

  if (dismissed && compact) return null;

  if (compact) {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-300">
        <AlertTriangle className="h-4 w-4 flex-shrink-0" />
        <span>Bet responsibly. 18+ only.</span>
        <button 
          onClick={() => setDismissed(true)}
          className="ml-auto text-amber-400 hover:text-amber-300"
        >
          ×
        </button>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-amber-500/30 bg-gradient-to-r from-amber-900/20 to-orange-900/20 p-4">
      <div className="flex items-start gap-3">
        <AlertTriangle className="h-5 w-5 flex-shrink-0 text-amber-400" />
        <div className="flex-1">
          <h2 className="font-semibold text-amber-300">Responsible Gambling</h2>
          <ul className="mt-2 space-y-1 text-xs text-amber-200/80">
            <li>• Only bet what you can afford to lose</li>
            <li>• Predictions are probabilistic estimates, not guarantees</li>
            <li>• Set limits and stick to them</li>
            <li>• If gambling stops being fun, stop gambling</li>
          </ul>
          <div className="mt-3 flex flex-wrap gap-2 text-xs">
            <a 
              href="https://www.begambleaware.org" 
              target="_blank" 
              rel="noopener noreferrer"
              className="rounded bg-amber-500/20 px-2 py-1 text-amber-300 hover:bg-amber-500/30"
            >
              BeGambleAware.org
            </a>
            <a 
              href="https://www.gamcare.org.uk" 
              target="_blank" 
              rel="noopener noreferrer"
              className="rounded bg-amber-500/20 px-2 py-1 text-amber-300 hover:bg-amber-500/30"
            >
              GamCare
            </a>
          </div>
        </div>
      </div>
    </div>
  );
}

/**
 * Kelly Criterion Explainer Tooltip
 */
export function KellyTooltip() {
  return (
    <Tooltip 
      content="Kelly Criterion suggests optimal bet sizing based on edge and probability. We recommend using 1/4 Kelly (shown here) for safer bankroll management."
      type="help"
    >
      <HelpCircle className="h-3.5 w-3.5 text-slate-500 hover:text-slate-400" />
    </Tooltip>
  );
}

/**
 * Edge Explainer Tooltip
 */
export function EdgeTooltip() {
  return (
    <Tooltip 
      content="Edge represents the difference between our model's probability and the bookmaker's implied probability. Positive edge suggests potential value."
      type="info"
    >
      <Info className="h-3.5 w-3.5 text-slate-500 hover:text-slate-400" />
    </Tooltip>
  );
}

/**
 * Model Confidence Disclaimer
 */
export function ConfidenceDisclaimer() {
  return (
    <div className="flex items-start gap-2 rounded-lg border border-blue-500/30 bg-blue-500/10 p-3 text-xs text-blue-300">
      <Info className="h-4 w-4 flex-shrink-0 mt-0.5" />
      <p>
        Model confidence represents statistical certainty in the prediction, not a guarantee of outcome. 
        Past performance does not guarantee future results.
      </p>
    </div>
  );
}

/**
 * Footer Gambling Disclaimer
 * Compact footer-style disclaimer for page bottoms
 */
export function GamblingDisclaimer() {
  return (
    <div className="mt-8 rounded-lg border border-slate-700/50 bg-slate-800/30 p-4 text-center">
      <p className="text-xs text-slate-500">
        <span className="font-semibold text-amber-400/80">18+</span> | Gambling involves risk. Only bet what you can afford to lose.
        {' '}Model predictions are probabilistic estimates, not guarantees.
      </p>
      <div className="mt-2 flex justify-center gap-4 text-xs">
        <a 
          href="https://www.begambleaware.org" 
          target="_blank" 
          rel="noopener noreferrer"
          className="text-slate-500 hover:text-slate-400 underline"
        >
          BeGambleAware.org
        </a>
        <span className="text-slate-600">|</span>
        <a 
          href="tel:1-800-522-4700" 
          className="text-slate-500 hover:text-slate-400 underline"
        >
          1-800-522-4700
        </a>
      </div>
    </div>
  );
}
