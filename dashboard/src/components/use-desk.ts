"use client";

import { useCallback, useEffect, useState } from "react";
import { api, loadDesk } from "@/lib/api";
import type { Alert, Lead, Mail, Run, Stats, Triage, WorkerStatus } from "@/lib/types";

export function useDesk() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [items, setItems] = useState<Triage[]>([]);
  const [pending, setPending] = useState<Mail[]>([]);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [worker, setWorker] = useState<WorkerStatus | null>(null);
  const [runs, setRuns] = useState<Run[]>([]);
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

  async function approve(id: number) {
    setBusy(true);
    try {
      await api(`/triage/${id}/approve`, { method: "POST" });
      await refresh();
    } finally {
      setBusy(false);
    }
  }

  async function resetDemo() {
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
    error,
    loading,
    busy,
    refresh,
    runIntake,
    saveDraft,
    approve,
    resetDemo,
  };
}
