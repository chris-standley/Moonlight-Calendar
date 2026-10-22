import { StrictMode, useEffect, useLayoutEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import fontUrl from "@fontsource-variable/nunito/files/nunito-latin-wght-normal.woff2?url";
import { App } from "./App";
import { httpApi } from "./api/http";
import { demoApi } from "./api/demo";
import { adoptTokenFromUrl, authStatus, UNPAIRED_EVENT } from "./api/pairing";
import { PairScreen } from "./views/PairScreen";
import { Layout } from "./state";
import "./styles.css";

const font = document.createElement("style");
font.textContent = `@font-face{font-family:"Nunito";font-style:normal;font-display:swap;font-weight:200 1000;src:url(${fontUrl}) format("woff2");}`;
document.head.appendChild(font);

/** CSS viewport and root font size per screen style. A compact 10.1in panel (1920x1200) runs at 2x zoom. */
export const SCREENS: Record<Layout, { w: number; h: number; font: number; label: string; detail: string }> = {
  large: { w: 2560, h: 1440, font: 20, label: "Large 27in", detail: "iiyama 2560×1440" },
  compact: { w: 960, h: 600, font: 15, label: "Compact 10.1in", detail: "Touch Display 2, 1920×1200 at 2× zoom" },
  phone: { w: 390, h: 844, font: 15, label: "iPhone", detail: "HA Companion panel" },
};

function setRootFont(layout: Layout) {
  document.documentElement.style.fontSize = `${SCREENS[layout].font}px`;
}

const STYLE = /(large|compact|phone|hallway|kitchen)/;
const OLD: Record<string, Layout> = { hallway: "large", kitchen: "compact" };
const asLayout = (s: string) => OLD[s] ?? (s as Layout);

/** The style to use before the server says what this screen is: an old /display/<style> address, else the window size. */
export function guessLayout(): Layout {
  const m = location.pathname.match(/\/display\/(\w+)/)?.[1].match(STYLE) ?? location.hash.match(STYLE);
  if (m) return asLayout(m[1]);
  // The short side, so a compact screen stood upright isn't taken for a phone.
  const short = Math.min(window.innerWidth, window.innerHeight);
  return window.innerWidth >= 1800 ? "large" : short >= 560 ? "compact" : "phone";
}

/** Live: served by the add-on (also under HA ingress, so API calls stay relative to the app's base path). */
function Live() {
  const base = useMemo(() => { adoptTokenFromUrl(); return location.pathname.replace(/\/display(\/\w+)?\/?$/, "").replace(/\/$/, ""); }, []);
  const api = useMemo(() => httpApi(base), [base]);
  const [layout, setLayout] = useState(guessLayout);
  // LAN screens must be paired (HA ingress and auth-off installs are let straight in): see API.md "Screens".
  // Every screen opens the same address; a paired screen's style comes from Settings > Screens.
  const [access, setAccess] = useState<"checking" | "ok" | "pair">("checking");
  useEffect(() => {
    authStatus(base).then((s) => {
      const l = s.display?.layout;
      if (l && l !== "service" && l !== "app") setLayout(l);
      setAccess(s.authorised ? "ok" : "pair");
    }).catch(() => setAccess("ok"));
    const onUnpaired = () => setAccess("pair");
    window.addEventListener(UNPAIRED_EVENT, onUnpaired);
    return () => window.removeEventListener(UNPAIRED_EVENT, onUnpaired);
  }, [base]);
  useLayoutEffect(() => setRootFont(layout), [layout]);
  if (access === "checking") return <div className="live-root" />;
  if (access === "pair") return <div className="live-root"><PairScreen base={base} layout={layout} /></div>;
  return <div className="live-root"><App key={layout} api={api} layout={layout} onLayout={setLayout} /></div>;
}

/** Preview frames: each screen style, plus the compact screen stood upright (the Touch Display 2 is portrait natively). */
const FRAMES = [
  { key: "large", layout: "large" as Layout, ...SCREENS.large },
  { key: "compact", layout: "compact" as Layout, ...SCREENS.compact },
  { key: "compact-portrait", layout: "compact" as Layout, ...SCREENS.compact, w: SCREENS.compact.h, h: SCREENS.compact.w,
    label: "Compact portrait", detail: "Touch Display 2 upright, 1200×1920 at 2× zoom" },
  { key: "phone", layout: "phone" as Layout, ...SCREENS.phone },
];

/** Published preview: in-browser demo data, with a switcher that renders each screen at its real size, scaled to fit. */
function Preview() {
  const api = useMemo(() => demoApi(), []);
  const [key, setKey] = useState(() => {
    const h = location.hash.slice(1);
    if (FRAMES.some((f) => f.key === h)) return h;
    const m = h.match(STYLE);
    return m ? asLayout(m[1]) : "large";
  });
  const f = FRAMES.find((x) => x.key === key) ?? FRAMES[0];
  const layout = f.layout;
  const [box, setBox] = useState({ w: window.innerWidth, h: window.innerHeight });
  useEffect(() => {
    const r = () => setBox({ w: window.innerWidth, h: window.innerHeight });
    window.addEventListener("resize", r);
    return () => window.removeEventListener("resize", r);
  }, []);
  useLayoutEffect(() => setRootFont(layout), [layout]);
  const bar = 56, pad = 16;
  const scale = Math.min((box.w - pad * 2) / f.w, (box.h - bar - pad * 2) / f.h, layout === "large" ? 1 : 2);
  return (
    <div className="preview">
      <div className="pv-bar">
        <span className="pv-name">Moonlight preview</span>
        <div className="pv-tabs">
          {FRAMES.map((x) => (
            <button key={x.key} className={x.key === key ? "on" : ""} onClick={() => { setKey(x.key); try { history.replaceState(null, "", "#" + x.key); } catch { /* sandboxed */ } }}>
              {x.label}
            </button>
          ))}
        </div>
        <span className="pv-detail">{f.detail} · shown at {Math.round(scale * 100)}% · demo PIN 1234</span>
      </div>
      <div className="pv-stage">
        <div style={{ width: f.w * scale, height: f.h * scale }}>
          <div className="pv-frame" style={{ width: f.w, height: f.h, transform: `scale(${scale})` }}>
            <App key={layout} api={api} layout={layout} />
          </div>
        </div>
      </div>
    </div>
  );
}

const demo = import.meta.env.MODE === "demo" || new URLSearchParams(location.search).has("demo");
createRoot(document.getElementById("root")!).render(<StrictMode>{demo ? <Preview /> : <Live />}</StrictMode>);
