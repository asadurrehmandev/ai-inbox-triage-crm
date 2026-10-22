import type { Alert, Lead, Mail, Run, Stats, Triage, WorkerStatus } from "@/lib/types";

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/backend${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    cache: "no-store",
    credentials: "same-origin",
  });
  if (response.status === 401) {
    throw new Error("unauthorized");
  }
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
