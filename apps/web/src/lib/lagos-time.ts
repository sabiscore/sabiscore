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
