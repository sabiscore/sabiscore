import { Metadata } from "next";
import { Suspense } from "react";
import { PerformancePageClient } from "@/components/performance/performance-page-client";

export const metadata: Metadata = {
  // Matches the <h1> and the sidebar's "Performance" entry. It previously read
  // "Intelligence Hub", which is a different route (/intelligence).
  title: "Performance",
  description:
    "Walk-forward model accuracy and ranked probability score, computed from predictions settled against final results.",
};

export default function PerformancePage() {
  // No wrapper padding, max-width or background here: the root <main>
  // (app/layout.tsx) already supplies px-4 py-5 sm:px-6 lg:px-8 over the shell
  // gradient. Re-adding them double-inset the page and pushed it 65px past the
  // viewport — the same container-parity trap logged four times on the match route.
  return (
    <>
      <header className="mb-8 space-y-2">
        <h1 className="text-3xl font-bold tracking-tight text-white md:text-4xl">
          Performance
        </h1>
        <p className="max-w-2xl text-slate-400">
          Model accuracy and ranked probability score, scored only on predictions that
          have settled against a completed fixture&apos;s final result.
        </p>
      </header>

      <Suspense
        fallback={
          <div className="grid gap-6">
            {[...Array(3)].map((_, i) => (
              <div
                key={i}
                className="h-48 animate-pulse rounded-2xl bg-slate-800/50"
                aria-hidden="true"
              />
            ))}
          </div>
        }
      >
        <PerformancePageClient />
      </Suspense>
    </>
  );
}
