"use client";

import { useParams } from "next/navigation";
import { InboxDesk } from "@/components/inbox-desk";

export default function ApprovePage() {
  const params = useParams<{ id: string }>();
  const id = Number(params.id);
  return <InboxDesk focusId={Number.isFinite(id) ? id : undefined} />;
}
