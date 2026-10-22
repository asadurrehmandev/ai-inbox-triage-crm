import { NextRequest, NextResponse } from "next/server";
import { issueSession, loginAllowed, passwordOk, SESSION_MAX_AGE } from "@/lib/session";

function secureCookie(request: NextRequest) {
  return request.nextUrl.protocol === "https:" || request.headers.get("x-forwarded-proto") === "https";
}

export async function POST(request: NextRequest) {
  if (!process.env.DASHBOARD_PASSWORD) {
    return NextResponse.json({ detail: "dashboard password is not configured" }, { status: 503 });
  }
  const ip = request.headers.get("x-forwarded-for")?.split(",")[0]?.trim() || "local";
  if (!loginAllowed(ip)) {
    return NextResponse.json({ detail: "too many attempts" }, { status: 429 });
  }
  const body = (await request.json().catch(() => ({}))) as { password?: string };
  if (!passwordOk(body.password ?? "")) {
    return NextResponse.json({ detail: "unauthorized" }, { status: 401 });
  }
  const session = issueSession();
  const response = NextResponse.json({ ok: true });
  response.cookies.set("lane_session", session.id, {
    httpOnly: true,
    sameSite: "lax",
    path: "/",
    secure: secureCookie(request),
    maxAge: SESSION_MAX_AGE,
  });
  return response;
}
