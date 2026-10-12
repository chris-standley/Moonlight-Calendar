import { useEffect, useState } from "react";
import { Layout, STYLE_LABEL } from "../api/types";
import { haLoginUrl, health, pairPoll, pairStart, setToken } from "../api/pairing";
import { Logo } from "../components/icons";


/** Shown on an unpaired LAN screen: a 6-digit code an adult approves from Settings > Screens. */
export function PairScreen({ base, layout }: { base: string; layout: Layout }) {
  const [pair, setPair] = useState<{ id: string; code: string; expires: number } | null>(null);
  const [status, setStatus] = useState<"waiting" | "offline" | "paired">("waiting");
  const [pairedAs, setPairedAs] = useState("");
  const [now, setNow] = useState(Date.now());
  const [round, setRound] = useState(0);
  const [haLogin, setHaLogin] = useState(false);

  useEffect(() => { health(base).then((h) => setHaLogin(!!h.ha_login)).catch(() => {}); }, [base]);

  // Ask for a code (again when it expires or the server was unreachable).
  useEffect(() => {
    let alive = true;
    pairStart(base, layout)
      .then((p) => { if (alive) { setPair({ id: p.pair_id, code: p.code, expires: Date.now() + p.expires_in * 1000 }); setStatus("waiting"); } })
      .catch(() => { if (alive) { setStatus("offline"); setTimeout(() => alive && setRound((r) => r + 1), 5000); } });
    return () => { alive = false; };
  }, [base, layout, round]);

  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t); }, []);

  // Poll until approved.
  useEffect(() => {
    if (!pair) return;
    let alive = true;
    const t = setInterval(async () => {
      try {
        const r = await pairPoll(base, pair.id);
        if (!alive) return;
        if (r.status === "approved") {
          clearInterval(t);
          setToken(r.token); // the response also set the HttpOnly cookie
          setPairedAs(r.display.name);
          setStatus("paired");
          setTimeout(() => location.reload(), 1200);
        } else if (r.status === "expired" || Date.now() > pair.expires) {
          clearInterval(t);
          setPair(null);
          setRound((x) => x + 1);
        } else setStatus("waiting");
      } catch { if (alive) setStatus("offline"); }
    }, 2000);
    return () => { alive = false; clearInterval(t); };
  }, [base, pair]);

  const left = pair ? Math.max(0, Math.round((pair.expires - now) / 1000)) : 0;
  const digits = (pair?.code ?? "      ").split("");
  return (
    <div className={`pair-screen layout-${layout}`}>
      <div className="pair-card">
        <div className="pair-logo"><Logo size={layout === "large" ? 64 : 44} /><span>Moonlight</span></div>
        {status === "paired" ? (
          <>
            <h1>Paired as {pairedAs}</h1>
            <p className="pair-help">Loading your family calendar…</p>
          </>
        ) : (
          <>
            <h1>Pair this screen</h1>
            <p className="pair-help">
              On a phone or a screen that already shows Moonlight, open <b>Settings → Screens → Pair a new screen</b> and
              enter this code.
            </p>
            <div className="pair-code" aria-label={`Pairing code ${pair?.code ?? ""}`}>
              {digits.map((d, i) => <span key={i} className={i === 3 ? "gap" : ""}>{d.trim()}</span>)}
            </div>
            <div className="pair-meta">
              {status === "offline" ? "Can't reach Moonlight, retrying…"
                : pair ? <>{STYLE_LABEL[layout]} screen · new code in {Math.floor(left / 60)}:{String(left % 60).padStart(2, "0")}</>
                : "Getting a code…"}
            </div>
            {haLogin && (
              <a className="btn pair-ha" href={haLoginUrl(base, layout)}>Sign in with Home Assistant</a>
            )}
          </>
        )}
      </div>
    </div>
  );
}
