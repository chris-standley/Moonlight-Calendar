import { CSSProperties, useEffect, useMemo, useRef, useState } from "react";
import { EventIn, Meal, Occurrence, Person, Weather } from "../api/types";
import {
  addDays, addMonths, dayNum, diffDays, fmtDayMonth, fmtDow, fmtMonthYear, fmtTime, iso, minutesOf, monthStart, parse,
  relativeDay, today, weekStart,
} from "../dates";
import { useApp, useData, useNow } from "../state";
import { Avatar, Segmented, tint } from "../components/ui";
import { IconLeft, IconPin, IconPlus, IconRepeat, IconRight, WeatherIcon } from "../components/icons";
import { EventDetail, EventForm, newEventDefaults } from "./EventSheets";

export type CalView = "day" | "week" | "month" | "schedule";

/** Days (YYYY-MM-DD) an occurrence covers. */
function daysOf(o: Occurrence): string[] {
  const s = o.start.slice(0, 10);
  let last = o.end.slice(0, 10);
  if (o.all_day || o.end.slice(11) === "00:00") last = addDays(last, -1);
  if (last < s) last = s;
  const out = [];
  for (let d = s; d <= last; d = addDays(d, 1)) out.push(d);
  return out;
}

function eventStyle(o: Occurrence, people: Person[]): CSSProperties {
  const colors = o.person_ids.map((id) => people.find((p) => p.id === id)?.color).filter(Boolean) as string[];
  // Busy blocks take the calendar's colour (its swatch in Settings), falling back to the person's.
  const c = (o.busy ? o.color : null) ?? colors[0] ?? o.color ?? "#8A94A6";
  const stripe = colors.length > 1 && !o.busy
    ? `linear-gradient(${colors.map((col, i) => `${col} ${(i * 100) / colors.length}% ${((i + 1) * 100) / colors.length}%`).join(",")})`
    : c;
  const style = { "--ec": c, "--ebg": tint(c, 0.16), "--stripe": stripe } as Record<string, string>;
  if (o.busy) {
    style["--ebg"] = tint(c, 0.07);
    style["--hatch"] = tint(c, o.busy === "tentative" ? 0.1 : 0.18);
  }
  return style as CSSProperties;
}

const BUSY_LABEL: Record<string, string> = { busy: "busy", tentative: "tentative", away: "away", elsewhere: "working elsewhere", free: "free" };

/** Title to show: free/busy blocks read "Chris – busy" (the feed's own "Busy" says nothing useful). */
export function evTitle(o: Occurrence, people: Person[]): string {
  if (!o.busy) return o.title;
  const names = o.person_ids.map((id) => people.find((p) => p.id === id)?.name).filter(Boolean);
  const label = BUSY_LABEL[o.busy] ?? "busy";
  return names.length ? `${names.join(" & ")} – ${label}` : label[0].toUpperCase() + label.slice(1);
}

/** Extra class names for busy blocks: hatched; tentative ones lighter. */
export const busyCls = (o: Occurrence) => (o.busy ? ` busy b-${o.busy}` : "");

/** Timed free/busy blocks from a work calendar: shown as a thin side bar (Day) or one summary line (Week, Schedule). */
const isBusyBlock = (o: Occurrence) => !!o.busy && !o.all_day && o.busy !== "free";

interface BusyRun { start: number; end: number; tentative: boolean; occs: Occurrence[] }

/** Merge one day's busy blocks into runs (minutes from midnight). Overlapping blocks show once; busy wins over tentative. */
function busyRuns(evs: Occurrence[], date: string): BusyRun[] {
  const segs = evs.filter(isBusyBlock).map((o) => ({
    o, s: o.start.slice(0, 10) < date ? 0 : minutesOf(o.start),
    e: o.end.slice(0, 10) > date ? 24 * 60 : minutesOf(o.end), t: o.busy === "tentative",
  })).filter((g) => g.e > g.s);
  const cuts = [...new Set(segs.flatMap((g) => [g.s, g.e]))].sort((a, b) => a - b);
  const runs: BusyRun[] = [];
  for (let i = 0; i + 1 < cuts.length; i++) {
    const [a, b] = [cuts[i], cuts[i + 1]];
    const on = segs.filter((g) => g.s < b && g.e > a);
    if (!on.length) continue;
    const tentative = on.every((g) => g.t);
    const last = runs[runs.length - 1];
    if (last && last.end === a && last.tentative === tentative) {
      last.end = b;
      on.forEach((g) => { if (!last.occs.includes(g.o)) last.occs.push(g.o); });
    } else runs.push({ start: a, end: b, tentative, occs: on.map((g) => g.o) });
  }
  return runs;
}

const fmtMin = (m: number) => fmtTime(`2000-01-01T${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`);
const fmtSpan = (a: number, b: number) => `${fmtMin(a)}–${fmtMin(b)}`;

interface BusyDay { key: string; occs: Occurrence[]; runs: BusyRun[]; start: number; end: number; gaps: [number, number][] }

/** One summary per set of people: first start, last end and the free gaps (15 minutes or more) between. */
function busyDays(evs: Occurrence[], date: string): BusyDay[] {
  const groups = new Map<string, Occurrence[]>();
  for (const o of evs.filter(isBusyBlock)) {
    const k = [...o.person_ids].sort().join(",");
    groups.set(k, [...(groups.get(k) ?? []), o]);
  }
  return [...groups].flatMap(([key, occs]) => {
    const runs = busyRuns(occs, date);
    if (!runs.length) return [];
    const gaps: [number, number][] = [];
    for (let i = 1; i < runs.length; i++) if (runs[i].start - runs[i - 1].end >= 15) gaps.push([runs[i - 1].end, runs[i].start]);
    return [{ key, occs, runs, start: runs[0].start, end: runs[runs.length - 1].end, gaps }];
  }).sort((a, b) => a.start - b.start);
}

function busyWho(b: BusyDay, people: Person[]): string {
  const names = b.occs[0].person_ids.map((id) => people.find((p) => p.id === id)?.name).filter(Boolean);
  return names.length ? `${names.join(" & ")} busy` : "Busy";
}

/** The day's busy time as one line: "Chris busy 9am – 5:30pm", then the gaps and anything tentative. */
function BusyLine({ b, people, onClick, variant }: { b: BusyDay; people: Person[]; onClick?: () => void; variant: "card" | "sched" }) {
  const tent = b.runs.filter((r) => r.tentative);
  const allTent = tent.length === b.runs.length;
  const free = b.gaps.length ? `Free ${b.gaps.map(([x, y]) => fmtSpan(x, y)).join(", ")}` : "No gaps";
  const maybe = tent.length && !allTent ? `Tentative ${tent.map((r) => fmtSpan(r.start, r.end)).join(", ")}` : "";
  const style = eventStyle(b.occs[0], people);
  const title = busyWho(b, people) + (allTent ? " (tentative)" : "");
  const Tag = onClick ? "button" : "div";
  if (variant === "card") return (
    <Tag className={"ev card busy-day" + (allTent ? " b-tentative" : "")} style={style} onClick={onClick}>
      <span className="ev-time">{fmtMin(b.start)} – {fmtMin(b.end)}</span>
      <span className="ev-title">{title}</span>
      <span className="bd-meta">{free}</span>
      {maybe && <span className="bd-meta">{maybe}</span>}
    </Tag>
  );
  return (
    <Tag className={"sched-ev busy-day" + (allTent ? " b-tentative" : "")} style={style} onClick={onClick}>
      <span className="se-time">{fmtMin(b.start)}<em>{fmtMin(b.end)}</em></span>
      <span className="se-bar" />
      <span className="se-main">
        <span className="ev-title">{title}</span>
        <span className="se-meta">{free}</span>
        {maybe && <span className="se-meta">{maybe}</span>}
      </span>
      <span className="se-who" />
    </Tag>
  );
}

function Who({ o, people, size = 1.25 }: { o: Occurrence; people: Person[]; size?: number }) {
  if (o.person_ids.length < 2) return null;
  return (
    <span className="who">
      {o.person_ids.map((id) => { const p = people.find((x) => x.id === id); return p ? <Avatar key={id} person={p} size={size} /> : null; })}
    </span>
  );
}

export function CalendarView({ defaultView }: { defaultView: CalView }) {
  const { people, settings, layout, go } = useApp();
  const ws = settings?.week_start ?? "monday";
  const [view, setView] = useState<CalView>(defaultView);
  const [anchor, setAnchor] = useState(today());
  const [hidden, setHidden] = useState<string[]>([]);
  const [open, setOpen] = useState<Occurrence | null>(null);
  const [form, setForm] = useState<{ initial: EventIn; id?: string } | null>(null);

  const [start, end] = useMemo(() => {
    if (view === "day") return [anchor, addDays(anchor, 1)];
    if (view === "week") { const s = weekStart(anchor, ws); return [s, addDays(s, 7)]; }
    if (view === "month") { const s = weekStart(monthStart(anchor), ws); return [s, addDays(s, 42)]; }
    return [anchor, addDays(anchor, 14)];
  }, [view, anchor, ws]);

  const [events] = useData((api) => api.events(start, end), ["events"], [start, end]);
  const [meals] = useData((api) => api.meals(start, end), ["meals"], [start, end]);
  const [weather] = useData((api) => api.weather(), ["settings"], []);
  const visible = useMemo(
    () => (events ?? []).filter((e) => e.person_ids.length === 0 || e.person_ids.some((id) => !hidden.includes(id))),
    [events, hidden],
  );

  const step = (dir: number) => {
    if (view === "day") setAnchor(addDays(anchor, dir));
    else if (view === "week") setAnchor(addDays(anchor, 7 * dir));
    else if (view === "month") setAnchor(addMonths(anchor, dir));
    else setAnchor(addDays(anchor, 14 * dir));
  };
  const title = view === "day" ? `${relativeDay(anchor)}, ${fmtDayMonth(anchor)}`
    : view === "month" ? fmtMonthYear(anchor)
    : view === "week" ? `${fmtDayMonth(start)} – ${fmtDayMonth(addDays(end, -1))}`
    : `From ${relativeDay(anchor).toLowerCase() === "today" ? "today" : fmtDayMonth(anchor)}`;

  const showDay = (d: string) => { setAnchor(d); setView("day"); };
  const shownPeople = people.filter((p) => !hidden.includes(p.id));
  const add = (date = view === "day" ? anchor : today(), hour = 9, pid?: string) =>
    setForm({ initial: newEventDefaults(date, pid ? [pid] : [], hour) });

  return (
    <div className="cal">
      <div className="toolbar">
        <div className="toolbar-l">
          <button className="btn ghost" onClick={() => setAnchor(today())}>Today</button>
          <button className="icon-btn" onClick={() => step(-1)} aria-label="Previous"><IconLeft /></button>
          <button className="icon-btn" onClick={() => step(1)} aria-label="Next"><IconRight /></button>
          <h1 className="toolbar-title">{title}</h1>
        </div>
        <div className="toolbar-r">
          {people.length === 0 && <button className="btn ghost small cal-family-cta" onClick={() => go("settings")}>Add your family</button>}
          <div className="filters">
            {people.map((p) => (
              <Avatar key={p.id} person={p} size={layout === "large" ? 2.3 : 2} dim={hidden.includes(p.id)} ring={!hidden.includes(p.id)}
                onClick={() => setHidden((h) => (h.includes(p.id) ? h.filter((x) => x !== p.id) : [...h, p.id]))} />
            ))}
          </div>
          <Segmented value={view} onChange={setView} options={[
            { value: "day", label: "Day" }, { value: "week", label: "Week" },
            { value: "month", label: "Month" }, { value: "schedule", label: "Schedule" },
          ]} />
        </div>
      </div>

      <div className="cal-body">
        {view === "week" && <WeekView start={start} events={visible} meals={meals ?? []} weather={weather} people={people} onOpen={setOpen} onAdd={(d) => add(d)} onDay={showDay} />}
        {view === "day" && <DayView date={anchor} events={visible} people={shownPeople} allPeople={people} weather={weather} onOpen={setOpen} onAdd={add} />}
        {view === "month" && <MonthView anchor={anchor} start={start} events={visible} people={people}
          onPick={showDay} />}
        {view === "schedule" && <ScheduleView start={start} days={14} events={visible} meals={meals ?? []} weather={weather} people={people} onOpen={setOpen} onDay={showDay} />}
      </div>

      <button className="fab" onClick={() => add()} aria-label="Add event"><IconPlus size={30} /></button>
      {open && <EventDetail occ={open} onClose={() => setOpen(null)} onEdit={() => {
        const ev = open;
        setOpen(null);
        // Edit the series: use the original first occurrence's date unless it's a one-off.
        setForm({ id: ev.id, initial: { ...ev } });
      }} />}
      {form && <EventForm initial={form.initial} id={form.id} onClose={() => setForm(null)} />}
    </div>
  );
}

function DayHeader({ date, weather, compact }: { date: string; weather?: Weather; compact?: boolean }) {
  const w = weather?.daily.find((d) => d.date === date);
  const isToday = date === today();
  return (
    <div className={"day-head" + (isToday ? " today" : "")}>
      <span className="dh-dow">{fmtDow(date)}</span>
      <span className="dh-num">{dayNum(date)}</span>
      {w && !compact && <span className="dh-wx"><WeatherIcon condition={w.condition} size={22} /> {w.high}°<em>{w.low}°</em></span>}
    </div>
  );
}

function WeekView({ start, events, meals, weather, people, onOpen, onAdd, onDay }: {
  start: string; events: Occurrence[]; meals: Meal[]; weather?: Weather; people: Person[];
  onOpen: (o: Occurrence) => void; onAdd: (d: string) => void; onDay?: (d: string) => void;
}) {
  const days = Array.from({ length: 7 }, (_, i) => addDays(start, i));
  const now = useNow();
  const nowStr = `${iso(now)}T${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`;
  return (
    <div className="week">
      {days.map((d) => {
        const dayEvents = events.filter((e) => daysOf(e).includes(d));
        const allDay = dayEvents.filter((e) => e.all_day);
        const timed = dayEvents.filter((e) => !e.all_day && !isBusyBlock(e));
        const busy = busyDays(dayEvents, d);
        const startOf = (o: Occurrence) => (o.start.slice(0, 10) < d ? 0 : minutesOf(o.start));
        const items = [
          ...timed.map((o) => ({ at: startOf(o), o })),
          ...busy.map((b) => ({ at: b.start, b })),
        ].sort((x, y) => x.at - y.at);
        const dinner = meals.find((m) => m.date === d && m.slot === "dinner");
        const past = d < today();
        return (
          <div key={d} className={"week-col" + (d === today() ? " today" : "") + (past ? " past" : "")}>
            <DayHeader date={d} weather={weather} />
            <div className="week-events" onClick={(e) => { if (e.target === e.currentTarget) onAdd(d); }}>
              {allDay.map((o) => (
                <button key={o.occurrence_id} className={"ev allday" + busyCls(o)} style={eventStyle(o, people)} onClick={() => onOpen(o)}>
                  <span className="ev-title">{evTitle(o, people)}</span><Who o={o} people={people} size={1.1} />
                </button>
              ))}
              {items.map((it) => "b" in it && it.b ? (
                <BusyLine key={"busy" + it.b.key} b={it.b} people={people} variant="card" onClick={onDay && (() => onDay(d))} />
              ) : "o" in it && it.o ? (
                <button key={it.o.occurrence_id} className={"ev card" + (it.o.end < nowStr ? " done" : "") + busyCls(it.o)} style={eventStyle(it.o, people)} onClick={() => onOpen(it.o)}>
                  <span className="ev-time">{fmtTime(it.o.start)}{it.o.start.slice(0, 10) === d ? ` – ${fmtTime(it.o.end)}` : ""}</span>
                  <span className="ev-title">{evTitle(it.o, people)}</span>
                  <Who o={it.o} people={people} />
                </button>
              ) : null)}
            </div>
            {dinner && <div className="week-meal"><span>🍽️</span>{dinner.title}</div>}
          </div>
        );
      })}
    </div>
  );
}

interface Placed { o: Occurrence; top: number; height: number; lane: number; lanes: number }
function placeLanes(evs: Occurrence[], startMin: number, date: string): Placed[] {
  const sorted = [...evs].sort((a, b) => a.start.localeCompare(b.start) || b.end.localeCompare(a.end));
  const out: Placed[] = [];
  let cluster: Placed[] = [];
  let clusterEnd = -1;
  const laneEnds: number[] = [];
  const flush = () => { const n = Math.max(1, ...cluster.map((p) => p.lane + 1)); cluster.forEach((p) => (p.lanes = n)); cluster = []; laneEnds.length = 0; };
  for (const o of sorted) {
    const s = o.start.slice(0, 10) < date ? 0 : minutesOf(o.start);
    const e = o.end.slice(0, 10) > date ? 24 * 60 : Math.max(minutesOf(o.end), s + 20);
    if (s >= clusterEnd && cluster.length) flush();
    let lane = laneEnds.findIndex((le) => le <= s);
    if (lane === -1) { lane = laneEnds.length; laneEnds.push(e); } else laneEnds[lane] = e;
    const p = { o, top: s - startMin, height: e - s, lane, lanes: 1 };
    cluster.push(p); out.push(p);
    clusterEnd = Math.max(clusterEnd, e);
  }
  flush();
  return out;
}

function DayView({ date, events, people, allPeople, weather, onOpen, onAdd }: {
  date: string; events: Occurrence[]; people: Person[]; allPeople: Person[]; weather?: Weather;
  onOpen: (o: Occurrence) => void; onAdd: (d: string, hour: number, pid?: string) => void;
}) {
  const dayEvents = events.filter((e) => daysOf(e).includes(date));
  const timed = dayEvents.filter((e) => !e.all_day);
  const allDay = dayEvents.filter((e) => e.all_day);
  const firstHour = Math.min(7, ...timed.map((e) => (e.start.slice(0, 10) < date ? 0 : Math.floor(minutesOf(e.start) / 60))));
  const lastHour = Math.max(21, ...timed.map((e) => (e.end.slice(0, 10) > date ? 24 : Math.ceil(minutesOf(e.end) / 60))));
  const hours = Array.from({ length: lastHour - firstHour }, (_, i) => firstHour + i);
  const now = useNow();
  const nowMin = now.getHours() * 60 + now.getMinutes();
  const scroller = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = scroller.current;
    if (el && date === today()) el.scrollTop = Math.max(0, ((nowMin - firstHour * 60) / 60 - 1.5) * el.clientHeight / 9);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [date]);
  const w = weather?.daily.find((d) => d.date === date);
  // One column per person; events with nobody (or only removed people) go in an "Everyone" column,
  // which is also the only column before any people are added.
  const known = (o: Occurrence) => o.person_ids.some((id) => allPeople.some((p) => p.id === id));
  const shown = people.length ? people : allPeople;
  const cols: { id: string; person?: Person; has: (o: Occurrence) => boolean }[] = shown.map((p) => ({ id: p.id, person: p, has: (o) => o.person_ids.includes(p.id) }));
  if (!cols.length || dayEvents.some((o) => !known(o))) cols.push({ id: "_everyone", has: (o) => !known(o) });
  return (
    <div className="dayview" style={{ "--cols": cols.length } as CSSProperties}>
      <div className="dv-head">
        <div className="dv-gutter">{w && <span className="dh-wx"><WeatherIcon condition={w.condition} size={26} />{w.high}°</span>}</div>
        {cols.map(({ id, person: p }) => p ? (
          <div key={id} className="dv-person" style={{ "--pc": p.color } as CSSProperties}>
            <Avatar person={p} size={2} /> <span>{p.name}</span>
          </div>
        ) : (
          <div key={id} className="dv-person unassigned"><span className="dv-dot" /> <span>Everyone</span></div>
        ))}
      </div>
      {allDay.length > 0 && (
        <div className="dv-allday">
          <div className="dv-gutter small">all day</div>
          {cols.map((c) => (
            <div key={c.id} className="dv-cell">
              {allDay.filter(c.has).map((o) => (
                <button key={o.occurrence_id} className={"ev allday" + busyCls(o)} style={eventStyle(o, allPeople)} onClick={() => onOpen(o)}><span className="ev-title">{evTitle(o, allPeople)}</span></button>
              ))}
            </div>
          ))}
        </div>
      )}
      <div className="dv-scroll" ref={scroller}>
        <div className="dv-grid" style={{ "--hours": hours.length } as CSSProperties}>
          <div className="dv-gutter">
            {hours.map((h) => <div key={h} className="dv-hour"><span>{h === 12 ? "12pm" : h > 12 ? `${h - 12}pm` : `${h}am`}</span></div>)}
          </div>
          {cols.map((c) => {
            const mine = timed.filter(c.has);
            const placed = placeLanes(mine.filter((o) => !isBusyBlock(o)), firstHour * 60, date);
            const runs = busyRuns(mine, date);
            // Leave room for the busy bar down the left edge.
            const inset = runs.length ? "0.55rem" : "0px";
            return (
              <div key={c.id} className="dv-col" onClick={(e) => {
                if (e.target !== e.currentTarget) return;
                const rect = (e.currentTarget as HTMLDivElement).getBoundingClientRect();
                const h = firstHour + Math.floor(((e.clientY - rect.top) / rect.height) * hours.length);
                onAdd(date, h, c.person?.id);
              }}>
                {hours.map((h) => <div key={h} className="dv-line" style={{ top: `calc(${h - firstHour} * var(--hour))` }} />)}
                {runs.map((r) => (
                  <button key={"busy" + r.start} className={"busy-bar" + (r.tentative ? " tentative" : "")}
                    title={`${r.tentative ? "Tentative" : "Busy"} ${fmtSpan(r.start, r.end)}`} aria-label={`${r.tentative ? "Tentative" : "Busy"} ${fmtSpan(r.start, r.end)}`}
                    style={{ "--ec": r.occs[0].color ?? "#8A94A6", top: `calc(${(r.start - firstHour * 60) / 60} * var(--hour))`, height: `calc(${(r.end - r.start) / 60} * var(--hour))` } as CSSProperties}
                    onClick={() => onOpen(r.occs[0])} />
                ))}
                {placed.map(({ o, top, height, lane, lanes }) => (
                  <button key={o.occurrence_id} className={"ev block" + (height < 35 ? " short" : "") + busyCls(o)} style={{
                    ...eventStyle(o, allPeople),
                    top: `calc(${top / 60} * var(--hour))`, height: `calc(${height / 60} * var(--hour) - 3px)`,
                    left: `calc(${inset} + (100% - ${inset}) * ${lane / lanes})`, width: `calc((100% - ${inset}) / ${lanes} - 4px)`,
                  }} onClick={() => onOpen(o)}>
                    <span className="ev-title">{evTitle(o, allPeople)}</span>
                    {height >= 40 && <span className="ev-time">{fmtTime(o.start)} – {fmtTime(o.end)}</span>}
                    {height >= 70 && o.location && <span className="ev-loc">{o.location}</span>}
                  </button>
                ))}
              </div>
            );
          })}
          {date === today() && nowMin >= firstHour * 60 && nowMin <= lastHour * 60 && (
            <div className="now-line" style={{ top: `calc(${(nowMin - firstHour * 60) / 60} * var(--hour))` }} />
          )}
        </div>
      </div>
    </div>
  );
}

function MonthView({ anchor, start, events, people, onPick }: {
  anchor: string; start: string; events: Occurrence[]; people: Person[]; onPick: (d: string) => void;
}) {
  const days = Array.from({ length: 42 }, (_, i) => addDays(start, i));
  const month = anchor.slice(0, 7);
  const rows = days[35].slice(0, 7) === month ? 6 : 5;
  const { layout } = useApp();
  const max = layout === "large" ? 4 : 3;
  return (
    <div className="month" style={{ "--rows": rows } as CSSProperties}>
      {days.slice(0, 7).map((d) => <div key={d} className="month-dow">{fmtDow(d)}</div>)}
      {days.slice(0, rows * 7).map((d) => {
        const evs = events.filter((e) => daysOf(e).includes(d) && !isBusyBlock(e));
        return (
          <button key={d} className={"month-cell" + (d.slice(0, 7) !== month ? " other" : "") + (d === today() ? " today" : "")} onClick={() => onPick(d)}>
            <span className="mc-num">{dayNum(d)}</span>
            {/* Phone cells are too narrow for titles: one coloured dot per event. */}
            {layout === "phone" ? evs.length > 0 && (
              <span className="mc-dots">{evs.slice(0, 6).map((o) => <i key={o.occurrence_id} style={eventStyle(o, people)} />)}</span>
            ) : evs.slice(0, max).map((o) => (
              <span key={o.occurrence_id} className={"mc-ev" + (o.all_day ? " allday" : "") + busyCls(o)} style={eventStyle(o, people)}>
                {!o.all_day && <i />}
                {!o.all_day && <b>{fmtTime(o.start)}</b>} {evTitle(o, people)}
              </span>
            ))}
            {layout !== "phone" && evs.length > max && <span className="mc-more">+{evs.length - max} more</span>}
          </button>
        );
      })}
    </div>
  );
}

export function ScheduleView({ start, days, events, meals, weather, people, onOpen, onDay, compact }: {
  start: string; days: number; events: Occurrence[]; meals: Meal[]; weather?: Weather; people: Person[];
  onOpen: (o: Occurrence) => void; onDay?: (d: string) => void; compact?: boolean;
}) {
  const list = Array.from({ length: days }, (_, i) => addDays(start, i));
  const t = today();
  return (
    <div className={"schedule" + (compact ? " compact" : "")}>
      {list.map((d) => {
        const onDayList = events.filter((e) => daysOf(e).includes(d));
        const busy = busyDays(onDayList, d);
        const evs = onDayList.filter((e) => !isBusyBlock(e));
        const startOf = (o: Occurrence) => (o.all_day ? -1 : o.start.slice(0, 10) < d ? 0 : minutesOf(o.start));
        const items = [...evs.map((o) => ({ at: startOf(o), o })), ...busy.map((b) => ({ at: b.start, b }))]
          .sort((x, y) => x.at - y.at || ("o" in x && x.o && "o" in y && y.o ? x.o.start.localeCompare(y.o.start) : 0));
        const w = weather?.daily.find((x) => x.date === d);
        const dinner = meals.find((m) => m.date === d && m.slot === "dinner");
        if (!items.length && !dinner && compact) return null;
        return (
          <section key={d} className={"sched-day" + (d === t ? " today" : "")}>
            <header>
              <div className="sd-date"><span className="sd-num">{dayNum(d)}</span><span><b>{relativeDay(d)}</b><em>{diffDays(d, t) > 1 || diffDays(d, t) < -1 ? fmtDayMonth(d) : fmtDow(d) + " " + fmtDayMonth(d)}</em></span></div>
              {w && <span className="dh-wx"><WeatherIcon condition={w.condition} size={22} />{w.high}°<em>{w.low}°</em></span>}
            </header>
            {items.length === 0 && <div className="sched-none">Nothing planned</div>}
            {items.map((it) => {
              if ("b" in it && it.b) return <BusyLine key={"busy" + it.b.key} b={it.b} people={people} variant="sched" onClick={onDay && (() => onDay(d))} />;
              const o = (it as { o: Occurrence }).o;
              const p = people.find((x) => x.id === o.person_ids[0]);
              return (
                <button key={o.occurrence_id} className={"sched-ev" + busyCls(o)} style={eventStyle(o, people)} onClick={() => onOpen(o)}>
                  <span className="se-time">{o.all_day ? "All day" : <>{fmtTime(o.start)}<em>{fmtTime(o.end)}</em></>}</span>
                  <span className="se-bar" />
                  <span className="se-main">
                    <span className="ev-title">{evTitle(o, people)}</span>
                    {(o.location || o.repeat) && <span className="se-meta">
                      {o.location && <><IconPin size={14} /> {o.location}</>} {o.repeat && <IconRepeat size={14} />}
                    </span>}
                  </span>
                  <span className="se-who">
                    {o.person_ids.length > 1 ? <Who o={o} people={people} size={1.6} /> : p && <><Avatar person={p} size={1.6} />{!compact && <span>{p.name}</span>}</>}
                  </span>
                </button>
              );
            })}
            {dinner && <div className="sched-meal">🍽️ <span>Dinner</span> {dinner.title}</div>}
          </section>
        );
      })}
    </div>
  );
}

export { daysOf, eventStyle, parse };
