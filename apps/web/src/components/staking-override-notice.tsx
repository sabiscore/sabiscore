"use client";

import { cn } from "@/lib/utils";
import type { StakingAuthorization } from "@/lib/api";

/**
 * Discloses that a published stake rests on an operator override rather than
 * on an earned certification (ADR-0011).
 *
 * ⚠️ This is a product surface, not an operator diagnostic. When
 * `certification_state` is `OPERATOR_OVERRIDE_UNCERTIFIED`, the platform is
 * publishing stake sizes derived from a model that did NOT pass its
 * certification gates — at time of writing it beat the de-vigged market in
 * 0 of 6 leagues and its epistemic-uncertainty signal is inverted (the model
 * is least accurate where its ensemble agrees most). A reader deciding what to
 * risk is entitled to know that before they act on the number, which is why
 * this renders next to the stake and not only in `/health`.
 *
 * Renders nothing when no override is in force, so it is safe to mount
 * unconditionally — and mounting it unconditionally is the point: a disclosure
 * that has to be remembered at each new call site is one that eventually is
 * not.
 */
export function StakingOverrideBadge({
  auth,
  className,
}: {
  auth: StakingAuthorization | null | undefined;
  className?: string;
}) {
  if (!auth?.is_override) return null;

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-amber-300",
        className,
      )}
      title={overrideTooltip(auth)}
    >
      <span aria-hidden>⚠</span>
      Unverified · operator override
    </span>
  );
}

/**
 * The expanded form, for surfaces with room to explain (match detail, any
 * page that sizes a stake). Same fail-quiet contract as the badge.
 */
export function StakingOverrideNotice({
  auth,
  className,
}: {
  auth: StakingAuthorization | null | undefined;
  className?: string;
}) {
  if (!auth?.is_override) return null;

  return (
    <div
      role="note"
      className={cn(
        "rounded-xl border border-amber-500/40 bg-amber-500/5 p-3 text-xs text-amber-200/90",
        className,
      )}
    >
      <p className="font-semibold uppercase tracking-wider text-amber-300">
        ⚠ Staking active without certification
      </p>
      <p className="mt-1.5 leading-relaxed">
        These stake sizes come from a model that did not pass its certification
        gates. An operator authorised publishing them anyway, accepting the
        failures below as a known risk. Treat them as research output, not a
        validated recommendation.
      </p>
      {auth.acknowledged_failures.length > 0 && (
        <p className="mt-1.5">
          <span className="text-amber-300/80">Gates overridden: </span>
          {auth.acknowledged_failures.join(", ")}
        </p>
      )}
      {auth.rationale && (
        <p className="mt-1.5">
          <span className="text-amber-300/80">Stated reason: </span>
          {auth.rationale}
        </p>
      )}
      {auth.authorizing_identity && (
        <p className="mt-1.5 text-amber-300/70">
          Authorised by {auth.authorizing_identity}
          {auth.authorized_at ? ` on ${auth.authorized_at}` : ""}
        </p>
      )}
    </div>
  );
}

function overrideTooltip(auth: StakingAuthorization): string {
  const parts = [
    "Staking is active under an operator override, not a passed certification.",
  ];
  if (auth.acknowledged_failures.length > 0) {
    parts.push(`Gates overridden: ${auth.acknowledged_failures.join(", ")}.`);
  }
  if (auth.rationale) parts.push(`Reason: ${auth.rationale}`);
  if (auth.authorizing_identity) {
    parts.push(`Authorised by ${auth.authorizing_identity}.`);
  }
  return parts.join(" ");
}
