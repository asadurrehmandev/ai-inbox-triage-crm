"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import {
  CATEGORY_COLOR,
  categoryLabel,
  formatWhen,
  type AcceptResult,
  type Triage,
} from "@/lib/types";

export function ApprovalCard({
  item,
  busy,
  onSave,
  onApprove,
  onAccept,
  onLive,
  inCrm = false,
}: {
  item: Triage;
  busy: boolean;
  onSave: (draft: string) => Promise<void>;
  onApprove: () => Promise<void>;
  onAccept?: (category: string, confirm?: boolean) => Promise<AcceptResult>;
  onLive?: () => Promise<void>;
  inCrm?: boolean;
}) {
  const [override, setOverride] = useState<{ id: number; saved: string; text: string } | null>(null);
  const [typed, setTyped] = useState("");
  const [thinking, setThinking] = useState(true);
  const [noteState, setNoteState] = useState<{ id: number; text: string } | null>(null);
  const [confirmState, setConfirmState] = useState<{
    id: number;
    category: string;
    message: string;
    reasons: string[];
  } | null>(null);
  const editing =
    override && override.id === item.id && override.saved === item.draft_reply ? override : null;
  const streaming = editing === null && typed.length < item.draft_reply.length;
  const draft = editing ? editing.text : streaming ? typed : item.draft_reply;

  useEffect(() => {
    if (item.edited) {
      setTyped(item.draft_reply);
      setThinking(false);
      return;
    }
    setThinking(true);
    setTyped("");
    let cursor = 0;
    let tick = 0;
    const think = window.setTimeout(() => {
      setThinking(false);
      tick = window.setInterval(() => {
        cursor = Math.min(item.draft_reply.length, cursor + 3);
        setTyped(item.draft_reply.slice(0, cursor));
        if (cursor >= item.draft_reply.length) {
          window.clearInterval(tick);
          setTyped(item.draft_reply);
        }
      }, 16);
    }, 420);
    return () => {
      window.clearTimeout(think);
      window.clearInterval(tick);
    };
  }, [item.id, item.draft_reply, item.edited]);
  const note = noteState && noteState.id === item.id ? noteState.text : null;
  const confirm = confirmState && confirmState.id === item.id ? confirmState : null;

  function setDraft(text: string) {
    setOverride({ id: item.id, saved: item.draft_reply, text });
  }

  function setNote(text: string) {
    setNoteState({ id: item.id, text });
  }

  const dirty = editing !== null && editing.text !== item.draft_reply;
  const color = CATEGORY_COLOR[item.category] ?? "#1c1915";
  const payment = (item.risk_flags || []).includes("payment_related");
  const suspicious = item.category === "suspicious";

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
    if (result.ok) {
      setNote(category === "lead" ? "Filed in the CRM." : "Label accepted.");
    } else if (result.message) {
      setNote(result.message);
    }
  }

  return (
    <article className="flex min-h-full flex-col">
      <header className="border-b border-border px-5 py-5 md:px-8">
        <div className="flex flex-wrap items-center gap-3 text-xs tracking-[0.14em] uppercase">
          <span className="inline-flex items-center gap-2" style={{ color }}>
            <span className="size-2 rounded-full" style={{ background: color }} />
            {categoryLabel(item.category)}
          </span>
          <span className="text-muted-foreground">
            {Math.round(item.confidence * 100)}% confidence
          </span>
          <span className="text-muted-foreground">{shownModel(item.model)}</span>
          <span className="text-muted-foreground">{formatWhen(item.received_at)}</span>
        </div>
        <h1 className="mt-3 font-serif text-3xl leading-tight tracking-tight">
          {item.subject}
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">
          {item.from_name || "Unknown sender"} · {item.from_email}
        </p>
        {item.llm_error ? (
          <p className="mt-2 text-xs text-muted-foreground">Rules fallback: {item.llm_error}</p>
        ) : null}
        {payment ? (
          <p className="mt-3 border border-border bg-card px-3 py-2 text-sm" role="status">
            payment-related: verify by phone
          </p>
        ) : null}
        {item.reasons && item.reasons.length > 0 ? (
          <p className="mt-3 text-sm text-muted-foreground">
            {item.category === "review" && item.suggested_category
              ? `Suggested ${item.suggested_category}. `
              : "Why: "}
            {item.reasons.join(" · ")}
          </p>
        ) : null}
        {confirm ? (
          <div className="mt-3 border border-border bg-card px-3 py-3 text-sm" role="status">
            <p>{confirm.message}</p>
            {confirm.reasons.length > 0 ? (
              <ul className="mt-2 list-disc space-y-1 pl-5">
                {confirm.reasons.map((reason) => (
                  <li key={reason}>{reason}</li>
                ))}
              </ul>
            ) : null}
            <Button
              type="button"
              className="mt-3"
              disabled={busy || item.approved}
              onClick={() => void requestAccept(confirm.category, true)}
            >
              Confirm and file
            </Button>
          </div>
        ) : null}
        {!confirm && !payment && !suspicious && item.category === "review" && item.suggested_category && onAccept ? (
          <div className="mt-3">
            <Button
              type="button"
              disabled={busy || item.approved}
              onClick={() => void requestAccept(item.suggested_category || "")}
            >
              Accept as {item.suggested_category}
            </Button>
          </div>
        ) : null}
        {!confirm && !payment && !suspicious && item.category === "lead" && !inCrm && onAccept ? (
          <div className="mt-3">
            <Button type="button" disabled={busy || item.approved} onClick={() => void requestAccept("lead")}>
              Accept and file in CRM
            </Button>
          </div>
        ) : null}
      </header>

      <div className="grid gap-6 px-5 py-5 md:px-8 lg:grid-cols-[minmax(0,1fr)_280px]">
        <div className="max-h-72 overflow-auto border border-border bg-card px-4 py-3 text-sm leading-6 whitespace-pre-wrap">
          {item.body}
        </div>
        <dl className="grid grid-cols-2 gap-4 text-sm lg:grid-cols-1">
          <Field label="Name" value={item.name} />
          <Field label="Company" value={item.company} />
          <Field label="Budget" value={item.budget} />
          <Field label="Intent" value={item.intent} />
        </dl>
      </div>

      <div className="flex flex-1 flex-col gap-3 px-5 pb-8 md:px-8">
        <div className="flex items-baseline justify-between gap-3">
          <h2 className="text-sm tracking-[0.14em] uppercase text-muted-foreground">
            {item.category === "spam" || item.category === "suspicious" || item.category === "review"
              ? "Internal note"
              : "Draft reply"}
          </h2>
          <p className="text-xs text-muted-foreground">
            {item.approved
              ? "Approved"
              : item.edited
                ? "Edited, still waiting"
                : "Waiting for a person"}
          </p>
        </div>
        {thinking ? (
          <p className="text-sm text-muted-foreground" role="status">
            Reading the message…
          </p>
        ) : null}
        <Textarea
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          className="min-h-40 bg-card font-serif text-base leading-7"
          aria-label="Draft reply"
        />
        {item.category === "spam" || item.category === "suspicious" || item.category === "review" ? (
          <p className="text-sm text-muted-foreground">
            {item.category === "suspicious"
              ? "Held for a person. Do not pay, do not reply, and do not write this to the CRM."
              : item.category === "review"
                ? payment
                  ? "payment-related: verify by phone. Nothing was written to the CRM."
                  : "A person has to accept this before it can be filed. Nothing was written to the CRM."
                : "Spam is not answered and is not written to the CRM."}
          </p>
        ) : null}
        <div className="flex flex-wrap gap-2">
          {onLive ? (
            <Button type="button" variant="outline" disabled={busy || item.approved} onClick={() => void onLive()}>
              Classify with live AI
            </Button>
          ) : null}
          <Button
            type="button"
            variant="outline"
            disabled={!dirty || busy}
            onClick={async () => {
              await onSave(draft);
              setNote("Draft saved.");
            }}
          >
            Save edits
          </Button>
          <Button
            type="button"
            disabled={busy || item.approved}
            onClick={async () => {
              if (dirty) await onSave(draft);
              await onApprove();
              setNote(item.category === "spam" ? "Archived." : "Reply approved.");
            }}
          >
            {item.category === "spam" || item.category === "suspicious" || item.category === "review"
              ? "Approve and archive"
              : "Approve reply"}
          </Button>
        </div>
        {note ? <p className="text-sm text-muted-foreground">{note}</p> : null}
      </div>
    </article>
  );
}

function shownModel(model: string) {
  if (model === "anthropic") return "Claude";
  if (model === "openai") return "OpenAI";
  if (model === "rules" || model === "rules-fallback") return "Demo";
  return model;
}

function Field({ label, value }: { label: string; value: string | null }) {
  return (
    <div>
      <dt className="text-[11px] tracking-[0.14em] text-muted-foreground uppercase">
        {label}
      </dt>
      <dd className="mt-1 leading-snug">{value || "Not stated"}</dd>
    </div>
  );
}
