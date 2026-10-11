import { CSSProperties, useState } from "react";
import { ApiError, Chore, ChoreDay, ChoreSchedule, Person, TimeOfDay } from "../api/types";
import { addDays, DAY_CODES, fmtDayMonth, relativeDay, today } from "../dates";
import { useApp, useData } from "../state";
import { Avatar, PersonPicker, Ring, Segmented, Sheet, tint } from "../components/ui";
import { IconCheck, IconFlame, IconLeft, IconPlus, IconRight, IconStar, IconTrash } from "../components/icons";
import { FamilyPrompt } from "./FamilySettings";

const TOD: { key: TimeOfDay; label: string; icon: string }[] = [
  { key: "morning", label: "Morning", icon: "🌅" },
  { key: "afternoon", label: "Afternoon", icon: "☀️" },
  { key: "evening", label: "Evening", icon: "🌙" },
  { key: "anytime", label: "Anytime", icon: "✨" },
];

export function ChoresView() {
  const { people, layout, askPin } = useApp();
  const [date, setDate] = useState(today());
  const [adding, setAdding] = useState(false);
  // Edit mode: tapping a chore opens it for changes instead of ticking it off (parents only).
  const [editing, setEditing] = useState(false);
  const [editChore, setEditChore] = useState<ChoreDay | null>(null);
  async function toggleEditing() {
    if (editing) { setEditing(false); return; }
    if (await askPin("Edit chores")) setEditing(true);
  }
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
          {people.length > 0 && <button className={"btn" + (editing ? "" : " ghost")} onClick={toggleEditing}>{editing ? "Done" : "Edit"}</button>}
        </div>
      </div>
      {editing && <div className="edit-banner">Tap a chore to change or delete it.</div>}
      {people.length === 0 ? <FamilyPrompt>Chore charts are per person. Add your family in Settings › Family, then give everyone their jobs.</FamilyPrompt>
        : cols.length === 0 ? <FamilyPrompt kids>Switch to Everyone to see the adults' chores, or add a child in Settings › Family.</FamilyPrompt>
        : (
          <div className="chore-cols" style={{ "--cols": cols.length } as CSSProperties}>
            {cols.map((p) => (
              <ChoreColumn key={p.id} person={p} date={date} onEdit={editing ? setEditChore : undefined}
                chores={(chores ?? []).filter((c) => c.person_id === p.id)}
                balance={points?.find((b) => b.person_id === p.id)?.balance ?? 0} />
            ))}
          </div>
        )}
      {people.length > 0 && <button className="fab" onClick={() => setAdding(true)} aria-label="Add chore"><IconPlus size={30} /></button>}
      {adding && <ChoreForm onClose={() => setAdding(false)} />}
      {editChore && <ChoreForm chore={editChore} onClose={() => setEditChore(null)} />}
    </div>
  );
}

function ChoreColumn({ person, chores, balance, date, onEdit }: {
  person: Person; chores: ChoreDay[]; balance: number; date: string; onEdit?: (c: ChoreDay) => void;
}) {
  const { api, celebrate, toast } = useApp();
  const done = chores.filter((c) => c.completed).length;
  const total = chores.length;
  const isFuture = date > today();
  async function toggle(c: ChoreDay, ev: React.MouseEvent) {
    if (onEdit) { onEdit(c); return; }
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
                <button key={c.id} className={"chore" + (c.completed ? " done" : "") + (onEdit ? " editing" : "")} onClick={(e) => toggle(c, e)}>
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

/** Which preset a saved schedule matches; "custom" for weekly days that aren't weekdays or weekends. */
function presetOf(s: ChoreSchedule): keyof typeof SCHEDULES | "custom" {
  if (s.type === "daily") return "daily";
  if (s.type === "once") return "once";
  const days = [...s.days].sort().join();
  if (days === [...DAY_CODES.slice(1, 6)].sort().join()) return "weekdays";
  if (days === ["SA", "SU"].sort().join()) return "weekends";
  return "custom";
}
const DAY_NAMES: Record<string, string> = { MO: "Mon", TU: "Tue", WE: "Wed", TH: "Thu", FR: "Fri", SA: "Sat", SU: "Sun" };

function ChoreForm({ chore, onClose }: { chore?: Chore; onClose: () => void }) {
  const { api, people, toast } = useApp();
  const [title, setTitle] = useState(chore?.title ?? "");
  const [emoji, setEmoji] = useState(chore?.emoji ?? EMOJIS[0]);
  const [who, setWho] = useState<string[]>(() => {
    if (chore) return [chore.person_id];
    const first = people.find((p) => p.role === "child") ?? people[0];
    return first ? [first.id] : [];
  });
  const [tod, setTod] = useState<TimeOfDay>(chore?.time_of_day ?? "morning");
  const [sched, setSched] = useState<keyof typeof SCHEDULES | "custom">(chore ? presetOf(chore.schedule) : "daily");
  const [pts, setPts] = useState(chore?.points ?? 2);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const schedOptions: { value: keyof typeof SCHEDULES | "custom"; label: string }[] =
    Object.entries(SCHEDULES).map(([v, l]) => ({ value: v as keyof typeof SCHEDULES, label: l }));
  if (chore && chore.schedule.type === "weekly" && presetOf(chore.schedule) === "custom")
    schedOptions.push({ value: "custom", label: DAY_CODES.filter((d) => (chore.schedule as { days: string[] }).days.includes(d)).map((d) => DAY_NAMES[d]).join(", ") });
  function schedule(): ChoreSchedule {
    if (sched === "custom" && chore) return chore.schedule;
    if (sched === "once") return chore?.schedule.type === "once" ? chore.schedule : { type: "once", date: today() };
    return sched === "daily" ? { type: "daily" } : { type: "weekly", days: sched === "weekdays" ? DAY_CODES.slice(1, 6) : ["SA", "SU"] };
  }
  async function save() {
    try {
      const fields = { title: title.trim(), emoji, time_of_day: tod, schedule: schedule(), points: pts };
      if (chore) {
        await api.updateChore(chore.id, { ...fields, person_id: who[0] });
        toast("Chore saved");
      } else {
        for (const pid of who) await api.createChore({ ...fields, person_id: pid });
        toast("Chore added");
      }
      onClose();
    } catch (e) { toast(e instanceof ApiError ? e.message : "Couldn't save the chore"); }
  }
  async function remove() {
    if (!chore) return;
    if (!confirmDelete) { setConfirmDelete(true); return; }
    try { await api.deleteChore(chore.id); toast("Chore deleted"); onClose(); }
    catch (e) { toast(e instanceof ApiError ? e.message : "Couldn't delete the chore"); }
  }
  return (
    <Sheet title={chore ? "Edit chore" : "New chore"} onClose={onClose} footer={<>
      {chore ? <button className="btn ghost danger" onClick={remove}><IconTrash size={20} /> {confirmDelete ? "Tap again to delete" : "Delete"}</button>
        : <button className="btn ghost" onClick={onClose}>Cancel</button>}
      <span style={{ flex: 1 }} />
      <button className="btn" disabled={!title.trim() || !who.length} onClick={save}>{chore ? "Save" : "Add chore"}</button>
    </>}>
      <div className="form">
        <input className="input big" placeholder="Chore name" value={title} onChange={(e) => setTitle(e.target.value)} autoFocus={!chore} />
        <label className="field-label">Icon</label>
        <div className="emoji-grid">{EMOJIS.map((e) => <button key={e} className={e === emoji ? "on" : ""} onClick={() => setEmoji(e)}>{e}</button>)}</div>
        <label className="field-label">Who</label>
        <PersonPicker people={people} value={who} onChange={setWho} multi={!chore} />
        <label className="field-label">When</label>
        <Segmented value={tod} onChange={setTod} options={TOD.map((t) => ({ value: t.key, label: t.label }))} />
        <label className="field-label">Repeats</label>
        <Segmented value={sched} onChange={setSched} options={schedOptions} />
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
