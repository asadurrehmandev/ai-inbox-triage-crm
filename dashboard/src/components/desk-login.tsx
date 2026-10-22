"use client";

import { useState, type FormEvent } from "react";
import { Inbox } from "lucide-react";
import { DemoBadge } from "@/components/demo-badge";
import { KeyDialog } from "@/components/key-dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export function DeskLogin({ onDone }: { onDone: () => void }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [keyOpen, setKeyOpen] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const response = await fetch("/backend/session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password }),
      });
      if (response.status === 429) {
        setError("Too many attempts. Wait a few minutes and try again.");
        return;
      }
      if (!response.ok) {
        setError("That password does not open the desk.");
        return;
      }
      onDone();
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="flex min-h-dvh flex-col bg-background">
      <header className="flex min-h-[52px] flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-2">
        <span className="flex items-center gap-2">
          <span className="flex size-7 items-center justify-center rounded-md bg-primary text-primary-foreground">
            <Inbox className="size-5" strokeWidth={1.75} />
          </span>
          <span className="text-sm font-semibold">Lane</span>
        </span>
        <DemoBadge stats={null} onOpenKey={() => setKeyOpen(true)} />
      </header>
      <form onSubmit={submit} className="mx-auto flex w-full max-w-sm flex-1 flex-col justify-center px-6">
        <h1 className="text-lg font-semibold tracking-[-0.01em]">Sign in</h1>
        <p className="mt-1 text-sm text-muted-foreground">The desk password stays on the server.</p>
        <label className="mt-6 text-sm font-medium" htmlFor="desk-password">
          Desk password
        </label>
        <Input
          id="desk-password"
          className="mt-2"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
        {error ? (
          <p className="mt-2 text-sm text-danger" role="alert">
            {error}
          </p>
        ) : null}
        <Button type="submit" className="mt-4" disabled={busy || !password}>
          Open the desk
        </Button>
      </form>
      <KeyDialog open={keyOpen} onOpenChange={setKeyOpen} />
    </main>
  );
}
