"use client";

import { Info } from "lucide-react";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import type { Stats } from "@/lib/types";

export function TimeSavedEstimate({ stats }: { stats: Stats }) {
  return (
    <div className="flex items-end justify-between gap-4 border-t border-border px-4 py-4">
      <div>
        <div className="flex items-center gap-1.5">
          <p className="text-xs font-medium text-muted-foreground">Time saved (estimate)</p>
          <Popover>
            <PopoverTrigger asChild>
              <button type="button" className="rounded-sm text-muted-foreground" aria-label="How the estimate is calculated">
                <Info className="size-3.5" strokeWidth={1.75} />
              </button>
            </PopoverTrigger>
            <PopoverContent>
              <p>
                {stats.minutes_per_email} minutes × messages that are not spam, suspicious, or needs-review.
                {stats.hours_saved_note ? ` ${stats.hours_saved_note}` : ""} {stats.projected_daily_hours.toFixed(1)} hours
                assumes {stats.projected_daily_volume} messages a day. It is not a measurement.
              </p>
            </PopoverContent>
          </Popover>
        </div>
        <p className="mt-1 text-xl font-semibold tabular-nums tracking-[-0.01em]">{stats.hours_saved.toFixed(1)}h</p>
      </div>
      <p className="text-right text-xs text-subtle-foreground tabular-nums">
        {stats.projected_daily_hours.toFixed(1)}h at {stats.projected_daily_volume} a day
      </p>
    </div>
  );
}
