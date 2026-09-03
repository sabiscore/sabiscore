import type { Metadata } from "next";
import { redirect } from "next/navigation";

export const metadata: Metadata = {
  title: "Model Monitoring",
  description: "Authoritative settled-prediction model performance",
};

/**
 * Bookmark-preserving alias for /performance — NOT a navigation destination.
 *
 * This route has always been a bare redirect, but "Monitoring" also sat in the
 * sidebar (app/layout.tsx) and the mobile nav next to "Performance", so two
 * visibly different entries landed on the same page. Worse, robots.ts
 * disallows /monitoring/ while /performance is deliberately indexable, so the
 * linked entry was the crawler-blocked spelling of a public page.
 *
 * The nav entries are gone; the redirect stays so existing bookmarks and any
 * external link still resolve. Do not re-add it to a nav list — give this route
 * its own distinct content first (provider/system health is the obvious
 * candidate, and is a different surface from settled-prediction performance).
 */
export default function MonitoringPage() {
  redirect("/performance");
}
