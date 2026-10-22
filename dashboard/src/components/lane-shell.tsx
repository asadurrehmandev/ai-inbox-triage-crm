"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { KeyDialog } from "@/components/key-dialog";
import { badgeText, resolvedProvider, useSessionKey } from "@/components/session-key";
import type { Stats } from "@/lib/types";
import { cn } from "@/lib/utils";

const LINKS = [
  { href: "/", label: "Queue" },
  { href: "/pipeline", label: "Worker" },
  { href: "/crm", label: "CRM" },
  { href: "/alerts", label: "Alerts" },
];

export function LaneShell({
  stats,
  children,
}: {
  stats: Stats | null;
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const session = useSessionKey();
  const [keyOpen, setKeyOpen] = useState(false);
  const serverProvider = stats?.mode === "anthropic" || stats?.mode === "openai" ? stats.mode : null;
  const pasted = session.live ? resolvedProvider(session.key, session.provider) : null;
  const badge = badgeText(Boolean(pasted || serverProvider), pasted ?? serverProvider);
  return (
    <div className="min-h-screen">
      <div className="mx-auto grid min-h-screen max-w-[1440px] md:grid-cols-[212px_minmax(0,1fr)]">
        <aside className="flex flex-col gap-8 border-b border-border px-5 py-5 md:border-r md:border-b-0 md:py-7">
          <div>
            <p className="font-serif text-[2rem] leading-none tracking-tight">Lane</p>
            <p className="mt-2 text-[11px] tracking-[0.18em] text-muted-foreground uppercase">
              Asad Rehman
            </p>
          </div>
          <nav className="flex gap-1 md:flex-col">
            {LINKS.map((link) => {
              const active = pathname === link.href;
              return (
                <Link
                  key={link.href}
                  href={link.href}
                  className={cn(
                    "rounded-md px-3 py-2 text-sm",
                    active
                      ? "bg-card text-foreground"
                      : "text-muted-foreground hover:bg-card hover:text-foreground",
                  )}
                >
                  {link.label}
                </Link>
              );
            })}
          </nav>
          <div className="mt-auto hidden text-sm leading-6 text-muted-foreground md:block">
            <p>AI triage with human approval.</p>
            <p className="mt-2">A person accepts the lead before it is written to the CRM.</p>
            <button
              type="button"
              className="mt-4 text-left text-xs underline-offset-2 hover:underline"
              onClick={() => setKeyOpen(true)}
            >
              API key
            </button>
            <p className="mt-1 text-xs">
              {stats ? `${stats.mailbox} · ${stats.crm}` : ""}
            </p>
            {stats && stats.fallbacks ? (
              <p className="mt-2 text-xs">Rules fallback on {stats.fallbacks} messages</p>
            ) : null}
          </div>
        </aside>
        <div className="min-w-0">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-5 py-3 md:px-8">
            <p className="text-xs leading-5" role="status">
              {badge}
            </p>
            <button
              type="button"
              className="text-xs underline-offset-2 hover:underline md:hidden"
              onClick={() => setKeyOpen(true)}
            >
              API key
            </button>
          </div>
          {session.notice ? (
            <p className="border-b border-border px-5 py-2 text-sm text-muted-foreground md:px-8">
              {session.notice}
            </p>
          ) : null}
          {children}
          <KeyDialog open={keyOpen} onOpenChange={setKeyOpen} />
        </div>
      </div>
    </div>
  );
}
