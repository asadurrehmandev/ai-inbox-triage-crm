"use client";

import { FlaskConical } from "lucide-react";
import { badgeText, resolvedProvider, useSessionKey } from "@/components/session-key";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { Stats } from "@/lib/types";

const SIMULATED = "No API key: replies come from rules and recorded samples. CRM sync is mocked.";

export function DemoBadge({
  stats,
  onOpenKey,
}: {
  stats: Stats | null;
  onOpenKey: () => void;
}) {
  const session = useSessionKey();
  const serverProvider = stats?.mode === "anthropic" || stats?.mode === "openai" ? stats.mode : null;
  const pasted = session.live ? resolvedProvider(session.key, session.provider) : null;
  const provider = pasted ?? serverProvider;
  const live = Boolean(provider);
  const full = badgeText(live, provider);
  const tip = live
    ? `${full}. The key stays in this tab and is not stored.`
    : `${full} ${SIMULATED}`;
  const tone = live
    ? "bg-info-soft text-info"
    : "bg-warning-soft text-warning";
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          onClick={onOpenKey}
          className={`inline-flex h-8 max-w-full items-center gap-1.5 rounded-sm px-2 text-left text-xs font-medium max-md:h-auto max-md:min-h-11 max-md:w-full max-md:whitespace-normal max-md:py-1.5 ${tone}`}
          aria-label={full}
          role="status"
          data-testid="demo-badge"
        >
          <FlaskConical className="size-3.5 shrink-0" strokeWidth={1.75} />
          <span className="min-w-0 md:truncate">{full}</span>
        </button>
      </TooltipTrigger>
      <TooltipContent>{tip}</TooltipContent>
    </Tooltip>
  );
}
