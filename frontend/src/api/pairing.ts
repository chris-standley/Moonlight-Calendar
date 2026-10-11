// Wall-screen pairing (see API.md "Screens"). A paired screen keeps its display token in localStorage and in
// an HttpOnly cookie set by the server; the cookie is what makes <img src> photo URLs work.
import { Display, Layout } from "./types";

const TOKEN_KEY = "moonlight-display-token";
export const UNPAIRED_EVENT = "moonlight:unpaired";

export function getToken(): string | null {
  try { return localStorage.getItem(TOKEN_KEY); } catch { return null; }
}
export function setToken(token: string | null) {
  try { if (token) localStorage.setItem(TOKEN_KEY, token); else localStorage.removeItem(TOKEN_KEY); } catch { /* private mode */ }
}
/** Any 401 from the API means this screen is (no longer) paired: the app swaps to the pairing screen. */
export function notifyUnpaired() {
  setToken(null);
  window.dispatchEvent(new Event(UNPAIRED_EVENT));
}

/** TouchKio setups can open `/display?token=...` once: keep the token, then strip it from the URL. */
export function adoptTokenFromUrl() {
  const url = new URL(location.href);
  const t = url.searchParams.get("token");
  if (!t) return;
  setToken(t);
  url.searchParams.delete("token");
  try { history.replaceState(null, "", url.pathname + url.search + url.hash); } catch { /* ignore */ }
}

export interface AuthStatus { required: boolean; authorised: boolean; via: "ingress" | "display" | "open" | null; display: Display | null }
export type PairPoll = { status: "pending"; expires_in: number } | { status: "expired" } | { status: "approved"; token: string; display: Display };

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error((await res.json().catch(() => null))?.detail ?? res.statusText);
  return res.json() as Promise<T>;
}
const authHeaders = (): HeadersInit => { const t = getToken(); return t ? { Authorization: `Bearer ${t}` } : {}; };

export const authStatus = (base: string) => fetch(base + "/api/auth/status", { headers: authHeaders() }).then((r) => json<AuthStatus>(r));
export const pairStart = (base: string, layout: Layout) =>
  fetch(base + "/api/pair/start", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ layout }) })
    .then((r) => json<{ pair_id: string; code: string; layout: Layout; expires_in: number }>(r));
export const pairPoll = (base: string, pairId: string) => fetch(base + `/api/pair/${encodeURIComponent(pairId)}`).then((r) => json<PairPoll>(r));
