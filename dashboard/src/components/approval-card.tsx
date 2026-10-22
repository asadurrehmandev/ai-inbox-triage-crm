"use client";

import { useEffect, useImperativeHandle, useRef, useState, type RefObject } from "react";
import { MoreHorizontal } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Textarea } from "@/components/ui/textarea";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import {
  StatusBadge,
  categoryTone,
  confidencePresentation,
  scoreSource,
} from "@/components/status-badge";
import {
  categoryLabel,
  formatWhen,
  type AcceptResult,
  type Triage,
} from "@/lib/types";
import { toast } from "sonner";

export type ReaderActions = {
  primary: () => void;
  edit: () => void;
  notLead: () => void;
  canNotLead: boolean;
  canPrimary: boolean;
  primaryLabel: string;
};

const ARCHIVE = new Set(["spam", "suspicious", "review"]);

export function ApprovalCard({
  item,
  busy,
  onSave,
  onApprove,
  onAccept,
  onLive,
  onSnooze,
  onDone,
  inCrm = false,
  actionRef,
}: {
  item: Triage;
  busy: boolean;
  onSave: (draft: string) => Promise<void>;
  onApprove: () => Promise<boolean>;
  onAccept?: (category: string, confirm?: boolean) => Promise<AcceptResult>;
  onLive?: () => Promise<void>;
  onSnooze?: () => void;
  onDone?: () => void;
  inCrm?: boolean;
  actionRef?: RefObject<ReaderActions | null>;
}) {
  const draftRef = useRef<HTMLTextAreaElement>(null);
  const localActions = useRef<ReaderActions | null>(null);
  const [override, setOverride] = useState<{ id: number; saved: string; text: string } | null>(null);
  const [stream, setStream] = useState<{ id: number; saved: string; text: string; thinking: boolean } | null>(null);
  const [noteState, setNoteState] = useState<{ id: number; text: string } | null>(null);
  const [confirmState, setConfirmState] = useState<{
    id: number;
    category: string;
    message: string;
    reasons: string[];
  } | null>(null);
  const editing = override && override.id === item.id && override.saved === item.draft_reply ? override : null;
  const live =
    !item.edited && stream && stream.id === item.id && stream.saved === item.draft_reply ? stream : null;
  const thinking = item.edited ? false : live ? live.thinking : true;
  const typed = item.edited ? item.draft_reply : live ? live.text : "";
  const streaming = editing === null && typed.length < item.draft_reply.length;
  const draft = editing ? editing.text : streaming ? typed : item.draft_reply;
  const note = noteState && noteState.id === item.id ? noteState.text : null;
  const confirm = confirmState && confirmState.id === item.id ? confirmState : null;
  const payment = (item.risk_flags || []).includes("payment_related");
  const suspicious = item.category === "suspicious";
  const canFile =
    !confirm &&
    !item.approved &&
    !payment &&
    !suspicious &&
    !inCrm &&
    item.category === "lead" &&
    Boolean(onAccept);
  const reviewLead =
    !confirm &&
    !item.approved &&
    !payment &&
    !suspicious &&
    !inCrm &&
    item.category === "review" &&
    item.suggested_category === "lead" &&
    Boolean(onAccept);
  const reviewOther =
    !confirm &&
    !item.approved &&
    !payment &&
    !suspicious &&
    item.category === "review" &&
    Boolean(item.suggested_category) &&
    item.suggested_category !== "lead" &&
    Boolean(onAccept);
  const primaryLabel = confirm
    ? "Confirm and file"
    : canFile || reviewLead
      ? "Approve and file to CRM"
      : reviewOther
        ? `Accept as ${item.suggested_category}`
        : ARCHIVE.has(item.category)
          ? "Approve and archive"
          : "Approve reply";
  const canNotLead =
    !item.approved &&
    !confirm &&
    Boolean(onAccept) &&
    (item.category === "lead" || (item.category === "review" && item.suggested_category === "lead"));
  const canPrimary = !busy && !item.approved;

  useEffect(() => {
    if (item.edited) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let tick = 0;
    const think = window.setTimeout(() => {
      if (reduce) {
        setStream({ id: item.id, saved: item.draft_reply, text: item.draft_reply, thinking: false });
        return;
      }
      setStream({ id: item.id, saved: item.draft_reply, text: "", thinking: false });
      let cursor = 0;
      tick = window.setInterval(() => {
        cursor = Math.min(item.draft_reply.length, cursor + 3);
        setStream({
          id: item.id,
          saved: item.draft_reply,
          text: item.draft_reply.slice(0, cursor),
          thinking: false,
        });
        if (cursor >= item.draft_reply.length) window.clearInterval(tick);
      }, 16);
    }, reduce ? 0 : 420);
    return () => {
      window.clearTimeout(think);
      window.clearInterval(tick);
    };
  }, [item.id, item.draft_reply, item.edited]);

  function setDraft(text: string) {
    setOverride({ id: item.id, saved: item.draft_reply, text });
  }

  function setNote(text: string) {
    setNoteState({ id: item.id, text });
  }

  const dirty = editing !== null && editing.text !== item.draft_reply;
  const confidence = confidencePresentation(
    item.category === "review" ? (item.suggestion_confidence ?? item.confidence) : item.confidence,
  );

  async function requestAccept(category: string, second = false) {
    if (!onAccept) return;
    const result = await onAccept(category, second);
    if (result.code === "confirm" && !second) {
      setConfirmState({
        id: item.id,
        category,
        message: result.message,
        reasons: result.reasons,
      });
      setNoteState(null);
      return;
    }
    setConfirmState(null);
    if (result.ok && category === "lead") {
      const approved = await onApprove();
      if (!approved) return;
      toast.success("Filed to CRM (mock).");
      onDone?.();
      return;
    }
    if (result.ok) {
      toast.success(category === "support" ? "Marked as support." : "Label accepted.");
      onDone?.();
    } else if (result.message) {
      setNote(result.message);
    }
  }

  async function doApprove() {
    if (dirty) await onSave(draft);
    const ok = await onApprove();
    if (!ok) return;
    const archived = ARCHIVE.has(item.category);
    toast.success(archived ? "Archived." : "Reply approved.");
    onDone?.();
  }

  function primary() {
    if (!canPrimary) return;
    if (confirm) {
      void requestAccept(confirm.category, true);
      return;
    }
    if (canFile || reviewLead) {
      void requestAccept("lead");
      return;
    }
    if (reviewOther && item.suggested_category) {
      void requestAccept(item.suggested_category);
      return;
    }
    void doApprove();
  }

  function edit() {
    draftRef.current?.focus();
  }

  function notLead() {
    if (!canNotLead) return;
    void requestAccept("support");
  }

  const latest = useRef({ primary, edit, notLead, canNotLead, canPrimary, primaryLabel });
  useEffect(() => {
    latest.current = { primary, edit, notLead, canNotLead, canPrimary, primaryLabel };
  });
  useImperativeHandle(
    actionRef ?? localActions,
    () => ({
      primary: () => latest.current.primary(),
      edit: () => latest.current.edit(),
      notLead: () => latest.current.notLead(),
      get canNotLead() {
        return latest.current.canNotLead;
      },
      get canPrimary() {
        return latest.current.canPrimary;
      },
      get primaryLabel() {
        return latest.current.primaryLabel;
      },
    }),
    [],
  );

  return (
    <article className="flex h-full min-h-0 flex-col">
      <header className="border-b border-border px-4 py-4 md:px-5">
        <div className="flex flex-wrap items-center gap-1.5">
          <StatusBadge tone={categoryTone(item.category)}>{categoryLabel(item.category)}</StatusBadge>
          <Tooltip>
            <TooltipTrigger asChild>
              <button type="button" className="rounded-sm">
                <StatusBadge tone={confidence.tone}>{confidence.label}</StatusBadge>
              </button>
            </TooltipTrigger>
            <TooltipContent>
              {Math.round((item.suggestion_confidence ?? item.confidence) * 100)}% confidence.{" "}
              {scoreSource(item.model)}
            </TooltipContent>
          </Tooltip>
          <StatusBadge tone="neutral">{shownModel(item.model)}</StatusBadge>
          {item.approved ? <StatusBadge tone="success">Approved</StatusBadge> : null}
        </div>
        <h2 className="mt-3 text-lg font-semibold tracking-[-0.01em]" data-testid="reading-subject">
          {item.subject || "No subject"}
        </h2>
        <p className="mt-1 text-sm text-muted-foreground" title={`${item.from_name || ""} ${item.from_email || ""}`}>
          <span className="break-words">
            {item.from_name || "Unknown sender"}
            {item.from_email ? ` <${item.from_email}>` : ""}
          </span>
          {item.received_at ? <span className="whitespace-nowrap"> · {formatWhen(item.received_at)}</span> : null}
        </p>
        {item.llm_error ? (
          <p className="mt-2 text-sm text-muted-foreground">Rules fallback: {item.llm_error}</p>
        ) : null}
        {payment ? (
          <p className="mt-3 rounded-md bg-warning-soft px-3 py-2 text-sm text-warning" role="status">
            payment-related: verify by phone
          </p>
        ) : null}
        {item.reasons && item.reasons.length > 0 ? (
          <p className="mt-3 max-w-[72ch] text-sm text-muted-foreground">
            {item.category === "review" && item.suggested_category
              ? `Suggested ${item.suggested_category}. `
              : "Why this label: "}
            {item.reasons.join(", ")}
          </p>
        ) : null}
        {confirm ? (
          <div className="mt-3 rounded-md border border-border bg-surface px-3 py-3 text-sm" role="status">
            <p>{confirm.message}</p>
            {confirm.reasons.length > 0 ? (
              <ul className="mt-2 list-disc space-y-1 pl-5">
                {confirm.reasons.map((reason) => (
                  <li key={reason}>{reason}</li>
                ))}
              </ul>
            ) : null}
          </div>
        ) : null}
      </header>

      <div className="min-h-0 flex-1 overflow-auto px-4 py-4 pb-6 md:px-5">
        <div className="max-w-[72ch] text-base leading-[22px] whitespace-pre-wrap">{item.body}</div>
        <div className="mt-6 flex items-baseline justify-between gap-3">
          <h3 className="text-xs font-medium text-muted-foreground">
            {ARCHIVE.has(item.category) ? "Internal note" : "Draft reply"}
          </h3>
          <p className="text-xs text-subtle-foreground">
            {item.approved ? "Approved" : item.edited ? "Edited, still waiting" : "Waiting for a person"}
          </p>
        </div>
        <div aria-live="polite">
          {thinking ? <p className="mt-2 text-sm text-muted-foreground">Reading the message…</p> : null}
          {!thinking && streaming ? <p className="mt-2 text-sm text-muted-foreground">Drafting…</p> : null}
        </div>
        <Textarea
          ref={draftRef}
          id="draft-reply"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          className="mt-2 min-h-40 bg-background font-sans text-base leading-[22px]"
          aria-label={ARCHIVE.has(item.category) ? "Internal note" : "Draft reply"}
        />
        {ARCHIVE.has(item.category) ? (
          <p className="mt-2 max-w-[72ch] text-sm text-muted-foreground">
            {item.category === "suspicious"
              ? "Held for a person. Do not pay, do not reply, and do not write this to the CRM."
              : item.category === "review"
                ? payment
                  ? "payment-related: verify by phone. Nothing was written to the CRM."
                  : "A person has to accept this before it can be filed. Nothing was written to the CRM."
                : "Spam is not answered and is not written to the CRM."}
          </p>
        ) : null}
        {note ? <p className="mt-2 text-sm text-muted-foreground">{note}</p> : null}
      </div>

      <footer className="flex shrink-0 flex-nowrap items-center gap-2 overflow-x-auto border-t border-border px-4 py-2 md:px-5">
        {canPrimary ? (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button type="button" size="lg" className="shrink-0" onClick={primary} data-testid="primary-action">
                {primaryLabel}
              </Button>
            </TooltipTrigger>
            <TooltipContent>{primaryLabel} (⌘↵ or E)</TooltipContent>
          </Tooltip>
        ) : null}
        <Tooltip>
          <TooltipTrigger asChild>
            <Button type="button" variant="outline" className="shrink-0" onClick={edit}>
              Edit draft
            </Button>
          </TooltipTrigger>
          <TooltipContent>Edit draft (R)</TooltipContent>
        </Tooltip>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button type="button" variant="outline" size="icon" className="shrink-0" aria-label="More actions">
              <MoreHorizontal className="size-4" strokeWidth={1.75} />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem
              disabled={!dirty || busy}
              onSelect={() => {
                void onSave(draft).then(() => {
                  setNote("Draft saved.");
                  toast.success("Draft saved.");
                });
              }}
            >
              Save edits
            </DropdownMenuItem>
            {canNotLead ? (
              <DropdownMenuItem disabled={busy} onSelect={notLead}>
                Mark not a lead
              </DropdownMenuItem>
            ) : null}
            {onSnooze ? <DropdownMenuItem onSelect={onSnooze}>Snooze</DropdownMenuItem> : null}
            {onLive ? (
              <DropdownMenuItem disabled={busy || item.approved} onSelect={() => void onLive()}>
                Classify with live AI
              </DropdownMenuItem>
            ) : null}
          </DropdownMenuContent>
        </DropdownMenu>
      </footer>
    </article>
  );
}

function shownModel(model: string) {
  if (model === "anthropic") return "Claude";
  if (model === "openai") return "OpenAI";
  if (model === "rules" || model === "rules-fallback") return "Demo";
  return model;
}
