import { useState } from "react";
import { useData } from "../state";
import { IconAlert } from "./CalendarsSettings";
import { IconClose } from "../components/icons";

const KEY = "moonlight-sync-banner";
const SNOOZE_MS = 6 * 3600_000;

function readSnooze(): { key: string; until: number } | null {
  try { return JSON.parse(localStorage.getItem(KEY) ?? "null"); } catch { return null; }
}

/** Shown on every screen while an account's sign-in is failing. Dismissing snoozes it for a few hours. */
export function SyncBanner({ onOpen }: { onOpen: () => void }) {
  const [accounts] = useData((a) => a.accounts(), ["accounts"], []);
  const [snooze, setSnooze] = useState(readSnooze);
  const failed = (accounts ?? []).filter((a) => a.status === "auth_failed");
  const key = failed.map((a) => a.id).sort().join(",");
  if (!failed.length || (snooze && snooze.key === key && snooze.until > Date.now())) return null;
  function dismiss() {
    const s = { key, until: Date.now() + SNOOZE_MS };
    setSnooze(s);
    try { localStorage.setItem(KEY, JSON.stringify(s)); } catch { /* storage blocked */ }
  }
  const who = failed.map((a) => a.label).join(", ");
  return (
    <div className="sync-banner" role="alert">
      <IconAlert size={24} />
      <div className="sb-text">
        <b>{failed.some((a) => a.kind === "icloud") ? "iCloud needs reconnecting" : "Calendar needs reconnecting"}</b>
        <span>Sign-in for {who} stopped working, so calendar changes aren't syncing.</span>
      </div>
      <button className="btn small" onClick={onOpen}>Reconnect</button>
      <button className="icon-btn subtle" onClick={dismiss} aria-label="Dismiss for now"><IconClose size={20} /></button>
    </div>
  );
}
