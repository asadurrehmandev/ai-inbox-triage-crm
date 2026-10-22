"use client";

import { Bell } from "lucide-react";
import { DeskError } from "@/components/desk-error";
import { DeskLogin } from "@/components/desk-login";
import { EmptyState } from "@/components/empty-state";
import { LaneShell } from "@/components/lane-shell";
import { StatusBadge, categoryTone } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Skeleton } from "@/components/ui/skeleton";
import { useDelayed } from "@/components/use-delayed";
import { useDesk } from "@/components/use-desk";
import { categoryLabel, formatWhen } from "@/lib/types";

export function AlertFeed() {
  const desk = useDesk();
  const showSkeleton = useDelayed(desk.loading && desk.alerts.length === 0);

  if (desk.error === "unauthorized" && !desk.stats) {
    return <DeskLogin onDone={() => void desk.refresh()} />;
  }

  return (
    <LaneShell>
      <div className="flex h-full flex-col overflow-auto">
        {desk.error ? <DeskError message={desk.error} onRetry={() => void desk.refresh()} /> : null}
        <div className="flex justify-end px-4 py-2">
          <Popover>
            <PopoverTrigger asChild>
              <Button type="button" variant="ghost">
                Mock Slack
              </Button>
            </PopoverTrigger>
            <PopoverContent align="end">
              Leads, urgent mail, support, and invoices are posted. Spam stays quiet. Set SLACK_WEBHOOK_URL and the
              same text goes to a real channel.
            </PopoverContent>
          </Popover>
        </div>
        {showSkeleton && desk.alerts.length === 0 ? (
          <div className="space-y-2 px-4">
            {Array.from({ length: 5 }, (_, index) => (
              <Skeleton key={index} className="h-14 w-full" />
            ))}
          </div>
        ) : desk.alerts.length === 0 ? (
          <EmptyState
            icon={Bell}
            title="No alerts yet"
            body="Run the worker to post the first one."
            action={
              <Button type="button" variant="outline" onClick={() => void desk.runIntake()} disabled={desk.busy || desk.pending.length === 0}>
                Run worker now
              </Button>
            }
          />
        ) : (
          <ul className="border-t border-border">
            {desk.alerts.map((alert) => (
              <li key={alert.id} className="border-b border-border px-4 py-3">
                <div className="flex items-center gap-2">
                  <StatusBadge tone={alert.category ? categoryTone(alert.category) : "neutral"}>
                    {alert.category ? categoryLabel(alert.category) : "Note"}
                  </StatusBadge>
                  <span className="ml-auto text-xs text-subtle-foreground tabular-nums">
                    {formatWhen(alert.created_at)}
                  </span>
                </div>
                <p className="mt-1 text-sm font-medium">{alert.title}</p>
                <p className="mt-0.5 text-sm text-muted-foreground">{alert.body}</p>
              </li>
            ))}
          </ul>
        )}
      </div>
    </LaneShell>
  );
}
