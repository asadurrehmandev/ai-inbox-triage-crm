"use client";

import { AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/button";

export function DeskError({ message, onRetry }: { message: string; onRetry: () => void }) {
  if (!message || message === "unauthorized") return null;
  return (
    <div role="alert" className="flex flex-wrap items-start gap-3 bg-danger-soft px-4 py-3 text-sm text-danger">
      <AlertCircle className="mt-0.5 size-4 shrink-0" strokeWidth={1.75} />
      <div className="min-w-0 flex-1">
        <p className="font-medium">The desk could not reach the triage API.</p>
        <p>Start the API on port 8741, then retry.</p>
        <p className="mt-1 text-xs">{message}</p>
      </div>
      <Button type="button" variant="outline" onClick={onRetry}>
        Retry
      </Button>
    </div>
  );
}
