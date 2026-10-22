"use client";

import { ListChecks } from "lucide-react";
import { DeskError } from "@/components/desk-error";
import { DeskLogin } from "@/components/desk-login";
import { EmptyState } from "@/components/empty-state";
import { LaneShell } from "@/components/lane-shell";
import { TimeSavedEstimate } from "@/components/metrics";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useDelayed } from "@/components/use-delayed";
import { useDesk } from "@/components/use-desk";
import { cadence, formatWhen, runDuration, type Run } from "@/lib/types";

const SOURCE: Record<string, string> = {
  startup: "Sample mailbox",
  manual: "Run worker",
  scheduler: "Scheduler",
  webhook: "Webhook",
};

export function WorkerBoard() {
  const desk = useDesk();
  const worker = desk.worker;
  const showSkeleton = useDelayed(desk.loading && desk.runs.length === 0);

  if (desk.error === "unauthorized" && !desk.stats) {
    return <DeskLogin onDone={() => void desk.refresh()} />;
  }

  return (
    <LaneShell>
      <div className="flex h-full flex-col overflow-auto">
        {desk.error ? <DeskError message={desk.error} onRetry={() => void desk.refresh()} /> : null}
        <div className="px-4 py-3">
          <p className="text-sm text-muted-foreground">
            {worker
              ? worker.enabled
                ? `APScheduler checks the mailbox ${cadence(worker.interval_seconds)}. Next pass ${formatWhen(worker.next_run_at) || "is scheduled"}.`
                : "APScheduler is paused in this process. Run worker still drains the queue."
              : "Connecting to the worker."}
          </p>
          <p className="mt-1 text-xs text-subtle-foreground">
            Point a forwarder at <span className="font-mono">POST /api/webhooks/email</span>.
          </p>
        </div>
        {showSkeleton && desk.runs.length === 0 ? (
          <div className="space-y-2 px-4">
            {Array.from({ length: 5 }, (_, index) => (
              <Skeleton key={index} className="h-10 w-full" />
            ))}
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Started</TableHead>
                <TableHead>Duration</TableHead>
                <TableHead className="text-right">Processed</TableHead>
                <TableHead className="text-right">Labelled</TableHead>
                <TableHead className="text-right">Errors</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow>
                <TableCell>
                  <div className="font-medium">Recorded Claude pass</div>
                  <div className="mt-1">
                    <StatusBadge tone={desk.recording?.present ? "success" : "neutral"}>
                      {desk.recording?.present ? "Recorded" : "No recording yet"}
                    </StatusBadge>
                  </div>
                  {desk.recording && !desk.recording.present ? (
                    <p className="mt-1 text-xs text-muted-foreground">{desk.recording.label}</p>
                  ) : null}
                </TableCell>
                <TableCell className="text-subtle-foreground">–</TableCell>
                <TableCell className="text-right tabular-nums">{desk.recording?.count ?? "–"}</TableCell>
                <TableCell className="text-right text-subtle-foreground">–</TableCell>
                <TableCell className="text-right text-subtle-foreground">–</TableCell>
              </TableRow>
              {desk.runs.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={5}>
                    <EmptyState
                      icon={ListChecks}
                      title="No passes yet"
                      body="The scheduler will take one, or you can run the worker now."
                    />
                  </TableCell>
                </TableRow>
              ) : (
                desk.runs.map((run) => (
                  <TableRow key={run.id}>
                    <TableCell>
                      <div className="tabular-nums">{formatWhen(run.started_at)}</div>
                      <div className="text-xs text-muted-foreground">{sourceLabel(run)}</div>
                    </TableCell>
                    <TableCell className="tabular-nums">{runDuration(run.started_at, run.finished_at)}</TableCell>
                    <TableCell className="text-right tabular-nums">{run.processed}</TableCell>
                    <TableCell className="text-right tabular-nums" title="Messages given a category in this pass">
                      {run.processed}
                    </TableCell>
                    <TableCell className="text-right text-subtle-foreground" title="This pass does not record a separate error count">
                      –
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        )}
        {desk.recording?.present ? (
          <div className="px-4 py-3">
            <Button
              type="button"
              variant="outline"
              disabled={desk.busy}
              onClick={() => void desk.replayRecording()}
            >
              Replay recorded pass
            </Button>
          </div>
        ) : null}
        <div className="mt-auto">
          {desk.stats ? <TimeSavedEstimate stats={desk.stats} /> : null}
          <div className="px-4 py-3">
            <button
              type="button"
              className="text-sm text-muted-foreground underline-offset-2 hover:underline"
              onClick={() => void desk.resetDemo()}
              disabled={desk.busy}
            >
              Reset sample mailbox
            </button>
          </div>
        </div>
      </div>
    </LaneShell>
  );
}

function sourceLabel(run: Run) {
  return SOURCE[run.source] ?? run.source;
}
