"use client";

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, ApiError, loadDesk, loadRecording } from "@/lib/api";
import type { AcceptResult, Alert, Lead, Mail, Recording, Run, Stats, Triage, WorkerStatus } from "@/lib/types";

function useDeskState() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [items, setItems] = useState<Triage[]>([]);
  const [pending, setPending] = useState<Mail[]>([]);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [worker, setWorker] = useState<WorkerStatus | null>(null);
  const [runs, setRuns] = useState<Run[]>([]);
  const [recording, setRecording] = useState<Recording | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const [nextStats, triage, mailbox, crm, feed, nextWorker, nextRuns] = await loadDesk();
      setStats(nextStats);
      setItems(triage.items);
      setPending(mailbox.emails);
      setLeads(crm.leads);
      setAlerts(feed.alerts);
      setWorker(nextWorker);
      setRuns(nextRuns.runs);
      setRecording(await loadRecording());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "The triage API is not answering.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void refresh();
    }, 0);
    const id = window.setInterval(() => void refresh(), 4000);
    return () => {
      window.clearTimeout(timer);
      window.clearInterval(id);
    };
  }, [refresh]);

  async function runIntake() {
    setBusy(true);
    try {
      await api("/worker/run", { method: "POST" });
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Intake failed.");
    } finally {
      setBusy(false);
    }
  }

  async function saveDraft(id: number, draft: string) {
    setBusy(true);
    try {
      await api(`/triage/${id}/draft`, {
        method: "POST",
        body: JSON.stringify({ draft_reply: draft }),
      });
      await refresh();
    } finally {
      setBusy(false);
    }
  }

  async function acceptLabel(id: number, category: string, confirm = false): Promise<AcceptResult> {
    setBusy(true);
    try {
      await api(`/triage/${id}/accept`, {
        method: "POST",
        body: JSON.stringify({ category, confirm }),
      });
      await refresh();
      return { ok: true, code: "ok", message: "", reasons: [] };
    } catch (err) {
      const result: AcceptResult = {
        ok: false,
        code: err instanceof ApiError ? err.code : "",
        message: err instanceof Error ? err.message : "Could not accept that label.",
        reasons: err instanceof ApiError ? err.reasons : [],
      };
      if (result.code !== "confirm") setError(result.message);
      return result;
    } finally {
      setBusy(false);
    }
  }

  async function replayRecording() {
    setBusy(true);
    try {
      await api("/demo/replay", { method: "POST" });
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not replay the recorded pass.");
    } finally {
      setBusy(false);
    }
  }

  async function classifyLive(id: number, key: string, provider: string | null) {
    setBusy(true);
    try {
      const headers: Record<string, string> = { "X-Lane-Key": key };
      if (provider) headers["X-Lane-Provider"] = provider;
      const result = await api<{ triage: Triage; mode: string; notice: string | null }>(
        `/triage/${id}/live`,
        { method: "POST", headers },
      );
      await refresh();
      return result;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Live AI did not answer.");
      return null;
    } finally {
      setBusy(false);
    }
  }

  async function approve(id: number) {
    setBusy(true);
    try {
      await api(`/triage/${id}/approve`, { method: "POST" });
      await refresh();
      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not approve that reply.");
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function resetDemo() {
    if (!window.confirm("Reset the sample mailbox? This clears the queue, the CRM, and the alerts.")) {
      return;
    }
    setBusy(true);
    try {
      await api("/demo/reset", { method: "POST" });
      await refresh();
    } finally {
      setBusy(false);
    }
  }

  return {
    stats,
    items,
    pending,
    leads,
    alerts,
    worker,
    runs,
    recording,
    error,
    loading,
    busy,
    refresh,
    runIntake,
    saveDraft,
    approve,
    acceptLabel,
    classifyLive,
    replayRecording,
    resetDemo,
  };
}

type Desk = ReturnType<typeof useDeskState>;

const DeskContext = createContext<Desk | null>(null);

export function DeskProvider({ children }: { children: ReactNode }) {
  const value = useDeskState();
  return <DeskContext.Provider value={value}>{children}</DeskContext.Provider>;
}

export function useDesk() {
  const value = useContext(DeskContext);
  if (!value) throw new Error("The desk is only available inside DeskProvider.");
  return value;
}
