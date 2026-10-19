import { useCallback, useEffect, useRef, useState } from "react";
import { SecurityAlert } from "../api/types";
import { useApp } from "../state";
import { IconClose } from "../components/icons";
import { LiveCamera, sized } from "./SecurityView";

/** After the person sensor clears, the camera stays up this long (people linger at the door). */
const LINGER_MS = 15_000;

interface Shown { alert: SecurityAlert; until: number | null }

/** When a shown camera sees a person, its live picture pops up in a corner of the screen (over the screensaver
 * too), and goes away a little after the person has gone. Settings > Security turns it on or off per style. */
export function SecurityAlerts() {
  const { api, layout, settings } = useApp();
  const enabled = settings?.security?.popup?.[layout] ?? layout !== "phone";
  const [shown, setShown] = useState<Shown[]>([]);
  const [big, setBig] = useState<SecurityAlert | null>(null);
  const dismissed = useRef(new Set<string>());

  const load = useCallback(() => {
    api.securityAlerts().then((alerts) => {
      const now = Date.now();
      const here = new Set(alerts.map((a) => a.camera));
      // Closing one keeps it closed until that person has gone.
      dismissed.current.forEach((c) => { if (!here.has(c)) dismissed.current.delete(c); });
      setShown((cur) => {
        const next: Shown[] = cur.map((s) => (here.has(s.alert.camera) ? s : { ...s, until: s.until ?? now + LINGER_MS }));
        for (const a of alerts) {
          if (dismissed.current.has(a.camera)) continue;
          const i = next.findIndex((s) => s.alert.camera === a.camera);
          if (i >= 0) next[i] = { alert: a, until: null };
          else next.unshift({ alert: a, until: null });
        }
        return next;
      });
    }).catch(() => { /* offline: keep what's showing */ });
  }, [api]);

  useEffect(() => {
    if (!enabled) { setShown([]); return; }
    load();
    return api.subscribe((t) => { if (t === "security_alert") load(); });
  }, [api, enabled, load]);

  // Drop the ones whose linger time is over.
  useEffect(() => {
    const ends = shown.map((s) => s.until).filter((u): u is number => u !== null);
    if (!ends.length) return;
    const t = setTimeout(() => setShown((cur) => cur.filter((s) => s.until === null || s.until > Date.now())),
      Math.max(0, Math.min(...ends) - Date.now()) + 50);
    return () => clearTimeout(t);
  }, [shown]);

  const close = (camera: string) => {
    dismissed.current.add(camera);
    setShown((cur) => cur.filter((s) => s.alert.camera !== camera));
  };

  if (!enabled) return null;
  const width = layout === "large" ? 800 : 640;
  return (
    <>
      {shown.length > 0 && (
        <div className="sec-pop-stack">
          {shown.slice(0, 2).map(({ alert, until }) => (
            <div key={alert.camera} className={"sec-pop" + (until ? " leaving" : "")}>
              <button className="sec-pop-pic" onClick={() => setBig(alert)} aria-label={`Show ${alert.name} full size`}>
                <img src={sized(alert.live_url, width)} alt="" />
              </button>
              <div className="sec-pop-bar">
                <span className="sec-live-dot" />
                <b>{alert.test ? `Test: ${alert.name}` : `Someone at ${alert.name}`}</b>
                <button className="icon-btn" onClick={() => close(alert.camera)} aria-label="Close"><IconClose size={20} /></button>
              </div>
            </div>
          ))}
        </div>
      )}
      {big && <LiveCamera name={big.name} url={big.live_url} onClose={() => setBig(null)} />}
    </>
  );
}
