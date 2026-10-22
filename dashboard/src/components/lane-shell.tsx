"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { Stats } from "@/lib/types";
import { modeLabel } from "@/lib/types";
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
            <p>Inbox triage for studios that sell automation.</p>
            <p className="mt-4 text-xs tracking-wide uppercase">
              {stats ? modeLabel(stats.mode) : "Connecting"}
            </p>
            <p className="mt-1 text-xs">
              {stats ? `${stats.mailbox} · ${stats.crm}` : ""}
            </p>
            {stats && stats.fallbacks ? (
              <p className="mt-2 text-xs">Rules fallback on {stats.fallbacks} messages</p>
            ) : null}
          </div>
        </aside>
        <div className="min-w-0">{children}</div>
      </div>
    </div>
  );
}
