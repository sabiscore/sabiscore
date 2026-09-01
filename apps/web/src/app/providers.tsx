"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { FeatureFlagProvider } from "@/lib/feature-flags";
import { shouldRetryQuery, queryRetryDelay } from "@/lib/query-retry";
import { AuthProvider } from "@/lib/auth-context";

export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 60 * 1000, // 1 minute
            gcTime: 5 * 60 * 1000, // 5 minutes
            refetchOnWindowFocus: false,
            // Error-aware policy: never retry permanent 4xx, ride out a
            // free-tier backend cold-start with bounded spaced retries.
            retry: shouldRetryQuery,
            retryDelay: queryRetryDelay,
          },
        },
      })
  );

  return (
    <FeatureFlagProvider>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>{children}</AuthProvider>
      </QueryClientProvider>
    </FeatureFlagProvider>
  );
}
