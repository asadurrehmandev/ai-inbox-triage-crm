import { NextRequest, NextResponse } from "next/server";
import { rotateSession, sessionValid, SESSION_MAX_AGE } from "@/lib/session";

function secureCookie(request: NextRequest) {
  return request.nextUrl.protocol === "https:" || request.headers.get("x-forwarded-proto") === "https";
}

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const cookie = request.cookies.get("lane_session")?.value;
  if (!sessionValid(cookie)) {
    return NextResponse.json({ detail: "unauthorized" }, { status: 401 });
  }
  const rotated = cookie ? rotateSession(cookie) : null;
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
  const outbound = new NextResponse(text, {
    status: response.status,
    headers: { "content-type": response.headers.get("content-type") ?? "application/json" },
  });
  if (rotated) {
    outbound.cookies.set("lane_session", rotated, {
      httpOnly: true,
      sameSite: "lax",
      path: "/",
      secure: secureCookie(request),
      maxAge: SESSION_MAX_AGE,
    });
  }
  return outbound;
}

export const GET = proxy;
export const POST = proxy;
