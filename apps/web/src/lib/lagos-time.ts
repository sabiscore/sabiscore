// Every consumer timestamp is shown in Lagos time and labelled WAT, so a
// server render and a browser in another zone print the same thing. Kept apart
// from full-analysis-contract so a page can format a time without loading the
// contract's Zod schemas.

export function formatLagosTimestamp(iso: string | number | Date): string {
  return new Intl.DateTimeFormat("en-NG", {
    timeZone: "Africa/Lagos",
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(iso));
}

export function formatLagosTime(iso: string | number | Date): string {
  return new Intl.DateTimeFormat("en-NG", {
    timeZone: "Africa/Lagos",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(iso));
}

// A <input type="datetime-local"> has no zone: the browser reads its value as
// browser-local time. These pin it to Lagos wall time (labelled WAT) both ways,
// so the value shown and the instant submitted agree in every browser zone.
// ponytail: fixed +01:00 — Africa/Lagos has no DST; use Intl if that ever changes.
const LAGOS_OFFSET_MS = 60 * 60 * 1000;

export function toLagosInputValue(iso: string | number | Date): string {
  return new Date(new Date(iso).getTime() + LAGOS_OFFSET_MS).toISOString().slice(0, 16);
}

export function fromLagosInputValue(value: string): string {
  return new Date(`${value}:00+01:00`).toISOString();
}
