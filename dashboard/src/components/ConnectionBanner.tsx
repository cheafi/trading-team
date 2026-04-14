"use client";

import { useProfit } from "@/lib/hooks";

/**
 * Global connection status banner.
 * Shows a red warning when the agent-runner API is unreachable,
 * preventing users from trusting stale data.
 */
export function ConnectionBanner() {
  const { error, isLoading } = useProfit();

  // Connected — show nothing
  if (!error && !isLoading) return null;

  // Loading on initial mount — brief grace period
  if (isLoading && !error) return null;

  return (
    <div className="mb-4 px-4 py-2.5 rounded-lg bg-red-500/10 border border-red-500/30 flex items-center gap-3">
      <span className="w-2.5 h-2.5 rounded-full bg-red-500 animate-pulse shrink-0" />
      <div>
        <span className="text-red-400 text-sm font-semibold">
          ⚠️ Connection Lost
        </span>
        <span className="text-red-300/60 text-xs ml-2">
          Cannot reach trading engine — data may be stale or unavailable.
          Dashboard values are NOT live.
        </span>
      </div>
    </div>
  );
}
