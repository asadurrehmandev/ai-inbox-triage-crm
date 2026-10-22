"use client";

import { Button } from "@/components/ui/button";
import { DeskLogin } from "@/components/desk-login";
import { LaneShell } from "@/components/lane-shell";
import { Metrics } from "@/components/metrics";
import { useDesk } from "@/components/use-desk";
import { cadence, formatWhen, modeLabel, type Run } from "@/lib/types";

const STEPS = [
  {
    n: "01",
    title: "Ingest",
    copy: "A webhook or an IMAP poll drops the message on the unseen queue.",
  },
  {
    n: "02",
    title: "Classify",
    copy: "Claude decides lead, support, invoice, spam, or urgent. Rules cover the demo.",
  },
  {
    n: "03",
    title: "Extract",
    copy: "Name, company, budget, and intent come off the message as fields.",
  },
  {
    n: "04",
    title: "Draft",
    copy: "A reply is written and held. Nothing is sent until a person approves it.",
  },
  {
    n: "05",
    title: "CRM",
    copy: "Leads go through the mock adapter, then HubSpot or GoHighLevel when a token is set.",
  },
  {
    n: "06",
    title: "Alert",
    copy: "Slack hears about leads, urgent mail, support, and invoices. Spam stays quiet.",
  },
];

const SOURCE: Record<string, string> = {
  startup: "Sample mailbox",
  manual: "Run worker",
  scheduler: "Scheduler",
  webhook: "Webhook",
};

export function WorkerBoard() {
  const desk = useDesk();
  const worker = desk.worker;
  if (desk.error === "unauthorized" && !desk.stats) {
    return <DeskLogin onDone={() => void desk.refresh()} />;
  }
  return (
    <LaneShell stats={desk.stats}>
      {desk.stats ? <Metrics stats={desk.stats} /> : null}
      <section className="px-5 py-6 md:px-8">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-[11px] tracking-[0.16em] text-muted-foreground uppercase">
              APScheduler
            </p>
            <h1 className="mt-1 font-serif text-3xl tracking-tight">Python worker</h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
              {worker
                ? worker.enabled
                  ? `Checks the mailbox ${cadence(worker.interval_seconds)}. Next pass ${formatWhen(worker.next_run_at) || "is scheduled"}. Classifier: ${desk.stats ? modeLabel(desk.stats.mode) : "rules"}.`
                  : "The scheduler is paused in this process. Run worker still drains the queue."
                : "Connecting to the worker."}
            </p>
          </div>
          <Button
            type="button"
            onClick={() => void desk.runIntake()}
            disabled={desk.busy || desk.pending.length === 0}
          >
            {desk.busy ? "Working" : "Run worker"}
          </Button>
        </div>

        <ol className="mt-8 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {STEPS.map((step) => (
            <li key={step.n} className="border border-border bg-card px-4 py-4">
              <p className="font-serif text-2xl leading-none text-muted-foreground">{step.n}</p>
              <h2 className="mt-3 text-sm tracking-[0.14em] uppercase">{step.title}</h2>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">{step.copy}</p>
            </li>
          ))}
        </ol>

        <h2 className="mt-10 font-serif text-2xl tracking-tight">Recent passes</h2>
        {desk.runs.length === 0 ? (
          <p className="mt-4 border border-dashed border-border px-4 py-8 text-sm text-muted-foreground">
            No passes yet. The scheduler will take one, or you can run the worker now.
          </p>
        ) : (
          <div className="mt-4 overflow-auto border border-border">
            <table className="w-full min-w-[640px] text-left text-sm">
              <thead className="bg-card text-[11px] tracking-[0.14em] text-muted-foreground uppercase">
                <tr>
                  <th className="px-4 py-3 font-medium">When</th>
                  <th className="px-4 py-3 font-medium">Source</th>
                  <th className="px-4 py-3 font-medium">Processed</th>
                  <th className="px-4 py-3 font-medium">Leads</th>
                  <th className="px-4 py-3 font-medium">Alerts</th>
                </tr>
              </thead>
              <tbody>
                {desk.runs.map((run) => (
                  <tr key={run.id} className="border-t border-border">
                    <td className="px-4 py-3">{formatWhen(run.finished_at)}</td>
                    <td className="px-4 py-3">{sourceLabel(run)}</td>
                    <td className="px-4 py-3">{run.processed}</td>
                    <td className="px-4 py-3">{run.leads}</td>
                    <td className="px-4 py-3">{run.alerts}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <p className="mt-6 max-w-2xl text-sm leading-6 text-muted-foreground">
          Point Gmail, Outlook, or a forwarder at{" "}
          <code className="font-mono text-xs">POST /api/webhooks/email</code>. The message waits
          on the unseen queue until this worker classifies it.
        </p>
      </section>
    </LaneShell>
  );
}

function sourceLabel(run: Run) {
  return SOURCE[run.source] ?? run.source;
}
