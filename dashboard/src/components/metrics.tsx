import { CATEGORIES, CATEGORY_COLOR, categoryLabel, type Stats } from "@/lib/types";

export function Metrics({ stats }: { stats: Stats }) {
  const processed = Math.max(stats.processed, 1);
  return (
    <section className="border-b border-border px-5 py-5 md:px-8">
      <div className="grid gap-6 md:grid-cols-[repeat(2,minmax(0,180px))_minmax(0,1fr)] md:items-end">
        <div>
          <p className="text-[11px] tracking-[0.16em] text-muted-foreground uppercase">
            Returned
          </p>
          <p className="mt-2 font-serif text-5xl leading-none tracking-tight">
            {stats.hours_saved.toFixed(1)}
          </p>
          <p className="mt-2 text-sm text-muted-foreground">hours on this mailbox</p>
        </div>
        <div>
          <p className="text-[11px] tracking-[0.16em] text-muted-foreground uppercase">
            At {stats.projected_daily_volume} a day
          </p>
          <p className="mt-2 font-serif text-5xl leading-none tracking-tight">
            {stats.projected_daily_hours.toFixed(1)}
          </p>
          <p className="mt-2 text-sm text-muted-foreground">hours a team gets back</p>
        </div>
        <dl className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm sm:grid-cols-4">
          <Stat label="Processed" value={stats.processed} />
          <Stat label="Waiting" value={stats.waiting} />
          <Stat label="Needs approval" value={stats.pending_approval} />
          <Stat label="Leads in CRM" value={stats.leads} />
        </dl>
      </div>
      <div className="mt-5 flex h-1.5 overflow-hidden rounded-full bg-secondary">
        {CATEGORIES.map((category) => {
          const count = stats.by_category[category] ?? 0;
          if (!count) return null;
          return (
            <div
              key={category}
              style={{
                width: `${(count / processed) * 100}%`,
                background: CATEGORY_COLOR[category],
              }}
              title={`${categoryLabel(category)} ${count}`}
            />
          );
        })}
      </div>
      <p className="mt-2 text-xs text-muted-foreground">
        {stats.minutes_per_email} minutes each for reading, labeling, the CRM entry, and a first reply.
        The {stats.projected_daily_hours.toFixed(1)} hour figure is that same rate on an{" "}
        {stats.projected_daily_volume}-message day.
      </p>
    </section>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="font-serif text-2xl leading-tight">{value}</dd>
    </div>
  );
}
