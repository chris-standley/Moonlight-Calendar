import { CSSProperties, ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { Api, DEFAULT_SCREENS, Display, Person, Section, Settings, Theme } from "./api/types";
import { AppProvider, Layout, useApp, useNow } from "./state";
import { fmtFull, today } from "./dates";
import { PinPad } from "./components/ui";
import {
  IconCalendar, IconChores, IconHome, IconLists, IconMeals, IconNursery, IconRecipes, IconSettings, IconShield, IconStar, Logo, WeatherIcon,
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
import { TimerTray } from "./views/recipes/TimerTray";
import { RecipesView } from "./views/RecipesView";
import { NurseryButton, NurseryFeed, NurseryView, useNurseryFeed } from "./views/NurseryView";

import { SecurityView } from "./views/SecurityView";
import { SecurityAlerts } from "./views/SecurityAlerts";

type Tab = "today" | "calendar" | "chores" | "rewards" | "meals" | "recipes" | "lists" | "nursery" | "security" | "settings";
const NAV: { key: Tab; label: string; icon: (p: { size?: number }) => ReactNode }[] = [
  { key: "today", label: "Today", icon: IconHome },
  { key: "calendar", label: "Calendar", icon: IconCalendar },
  { key: "chores", label: "Chores", icon: IconChores },
  { key: "rewards", label: "Rewards", icon: IconStar },
  { key: "meals", label: "Meals", icon: IconMeals },
  { key: "recipes", label: "Recipes", icon: IconRecipes },
  { key: "lists", label: "Lists", icon: IconLists },
  { key: "nursery", label: "Nursery", icon: IconNursery },
  { key: "security", label: "Security", icon: IconShield },
  { key: "settings", label: "Settings", icon: IconSettings },
];
const THEME_KEY = "moonlight-theme";
/** Light or dark, from Settings > Display > Appearance; "auto" follows the device and changes with it. The last
 * choice is remembered on the device so the screen doesn't flash light while settings load. */
function useTheme(theme: Theme | undefined) {
  useEffect(() => {
    let want = theme;
    if (want) { try { localStorage.setItem(THEME_KEY, want); } catch { /* private mode */ } }
    else { try { want = (localStorage.getItem(THEME_KEY) as Theme | null) ?? "auto"; } catch { want = "auto"; } }
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const apply = () => { document.documentElement.dataset.theme = want === "auto" ? (media.matches ? "dark" : "light") : want; };
    apply();
    if (want !== "auto") return;
    media.addEventListener("change", apply);
    return () => media.removeEventListener("change", apply);
  }, [theme]);
}

const IDLE_MS = { large: 5 * 60_000, compact: 3 * 60_000, phone: 0 };

interface Burst { id: number; x: number; y: number; color: string }

/** Inside Home Assistant (ingress panel iframe): HA's own frame already keeps clear of the iPhone home indicator. */
const EMBEDDED = (() => { try { return window.self !== window.top; } catch { return true; } })();

/** `onLayout`: the paired screen was given another style in Settings > Screens (the live app re-renders in it). */
export function App({ api, layout, onLayout }: { api: Api; layout: Layout; onLayout?: (l: Layout) => void }) {
  const [tab, setTab] = useState<Tab>(DEFAULT_SCREENS[layout].start);
  const [people, setPeople] = useState<Person[]>([]);
  const [peopleLoaded, setPeopleLoaded] = useState(false);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [screen, setScreen] = useState<Display | null | undefined>(undefined);
  const [pinReq, setPinReq] = useState<{ why: string; resolve: (p: string | null) => void; error?: string; check: boolean } | null>(null);
  const [toasts, setToasts] = useState<{ id: number; msg: string }[]>([]);
  const [bursts, setBursts] = useState<Burst[]>([]);
  const [saver, setSaver] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const nursery = useNurseryFeed(api);

  useEffect(() => {
    const load = () => {
      api.people().then((p) => { setPeople(p); setPeopleLoaded(true); }).catch((e) => console.error(e));
      api.settings().then(setSettings).catch((e) => console.error(e));
    };
    const loadScreen = () => api.thisScreen().then(setScreen).catch(() => setScreen((s) => s ?? null));
    load();
    loadScreen();
    return api.subscribe((t) => {
      if (t === "people" || t === "settings") load();
      if (t === "displays" || t === "settings") loadScreen();
    });
  }, [api]);
  useEffect(() => {
    const l = screen?.layout;
    if (l && l !== "service" && l !== "app" && l !== layout) onLayout?.(l);
  }, [screen?.layout, layout, onLayout]);

  useTheme(settings?.theme);

  // Idle -> photo screensaver (minutes per screen, else per style from settings; 0 = never).
  const idleMin = screen?.setup?.idle_minutes ?? settings?.idle_minutes?.[layout];
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

  const askPin = useCallback((why: string, opts?: { check?: boolean }) =>
    new Promise<string | null>((resolve) => setPinReq({ why, resolve, check: opts?.check ?? true })), []);
  const onPin = useCallback(async (pin: string | null) => {
    if (!pinReq) return;
    if (pin === null) { pinReq.resolve(null); setPinReq(null); return; }
    if (!pinReq.check || await api.verifyPin(pin)) { pinReq.resolve(pin); setPinReq(null); }
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

  // Sections chosen for this screen, else for its style (Settings > Screens); Settings itself is always there.
  const chosen = screen?.setup ?? settings?.screens?.[layout] ?? DEFAULT_SCREENS[layout];
  // Nursery only once Tapestry is connected (Settings › Nursery).
  const setup = { ...chosen, sections: chosen.sections.filter((x) => x !== "nursery" || nursery.config?.configured) };
  const nav = NAV.filter((n) => n.key === "settings" || setup.sections.includes(n.key as Section));
  // Open on the chosen start section once settings arrive, and leave a section that was just hidden.
  const opened = useRef(false);
  useEffect(() => {
    if (!settings || screen === undefined) return;
    if (!opened.current) { opened.current = true; setTab(setup.start); return; }
    setTab((t) => (t === "settings" || setup.sections.includes(t as Section) ? t : setup.start));
  }, [settings, screen, setup.start, setup.sections]);
  // A new install has nobody yet: still show every view (they point to Settings > Family).
  const ready = peopleLoaded && settings;
  const go = useCallback((t: string) => setTab(t as Tab), []);

  // On a phone the top bar (clock, date, weather) stays put and the page slides up over it as it scrolls, giving the
  // content the whole screen. Whichever list scrolls inside the page drives it; sheets and sideways scrolling don't.
  const content = useRef<HTMLDivElement>(null);
  const [lift, setLift] = useState(0);
  useEffect(() => {
    setLift(0);
    const el = content.current;
    if (layout !== "phone" || !el) return;
    const onScroll = (e: Event) => {
      const t = e.target as HTMLElement;
      if (!(t instanceof HTMLElement) || t.closest(".scrim")) return;
      const bar = el.parentElement?.querySelector<HTMLElement>(".topbar");
      setLift(Math.min(Math.max(t.scrollTop, 0), bar?.offsetHeight ?? 0));
    };
    el.addEventListener("scroll", onScroll, { capture: true, passive: true });
    return () => el.removeEventListener("scroll", onScroll, { capture: true });
  }, [layout, tab]);

  return (
    <AppProvider value={{ api, layout, screen: screen ?? null, people, settings, personById, askPin, toast, celebrate, go }}>
      <div className={`app layout-${layout}` + (EMBEDDED ? " embedded" : "")} ref={root}>
       <MediaProvider api={api} layout={layout}>
        <nav className="rail">
          <div className="rail-logo"><Logo size={layout === "large" ? 44 : 34} /></div>
          {nav.map((n) => (
            <button key={n.key} className={"rail-item" + (tab === n.key ? " on" : "")} onClick={() => setTab(n.key)}>
              <n.icon size={layout === "large" ? 30 : layout === "phone" ? 21 : 24} />
              {n.key === "nursery" && nursery.unread > 0 && tab !== "nursery" && <i className="rail-dot" aria-label="New" />}
              <span>{n.label}</span>
            </button>
          ))}
        </nav>
        <main className="main">
          {/* A compact screen's Today has its own Now playing card; everywhere else a small pill in the top bar. */}
          <TopBar familyName={settings?.family_name ?? ""} music={!(layout === "compact" && tab === "today")}
            nursery={setup.sections.includes("nursery") ? null : nursery} />
          {ready && <SyncBanner onOpen={() => setTab("settings")} />}
          <div className={"content" + (lift > 0 ? " lifted" : "")} ref={content} style={lift ? { marginTop: -lift } : undefined}>
            {ready && <>
              {tab === "today" && <TodayView go={go} />}
              {tab === "calendar" && <CalendarView defaultView={layout === "large" ? "week" : "schedule"} />}
              {tab === "chores" && <ChoresView />}
              {tab === "rewards" && <RewardsView />}
              {tab === "meals" && <MealsView />}
              {tab === "recipes" && <RecipesView />}
              {tab === "lists" && <ListsView />}
              {tab === "nursery" && <NurseryView feed={nursery} />}
              {tab === "security" && <SecurityView />}
              {tab === "settings" && <SettingsView onScreensaver={() => setSaver(true)} />}
            </>}
          </div>
        </main>
        {pinReq && <PinPad why={pinReq.why} error={pinReq.error} onDone={onPin} />}
        <TimerTray />
        <div className="toasts">{toasts.map((t) => <div key={t.id} className="toast">{t.msg}</div>)}</div>
        {bursts.map((b) => <Confetti key={b.id} {...b} />)}
        {ready && <SecurityAlerts saver={saver}>{saver && <Screensaver onWake={() => setSaver(false)} />}</SecurityAlerts>}
       </MediaProvider>
      </div>
    </AppProvider>
  );
}

/** `nursery`: a button for the updates, on screens whose menu has no Nursery section. */
function TopBar({ familyName, music, nursery }: { familyName: string; music: boolean; nursery: NurseryFeed | null }) {
  const now = useNow(10_000);
  const [wx, setWx] = useState<{ temp: number; condition: string } | null>(null);
  const { api, settings } = useApp();
  useEffect(() => { api.weather().then((w) => setWx(w.current)); }, [api, settings?.weather_entity, settings?.temp_unit]);
  const time = now.toLocaleTimeString("en-GB", { hour: "numeric", minute: "2-digit", hour12: true }).replace(" ", "");
  return (
    <header className="topbar">
      <div className="tb-time">{time}</div>
      <div className="tb-date">{fmtFull(today())}</div>
      {wx && <div className="tb-wx"><WeatherIcon condition={wx.condition} size={34} /> {wx.temp}°</div>}
      {music && <NowPlayingPill />}
      {nursery && <NurseryButton feed={nursery} />}
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
