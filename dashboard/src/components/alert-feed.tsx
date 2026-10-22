"use client";

import { DeskLogin } from "@/components/desk-login";
import { LaneShell } from "@/components/lane-shell";
import { Metrics } from "@/components/metrics";
import { useDesk } from "@/components/use-desk";
import { CATEGORY_COLOR, categoryLabel, formatWhen } from "@/lib/types";

export function AlertFeed() {
  const desk = useDesk();
  if (desk.error === "unauthorized" && !desk.stats) {
    return <DeskLogin onDone={() => void desk.refresh()} />;
  }
  return (
    <LaneShell stats={desk.stats}>
      {desk.stats ? <Metrics stats={desk.stats} /> : null}
      <section className="px-5 py-6 md:px-8">
        <h1 className="font-serif text-3xl tracking-tight">#lane-inbox</h1>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
          This is the mock Slack webhook. Leads, urgent mail, support, and invoices are posted.
          Spam stays quiet. Set SLACK_WEBHOOK_URL and the same text is delivered to a real channel.
        </p>
        {desk.loading && desk.alerts.length === 0 ? (
          <p className="mt-8 text-sm text-muted-foreground">Loading alerts…</p>
        ) : null}
        {desk.error ? <p className="mt-6 text-sm text-muted-foreground">{desk.error}</p> : null}
        {!desk.loading && desk.alerts.length === 0 ? (
          <p className="mt-8 border border-dashed border-border px-4 py-8 text-sm text-muted-foreground">
            No alerts yet. Run the worker to post the first one.
          </p>
        ) : null}
        <ol className="mt-6 max-w-3xl space-y-3">
          {desk.alerts.map((alert) => {
            const color = CATEGORY_COLOR[alert.category || ""] ?? "#6b6258";
            return (
              <li key={alert.id} className="border border-border bg-card px-4 py-3">
                <div className="flex items-baseline justify-between gap-3 text-xs">
                  <span className="tracking-[0.14em] uppercase" style={{ color }}>
                    Lane · {alert.category ? categoryLabel(alert.category) : "Note"}
                  </span>
                  <span className="text-muted-foreground">{formatWhen(alert.created_at)}</span>
                </div>
                <p className="mt-2 text-sm font-medium">{alert.title}</p>
                <p className="mt-1 text-sm leading-6 text-muted-foreground">{alert.body}</p>
              </li>
            );
          })}
        </ol>
      </section>
    </LaneShell>
  );
}
