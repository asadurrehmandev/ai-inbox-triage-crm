import type { Alert, Lead, Mail, Run, Stats, Triage, WorkerStatus } from "@/lib/types";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8741/api";

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const token = process.env.NEXT_PUBLIC_API_TOKEN;
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers ?? {}),
    },
    cache: "no-store",
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

export function loadDesk() {
  return Promise.all([
    api<Stats>("/stats"),
    api<{ items: Triage[] }>("/triage?limit=200"),
    api<{ emails: Mail[] }>("/intake/pending"),
    api<{ leads: Lead[] }>("/crm/leads"),
    api<{ alerts: Alert[] }>("/alerts"),
    api<WorkerStatus>("/worker"),
    api<{ runs: Run[] }>("/runs"),
  ]);
}
