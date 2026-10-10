import { CSSProperties, useState } from "react";
import { Occurrence } from "../api/types";
import { addDays, fmtDow, today } from "../dates";
import { useApp, useData } from "../state";
import { Avatar, Ring, tint } from "../components/ui";
import { IconStar } from "../components/icons";
import { ScheduleView } from "./CalendarView";
import { EventDetail, EventForm } from "./EventSheets";
import { ListPanel } from "./ListsView";
import { SLOTS } from "./MealsView";
import { FamilyPrompt } from "./FamilySettings";

/** Kitchen home: today + tomorrow, meals, kids' chores, groceries. */
export function TodayView({ go }: { go: (tab: string) => void }) {
  const { people } = useApp();
  const t = today();
  const [events] = useData((api) => api.events(t, addDays(t, 2)), ["events"], [t]);
  const [meals] = useData((api) => api.meals(t, addDays(t, 7)), ["meals"], [t]);
  const [weather] = useData((api) => api.weather(), [], []);
  const [chores] = useData((api) => api.chores(t), ["chores"], [t]);
  const [points] = useData((api) => api.points(), ["points"], []);
  const [lists] = useData((api) => api.lists(), ["lists"], []);
  const [open, setOpen] = useState<Occurrence | null>(null);
  const [edit, setEdit] = useState<Occurrence | null>(null);
  const grocery = lists?.find((l) => l.kind === "grocery");
  const todayMeals = SLOTS.map((s) => ({ s, m: meals?.find((x) => x.date === t && x.slot === s.key) })).filter((x) => x.m);
  const dinners = Array.from({ length: 6 }, (_, i) => addDays(t, i + 1)).map((d) => ({ d, m: meals?.find((x) => x.date === d && x.slot === "dinner") }));
  const kids = people.filter((p) => p.role === "child");

  return (
    <div className="today-view">
      <section className="panel agenda">
        <h2 className="panel-title">Coming up</h2>
        {events && events.length === 0 ? <div className="sched-none">Nothing planned today or tomorrow</div>
          : <ScheduleView start={t} days={2} events={events ?? []} meals={[]} weather={weather} people={people} onOpen={setOpen} compact />}
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
              const next = mine.find((c) => !c.completed);
              return (
                <button key={k.id} className="kp" style={{ "--pc": k.color, background: tint(k.color, 0.1) } as CSSProperties} onClick={() => go("chores")}>
                  <Ring value={mine.length ? done / mine.length : 0} size={3.2} color={k.color}><Avatar person={k} size={2.3} /></Ring>
                  <span className="kp-main">
                    <b>{k.name}</b>
                    <span>{mine.length === 0 ? "No chores today" : `${done}/${mine.length} · next: ${next ? `${next.emoji} ${next.title}` : "all done 🎉"}`}</span>
                  </span>
                  <span className="stars"><IconStar size={18} filled /> {points?.find((p) => p.person_id === k.id)?.balance ?? 0}</span>
                </button>
              );
            })}
          </div>
        </section>
      </div>
      <section className="panel">
        <h2 className="panel-title" onClick={() => go("lists")}>{grocery ? `${grocery.emoji} ${grocery.name}` : "Lists"}</h2>
        {grocery ? <ListPanel list={grocery} compact /> : lists && <div className="sched-none">No shopping list yet. Make one in Lists.</div>}
      </section>
      {open && <EventDetail occ={open} onClose={() => setOpen(null)} onEdit={() => { setEdit(open); setOpen(null); }} />}
      {edit && <EventForm id={edit.id} initial={edit} onClose={() => setEdit(null)} />}
    </div>
  );
}
