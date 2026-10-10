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
  const [weather] = useData((api) => api.weather(), [], []);
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
              <Avatar key={p.id} person={p} size={layout === "hallway" ? 2.3 : 2} dim={hidden.includes(p.id)} ring={!hidden.includes(p.id)}
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
        {view === "week" && <WeekView start={start} events={visible} meals={meals ?? []} weather={weather} people={people} onOpen={setOpen} onAdd={(d) => add(d)} />}
        {view === "day" && <DayView date={anchor} events={visible} people={shownPeople} allPeople={people} weather={weather} onOpen={setOpen} onAdd={add} />}
        {view === "month" && <MonthView anchor={anchor} start={start} events={visible} people={people}
          onPick={(d) => { setAnchor(d); setView("day"); }} />}
        {view === "schedule" && <ScheduleView start={start} days={14} events={visible} meals={meals ?? []} weather={weather} people={people} onOpen={setOpen} />}
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

function WeekView({ start, events, meals, weather, people, onOpen, onAdd }: {
  start: string; events: Occurrence[]; meals: Meal[]; weather?: Weather; people: Person[];
  onOpen: (o: Occurrence) => void; onAdd: (d: string) => void;
}) {
  const days = Array.from({ length: 7 }, (_, i) => addDays(start, i));
  const now = useNow();
  const nowStr = `${iso(now)}T${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`;
  return (
    <div className="week">
      {days.map((d) => {
        const dayEvents = events.filter((e) => daysOf(e).includes(d));
        const allDay = dayEvents.filter((e) => e.all_day);
        const timed = dayEvents.filter((e) => !e.all_day);
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
              {timed.map((o) => (
                <button key={o.occurrence_id} className={"ev card" + (o.end < nowStr ? " done" : "") + busyCls(o)} style={eventStyle(o, people)} onClick={() => onOpen(o)}>
                  <span className="ev-time">{fmtTime(o.start)}{o.start.slice(0, 10) === d ? ` – ${fmtTime(o.end)}` : ""}</span>
                  <span className="ev-title">{evTitle(o, people)}</span>
                  <Who o={o} people={people} />
                </button>
              ))}
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
            const placed = placeLanes(timed.filter(c.has), firstHour * 60, date);
            return (
              <div key={c.id} className="dv-col" onClick={(e) => {
                if (e.target !== e.currentTarget) return;
                const rect = (e.currentTarget as HTMLDivElement).getBoundingClientRect();
                const h = firstHour + Math.floor(((e.clientY - rect.top) / rect.height) * hours.length);
                onAdd(date, h, c.person?.id);
              }}>
                {hours.map((h) => <div key={h} className="dv-line" style={{ top: `calc(${h - firstHour} * var(--hour))` }} />)}
                {placed.map(({ o, top, height, lane, lanes }) => (
                  <button key={o.occurrence_id} className={"ev block" + busyCls(o)} style={{
                    ...eventStyle(o, allPeople),
                    top: `calc(${top / 60} * var(--hour))`, height: `calc(${height / 60} * var(--hour) - 3px)`,
                    left: `${(lane / lanes) * 100}%`, width: `calc(${100 / lanes}% - 4px)`,
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
  const max = layout === "hallway" ? 4 : 3;
  return (
    <div className="month" style={{ "--rows": rows } as CSSProperties}>
      {days.slice(0, 7).map((d) => <div key={d} className="month-dow">{fmtDow(d)}</div>)}
      {days.slice(0, rows * 7).map((d) => {
        const evs = events.filter((e) => daysOf(e).includes(d));
        return (
          <button key={d} className={"month-cell" + (d.slice(0, 7) !== month ? " other" : "") + (d === today() ? " today" : "")} onClick={() => onPick(d)}>
            <span className="mc-num">{dayNum(d)}</span>
            {evs.slice(0, max).map((o) => (
              <span key={o.occurrence_id} className={"mc-ev" + (o.all_day ? " allday" : "") + busyCls(o)} style={eventStyle(o, people)}>
                {!o.all_day && <i />}
                {!o.all_day && <b>{fmtTime(o.start)}</b>} {evTitle(o, people)}
              </span>
            ))}
            {evs.length > max && <span className="mc-more">+{evs.length - max} more</span>}
          </button>
        );
      })}
    </div>
  );
}

export function ScheduleView({ start, days, events, meals, weather, people, onOpen, compact }: {
  start: string; days: number; events: Occurrence[]; meals: Meal[]; weather?: Weather; people: Person[];
  onOpen: (o: Occurrence) => void; compact?: boolean;
}) {
  const list = Array.from({ length: days }, (_, i) => addDays(start, i));
  const t = today();
  return (
    <div className={"schedule" + (compact ? " compact" : "")}>
      {list.map((d) => {
        const evs = events.filter((e) => daysOf(e).includes(d)).sort((a, b) => Number(b.all_day) - Number(a.all_day) || a.start.localeCompare(b.start));
        const w = weather?.daily.find((x) => x.date === d);
        const dinner = meals.find((m) => m.date === d && m.slot === "dinner");
        if (!evs.length && !dinner && compact) return null;
        return (
          <section key={d} className={"sched-day" + (d === t ? " today" : "")}>
            <header>
              <div className="sd-date"><span className="sd-num">{dayNum(d)}</span><span><b>{relativeDay(d)}</b><em>{diffDays(d, t) > 1 || diffDays(d, t) < -1 ? fmtDayMonth(d) : fmtDow(d) + " " + fmtDayMonth(d)}</em></span></div>
              {w && <span className="dh-wx"><WeatherIcon condition={w.condition} size={22} />{w.high}°<em>{w.low}°</em></span>}
            </header>
            {evs.length === 0 && <div className="sched-none">Nothing planned</div>}
            {evs.map((o) => {
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
