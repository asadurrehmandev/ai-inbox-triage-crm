"use client";

import { useSyncExternalStore } from "react";
import { useRouter } from "next/navigation";
import { useTheme } from "next-themes";
import { toast } from "sonner";
import { useCommandBus } from "@/components/command-bus";
import { Kbd } from "@/components/ui/kbd";
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { useDesk } from "@/components/use-desk";
import { useSessionKey } from "@/components/session-key";

export function CommandMenu({
  open,
  onOpenChange,
  onOpenKey,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onOpenKey: () => void;
}) {
  const desk = useDesk();
  const bus = useCommandBus();
  const router = useRouter();
  const session = useSessionKey();
  const { setTheme } = useTheme();
  const snap = useSyncExternalStore(bus.subscribe, bus.snapshot, bus.snapshot);
  const mail = snap ? bus.get() : null;

  function go(href: string) {
    router.push(href);
    onOpenChange(false);
  }

  function run(action: () => void) {
    action();
    onOpenChange(false);
  }

  return (
    <CommandDialog open={open} onOpenChange={onOpenChange}>
      <CommandInput placeholder="Search mail and actions" aria-label="Search mail and actions" />
      <CommandList>
        <CommandEmpty>No matches.</CommandEmpty>
        {mail?.hasItem ? (
          <CommandGroup heading="This message">
            <CommandItem disabled={!mail.canPrimary} onSelect={() => run(() => bus.get()?.runPrimary())}>
              {mail.primaryLabel}
              <Kbd>⌘↵</Kbd>
            </CommandItem>
            <CommandItem onSelect={() => run(() => bus.get()?.edit())}>
              Edit draft
              <Kbd>R</Kbd>
            </CommandItem>
            <CommandItem disabled={!mail.canNotLead} onSelect={() => run(() => bus.get()?.notLead())}>
              Mark not a lead
              <Kbd>N</Kbd>
            </CommandItem>
            <CommandItem onSelect={() => run(() => bus.get()?.snooze())}>
              Snooze
              <Kbd>H</Kbd>
            </CommandItem>
            <CommandItem onSelect={() => run(() => bus.get()?.next())}>
              Next
              <Kbd>J</Kbd>
            </CommandItem>
            <CommandItem onSelect={() => run(() => bus.get()?.previous())}>
              Previous
              <Kbd>K</Kbd>
            </CommandItem>
          </CommandGroup>
        ) : null}
        <CommandGroup heading="Mailbox">
          <CommandItem
            disabled={desk.busy || desk.pending.length === 0}
            onSelect={() =>
              run(() => {
                void desk.runIntake();
              })
            }
          >
            Run worker
          </CommandItem>
          <CommandItem
            disabled={desk.busy || !desk.recording?.present}
            onSelect={() =>
              run(() => {
                void desk.replayRecording();
              })
            }
          >
            Replay recorded pass
          </CommandItem>
          <CommandItem
            disabled={desk.busy}
            onSelect={() =>
              run(() => {
                void desk.resetDemo();
              })
            }
          >
            Reset sample mailbox
          </CommandItem>
        </CommandGroup>
        <CommandGroup heading="Go to">
          <CommandItem onSelect={() => go("/")}>Inbox</CommandItem>
          <CommandItem onSelect={() => go("/crm")}>CRM</CommandItem>
          <CommandItem onSelect={() => go("/pipeline")}>Worker</CommandItem>
          <CommandItem onSelect={() => go("/alerts")}>Alerts</CommandItem>
        </CommandGroup>
        <CommandGroup heading="Messages">
          {desk.items.slice(0, 80).map((item) => (
            <CommandItem
              key={item.id}
              value={`${item.from_name ?? ""} ${item.name ?? ""} ${item.subject ?? ""} ${item.from_email ?? ""} ${item.company ?? ""}`}
              onSelect={() =>
                run(() => {
                  const openItem = bus.get()?.openItem;
                  if (openItem) openItem(item.id);
                  else router.push(`/approve/${item.id}`);
                })
              }
            >
              <span className="truncate">
                {item.from_name || item.name || "Unknown sender"}
                <span className="text-muted-foreground"> {item.subject}</span>
              </span>
            </CommandItem>
          ))}
        </CommandGroup>
        <CommandGroup heading="Session">
          <CommandItem onSelect={() => run(onOpenKey)}>API key</CommandItem>
          <CommandItem
            disabled={!session.live}
            onSelect={() =>
              run(() => {
                session.clearKey();
                toast("API key cleared for this session.");
              })
            }
          >
            Clear API key
          </CommandItem>
          <CommandItem onSelect={() => run(() => setTheme("light"))}>Light theme</CommandItem>
          <CommandItem onSelect={() => run(() => setTheme("dark"))}>Dark theme</CommandItem>
          <CommandItem onSelect={() => run(() => setTheme("system"))}>System theme</CommandItem>
        </CommandGroup>
      </CommandList>
    </CommandDialog>
  );
}
