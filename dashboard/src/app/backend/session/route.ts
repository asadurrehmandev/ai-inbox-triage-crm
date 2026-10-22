import { NextRequest, NextResponse } from "next/server";
import { passwordOk, sessionToken } from "@/lib/session";

export async function POST(request: NextRequest) {
  const token = sessionToken();
  if (!token) {
    return NextResponse.json({ detail: "dashboard password is not configured" }, { status: 503 });
  }
  const body = (await request.json().catch(() => ({}))) as { password?: string };
  if (!passwordOk(body.password ?? "")) {
    return NextResponse.json({ detail: "unauthorized" }, { status: 401 });
  }
  const response = NextResponse.json({ ok: true });
  response.cookies.set("lane_session", token, {
    httpOnly: true,
    sameSite: "lax",
    path: "/",
    secure: false,
  });
  return response;
}
