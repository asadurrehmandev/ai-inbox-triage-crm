"use client";

import { useState } from "react";
import Link from "next/link";
import { Users } from "lucide-react";
import { DeskError } from "@/components/desk-error";
import { DeskLogin } from "@/components/desk-login";
import { EmptyState } from "@/components/empty-state";
import { LaneShell } from "@/components/lane-shell";
import { StatusBadge, type Tone } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useDelayed } from "@/components/use-delayed";
import { useDesk } from "@/components/use-desk";
import { formatWhen, type Lead } from "@/lib/types";

function syncLabel(lead: Lead): { tone: Tone; label: string } {
  if (lead.remote_status === "error") return { tone: "danger", label: "Failed" };
  if ((lead.destination || "mock").toLowerCase().includes("mock")) return { tone: "neutral", label: "Mock" };
  if (lead.remote_status === "ok") return { tone: "success", label: "Synced" };
  return { tone: "neutral", label: lead.destination || "Mock" };
}

function statusLabel(status: string): { tone: Tone; label: string } {
  if (!status) return { tone: "neutral", label: "–" };
  const label = status.slice(0, 1).toUpperCase() + status.slice(1);
  if (/filed|accept|sync/i.test(status)) return { tone: "success", label };
  return { tone: "neutral", label };
}

export function CrmBoard() {
  const desk = useDesk();
  const [open, setOpen] = useState<Lead | null>(null);
  const showSkeleton = useDelayed(desk.loading && desk.leads.length === 0);

  if (desk.error === "unauthorized" && !desk.stats) {
    return <DeskLogin onDone={() => void desk.refresh()} />;
  }

  return (
    <LaneShell>
      <div className="flex h-full flex-col">
        {desk.error ? <DeskError message={desk.error} onRetry={() => void desk.refresh()} /> : null}
        <div className="flex items-center justify-end px-4 py-2">
          <Popover>
            <PopoverTrigger asChild>
              <Button type="button" variant="ghost">
                How filing works
              </Button>
            </PopoverTrigger>
            <PopoverContent align="end">
              A person accepts every lead before it is written here. Demo mode never files on its own. Mail
              about moving money or changing a payee stays out. HubSpot stores lane_budget and lane_intent when
              those properties exist, otherwise as a note. GoHighLevel gets the same two fields, or a source note
              if custom fields are rejected.
            </PopoverContent>
          </Popover>
        </div>
        <div className="min-h-0 flex-1 overflow-auto">
          {showSkeleton && desk.leads.length === 0 ? (
            <div className="space-y-2 p-4">
              {Array.from({ length: 6 }, (_, index) => (
                <Skeleton key={index} className="h-10 w-full" />
              ))}
            </div>
          ) : desk.leads.length === 0 ? (
            <EmptyState
              icon={Users}
              title="No leads yet"
              body="Accept a lead from Inbox. Payment-related mail cannot be filed."
              action={
                <Button type="button" variant="outline" asChild>
                  <Link href="/">Open Inbox</Link>
                </Button>
              }
            />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="sticky left-0 bg-surface">Name</TableHead>
                  <TableHead>Company</TableHead>
                  <TableHead className="text-right">Budget</TableHead>
                  <TableHead>Intent</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Sync</TableHead>
                  <TableHead>Added</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {desk.leads.map((lead) => {
                  const sync = syncLabel(lead);
                  const status = statusLabel(lead.status);
                  return (
                    <TableRow
                      key={lead.id}
                      tabIndex={0}
                      className="cursor-pointer"
                      onClick={() => setOpen(lead)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") setOpen(lead);
                      }}
                    >
                      <TableCell className="sticky left-0 bg-background">
                        <div className="font-medium">{lead.name || "–"}</div>
                        <div className="text-xs text-muted-foreground">{lead.email || "–"}</div>
                      </TableCell>
                      <TableCell>{lead.company || "–"}</TableCell>
                      <TableCell className="text-right tabular-nums">{lead.budget || "–"}</TableCell>
                      <TableCell className="max-w-[240px] truncate" title={lead.intent || undefined}>
                        {lead.intent || "–"}
                      </TableCell>
                      <TableCell>
                        <StatusBadge tone={status.tone}>{status.label}</StatusBadge>
                      </TableCell>
                      <TableCell>
                        <StatusBadge tone={sync.tone}>{sync.label}</StatusBadge>
                      </TableCell>
                      <TableCell className="text-subtle-foreground tabular-nums">{formatWhen(lead.created_at)}</TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </div>
      </div>
      <Sheet open={open != null} onOpenChange={(value) => !value && setOpen(null)}>
        <SheetContent side="right" aria-label="Lead">
          <SheetHeader>
            <SheetTitle>{open?.name || "Lead"}</SheetTitle>
          </SheetHeader>
          {open ? (
            <dl className="space-y-3 px-4 py-4 text-sm">
              <Field label="Email" value={open.email} />
              <Field label="Company" value={open.company} />
              <Field label="Budget" value={open.budget} />
              <Field label="Intent" value={open.intent} />
              <Field label="Subject" value={open.source_subject} />
              <Field label="Status" value={open.status} />
              <Field label="Sync" value={syncLabel(open).label} />
              {open.remote_error ? <Field label="Error" value={open.remote_error} /> : null}
              <Field label="Added" value={formatWhen(open.created_at)} />
            </dl>
          ) : null}
        </SheetContent>
      </Sheet>
    </LaneShell>
  );
}

function Field({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-0.5 break-words">{value || "–"}</dd>
    </div>
  );
}
