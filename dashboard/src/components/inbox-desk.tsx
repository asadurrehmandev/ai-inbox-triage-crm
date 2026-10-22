"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Inbox, PanelRight } from "lucide-react";
import { Panel, PanelGroup, PanelResizeHandle } from "react-resizable-panels";
import { toast } from "sonner";
import { ApprovalCard, type ReaderActions } from "@/components/approval-card";
import { useCommandBus } from "@/components/command-bus";
import { DeskError } from "@/components/desk-error";
import { DeskLogin } from "@/components/desk-login";
import { EmptyState } from "@/components/empty-state";
import { LaneShell } from "@/components/lane-shell";
import { MessageDetails } from "@/components/message-details";
import { resolvedProvider, useSessionKey } from "@/components/session-key";
import { StatusBadge, categoryTone } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useDelayed } from "@/components/use-delayed";
import { useDesk } from "@/components/use-desk";
import { cadence, categoryLabel, formatListTime, type Triage } from "@/lib/types";
import { cn } from "@/lib/utils";

const MAIN_FILTERS = [
  { id: "approval", label: "Needs approval" },
  { id: "lead", label: "Leads" },
  { id: "urgent", label: "Urgent" },
  { id: "review", label: "Review" },
] as const;

const MORE_FILTERS = [
  { id: "suspicious", label: "Suspicious" },
  { id: "support", label: "Support" },
  { id: "invoice", label: "Invoice" },
  { id: "spam", label: "Spam" },
  { id: "waiting", label: "Waiting" },
  { id: "all", label: "All" },
] as const;

type FilterId = (typeof MAIN_FILTERS)[number]["id"] | (typeof MORE_FILTERS)[number]["id"];

function matches(item: Triage, filter: FilterId) {
  if (filter === "approval") {
    return !item.approved && !["spam", "suspicious", "review"].includes(item.category);
  }
  if (filter === "all" || filter === "waiting") return true;
  return item.category === filter;
}

function isTyping(target: EventTarget | null) {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || target.isContentEditable;
}

export function InboxDesk({ focusId }: { focusId?: number }) {
  const desk = useDesk();
  const session = useSessionKey();
  const router = useRouter();
  const bus = useCommandBus();
  const [filter, setFilter] = useState<FilterId>("approval");
  const [query, setQuery] = useState("");
  const [pickedId, setPickedId] = useState<number | null>(focusId ?? null);
  const [snoozed, setSnoozed] = useState<number[]>([]);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [wide, setWide] = useState(false);
  const actionRef = useRef<ReaderActions | null>(null);
  const showSkeleton = useDelayed(desk.loading && !desk.stats);

  useEffect(() => {
    const query = window.matchMedia("(min-width: 1024px)");
    const apply = () => setWide(query.matches);
    const timer = window.setTimeout(apply, 0);
    query.addEventListener("change", apply);
    return () => {
      window.clearTimeout(timer);
      query.removeEventListener("change", apply);
    };
  }, []);

  const counts = useMemo(() => {
    const next: Record<string, number> = { waiting: desk.pending.length, all: desk.items.length };
    for (const item of desk.items) {
      next[item.category] = (next[item.category] ?? 0) + 1;
      if (!item.approved && !["spam", "suspicious", "review"].includes(item.category)) {
        next.approval = (next.approval ?? 0) + 1;
      }
    }
    return next;
  }, [desk.items, desk.pending.length]);

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    let rows = desk.items.filter((item) => !snoozed.includes(item.id) && matches(item, filter));
    if (filter === "review") {
      rows = [...rows].sort(
        (a, b) => (b.suggestion_confidence ?? b.confidence) - (a.suggestion_confidence ?? a.confidence),
      );
    }
    if (!needle) return rows;
    return rows.filter((item) =>
      [item.from_name, item.name, item.subject, item.from_email, item.company, item.budget]
        .filter(Boolean)
        .join(" ")
        .toLowerCase()
        .includes(needle),
    );
  }, [desk.items, filter, query, snoozed]);

  const waiting = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return desk.pending.filter((mail) => {
      if (!needle) return true;
      return `${mail.from_name ?? ""} ${mail.subject ?? ""}`.toLowerCase().includes(needle);
    });
  }, [desk.pending, query]);

  const selectedId = (() => {
    if (focusId != null && desk.items.some((item) => item.id === focusId)) return focusId;
    if (filter !== "waiting" && pickedId != null && visible.some((item) => item.id === pickedId)) return pickedId;
    if (filter === "waiting") return pickedId;
    return (visible.find((item) => item.email_id === "m01") ?? visible[0])?.id ?? null;
  })();
  const selected = desk.items.find((item) => item.id === selectedId) ?? null;

  useEffect(() => {
    if (selectedId == null) return;
    document.getElementById(`queue-${selectedId}`)?.scrollIntoView({ block: "nearest" });
  }, [selectedId]);

  const openItem = useCallback(
    (id: number) => {
      setPickedId(id);
      const item = desk.items.find((row) => row.id === id);
      if (item && !matches(item, filter)) setFilter("all");
      if (window.matchMedia("(max-width: 1023px)").matches) router.push(`/approve/${id}`);
    },
    [desk.items, filter, router],
  );

  const advance = useCallback(
    (id: number) => {
      const index = visible.findIndex((item) => item.id === id);
      const next = visible[index + 1] ?? visible[index - 1] ?? null;
      if (focusId != null) {
        router.push(next ? `/approve/${next.id}` : "/");
        return;
      }
      setPickedId(next?.id ?? null);
    },
    [visible, focusId, router],
  );

  const snooze = useCallback(
    (id: number) => {
      setSnoozed((current) => (current.includes(id) ? current : [...current, id]));
      toast("Snoozed for this session.");
      advance(id);
    },
    [advance],
  );

  const handlerRef = useRef({
    next: () => undefined as void,
    previous: () => undefined as void,
    snooze: () => undefined as void,
  });

  useEffect(() => {
    const actions = actionRef.current;
    handlerRef.current = {
      next: () => {
        if (!selected) return;
        const index = visible.findIndex((item) => item.id === selected.id);
        const next = visible[index + 1];
        if (next) openItem(next.id);
      },
      previous: () => {
        if (!selected) return;
        const index = visible.findIndex((item) => item.id === selected.id);
        const previous = visible[index - 1];
        if (previous) openItem(previous.id);
      },
      snooze: () => {
        if (selected) snooze(selected.id);
      },
    };
    bus.set({
      primaryLabel: actions?.primaryLabel ?? "Approve and file to CRM",
      hasItem: Boolean(selected),
      canPrimary: Boolean(actions?.canPrimary),
      canNotLead: Boolean(actions?.canNotLead),
      canRun: !desk.busy && desk.pending.length > 0,
      canReplay: Boolean(desk.recording?.present),
      runPrimary: () => actionRef.current?.primary(),
      edit: () => actionRef.current?.edit(),
      notLead: () => actionRef.current?.notLead(),
      snooze: () => handlerRef.current.snooze(),
      next: () => handlerRef.current.next(),
      previous: () => handlerRef.current.previous(),
      openItem,
    });
  }, [bus, desk.busy, desk.pending.length, desk.recording, openItem, selected, snooze, visible]);

  useEffect(() => () => bus.set(null), [bus]);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (document.querySelector("[role='dialog']")) return;
      if (event.metaKey || event.ctrlKey) {
        if (event.key === "Enter" && !event.altKey) {
          event.preventDefault();
          actionRef.current?.primary();
        }
        return;
      }
      if (event.altKey) return;
      if (isTyping(event.target)) return;
      const key = event.key.toLowerCase();
      if (key === "j" || event.key === "ArrowDown") {
        event.preventDefault();
        handlerRef.current.next();
      } else if (key === "k" || event.key === "ArrowUp") {
        event.preventDefault();
        handlerRef.current.previous();
      } else if (key === "e") {
        event.preventDefault();
        actionRef.current?.primary();
      } else if (key === "r") {
        event.preventDefault();
        actionRef.current?.edit();
      } else if (key === "n") {
        event.preventDefault();
        actionRef.current?.notLead();
      } else if (key === "h") {
        event.preventDefault();
        handlerRef.current.snooze();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  if (desk.error === "unauthorized" && !desk.stats) {
    return <DeskLogin onDone={() => void desk.refresh()} />;
  }

  const list = (
    <section className="flex h-full min-h-0 flex-col bg-surface" aria-label="Inbox list">
      <div className="flex flex-wrap items-center gap-1 border-b border-border px-2 py-2">
        <Tabs value={MAIN_FILTERS.some((item) => item.id === filter) ? filter : ""} onValueChange={(value) => setFilter(value as FilterId)}>
          <TabsList aria-label="Filters">
            {MAIN_FILTERS.map((option) => (
              <TabsTrigger key={option.id} value={option.id}>
                {option.label}
                <span className="text-xs text-muted-foreground tabular-nums">{counts[option.id] ?? 0}</span>
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button type="button" variant={MORE_FILTERS.some((item) => item.id === filter) ? "secondary" : "ghost"} size="sm">
              {MORE_FILTERS.find((item) => item.id === filter)?.label ?? "More"}
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start">
            {MORE_FILTERS.map((option) => (
              <DropdownMenuItem key={option.id} onSelect={() => setFilter(option.id)}>
                {option.label}
                <span className="ml-auto text-xs text-muted-foreground tabular-nums">{counts[option.id] ?? 0}</span>
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
      <div className="border-b border-border px-2 py-2">
        <Input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search"
          aria-label="Search inbox"
        />
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
        {filter === "waiting" ? (
          waiting.length === 0 ? (
            <EmptyState
              icon={Inbox}
              title="Intake is caught up"
              body={
                desk.worker?.enabled
                  ? `New mail shows up here ${cadence(desk.worker.interval_seconds)}.`
                  : "Run the worker when new mail arrives."
              }
              action={
                <Button type="button" onClick={() => void desk.runIntake()} disabled={desk.busy || desk.pending.length === 0}>
                  Run worker now
                </Button>
              }
            />
          ) : (
            <ul>
              {waiting.map((mail) => (
                <li key={mail.id} className="border-b border-border px-3 py-2">
                  <p className="truncate text-sm font-medium">{mail.from_name || "Unknown sender"}</p>
                  <p className="truncate text-sm" title={mail.subject || undefined}>
                    {mail.subject || "No subject"}
                  </p>
                  <p className="truncate text-sm text-muted-foreground">Not classified yet</p>
                </li>
              ))}
            </ul>
          )
        ) : visible.length === 0 ? (
          <EmptyState
            icon={Inbox}
            title={desk.pending.length > 0 ? "Mail is waiting" : "Inbox zero"}
            body={
              desk.pending.length > 0
                ? `${desk.pending.length} messages are not classified yet.`
                : desk.worker?.enabled
                  ? `New mail shows up here ${cadence(desk.worker.interval_seconds)}.`
                  : "Nothing in this filter."
            }
            action={
              <Button type="button" onClick={() => void desk.runIntake()} disabled={desk.busy || desk.pending.length === 0}>
                Run worker now
              </Button>
            }
          />
        ) : (
          <ul>
            {visible.map((item) => {
              const active = item.id === selected?.id;
              const meta = [item.company, item.budget].filter(Boolean).slice(0, 2).join(" · ");
              return (
                <li key={item.id}>
                  <button
                    id={`queue-${item.id}`}
                    type="button"
                    onClick={() => openItem(item.id)}
                    className={cn(
                      "flex w-full gap-2 border-b border-border px-3 py-2 text-left",
                      active ? "bg-primary-soft shadow-[inset_2px_0_0_0_var(--primary)]" : "hover:bg-muted",
                    )}
                    aria-current={active ? "true" : undefined}
                  >
                    <span className="mt-1.5 flex w-2 shrink-0 justify-center" aria-hidden>
                      {item.approved ? null : <span className="size-1.5 rounded-full bg-primary" />}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="flex items-baseline justify-between gap-2">
                        <span className="truncate text-sm font-semibold">
                          {item.name || item.from_name || "Unknown sender"}
                        </span>
                        <span className="shrink-0 text-xs text-subtle-foreground tabular-nums">
                          {item.approved ? "Approved" : formatListTime(item.received_at)}
                        </span>
                      </span>
                      <span className="mt-0.5 flex min-w-0 items-center gap-1.5">
                        <span className="min-w-0 truncate text-sm" title={item.subject || undefined}>
                          {item.subject || "No subject"}
                        </span>
                        <StatusBadge tone={categoryTone(item.category)}>{categoryLabel(item.category)}</StatusBadge>
                      </span>
                      {meta ? <span className="mt-0.5 block truncate text-sm text-muted-foreground">{meta}</span> : null}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </section>
  );

  const reader = selected ? (
    <div className="flex h-full min-h-0">
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-center gap-2 border-b border-border px-3 py-2 xl:hidden">
          {focusId != null ? (
            <Button type="button" variant="ghost" onClick={() => router.push("/")}>
              Back
            </Button>
          ) : null}
          <Button type="button" variant="outline" className="ml-auto" onClick={() => setDetailsOpen(true)}>
            <PanelRight className="size-4" strokeWidth={1.75} />
            Details
          </Button>
        </div>
        {focusId != null ? (
          <div className="hidden border-b border-border px-3 py-2 xl:block">
            <Button type="button" variant="ghost" onClick={() => router.push("/")}>
              Back
            </Button>
          </div>
        ) : null}
        <div className="min-h-0 flex-1">
          <ApprovalCard
            item={selected}
            busy={desk.busy}
            actionRef={actionRef}
            inCrm={desk.leads.some((lead) => lead.email_id === selected.email_id)}
            onSave={(draft) => desk.saveDraft(selected.id, draft)}
            onApprove={() => desk.approve(selected.id)}
            onAccept={(category, confirm) => desk.acceptLabel(selected.id, category, confirm)}
            onSnooze={() => snooze(selected.id)}
            onDone={() => advance(selected.id)}
            onLive={
              session.live
                ? async () => {
                    const provider = resolvedProvider(session.key, session.provider);
                    const result = await desk.classifyLive(selected.id, session.key, provider);
                    if (result?.notice && result.mode === "demo") session.markDemo(result.notice);
                  }
                : undefined
            }
          />
        </div>
      </div>
      <aside className="hidden w-[280px] shrink-0 overflow-auto border-l border-border bg-surface xl:block" aria-label="Contact">
        <MessageDetails
          item={selected}
          inCrm={desk.leads.some((lead) => lead.email_id === selected.email_id)}
          destination={desk.stats?.crm ?? "mock"}
        />
      </aside>
    </div>
  ) : (
    <EmptyState
      icon={Inbox}
      title="Select a message"
      body="The draft stays here until you approve it."
    />
  );

  return (
    <LaneShell>
      {desk.error ? <DeskError message={desk.error} onRetry={() => void desk.refresh()} /> : null}
      {showSkeleton && !desk.stats ? (
        <div className="space-y-2 p-4" aria-hidden>
          {Array.from({ length: 8 }, (_, index) => (
            <Skeleton key={index} className="h-14 w-full" />
          ))}
        </div>
      ) : wide && !focusId ? (
        <PanelGroup direction="horizontal" autoSaveId="lane-inbox" className="h-full">
          <Panel defaultSize={32} minSize={22} maxSize={46} id="list" className="min-w-0">
            {list}
          </Panel>
          <PanelResizeHandle className="w-px bg-border" />
          <Panel minSize={40} id="reader" className="min-w-0">
            {reader}
          </Panel>
        </PanelGroup>
      ) : (
        <div className="h-full min-h-0">{focusId ? reader : list}</div>
      )}
      <Sheet open={detailsOpen} onOpenChange={setDetailsOpen}>
        <SheetContent side="right" aria-label="Contact">
          <SheetHeader>
            <SheetTitle>Details</SheetTitle>
          </SheetHeader>
          {selected ? (
            <MessageDetails
              item={selected}
              inCrm={desk.leads.some((lead) => lead.email_id === selected.email_id)}
              destination={desk.stats?.crm ?? "mock"}
            />
          ) : null}
        </SheetContent>
      </Sheet>
    </LaneShell>
  );
}
