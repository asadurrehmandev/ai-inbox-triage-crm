import { StatusBadge, categoryTone } from "@/components/status-badge";
import { categoryLabel, formatWhen, type Triage } from "@/lib/types";

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid grid-cols-[88px_minmax(0,1fr)] gap-2 py-2 text-sm">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 break-words">{value}</dd>
    </div>
  );
}

export function MessageDetails({
  item,
  inCrm,
  destination,
}: {
  item: Triage;
  inCrm: boolean;
  destination: string;
}) {
  const mock = !destination || destination.toLowerCase().includes("mock");
  return (
    <div className="px-4 py-3">
      <h2 className="text-xs font-medium text-muted-foreground">Contact</h2>
      <p className="mt-2 text-sm font-semibold">{item.name || item.from_name || "–"}</p>
      <p className="truncate text-sm text-muted-foreground" title={item.from_email || undefined}>
        {item.from_email || "–"}
      </p>
      <dl className="mt-3 divide-y divide-border border-y border-border">
        <Row label="Company" value={item.company || "–"} />
        <Row label="Budget" value={item.budget || "–"} />
        <Row label="Intent" value={item.intent || "–"} />
        <Row label="Received" value={formatWhen(item.received_at) || "–"} />
      </dl>
      <div className="mt-4 flex flex-wrap gap-1.5">
        <StatusBadge tone={categoryTone(item.category)}>{categoryLabel(item.category)}</StatusBadge>
        <StatusBadge tone={mock ? "neutral" : "info"}>{mock ? "Mock" : destination}</StatusBadge>
        {inCrm ? <StatusBadge tone="success">Filed</StatusBadge> : <StatusBadge tone="neutral">Not filed</StatusBadge>}
        {item.approved ? <StatusBadge tone="success">Approved</StatusBadge> : null}
      </div>
    </div>
  );
}
