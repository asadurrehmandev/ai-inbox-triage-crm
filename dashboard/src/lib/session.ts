import { createHmac, timingSafeEqual } from "crypto";

function password() {
  return process.env.DASHBOARD_PASSWORD ?? "";
}

export function sessionToken() {
  const secret = password();
  if (!secret) return "";
  return createHmac("sha256", secret).update("lane-desk").digest("hex");
}

export function passwordOk(given: string) {
  const expected = password();
  if (!expected || !given) return false;
  const left = createHmac("sha256", "lane-login").update(given).digest();
  const right = createHmac("sha256", "lane-login").update(expected).digest();
  return timingSafeEqual(left, right);
}
