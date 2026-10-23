"use client";

import { useEffect, useState, type ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTheme } from "next-themes";
import { Bell, Inbox, Menu, Monitor, Moon, Play, Sun, Users } from "lucide-react";
import { CommandMenu } from "@/components/command-menu";
import { DemoBadge } from "@/components/demo-badge";
import { KeyDialog } from "@/components/key-dialog";
import { useSessionKey } from "@/components/session-key";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useDesk } from "@/components/use-desk";
import { formatWhen, type Stats } from "@/lib/types";
import { cn } from "@/lib/utils";

const LINKS = [
  { href: "/", label: "Inbox", icon: Inbox, count: "pending_approval" as const },
  { href: "/crm", label: "CRM", icon: Users, count: "leads" as const },
  { href: "/pipeline", label: "Worker", icon: Play, count: null },
  { href: "/alerts", label: "Alerts", icon: Bell, count: "alerts" as const },
];

function pageTitle(pathname: string) {
  if (pathname === "/crm") return "CRM";
  if (pathname === "/pipeline") return "Python worker";
  if (pathname === "/alerts") return "Alerts";
  if (pathname.startsWith("/approve")) return "Approval";
  return "Inbox";
}

function activePath(pathname: string, href: string) {
  if (href === "/") return pathname === "/" || pathname.startsWith("/approve");
  return pathname === href;
}

export function LaneShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const desk = useDesk();
  const session = useSessionKey();
  const [keyOpen, setKeyOpen] = useState(false);
  const [navPath, setNavPath] = useState<string | null>(null);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const navOpen = navPath != null && navPath === pathname;
  const stats = desk.stats;
  const title = pageTitle(pathname);
  const lastRun = desk.worker?.last_run?.finished_at;

  useEffect(() => {
    document.title = title === "Inbox" ? "Lane" : `${title} · Lane`;
  }, [title]);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen((open) => !open);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className="flex h-dvh overflow-hidden bg-background text-foreground">
      <aside className="hidden h-full w-14 shrink-0 flex-col border-r border-border bg-surface md:flex lg:w-[232px]">
        <Sidebar stats={stats} pathname={pathname} />
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="shrink-0 border-b border-border">
          <div className="flex h-11 items-center gap-2 px-2 md:h-[52px] md:px-4">
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="md:hidden"
              aria-label="Open navigation"
              onClick={() => setNavPath(pathname)}
            >
              <Menu className="size-4" strokeWidth={1.75} />
            </Button>
            <h1 className="min-w-0 flex-1 truncate text-md font-semibold tracking-[-0.01em]">{title}</h1>
            <div className="flex shrink-0 items-center gap-1 md:gap-2">
              {lastRun ? (
                <span className="hidden text-xs text-subtle-foreground tabular-nums lg:inline">
                  Last run {formatWhen(lastRun)}
                </span>
              ) : null}
              <Button
                type="button"
                variant="outline"
                className="h-8 min-h-8 whitespace-nowrap px-2 text-xs max-md:!h-8 max-md:!min-h-8 max-md:px-2 md:px-2.5 md:text-sm"
                onClick={() => void desk.runIntake()}
                disabled={desk.busy || desk.pending.length === 0}
              >
                {desk.busy ? "Working" : "Run worker"}
              </Button>
              <span className="hidden md:contents">
                <DemoBadge stats={stats} onOpenKey={() => setKeyOpen(true)} />
              </span>
              <ThemeToggle />
            </div>
          </div>
          <div className="px-2 pb-2 md:hidden">
            <DemoBadge stats={stats} onOpenKey={() => setKeyOpen(true)} />
          </div>
        </header>
        {session.notice ? (
          <p className="border-b border-border bg-warning-soft px-4 py-2 text-sm text-warning" role="status">
            {session.notice}
          </p>
        ) : null}
        <main className="min-h-0 flex-1 overflow-hidden">{children}</main>
      </div>
      <Sheet open={navOpen} onOpenChange={(open) => setNavPath(open ? pathname : null)}>
        <SheetContent side="left" aria-label="Navigation">
          <SheetHeader>
            <SheetTitle>Lane</SheetTitle>
          </SheetHeader>
          <nav className="flex flex-col gap-1 p-2" aria-label="Pages">
            {LINKS.map((link) => (
              <NavLink key={link.href} link={link} pathname={pathname} stats={stats} rail={false} />
            ))}
          </nav>
          <p className="mt-auto px-4 py-4 text-xs text-subtle-foreground">Sample data</p>
        </SheetContent>
      </Sheet>
      <CommandMenu open={paletteOpen} onOpenChange={setPaletteOpen} onOpenKey={() => setKeyOpen(true)} />
      <KeyDialog open={keyOpen} onOpenChange={setKeyOpen} />
    </div>
  );
}

function Sidebar({ stats, pathname }: { stats: Stats | null; pathname: string }) {
  return (
    <>
      <div className="flex h-[52px] items-center gap-2 px-3 lg:px-4">
        <span className="flex size-7 shrink-0 items-center justify-center rounded-md bg-primary text-primary-foreground">
          <Inbox className="size-5" strokeWidth={1.75} />
        </span>
        <span className="hidden text-sm font-semibold lg:inline">Lane</span>
      </div>
      <nav className="flex flex-1 flex-col gap-0.5 px-2" aria-label="Pages">
        {LINKS.map((link) => (
          <NavLink key={link.href} link={link} pathname={pathname} stats={stats} rail />
        ))}
      </nav>
      <p className="hidden px-4 py-4 text-xs text-subtle-foreground lg:block">Sample data</p>
    </>
  );
}

function NavLink({
  link,
  pathname,
  stats,
  rail,
}: {
  link: (typeof LINKS)[number];
  pathname: string;
  stats: Stats | null;
  rail: boolean;
}) {
  const active = activePath(pathname, link.href);
  const Icon = link.icon;
  const count = link.count && stats ? stats[link.count] : null;
  const className = cn(
    "flex h-8 items-center gap-2 rounded-md px-2 text-sm font-medium max-md:min-h-11",
    active ? "bg-muted text-foreground" : "text-muted-foreground hover:bg-muted hover:text-foreground",
    rail && "justify-center lg:justify-start",
  );
  const content = (
    <>
      <Icon className="size-4 shrink-0" strokeWidth={1.75} />
      <span className={cn(rail && "hidden lg:inline")}>{link.label}</span>
      {count != null ? (
        <span className={cn("ml-auto text-xs text-muted-foreground tabular-nums", rail && "hidden lg:inline")}>
          {count}
        </span>
      ) : null}
    </>
  );
  if (rail) {
    return <RailLink className={className} href={link.href} active={active} label={link.label} count={count} content={content} />;
  }
  return (
    <Link href={link.href} className={className} aria-current={active ? "page" : undefined}>
      {content}
    </Link>
  );
}

function RailLink({
  className,
  href,
  active,
  label,
  count,
  content,
}: {
  className: string;
  href: string;
  active: boolean;
  label: string;
  count: number | null;
  content: ReactNode;
}) {
  const [wide, setWide] = useState(false);
  useEffect(() => {
    const query = window.matchMedia("(min-width: 1024px)");
    const apply = () => setWide(query.matches);
    const timer = window.setTimeout(apply, 0);
    query.addEventListener("change", apply);
    return () => {
      window.clearTimeout(timer);
      query.removeEventListener("change", apply);
    };
  }, []);
  const link = (
    <Link href={href} className={className} aria-current={active ? "page" : undefined} aria-label={label}>
      {content}
    </Link>
  );
  if (wide) return link;
  return (
    <Tooltip>
      <TooltipTrigger asChild>{link}</TooltipTrigger>
      <TooltipContent side="right">
        {label}
        {count != null ? ` ${count}` : ""}
      </TooltipContent>
    </Tooltip>
  );
}

function ThemeToggle() {
  const { setTheme, theme } = useTheme();
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button type="button" variant="ghost" size="icon" aria-label="Theme">
          <Sun className="size-4 dark:hidden" strokeWidth={1.75} />
          <Moon className="hidden size-4 dark:block" strokeWidth={1.75} />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem onSelect={() => setTheme("light")}>
          <Sun className="size-4" strokeWidth={1.75} /> Light {theme === "light" ? "· on" : ""}
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => setTheme("dark")}>
          <Moon className="size-4" strokeWidth={1.75} /> Dark {theme === "dark" ? "· on" : ""}
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => setTheme("system")}>
          <Monitor className="size-4" strokeWidth={1.75} /> System {theme === "system" ? "· on" : ""}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
