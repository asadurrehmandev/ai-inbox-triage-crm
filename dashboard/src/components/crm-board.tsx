"use client";

import { LaneShell } from "@/components/lane-shell";
import { Metrics } from "@/components/metrics";
import { useDesk } from "@/components/use-desk";
import { formatWhen } from "@/lib/types";

export function CrmBoard() {
  const desk = useDesk();
  return (
    <LaneShell stats={desk.stats}>
      {desk.stats ? <Metrics stats={desk.stats} /> : null}
      <section className="px-5 py-6 md:px-8">
        <h1 className="font-serif text-3xl tracking-tight">Qualified leads</h1>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
          Only mail classified as a lead is written here, through the CRM adapter. The reply still
          waits for a person. A HubSpot token or a GoHighLevel key mirrors the same contact.
        </p>
        {desk.loading && desk.leads.length === 0 ? (
          <p className="mt-8 text-sm text-muted-foreground">Loading the CRM…</p>
        ) : null}
        {desk.error ? (
          <p className="mt-6 text-sm text-muted-foreground">{desk.error}</p>
        ) : null}
        {!desk.loading && desk.leads.length === 0 ? (
          <p className="mt-8 border border-dashed border-border px-4 py-8 text-sm text-muted-foreground">
            No qualified leads yet. Run the worker on the queue. Spam, support, and invoices stay out of this list.
          </p>
        ) : null}
        {desk.leads.length > 0 ? (
          <div className="mt-6 overflow-auto border border-border">
            <table className="w-full min-w-[760px] text-left text-sm">
              <thead className="bg-card text-[11px] tracking-[0.14em] text-muted-foreground uppercase">
                <tr>
                  <th className="px-4 py-3 font-medium">Name</th>
                  <th className="px-4 py-3 font-medium">Company</th>
                  <th className="px-4 py-3 font-medium">Budget</th>
                  <th className="px-4 py-3 font-medium">Intent</th>
                  <th className="px-4 py-3 font-medium">Status</th>
                  <th className="px-4 py-3 font-medium">CRM sync</th>
                  <th className="px-4 py-3 font-medium">Added</th>
                </tr>
              </thead>
              <tbody>
                {desk.leads.map((lead) => (
                  <tr key={lead.id} className="border-t border-border">
                    <td className="px-4 py-3">
                      <div>{lead.name || "No personal name"}</div>
                      <div className="text-xs text-muted-foreground">{lead.email}</div>
                    </td>
                    <td className="px-4 py-3">{lead.company || "Not stated"}</td>
                    <td className="px-4 py-3">{lead.budget || "Not stated"}</td>
                    <td className="px-4 py-3">{lead.intent}</td>
                    <td className="px-4 py-3">{lead.status}</td>
                    <td className="px-4 py-3">
                      <div>
                        {lead.remote_status === "ok" || lead.remote_status === "error"
                          ? lead.remote_status
                          : lead.destination}
                      </div>
                      {lead.remote_error ? (
                        <div className="text-xs text-muted-foreground">{lead.remote_error}</div>
                      ) : null}
                    </td>
                    <td className="px-4 py-3 text-muted-foreground">{formatWhen(lead.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>
    </LaneShell>
  );
}
