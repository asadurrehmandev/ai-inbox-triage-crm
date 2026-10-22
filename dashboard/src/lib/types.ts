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

export type Alert = {
  id: number;
  email_id: string | null;
  category: string | null;
  title: string;
  body: string;
  created_at: string;
};

export const CATEGORIES = ["lead", "support", "invoice", "spam", "urgent", "suspicious", "review"] as const;

export const CATEGORY_COLOR: Record<string, string> = {
  lead: "#1f6b45",
  support: "#1e4f78",
  invoice: "#8a5a12",
  spam: "#7a403c",
  urgent: "#9c3d22",
  suspicious: "#6b3fa0",
  review: "#3d4a66",
};

export function categoryLabel(category: string) {
  if (category === "review") return "Needs review";
  return category.slice(0, 1).toUpperCase() + category.slice(1);
}

export function modeLabel(mode: string) {
  if (mode === "anthropic") return "Claude";
  if (mode === "openai") return "OpenAI";
  if (mode === "rules-fallback") return "Rules fallback";
  return "Rules · no API key";
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
