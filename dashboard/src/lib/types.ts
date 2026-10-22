export type Stats = {
  processed: number;
  waiting: number;
  pending_approval: number;
  approved: number;
  leads: number;
  alerts: number;
  by_category: Record<string, number>;
  hours_saved: number;
  minutes_per_email: number;
  projected_daily_hours: number;
  projected_daily_volume: number;
  hours_saved_note?: string;
  fallbacks?: number;
  mode: string;
  mailbox: string;
  crm: string;
};

export type Triage = {
  id: number;
  email_id: string;
  category: string;
  confidence: number;
  name: string | null;
  company: string | null;
  budget: string | null;
  intent: string | null;
  draft_reply: string;
  model: string;
  approved: boolean;
  edited: boolean;
  created_at: string;
  subject: string | null;
  from_name: string | null;
  from_email: string | null;
  body: string | null;
  received_at: string | null;
  risk_flags?: string[];
  llm_error?: string | null;
  suggested_category?: string | null;
  suggestion_confidence?: number | null;
  reasons?: string[];
};

export type Mail = {
  id: string;
  from_name: string | null;
  from_email: string | null;
  subject: string | null;
  body: string | null;
  received_at: string | null;
  status: string;
};

export type Lead = {
  id: number;
  email_id: string;
  name: string | null;
  company: string | null;
  email: string | null;
  budget: string | null;
  intent: string | null;
  category: string | null;
  source_subject: string | null;
  status: string;
  destination: string;
  remote_status?: string;
  remote_error?: string | null;
  created_at: string;
};

export type Run = {
  id: number;
  source: string;
  started_at: string;
  finished_at: string;
  processed: number;
  leads: number;
  alerts: number;
  ingested: number;
};

export type WorkerStatus = {
  enabled: boolean;
  interval_seconds: number;
  next_run_at: string | null;
  last_run: Run | null;
  engine: string;
};

export type Recording = {
  present: boolean;
  label: string;
  recorded_at?: string;
  model?: string;
  mailbox?: string;
  count?: number;
};

export type AcceptResult = {
  ok: boolean;
  code: string;
  message: string;
  reasons: string[];
};

export type Alert = {
  id: number;
  email_id: string | null;
  category: string | null;
  title: string;
  body: string;
  created_at: string;
};

export const CATEGORIES = ["lead", "support", "invoice", "spam", "urgent", "suspicious", "review"] as const;

export function categoryLabel(category: string) {
  if (category === "review") return "Needs review";
  return category.slice(0, 1).toUpperCase() + category.slice(1);
}

export function modeLabel(mode: string) {
  if (mode === "anthropic") return "Live AI (Claude)";
  if (mode === "openai") return "Live AI (OpenAI)";
  return "Demo mode: sample responses. Add your API key for live AI.";
}

export function cadence(seconds: number) {
  if (seconds >= 60 && seconds % 60 === 0) {
    const minutes = seconds / 60;
    return minutes === 1 ? "every minute" : `every ${minutes} minutes`;
  }
  return `every ${seconds} seconds`;
}

export function formatWhen(iso: string | null | undefined) {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function formatListTime(iso: string | null | undefined) {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const now = new Date();
  const sameDay = date.toDateString() === now.toDateString();
  if (sameDay) {
    return date.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
  }
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

export function runDuration(started: string, finished: string) {
  const a = new Date(started).getTime();
  const b = new Date(finished).getTime();
  if (!Number.isFinite(a) || !Number.isFinite(b) || b < a) return "–";
  const seconds = Math.round((b - a) / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return rest ? `${minutes}m ${rest}s` : `${minutes}m`;
}
