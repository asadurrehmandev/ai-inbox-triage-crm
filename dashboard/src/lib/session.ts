import { createHmac, randomBytes, timingSafeEqual } from "crypto";
import { mkdirSync, readFileSync, writeFileSync } from "fs";
import path from "path";

export const SESSION_MAX_AGE = 60 * 60 * 12;

type Session = { id: string; expires: number };

const file = path.join(process.cwd(), ".desk-sessions.json");
const attempts = new Map<string, { count: number; reset: number }>();

function password() {
  return process.env.DASHBOARD_PASSWORD ?? "";
}

function load(): Session[] {
  try {
    const parsed = JSON.parse(readFileSync(file, "utf8")) as { sessions?: Session[] };
    return Array.isArray(parsed.sessions) ? parsed.sessions : [];
  } catch {
    return [];
  }
}

function save(sessions: Session[]) {
  mkdirSync(path.dirname(file), { recursive: true });
  const live = sessions.filter((session) => session.expires > Date.now()).slice(-32);
  writeFileSync(file, JSON.stringify({ sessions: live }));
}

export function passwordOk(given: string) {
  const expected = password();
  if (!expected || !given) return false;
  const left = createHmac("sha256", "lane-login").update(given).digest();
  const right = createHmac("sha256", "lane-login").update(expected).digest();
  return timingSafeEqual(left, right);
}

export function loginAllowed(ip: string) {
  const now = Date.now();
  const row = attempts.get(ip);
  if (!row || row.reset < now) {
    attempts.set(ip, { count: 1, reset: now + 10 * 60 * 1000 });
    return true;
  }
  row.count += 1;
  return row.count <= 8;
}

export function issueSession() {
  const id = randomBytes(32).toString("hex");
  const sessions = load().filter((session) => session.expires > Date.now());
  sessions.push({ id, expires: Date.now() + SESSION_MAX_AGE * 1000 });
  save(sessions);
  return { id, maxAge: SESSION_MAX_AGE };
}

export function sessionValid(id: string | undefined) {
  if (!id) return false;
  return load().some((session) => session.id === id && session.expires > Date.now());
}

export function rotateSession(id: string) {
  const sessions = load();
  const current = sessions.find((session) => session.id === id && session.expires > Date.now());
  if (!current) return null;
  const quarter = SESSION_MAX_AGE * 1000 * 0.25;
  if (current.expires - Date.now() > quarter) return null;
  const next = randomBytes(32).toString("hex");
  const kept = sessions.filter((session) => session.id !== id && session.expires > Date.now());
  kept.push({ id: next, expires: Date.now() + SESSION_MAX_AGE * 1000 });
  save(kept);
  return next;
}
