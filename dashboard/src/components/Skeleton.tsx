"use client";

/**
 * Reusable skeleton/shimmer loading placeholders.
 * Shows pulsing placeholder shapes while SWR data loads.
 */

interface SkeletonProps {
  className?: string;
}

export function SkeletonBox({ className = "" }: SkeletonProps) {
  return (
    <div
      className={`bg-slate-700/30 rounded-lg animate-pulse ${className}`}
    />
  );
}

export function SkeletonText({ className = "" }: SkeletonProps) {
  return (
    <div
      className={`bg-slate-700/30 rounded h-4 animate-pulse ${className}`}
    />
  );
}

export function SkeletonCircle({ className = "" }: SkeletonProps) {
  return (
    <div
      className={`bg-slate-700/30 rounded-full animate-pulse ${className}`}
    />
  );
}

/** PnLCard loading skeleton */
export function PnLSkeleton() {
  return (
    <div className="bg-[#1a2332] rounded-xl border border-slate-800 p-5">
      <div className="flex items-center justify-between mb-3">
        <SkeletonText className="w-28 h-4" />
        <SkeletonText className="w-20 h-3" />
      </div>
      <div className="mb-3">
        <SkeletonBox className="w-48 h-9 mb-1" />
        <SkeletonText className="w-20 h-4" />
      </div>
      <div className="grid grid-cols-3 gap-2">
        {[1, 2, 3].map((i) => (
          <SkeletonBox key={i} className="h-14" />
        ))}
      </div>
    </div>
  );
}

/** RiskGauge loading skeleton */
export function RiskGaugeSkeleton() {
  return (
    <div className="bg-[#1a2332] rounded-xl border border-slate-800 p-5">
      <div className="flex items-center justify-between mb-4">
        <SkeletonText className="w-28 h-4" />
        <SkeletonBox className="w-16 h-6 rounded" />
      </div>
      <div className="mb-4">
        <div className="flex justify-between mb-1">
          <SkeletonText className="w-24 h-3" />
          <SkeletonText className="w-12 h-3" />
        </div>
        <SkeletonBox className="w-full h-2 rounded-full" />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <SkeletonText className="w-16 h-3 mb-1" />
          <SkeletonText className="w-12 h-5" />
        </div>
        <div>
          <SkeletonText className="w-20 h-3 mb-1" />
          <SkeletonText className="w-12 h-5" />
        </div>
      </div>
    </div>
  );
}

/** TradesPanel loading skeleton */
export function TradesSkeleton() {
  return (
    <div className="bg-[#1a2332] rounded-xl border border-slate-800 p-5">
      <div className="flex items-center justify-between mb-4">
        <SkeletonText className="w-28 h-4" />
        <SkeletonBox className="w-20 h-5 rounded-full" />
      </div>
      <div className="space-y-2">
        {[1, 2, 3].map((i) => (
          <div
            key={i}
            className="rounded-lg border border-slate-700/30 p-3"
          >
            <div className="flex items-center justify-between mb-1">
              <div className="flex items-center gap-2">
                <SkeletonBox className="w-14 h-5 rounded" />
                <SkeletonText className="w-12 h-4" />
              </div>
              <SkeletonText className="w-16 h-4" />
            </div>
            <div className="flex justify-between">
              <SkeletonText className="w-32 h-3" />
              <SkeletonText className="w-20 h-3" />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/** EquityMini / Trade Stats loading skeleton */
export function EquitySkeleton() {
  return (
    <div className="bg-[#1a2332] rounded-xl border border-slate-800 p-5">
      <div className="flex items-center justify-between mb-3">
        <SkeletonText className="w-24 h-4" />
        <SkeletonText className="w-16 h-6" />
      </div>
      <div className="grid grid-cols-2 gap-3">
        {[1, 2, 3, 4].map((i) => (
          <SkeletonBox key={i} className="h-20 rounded-lg" />
        ))}
      </div>
      <div className="mt-3">
        <SkeletonBox className="w-full h-3 rounded-full" />
        <div className="flex justify-between mt-1">
          <SkeletonText className="w-20 h-3" />
          <SkeletonText className="w-20 h-3" />
        </div>
      </div>
    </div>
  );
}
