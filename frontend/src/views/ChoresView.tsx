import { CSSProperties, useState } from "react";
import { ChoreDay, ChoreSchedule, Person, TimeOfDay } from "../api/types";
import { addDays, DAY_CODES, fmtDayMonth, relativeDay, today } from "../dates";
import { useApp, useData } from "../state";
import { Avatar, PersonPicker, Ring, Segmented, Sheet, tint } from "../components/ui";
import { IconCheck, IconFlame, IconLeft, IconPlus, IconRight, IconStar } from "../components/icons";
import { FamilyPrompt } from "./FamilySettings";

const TOD: { key: TimeOfDay; label: string; icon: string }[] = [
  { key: "morning", label: "Morning", icon: "🌅" },
  { key: "afternoon", label: "Afternoon", icon: "☀️" },
  { key: "evening", label: "Evening", icon: "🌙" },
  { key: "anytime", label: "Anytime", icon: "✨" },
];

export function ChoresView() {
  const { people, layout } = useApp();
  const [date, setDate] = useState(today());
  const [adding, setAdding] = useState(false);
  const [who, setWho] = useState<"everyone" | "kids">(layout === "kitchen" ? "kids" : "everyone");
  const [chores] = useData((api) => api.chores(date), ["chores"], [date]);
  const [points] = useData((api) => api.points(), ["points"], []);
  const cols = people.filter((p) => who === "everyone" || p.role === "child");

  return (
    <div className="chores">
      <div className="toolbar">
        <div className="toolbar-l">
          <button className="btn ghost" onClick={() => setDate(today())}>Today</button>
          <button className="icon-btn" onClick={() => setDate(addDays(date, -1))} aria-label="Previous day"><IconLeft /></button>
          <button className="icon-btn" onClick={() => setDate(addDays(date, 1))} aria-label="Next day"><IconRight /></button>
          <h1 className="toolbar-title">{relativeDay(date)}<span className="sub">{fmtDayMonth(date)}</span></h1>
        </div>
        <div className="toolbar-r">
          <Segmented value={who} onChange={setWho} options={[{ value: "everyone", label: "Everyone" }, { value: "kids", label: "Kids" }]} />
        </div>
      </div>
      {people.length === 0 ? <FamilyPrompt>Chore charts are per person. Add your family in Settings › Family, then give everyone their jobs.</FamilyPrompt>
        : cols.length === 0 ? <FamilyPrompt kids>Switch to Everyone to see the adults' chores, or add a child in Settings › Family.</FamilyPrompt>
        : (
          <div className="chore-cols" style={{ "--cols": cols.length } as CSSProperties}>
            {cols.map((p) => (
              <ChoreColumn key={p.id} person={p} date={date}
                chores={(chores ?? []).filter((c) => c.person_id === p.id)}
                balance={points?.find((b) => b.person_id === p.id)?.balance ?? 0} />
            ))}
          </div>
        )}
      {people.length > 0 && <button className="fab" onClick={() => setAdding(true)} aria-label="Add chore"><IconPlus size={30} /></button>}
      {adding && <ChoreForm onClose={() => setAdding(false)} />}
    </div>
  );
}

function ChoreColumn({ person, chores, balance, date }: { person: Person; chores: ChoreDay[]; balance: number; date: string }) {
  const { api, celebrate, toast } = useApp();
  const done = chores.filter((c) => c.completed).length;
  const total = chores.length;
  const isFuture = date > today();
  async function toggle(c: ChoreDay, ev: React.MouseEvent) {
    if (isFuture) { toast("That's in the future, no peeking!"); return; }
    if (c.completed) await api.uncompleteChore(c.id, date);
    else {
      celebrate(ev.clientX, ev.clientY, person.color);
      await api.completeChore(c.id, date);
      if (done + 1 === total) toast(`${person.name} finished everything! 🎉`);
    }
  }
  return (
    <div className="chore-col" style={{ "--pc": person.color, "--pbg": tint(person.color, 0.1) } as CSSProperties}>
      <header className="cc-head">
        <Ring value={total ? done / total : 0} size={3.6} color={person.color}>
          <Avatar person={person} size={2.6} />
        </Ring>
        <div className="cc-name">
          <b>{person.name}</b>
          <span>{total ? `${done} of ${total} done` : "No chores"}</span>
        </div>
        {person.role === "child" && <span className="stars"><IconStar size={20} filled /> {balance}</span>}
      </header>
      <div className="cc-list">
        {total > 0 && done === total && <div className="cc-alldone">All done! 🎉</div>}
        {TOD.map((t) => {
          const group = chores.filter((c) => c.time_of_day === t.key);
          if (!group.length) return null;
          return (
            <div key={t.key} className="cc-group">
              <div className="cc-group-label">{t.icon} {t.label}</div>
              {group.map((c) => (
                <button key={c.id} className={"chore" + (c.completed ? " done" : "")} onClick={(e) => toggle(c, e)}>
                  <span className="ch-emoji">{c.emoji}</span>
                  <span className="ch-main">
                    <span className="ch-title">{c.title}</span>
                    <span className="ch-meta">
                      {c.points > 0 && <span className="ch-pts"><IconStar size={14} filled /> {c.points}</span>}
                      {c.streak >= 3 && <span className="ch-streak"><IconFlame size={14} /> {c.streak}</span>}
                    </span>
                  </span>
                  <span className="ch-check">{c.completed && <IconCheck size={22} />}</span>
                </button>
              ))}
            </div>
          );
        })}
      </div>
    </div>
  );
}

const EMOJIS = ["🛏️", "🪥", "🎒", "📚", "🎹", "🍽️", "🧸", "👕", "🐶", "🧩", "🧺", "🪴", "🗑️", "🧽", "🚿", "🥪", "💊", "🏃", "🎻", "✏️", "🧹", "🛁", "🥦", "💤"];
const SCHEDULES = { daily: "Every day", weekdays: "Weekdays", weekends: "Weekends", once: "Just today" } as const;

function ChoreForm({ onClose }: { onClose: () => void }) {
  const { api, people, toast } = useApp();
  const [title, setTitle] = useState("");
  const [emoji, setEmoji] = useState(EMOJIS[0]);
  const [who, setWho] = useState<string[]>(() => {
    const first = people.find((p) => p.role === "child") ?? people[0];
    return first ? [first.id] : [];
  });
  const [tod, setTod] = useState<TimeOfDay>("morning");
  const [sched, setSched] = useState<keyof typeof SCHEDULES>("daily");
  const [pts, setPts] = useState(2);
  async function save() {
    const schedule: ChoreSchedule = sched === "daily" ? { type: "daily" }
      : sched === "once" ? { type: "once", date: today() }
      : { type: "weekly", days: sched === "weekdays" ? DAY_CODES.slice(1, 6) : ["SA", "SU"] };
    for (const pid of who) await api.createChore({ title: title.trim(), emoji, person_id: pid, time_of_day: tod, schedule, points: pts });
    toast("Chore added");
    onClose();
  }
  return (
    <Sheet title="New chore" onClose={onClose} footer={<>
      <button className="btn ghost" onClick={onClose}>Cancel</button><span style={{ flex: 1 }} />
      <button className="btn" disabled={!title.trim() || !who.length} onClick={save}>Add chore</button>
    </>}>
      <div className="form">
        <input className="input big" placeholder="Chore name" value={title} onChange={(e) => setTitle(e.target.value)} autoFocus />
        <label className="field-label">Icon</label>
        <div className="emoji-grid">{EMOJIS.map((e) => <button key={e} className={e === emoji ? "on" : ""} onClick={() => setEmoji(e)}>{e}</button>)}</div>
        <label className="field-label">Who</label>
        <PersonPicker people={people} value={who} onChange={setWho} />
        <label className="field-label">When</label>
        <Segmented value={tod} onChange={setTod} options={TOD.map((t) => ({ value: t.key, label: t.label }))} />
        <label className="field-label">Repeats</label>
        <Segmented value={sched} onChange={setSched} options={Object.entries(SCHEDULES).map(([v, l]) => ({ value: v as keyof typeof SCHEDULES, label: l }))} />
        <label className="field-label">Stars</label>
        <div className="stepper">
          <button className="icon-btn" onClick={() => setPts(Math.max(0, pts - 1))}>−</button>
          <span><IconStar size={20} filled /> {pts}</span>
          <button className="icon-btn" onClick={() => setPts(pts + 1)}>+</button>
        </div>
      </div>
    </Sheet>
  );
}
