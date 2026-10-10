import { CSSProperties, ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { Api, Person, Settings } from "./api/types";
import { AppProvider, Layout, useApp, useNow } from "./state";
import { fmtFull, today } from "./dates";
import { PinPad } from "./components/ui";
import {
  IconCalendar, IconChores, IconHome, IconLists, IconMeals, IconSettings, IconStar, Logo, WeatherIcon,
} from "./components/icons";
import { CalendarView } from "./views/CalendarView";
import { ChoresView } from "./views/ChoresView";
import { RewardsView } from "./views/RewardsView";
import { MealsView } from "./views/MealsView";
import { ListsView } from "./views/ListsView";
import { TodayView } from "./views/TodayView";
import { Screensaver } from "./views/Screensaver";
import { SettingsView } from "./views/SettingsView";
import { SyncBanner } from "./views/SyncBanner";
import { MediaProvider, NowPlayingPill } from "./views/NowPlaying";

type Tab = "today" | "calendar" | "chores" | "rewards" | "meals" | "lists" | "settings";
const NAV: { key: Tab; label: string; icon: (p: { size?: number }) => ReactNode }[] = [
  { key: "today", label: "Today", icon: IconHome },
  { key: "calendar", label: "Calendar", icon: IconCalendar },
  { key: "chores", label: "Chores", icon: IconChores },
  { key: "rewards", label: "Rewards", icon: IconStar },
  { key: "meals", label: "Meals", icon: IconMeals },
  { key: "lists", label: "Lists", icon: IconLists },
  { key: "settings", label: "Settings", icon: IconSettings },
];
const IDLE_MS = { hallway: 5 * 60_000, kitchen: 3 * 60_000, phone: 0 };

interface Burst { id: number; x: number; y: number; color: string }

export function App({ api, layout }: { api: Api; layout: Layout }) {
  const [tab, setTab] = useState<Tab>(layout === "hallway" ? "calendar" : "today");
  const [people, setPeople] = useState<Person[]>([]);
  const [peopleLoaded, setPeopleLoaded] = useState(false);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [pinReq, setPinReq] = useState<{ why: string; resolve: (p: string | null) => void; error?: string } | null>(null);
  const [toasts, setToasts] = useState<{ id: number; msg: string }[]>([]);
  const [bursts, setBursts] = useState<Burst[]>([]);
  const [saver, setSaver] = useState(false);
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const load = () => {
      api.people().then((p) => { setPeople(p); setPeopleLoaded(true); }).catch((e) => console.error(e));
      api.settings().then(setSettings).catch((e) => console.error(e));
    };
    load();
    return api.subscribe((t) => { if (t === "people" || t === "settings") load(); });
  }, [api]);

  // Idle -> photo screensaver (minutes per screen from settings, 0 = never).
  const idleMin = settings?.idle_minutes?.[layout];
  useEffect(() => {
    const ms = idleMin !== undefined ? idleMin * 60_000 : IDLE_MS[layout];
    if (!ms) return;
    const start = () => setSaver(true);
    let t = setTimeout(start, ms);
    const reset = () => { clearTimeout(t); t = setTimeout(start, ms); };
    const el = root.current!;
    el.addEventListener("pointerdown", reset);
    return () => { clearTimeout(t); el.removeEventListener("pointerdown", reset); };
  }, [layout, idleMin]);

  const askPin = useCallback((why: string) => new Promise<string | null>((resolve) => setPinReq({ why, resolve })), []);
  const onPin = useCallback(async (pin: string | null) => {
    if (!pinReq) return;
    if (pin === null) { pinReq.resolve(null); setPinReq(null); return; }
    if (await api.verifyPin(pin)) { pinReq.resolve(pin); setPinReq(null); }
    else setPinReq({ ...pinReq, error: "Wrong PIN, try again" });
  }, [api, pinReq]);
  const toast = useCallback((msg: string) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, msg }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 2600);
  }, []);
  const celebrate = useCallback((cx: number, cy: number, color: string) => {
    const el = root.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const scale = r.width / el.offsetWidth || 1; // the preview shell scales the app
    const id = Date.now() + Math.random();
    setBursts((b) => [...b, { id, x: (cx - r.left) / scale, y: (cy - r.top) / scale, color }]);
    setTimeout(() => setBursts((b) => b.filter((x) => x.id !== id)), 1200);
  }, []);
  const personById = useCallback((id: string | null | undefined) => people.find((p) => p.id === id), [people]);

  const nav = layout === "hallway" ? NAV.filter((n) => n.key !== "today") : NAV;
  // A new install has nobody yet: still show every view (they point to Settings > Family).
  const ready = peopleLoaded && settings;
  const go = useCallback((t: string) => setTab(t as Tab), []);

  return (
    <AppProvider value={{ api, layout, people, settings, personById, askPin, toast, celebrate, go }}>
      <div className={`app layout-${layout}`} ref={root}>
       <MediaProvider api={api} layout={layout}>
        <nav className="rail">
          <div className="rail-logo"><Logo size={layout === "hallway" ? 44 : 34} /></div>
          {nav.map((n) => (
            <button key={n.key} className={"rail-item" + (tab === n.key ? " on" : "")} onClick={() => setTab(n.key)}>
              <n.icon size={layout === "hallway" ? 30 : 24} />
              <span>{n.label}</span>
            </button>
          ))}
        </nav>
        <main className="main">
          {/* The kitchen's Today has its own Now playing card; everywhere else a small pill in the top bar. */}
          <TopBar familyName={settings?.family_name ?? ""} music={!(layout === "kitchen" && tab === "today")} />
          {ready && <SyncBanner onOpen={() => setTab("settings")} />}
          <div className="content">
            {ready && <>
              {tab === "today" && <TodayView go={go} />}
              {tab === "calendar" && <CalendarView defaultView={layout === "hallway" ? "week" : "schedule"} />}
              {tab === "chores" && <ChoresView />}
              {tab === "rewards" && <RewardsView />}
              {tab === "meals" && <MealsView />}
              {tab === "lists" && <ListsView />}
              {tab === "settings" && <SettingsView onScreensaver={() => setSaver(true)} />}
            </>}
          </div>
        </main>
        {pinReq && <PinPad why={pinReq.why} error={pinReq.error} onDone={onPin} />}
        <div className="toasts">{toasts.map((t) => <div key={t.id} className="toast">{t.msg}</div>)}</div>
        {bursts.map((b) => <Confetti key={b.id} {...b} />)}
        {saver && ready && <Screensaver onWake={() => setSaver(false)} />}
       </MediaProvider>
      </div>
    </AppProvider>
  );
}

function TopBar({ familyName, music }: { familyName: string; music: boolean }) {
  const now = useNow(10_000);
  const [wx, setWx] = useState<{ temp: number; condition: string } | null>(null);
  const { api } = useApp();
  useEffect(() => { api.weather().then((w) => setWx(w.current)); }, [api]);
  const time = now.toLocaleTimeString("en-GB", { hour: "numeric", minute: "2-digit", hour12: true }).replace(" ", "");
  return (
    <header className="topbar">
      <div className="tb-time">{time}</div>
      <div className="tb-date">{fmtFull(today())}</div>
      {wx && <div className="tb-wx"><WeatherIcon condition={wx.condition} size={34} /> {wx.temp}°</div>}
      {music && <NowPlayingPill />}
      <div className="tb-family">{familyName}</div>
    </header>
  );
}
const CONF_COLORS = ["#FFB938", "#4F7CEC", "#F0679A", "#2FB58A", "#9B6BE0"];
function Confetti({ x, y, color }: Burst) {
  const bits = Array.from({ length: 18 }, (_, i) => {
    const a = (i / 18) * Math.PI * 2 + Math.random() * 0.3;
    const d = 60 + Math.random() * 70;
    return { dx: Math.cos(a) * d, dy: Math.sin(a) * d - 30, c: i % 3 === 0 ? color : CONF_COLORS[i % CONF_COLORS.length], r: Math.random() * 360 };
  });
  return (
    <div className="confetti" style={{ left: x, top: y }}>
      {bits.map((b, i) => <i key={i} style={{ "--dx": `${b.dx}px`, "--dy": `${b.dy}px`, "--r": `${b.r}deg`, background: b.c } as CSSProperties} />)}
    </div>
  );
}
