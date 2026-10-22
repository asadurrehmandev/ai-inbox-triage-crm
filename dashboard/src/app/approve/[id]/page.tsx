import { Suspense } from "react";
import { InboxDesk } from "@/components/inbox-desk";

async function Desk({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const focusId = Number(id);
  return <InboxDesk focusId={Number.isFinite(focusId) ? focusId : undefined} />;
}

export default function ApprovePage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  return (
    <Suspense
      fallback={
        <p className="px-8 py-16 text-sm text-muted-foreground">Opening the draft…</p>
      }
    >
      <Desk params={params} />
    </Suspense>
  );
}
