"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { resolvedProvider, useSessionKey, type ProviderChoice } from "@/components/session-key";

const NOTE =
  "Your key is used only for this session and is never stored or logged. We recommend rotating or revoking the key after testing.";

export function KeyDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const session = useSessionKey();
  const [draft, setDraft] = useState(session.key);
  const [provider, setProvider] = useState<ProviderChoice>(session.provider);
  const detected = resolvedProvider(draft, provider);

  useEffect(() => {
    if (!open) return;
    setDraft(session.key);
    setProvider(session.provider);
  }, [open, session.key, session.provider]);

  function save() {
    if (!draft.trim() || !detected) return;
    session.setKey(draft, provider);
    onOpenChange(false);
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Use your own API key</DialogTitle>
          <DialogDescription>{NOTE}</DialogDescription>
        </DialogHeader>
        <label className="grid gap-1 text-sm" htmlFor="lane-provider">
          Provider
          <select
            id="lane-provider"
            className="h-8 rounded-lg border border-input bg-transparent px-2 text-sm"
            value={provider}
            onChange={(event) => setProvider(event.target.value as ProviderChoice)}
          >
            <option value="auto">Detect from the key</option>
            <option value="anthropic">Anthropic · claude-sonnet-5-5</option>
            <option value="openai">OpenAI · the configured GPT model</option>
          </select>
        </label>
        <label className="grid gap-1 text-sm" htmlFor="lane-api-key">
          API key
          <Input
            id="lane-api-key"
            type="password"
            autoComplete="off"
            spellCheck={false}
            value={draft}
            placeholder="Paste an Anthropic or OpenAI key"
            onChange={(event) => setDraft(event.target.value)}
          />
        </label>
        <p className="text-xs text-muted-foreground">
          {detected === "anthropic"
            ? "This session will call Claude."
            : detected === "openai"
              ? "This session will call OpenAI."
              : "Paste a key that starts with sk-ant- or sk-."}
        </p>
        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={() => {
              setDraft("");
              session.clearKey();
            }}
          >
            Clear key
          </Button>
          <Button type="button" disabled={!detected} onClick={save}>
            Use for this session
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
