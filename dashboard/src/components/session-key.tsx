"use client";

import { createContext, useContext, useMemo, useState } from "react";

export type LiveProvider = "anthropic" | "openai";
export type ProviderChoice = LiveProvider | "auto";

type SessionKeyValue = {
  key: string;
  provider: ProviderChoice;
  live: boolean;
  notice: string | null;
  setKey: (key: string, provider: ProviderChoice) => void;
  clearKey: () => void;
  markDemo: (notice: string) => void;
};

const SessionKeyContext = createContext<SessionKeyValue | null>(null);

export function SessionKeyProvider({ children }: { children: React.ReactNode }) {
  const [key, setKeyValue] = useState("");
  const [provider, setProvider] = useState<ProviderChoice>("auto");
  const [live, setLive] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const value = useMemo<SessionKeyValue>(
    () => ({
      key,
      provider,
      live: live && key.length > 0,
      notice,
      setKey: (next, nextProvider) => {
        const trimmed = next.trim();
        setKeyValue(trimmed);
        setProvider(nextProvider);
        setLive(trimmed.length > 0);
        setNotice(null);
      },
      clearKey: () => {
        setKeyValue("");
        setLive(false);
        setNotice(null);
      },
      markDemo: (message) => {
        setLive(false);
        setNotice(message);
      },
    }),
    [key, provider, live, notice],
  );
  return <SessionKeyContext.Provider value={value}>{children}</SessionKeyContext.Provider>;
}

export function useSessionKey() {
  const value = useContext(SessionKeyContext);
  if (!value) {
    throw new Error("The API key session is only available inside the desk.");
  }
  return value;
}

export function resolvedProvider(key: string, provider: ProviderChoice): LiveProvider | null {
  if (provider === "anthropic" || provider === "openai") return provider;
  if (key.startsWith("sk-ant-")) return "anthropic";
  if (key.startsWith("sk-")) return "openai";
  return null;
}

export const DEMO_BADGE = "Demo mode: sample responses. Add your API key for live AI.";

export function badgeText(live: boolean, provider: LiveProvider | null) {
  if (live && provider === "anthropic") return "Live AI (Claude)";
  if (live && provider === "openai") return "Live AI (OpenAI)";
  return DEMO_BADGE;
}
