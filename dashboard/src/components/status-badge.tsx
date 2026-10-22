import type { ReactNode } from "react";
import { Badge } from "@/components/ui/badge";

export type Tone = "success" | "warning" | "danger" | "info" | "neutral";

export function categoryTone(category: string): Tone {
  if (category === "lead") return "info";
  if (category === "urgent" || category === "suspicious") return "danger";
  if (category === "review" || category === "invoice") return "warning";
  return "neutral";
}

export function confidencePresentation(confidence: number) {
  const pct = Math.round(confidence * 100);
  if (confidence >= 0.85) return { tone: "info" as const, label: `${pct}%` };
  if (confidence >= 0.6) return { tone: "warning" as const, label: "Review" };
  return { tone: "neutral" as const, label: "Needs a person" };
}

export function scoreSource(model: string) {
  if (model === "anthropic" || model === "openai") return "This score comes from the model.";
  return "This score comes from the rule engine.";
}

export function StatusBadge({
  tone,
  children,
}: {
  tone: Tone;
  children: ReactNode;
}) {
  return <Badge variant={tone}>{children}</Badge>;
}
