import { useEffect, useState } from "react";
import { useApp } from "../state";
import { IconAlert } from "./CalendarsSettings";

const GRACE_MS = 10_000; // a short blip (Moonlight restarting, Wi-Fi waking) fixes itself before anyone notices
const RELOAD_AFTER_MS = 120_000;

/** Shown over everything while this screen has lost its live link to Moonlight, with a button to try again now. */
export function ConnectionBanner() {
  const { api } = useApp();
  const [downSince, setDownSince] = useState<number | null>(null);
  const [showing, setShowing] = useState(false);
  const [trying, setTrying] = useState(false);

  useEffect(() => api.connection?.((up) => setDownSince(up ? null : Date.now())), [api]);
  useEffect(() => {
    setShowing(false);
    setTrying(false);
    if (downSince === null) return;
    const t = setTimeout(() => setShowing(true), GRACE_MS);
    return () => clearTimeout(t);
  }, [downSince]);

  if (!showing || downSince === null) return null;

  async function retry() {
    setTrying(true);
    // Down a long while: if the page itself loads, start the screen afresh in case something on it got stuck.
    if (Date.now() - downSince! > RELOAD_AFTER_MS) {
      try {
        const res = await fetch(location.href, { cache: "no-store" });
        if (res.ok) { location.reload(); return; }
      } catch { /* still unreachable */ }
    }
    api.reconnect?.();
    setTimeout(() => setTrying(false), 4000);
  }

  return (
    <div className="sync-banner conn-banner" role="alert">
      <IconAlert size={24} />
      <div className="sb-text">
        <b>Lost connection to Moonlight</b>
        <span>{trying ? "Trying again…" : "This screen will reconnect by itself when it can."}</span>
      </div>
      <button className="btn small" onClick={retry} disabled={trying}>Retry</button>
    </div>
  );
}
