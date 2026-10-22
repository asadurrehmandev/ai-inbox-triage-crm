import type { Alert, Lead, Mail, Recording, Run, Stats, Triage, WorkerStatus } from "@/lib/types";

export class ApiError extends Error {
  status: number;
  code: string;
  reasons: string[];

  constructor(status: number, message: string, code = "", reasons: string[] = []) {
    super(message);
    this.status = status;
    this.code = code;
    this.reasons = reasons;
  }
}

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
    throw new ApiError(401, "unauthorized");
  }
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    let code = "";
    let reasons: string[] = [];
    try {
      const body = (await response.json()) as { detail?: unknown };
      const detail = body?.detail;
      if (typeof detail === "string") {
        message = detail;
      } else if (detail && typeof detail === "object") {
        const record = detail as { message?: unknown; code?: unknown; reasons?: unknown };
        if (typeof record.message === "string" && record.message) message = record.message;
        if (typeof record.code === "string") code = record.code;
        if (Array.isArray(record.reasons)) {
          reasons = record.reasons.filter((item): item is string => typeof item === "string");
        }
      }
    } catch {
      // The status line is enough when the body is not JSON.
    }
    throw new ApiError(response.status, message, code, reasons);
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

export async function loadRecording(): Promise<Recording | null> {
  try {
    return await api<Recording>("/demo/recording");
  } catch (err) {
    if (err instanceof ApiError && (err.status === 404 || err.status === 401)) return null;
    return null;
  }
}
