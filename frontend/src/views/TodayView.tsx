import { CSSProperties, useState } from "react";
import { ApiError, ChoreDay, Occurrence, TimeOfDay } from "../api/types";
import { addDays, fmtDow, today } from "../dates";
import { useApp, useData, useNow } from "../state";
import { Avatar, Ring, tint } from "../components/ui";
import { IconPlus, IconStar } from "../components/icons";
import { ScheduleView } from "./CalendarView";
import { EventDetail, EventForm, newEventDefaults } from "./EventSheets";
import { ListPanel } from "./ListsView";
import { SLOTS } from "./MealsView";
import { FamilyPrompt } from "./FamilySettings";
import { NowPlayingCard } from "./NowPlaying";

const ORDER: TimeOfDay[] = ["morning", "afternoon", "evening"];
/** Morning until noon, afternoon until 5pm, then evening. */
export function periodOf(d: Date): TimeOfDay { const h = d.getHours(); return h < 12 ? "morning" : h < 17 ? "afternoon" : "evening"; }
/** Unfinished chores for now: earlier ones still not done first, then this part of the day, then "anytime". */
export function dueNow(chores: ChoreDay[], period: TimeOfDay): ChoreDay[] {
  const upTo = ORDER.slice(0, ORDER.indexOf(period) + 1);
  const rank = (c: ChoreDay) => (c.time_of_day === "anytime" ? 3 : ORDER.indexOf(c.time_of_day));
  return chores.filter((c) => !c.completed && (c.time_of_day === "anytime" || upTo.includes(c.time_of_day)))
    .sort((a, b) => rank(a) - rank(b));
}

/** Kitchen home: today + tomorrow, meals, kids' chores, groceries. */
export function TodayView({ go }: { go: (tab: string) => void }) {
  const { api, people, layout, celebrate, toast } = useApp();
  const t = today();
  const [events] = useData((api) => api.events(t, addDays(t, 2)), ["events"], [t]);
  const [meals] = useData((api) => api.meals(t, addDays(t, 7)), ["meals"], [t]);
  const [weather] = useData((api) => api.weather(), ["settings"], []);
  const [chores] = useData((api) => api.chores(t), ["chores"], [t]);
  const [points] = useData((api) => api.points(), ["points"], []);
  const [lists] = useData((api) => api.lists(), ["lists"], []);
  const [open, setOpen] = useState<Occurrence | null>(null);
  const [edit, setEdit] = useState<Occurrence | null>(null);
  const [adding, setAdding] = useState(false);
  const grocery = lists?.find((l) => l.kind === "grocery");
  const todayMeals = SLOTS.map((s) => ({ s, m: meals?.find((x) => x.date === t && x.slot === s.key) })).filter((x) => x.m);
  const dinners = Array.from({ length: 6 }, (_, i) => addDays(t, i + 1)).map((d) => ({ d, m: meals?.find((x) => x.date === d && x.slot === "dinner") }));
  const kids = people.filter((p) => p.role === "child");
  const period = periodOf(useNow(60_000));
  const MAX_DUE = layout === "compact" ? 2 : 3; // the kitchen screen shows the whole page without scrolling
  async function complete(c: ChoreDay, ev: React.MouseEvent, color: string) {
    celebrate(ev.clientX, ev.clientY, color);
    try { await api.completeChore(c.id, t); } catch (e) { toast(e instanceof ApiError ? e.message : "Couldn't tick that off"); }
  }

  return (
    <div className="today-view">
      <section className="panel agenda">
        <div className="panel-head">
          <h2 className="panel-title">Coming up</h2>
          <button className="btn small" onClick={() => setAdding(true)}><IconPlus size={18} /> Add event</button>
        </div>
        <ScheduleView start={t} days={2} events={events ?? []} meals={[]} weather={weather} people={people} onOpen={setOpen} compact />
      </section>
      <div className="today-mid">
        <section className="panel">
          <h2 className="panel-title" onClick={() => go("meals")}>Today's meals</h2>
          {todayMeals.length === 0 && <div className="sched-none">Nothing planned yet</div>}
          {todayMeals.map(({ s, m }) => (
            <div key={s.key} className={"tm-row " + s.key}><span className="tm-slot">{s.icon} {s.label}</span><b>{m!.title}</b></div>
          ))}
          <div className="tm-next">
            {dinners.map(({ d, m }) => (
              <div key={d}><span>{fmtDow(d)}</span>{m?.title ?? "—"}</div>
            ))}
          </div>
        </section>
        <section className="panel">
          <h2 className="panel-title" onClick={() => go("chores")}>Chores today</h2>
          {kids.length === 0 && (people.length === 0 ? <FamilyPrompt />
            : <FamilyPrompt kids>Add a child in Settings › Family to track their chores and stars here.</FamilyPrompt>)}
          <div className="kid-progress">
            {kids.map((k) => {
              const mine = (chores ?? []).filter((c) => c.person_id === k.id);
              const done = mine.filter((c) => c.completed).length;
              const due = dueNow(mine, period);
              const later = mine.find((c) => !c.completed && !due.includes(c));
              return (
                <div key={k.id} className="kp" style={{ "--pc": k.color, background: tint(k.color, 0.1) } as CSSProperties}>
                  <button className="kp-head" onClick={() => go("chores")}>
                    <Ring value={mine.length ? done / mine.length : 0} size={3.2} color={k.color}><Avatar person={k} size={2.3} /></Ring>
                    <span className="kp-main">
                      <b>{k.name}</b>
                      <span>{mine.length === 0 ? "No chores today" : done === mine.length ? `All ${done} done 🎉`
                        : due.length ? `${done} of ${mine.length} done` : `${done} of ${mine.length} done · later: ${later!.emoji} ${later!.title}`}</span>
                    </span>
                    <span className="stars"><IconStar size={18} filled /> {points?.find((p) => p.person_id === k.id)?.balance ?? 0}</span>
                  </button>
                  {due.slice(0, MAX_DUE).map((c) => (
                    <button key={c.id} className="kp-chore" onClick={(e) => complete(c, e, k.color)}>
                      <span className="ch-emoji">{c.emoji}</span>
                      <span className="kp-chore-title">{c.title}</span>
                      <span className="kp-check" aria-label={`Done: ${c.title}`} />
                    </button>
                  ))}
                  {due.length > MAX_DUE && <button className="kp-more" onClick={() => go("chores")}>+{due.length - MAX_DUE} more</button>}
                </div>
              );
            })}
          </div>
        </section>
      </div>
      <div className="today-right">
        {layout === "compact" && <NowPlayingCard />}
        <section className="panel">
          <h2 className="panel-title" onClick={() => go("lists")}>{grocery ? `${grocery.emoji} ${grocery.name}` : "Lists"}</h2>
          {grocery ? <ListPanel list={grocery} compact /> : lists && <div className="sched-none">No shopping list yet. Make one in Lists.</div>}
        </section>
      </div>
      {open && <EventDetail occ={open} onClose={() => setOpen(null)} onEdit={() => { setEdit(open); setOpen(null); }} />}
      {edit && <EventForm id={edit.id} initial={edit} onClose={() => setEdit(null)} />}
      {adding && <EventForm initial={newEventDefaults(t, [], 9)} onClose={() => setAdding(false)} />}
    </div>
  );
}
