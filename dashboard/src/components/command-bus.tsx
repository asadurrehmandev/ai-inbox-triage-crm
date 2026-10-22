"use client";

import { createContext, useContext, useState, type ReactNode } from "react";

export type MailHandler = {
  primaryLabel: string;
  hasItem: boolean;
  canPrimary: boolean;
  canNotLead: boolean;
  canRun: boolean;
  canReplay: boolean;
  runPrimary: () => void;
  edit: () => void;
  notLead: () => void;
  snooze: () => void;
  next: () => void;
  previous: () => void;
  openItem: (id: number) => void;
};

type Bus = {
  set: (next: MailHandler | null) => void;
  get: () => MailHandler | null;
  snapshot: () => string;
  subscribe: (fn: () => void) => () => void;
};

const CommandBusContext = createContext<Bus | null>(null);

function createBus(): Bus {
  let handler: MailHandler | null = null;
  let snap = "";
  const listeners = new Set<() => void>();
  return {
    set(next) {
      handler = next;
      const nsnap = next
        ? `${next.primaryLabel}|${next.hasItem}|${next.canPrimary}|${next.canNotLead}|${next.canRun}|${next.canReplay}`
        : "";
      if (nsnap !== snap) {
        snap = nsnap;
        listeners.forEach((listener) => listener());
      }
    },
    get: () => handler,
    snapshot: () => snap,
    subscribe(fn) {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
  };
}

export function CommandBusProvider({ children }: { children: ReactNode }) {
  const [bus] = useState(createBus);
  return <CommandBusContext.Provider value={bus}>{children}</CommandBusContext.Provider>;
}

export function useCommandBus() {
  const bus = useContext(CommandBusContext);
  if (!bus) throw new Error("Command shortcuts are only available inside the desk.");
  return bus;
}
