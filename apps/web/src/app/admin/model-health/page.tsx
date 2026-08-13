import { Metadata } from "next";
import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { Suspense } from "react";
import { ModelHealthClient } from "@/components/admin/model-health-client";

export const metadata: Metadata = {
  title: "Model Health | Admin",
  description: "Admin model health dashboard — artifact status, readiness checks, and load diagnostics.",
};

// Server-side bearer token guard.
// The ADMIN_TOKEN env var must match the Authorization header (or be set).
// On Vercel/Render, set ADMIN_TOKEN as a secret env var. For dev, any value works.
async function verifyAdminToken(): Promise<boolean> {
  const adminToken = process.env.ADMIN_TOKEN;
  // No token configured → allow in development only
  if (!adminToken) {
    return process.env.NODE_ENV !== "production";
  }
  const headersList = await headers();
  const auth = headersList.get("x-admin-token") ?? headersList.get("authorization");
  if (!auth) return false;
  const provided = auth.startsWith("Bearer ") ? auth.slice(7) : auth;
  return provided === adminToken;
}

export default async function AdminModelHealthPage() {
  const authorized = await verifyAdminToken();
  if (!authorized) {
    redirect("/");
  }

  return (
    // No wrapper padding, min-h-screen, or background here: the root <main>
    // (app/layout.tsx) already supplies px-4 py-5 sm:px-6 lg:px-8 over the
    // shell's own background — same container-parity convention as
    // /performance and /monitoring.
    <div className="mx-auto max-w-5xl">
      {/* Header */}
      <header className="mb-8 flex items-center justify-between gap-4">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <span className="rounded-full border border-rose-500/30 bg-rose-500/10 px-2.5 py-0.5 text-xs font-bold text-rose-300">
              ADMIN
            </span>
            <h1 className="text-2xl font-bold text-white">Model Health</h1>
          </div>
          <p className="text-sm text-slate-400">
            Artifact inventory, readiness gate status, and startup diagnostics.
          </p>
        </div>
      </header>

      <Suspense
        fallback={
          <div className="space-y-4">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="h-24 animate-pulse rounded-2xl bg-slate-800/40" aria-hidden="true" />
            ))}
          </div>
        }
      >
        <ModelHealthClient />
      </Suspense>
    </div>
  );
}
