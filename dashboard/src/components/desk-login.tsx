"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export function DeskLogin({ onDone }: { onDone: () => void }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const response = await fetch("/backend/session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password }),
      });
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
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-6">
      <p className="font-serif text-4xl tracking-tight">Lane</p>
      <p className="mt-3 text-sm text-muted-foreground">
        The desk password stays on the server. The API token is not in the page.
      </p>
      <form onSubmit={submit} className="mt-8 flex flex-col gap-3">
        <label className="text-xs tracking-[0.16em] text-muted-foreground uppercase" htmlFor="desk-password">
          Desk password
        </label>
        <Input
          id="desk-password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
        {error ? <p className="text-sm text-destructive">{error}</p> : null}
        <Button type="submit" disabled={busy || !password}>
          Open the desk
        </Button>
      </form>
    </main>
  );
}
