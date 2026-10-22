import { NextRequest, NextResponse } from "next/server";
import { sessionToken } from "@/lib/session";

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const expected = sessionToken();
  const cookie = request.cookies.get("lane_session")?.value;
  if (!expected || cookie !== expected) {
    return NextResponse.json({ detail: "unauthorized" }, { status: 401 });
  }
  const { path } = await context.params;
  const base = (process.env.API_BASE_URL ?? "http://127.0.0.1:8741/api").replace(/\/$/, "");
  const url = `${base}/${path.join("/")}${request.nextUrl.search}`;
  const headers: Record<string, string> = {
    Authorization: `Bearer ${process.env.API_TOKEN ?? ""}`,
  };
  const init: RequestInit = { method: request.method, headers, cache: "no-store" };
  if (request.method !== "GET" && request.method !== "HEAD") {
    headers["Content-Type"] = "application/json";
    init.body = await request.text();
  }
  const response = await fetch(url, init);
  const text = await response.text();
  return new NextResponse(text, {
    status: response.status,
    headers: { "content-type": response.headers.get("content-type") ?? "application/json" },
  });
}

export const GET = proxy;
export const POST = proxy;
