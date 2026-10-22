"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { ApprovalCard } from "@/components/approval-card";
import { resolvedProvider, useSessionKey } from "@/components/session-key";
import { LaneShell } from "@/components/lane-shell";
import { Metrics } from "@/components/metrics";
import { DeskLogin } from "@/components/desk-login";
import { useDesk } from "@/components/use-desk";
import { cadence, CATEGORY_COLOR, categoryLabel, formatWhen, type Triage } from "@/lib/types";
import { cn } from "@/lib/utils";

const FILTERS = [
  { id: "approval", label: "Needs approval" },
  { id: "lead", label: "Leads" },
  { id: "urgent", label: "Urgent" },
  { id: "review", label: "Needs review" },
  { id: "suspicious", label: "Suspicious" },
  { id: "all", label: "All classified" },
] as const;

export function InboxDesk({ focusId }: { focusId?: number }) {
  const desk = useDesk();
  const session = useSessionKey();
  const router = useRouter();
  const [filter, setFilter] = useState<(typeof FILTERS)[number]["id"]>("approval");
  const [pickedId, setPickedId] = useState<number | null>(null);

  const visible = useMemo(() => {
    const rows = desk.items.filter((item) => {
      if (filter === "approval") {
        return !item.approved && !["spam", "suspicious", "review"].includes(item.category);
      }
      if (filter === "all") return true;
      return item.category === filter;
    });
    if (filter !== "review") return rows;
    return [...rows].sort(
      (a, b) => (b.suggestion_confidence ?? b.confidence) - (a.suggestion_confidence ?? a.confidence),
    );
  }, [desk.items, filter]);

  const selectedId = useMemo(() => {
    if (focusId != null && desk.items.some((item) => item.id === focusId)) return focusId;
    if (pickedId != null && desk.items.some((item) => item.id === pickedId)) return pickedId;
    const preferred = desk.items.find((item) => item.email_id === "m01") ?? desk.items[0];
    return preferred?.id ?? null;
  }, [desk.items, focusId, pickedId]);

  const selected = desk.items.find((item) => item.id === selectedId) ?? null;

  function choose(item: Triage) {
    if (window.matchMedia("(max-width: 1023px)").matches && !focusId) {
      router.push(`/approve/${item.id}`);
      return;
    }
    setPickedId(item.id);
  }

  if (desk.error === "unauthorized" && !desk.stats) {
    return <DeskLogin onDone={() => void desk.refresh()} />;
  }

  return (
    <LaneShell stats={desk.stats}>
      {desk.loading && !desk.stats ? (
        <p className="px-8 py-16 text-sm text-muted-foreground">Reading the mailbox…</p>
      ) : null}
      {desk.error ? (
        <p className="mx-5 mt-5 border border-border bg-card px-4 py-3 text-sm md:mx-8">
          The triage API is not answering. Start it with{" "}
          <code className="font-mono text-xs">uvicorn app.main:app --port 8741</code>.
          <span className="mt-1 block text-muted-foreground">{desk.error}</span>
        </p>
      ) : null}
      {desk.stats ? <Metrics stats={desk.stats} /> : null}

      <div className={focusId ? "" : "lg:grid lg:grid-cols-[380px_minmax(0,1fr)]"}>
        {focusId ? null : (
          <section className="border-b border-border lg:border-r lg:border-b-0">
            <div className="flex items-center justify-between gap-3 px-5 py-4">
              <div>
                <h2 className="font-serif text-2xl tracking-tight">The morning queue</h2>
                <p className="text-sm text-muted-foreground">
                  AI triage with human approval. {desk.pending.length} waiting for the worker
                  {desk.worker?.enabled ? ` · ${cadence(desk.worker.interval_seconds)}` : ""}
                </p>
              </div>
              <Button type="button" onClick={() => void desk.runIntake()} disabled={desk.busy || desk.pending.length === 0}>
                {desk.busy ? "Working" : "Run worker"}
              </Button>
            </div>
            {desk.recording ? (
              <div className="mx-5 mb-4 border border-border px-3 py-3 text-sm">
                <p>{desk.recording.label}</p>
                {!desk.recording.present ? (
                  <p className="mt-1 text-xs text-muted-foreground">no recording yet</p>
                ) : null}
                <Button
                  type="button"
                  variant="outline"
                  className="mt-3"
                  disabled={desk.busy || !desk.recording.present}
                  onClick={() => void desk.replayRecording()}
                >
                  Replay recorded pass
                </Button>
              </div>
            ) : null}
            {desk.pending.length > 0 ? (
              <div className="mx-5 mb-4 border border-dashed border-border px-3 py-2 text-sm">
                <p className="text-[11px] tracking-[0.14em] text-muted-foreground uppercase">
                  Not classified yet
                </p>
                <ul className="mt-2 space-y-1">
                  {desk.pending.slice(0, 4).map((mail) => (
                    <li key={mail.id} className="truncate text-muted-foreground">
                      {mail.from_name}: {mail.subject}
                    </li>
                  ))}
                  {desk.pending.length > 4 ? (
                    <li className="text-muted-foreground">
                      + {desk.pending.length - 4} more
                    </li>
                  ) : null}
                </ul>
              </div>
            ) : (
              <p className="mx-5 mb-4 text-sm text-muted-foreground">
                Intake is caught up. New mail will show here.
              </p>
            )}
            <div className="flex gap-1 overflow-auto px-5 pb-3">
              {FILTERS.map((option) => (
                <button
                  key={option.id}
                  type="button"
                  onClick={() => setFilter(option.id)}
                  className={cn(
                    "shrink-0 rounded-full px-3 py-1 text-xs",
                    filter === option.id
                      ? "bg-foreground text-background"
                      : "bg-secondary text-muted-foreground",
                  )}
                >
                  {option.label}
                </button>
              ))}
            </div>
            <ul className="max-h-[70vh] overflow-auto border-t border-border">
              {visible.length === 0 ? (
                <li className="px-5 py-8 text-sm text-muted-foreground">
                  Nothing in this filter. Run the worker, or switch to all classified mail.
                </li>
              ) : (
                visible.map((item) => (
                  <li key={item.id}>
                    <button
                      type="button"
                      onClick={() => choose(item)}
                      className={cn(
                        "w-full border-b border-border px-5 py-3 text-left",
                        selected?.id === item.id ? "bg-card" : "hover:bg-card/70",
                      )}
                    >
                      <QueueRow item={item} />
                    </button>
                  </li>
                ))
              )}
            </ul>
          </section>
        )}

        <section className="min-w-0 bg-background">
          {selected ? (
            <ApprovalCard
              item={selected}
              busy={desk.busy}
              onSave={(draft) => desk.saveDraft(selected.id, draft)}
              onApprove={() => desk.approve(selected.id)}
              onAccept={(category, confirm) => desk.acceptLabel(selected.id, category, confirm)}
              onLive={
                session.live
                  ? async () => {
                      const provider = resolvedProvider(session.key, session.provider);
                      const result = await desk.classifyLive(selected.id, session.key, provider);
                      if (result?.notice && result.mode === "demo") session.markDemo(result.notice);
                    }
                  : undefined
              }
              inCrm={desk.leads.some((lead) => lead.email_id === selected.email_id)}
            />
          ) : (
            <p className="px-8 py-16 text-sm text-muted-foreground">
              Select a message to review the draft.
            </p>
          )}
        </section>
      </div>
      <footer className="border-t border-border px-5 py-3 text-xs text-muted-foreground md:px-8">
        <button type="button" className="underline-offset-2 hover:underline" onClick={() => void desk.resetDemo()} disabled={desk.busy}>
          Reset the sample mailbox
        </button>
      </footer>
    </LaneShell>
  );
}

function QueueRow({ item }: { item: Triage }) {
  const color = CATEGORY_COLOR[item.category] ?? "#1c1915";
  return (
    <span className="block">
      <span className="flex items-baseline justify-between gap-3">
        <span className="truncate text-sm">{item.name || item.from_name || "Unknown sender"}</span>
        <span className="shrink-0 text-[11px] tracking-[0.12em] uppercase" style={{ color }}>
          {categoryLabel(item.category)}
        </span>
      </span>
      <span className="mt-1 block truncate text-sm text-muted-foreground">{item.subject}</span>
      <span className="mt-1 flex gap-3 text-xs text-muted-foreground">
        <span>{item.company || "No company"}</span>
        <span>{item.budget || "No amount"}</span>
        {item.risk_flags?.includes("payment_related") ? (
          <span>payment-related: verify by phone</span>
        ) : null}
        <span>
          {item.category === "review" && item.suggested_category
            ? `Suggest ${item.suggested_category} ${Math.round((item.suggestion_confidence ?? item.confidence) * 100)}%`
            : `${Math.round(item.confidence * 100)}%`}
        </span>
        <span>{item.approved ? "Approved" : formatWhen(item.received_at)}</span>
      </span>
    </span>
  );
}
