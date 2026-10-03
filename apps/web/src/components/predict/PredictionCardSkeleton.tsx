import React from "react";

export function PredictionCardSkeleton() {
  return (
    <div
      className="w-full rounded-2xl border border-[#2A2A2E] bg-[#1B1B1D] p-5 shadow-2xl animate-pulse"
      aria-label="Loading match prediction..."
    >
      {/* Header Skeleton */}
      <div className="flex items-center justify-between border-b border-[#2A2A2E] pb-4">
        <div className="space-y-2">
          <div className="h-3 w-28 rounded bg-slate-800" />
          <div className="h-6 w-52 rounded bg-slate-700" />
        </div>
        <div className="h-8 w-24 rounded-full bg-slate-800" />
      </div>

      {/* Probabilities Progress Bar Skeleton */}
      <div className="mt-5 space-y-2.5">
        <div className="flex justify-between">
          <div className="h-4 w-64 rounded bg-slate-700" />
          <div className="h-4 w-16 rounded bg-slate-800" />
        </div>
        <div className="h-3.5 w-full rounded-full bg-slate-800" />
      </div>

      {/* Actionable Staking Recommendation Skeleton */}
      <div className="mt-5 rounded-xl border border-[#2A2A2E] bg-[#0E0E10] p-4">
        <div className="flex items-center justify-between">
          <div className="space-y-1.5">
            <div className="h-5 w-60 rounded bg-slate-700" />
            <div className="h-3.5 w-80 rounded bg-slate-800" />
          </div>
          <div className="h-8 w-20 rounded-lg bg-slate-800" />
        </div>
      </div>

      {/* Attacking Form (xG) Skeleton */}
      <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div className="rounded-xl border border-[#2A2A2E] bg-[#0E0E10] p-3.5">
          <div className="h-3 w-32 rounded bg-slate-800" />
          <div className="mt-2 h-5 w-24 rounded bg-slate-700" />
        </div>
        <div className="rounded-xl border border-[#2A2A2E] bg-[#0E0E10] p-3.5">
          <div className="h-3 w-36 rounded bg-slate-800" />
          <div className="mt-2 h-5 w-28 rounded bg-slate-700" />
        </div>
      </div>
    </div>
  );
}
