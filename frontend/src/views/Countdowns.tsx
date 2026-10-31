import { CSSProperties, useState } from "react";
import { ApiError, Countdown, CountdownIn, CountdownSuggestion, Occurrence } from "../api/types";
import { fmtDayMonth, fmtFull, iso, today } from "../dates";
import { useApp, useData, useNow } from "../state";
import { Avatar, PersonPicker, Segmented, Sheet } from "../components/ui";
import { IconCheck, IconPlus, IconTrash } from "../components/icons";

/** Every countdown, soonest first, counted from this screen's today (refetched just after midnight). */
export function useCountdowns(): Countdown[] | undefined {
  const t = iso(useNow(60_000));
  const [list] = useData((api) => api.countdowns(t), ["countdowns", "events", "people", "settings"], [t]);
  return list;
}

/** "55 days", "Tomorrow", "Today". */
export function daysText(days: number): string {
  return days <= 0 ? "Today" : days === 1 ? "Tomorrow" : `${days} days`;
}
/** "55 days to Christmas", "Christmas is tomorrow", "Christmas is today!" */
export function countdownSentence(c: Countdown): string {
  return c.days <= 0 ? `${c.title} is today!` : c.days === 1 ? `${c.title} is tomorrow` : `${c.days} days to ${c.title}`;
}
const EMOJI = "⏳";

/** A guess at an emoji for an event's countdown, from its title. */
export function emojiFor(title: string): string {
  const t = title.toLowerCase();
  const rules: [RegExp, string][] = [
    [/birthday|bday/, "🎂"], [/christmas|xmas/, "🎄"], [/halloween/, "🎃"], [/easter/, "🐣"], [/wedding|anniversary/, "💍"],
    [/holiday|vacation|beach|villa|camping|cornwall|spain|france|disney/, "🏖️"], [/flight|fly|airport|trip|travel/, "✈️"],
    [/half term|school|term/, "🏫"], [/party|celebrat/, "🎉"], [/concert|gig|show|theatre|musical/, "🎭"],
    [/football|match|game/, "⚽"], [/baby|due date/, "👶"], [/graduat/, "🎓"],
  ];
  return rules.find(([re]) => re.test(t))?.[1] ?? "🎉";
}

/** The top bar's countdowns: the soonest few, tap for all of them. */
export function CountdownChips() {
  const { layout, portrait } = useApp();
  const list = useCountdowns();
  const [open, setOpen] = useState(false);
  if (!list?.length) return null;
  const max = layout === "large" ? 3 : 2;
  return (
    <>
      <div className="tb-cds">
        {list.slice(0, portrait ? 1 : max).map((c) => (
          <button key={c.id} className={"tb-cd" + (c.days <= 1 ? " soon" : "")} onClick={() => setOpen(true)} aria-label={countdownSentence(c)}>
            <span className="cd-emoji">{c.emoji || EMOJI}</span>
            {c.days > 1 && <b className="cd-num">{c.days}</b>}
            <span className="cd-text">
              <small>{c.days > 1 ? "days to" : c.days === 1 ? "Tomorrow" : "Today!"}</small>
              <span className="cd-title">{c.title}</span>
            </span>
          </button>
        ))}
      </div>
      {open && <CountdownsSheet list={list} onClose={() => setOpen(false)} />}
    </>
  );
}

function whenText(c: Countdown): string {
  const repeat = c.kind === "birthday" ? (c.turns ? ` · turns ${c.turns}` : "") : c.kind === "event" ? " · from the calendar"
    : c.yearly ? " · every year" : "";
  return `${fmtFull(c.date)}${repeat}`;
}

/** Every countdown; tap one to change it, or add another. */
export function CountdownsSheet({ list, onClose }: { list: Countdown[]; onClose: () => void }) {
  const { personById, toast } = useApp();
  const [edit, setEdit] = useState<Countdown | "new" | null>(null);
  if (edit) return <CountdownForm existing={edit === "new" ? undefined : edit} onClose={() => setEdit(null)} />;
  return (
    <Sheet title="Countdowns" onClose={onClose} footer={<>
      <span style={{ flex: 1 }} />
      <button className="btn" onClick={() => setEdit("new")}><IconPlus size={20} /> Add countdown</button>
    </>}>
      <div className="cd-list">
        {list.length === 0 && <p className="muted">Nothing to count down to yet. Add Christmas, a holiday or a big day.</p>}
        {list.map((c) => (
          <button key={c.id} className="cd-row" onClick={() => c.kind === "birthday"
            ? toast("Birthdays come from Settings › Family") : setEdit(c)}>
            <span className="cd-row-emoji">{c.emoji || EMOJI}</span>
            <span className="cd-row-main">
              <b>{c.title}</b>
              <span>{whenText(c)}</span>
            </span>
            <span className="cd-row-people">
              {c.person_ids.map((id) => personById(id)).filter(Boolean).map((p) => <Avatar key={p!.id} person={p!} size={1.6} />)}
            </span>
            <span className={"cd-row-days" + (c.days <= 1 ? " soon" : "")}>
              {c.days > 1 ? <><b>{c.days}</b><small>days</small></> : <b className="cd-word">{daysText(c.days)}</b>}
            </span>
          </button>
        ))}
      </div>
    </Sheet>
  );
}

const QUICK_EMOJI = ["🎉", "🎂", "🏖️", "✈️", "🎄", "🎃", "🐣", "🏫", "🎁", "💍", "⚽", "🎭", "🎓", "👶"];

/** Add a countdown (a well-known day, or the family's own), or change or remove one. `event`: start from that event. */
export function CountdownForm({ existing, event, onClose }: { existing?: Countdown; event?: Occurrence; onClose: () => void }) {
  const { api, people, toast } = useApp();
  const [tab, setTab] = useState<"special" | "own">(existing || event ? "own" : "special");
  const [title, setTitle] = useState(existing?.title ?? event?.title ?? "");
  const [emoji, setEmoji] = useState(existing?.emoji ?? (event ? emojiFor(event.title) : "🎉"));
  const [date, setDate] = useState(existing?.date ?? event?.start.slice(0, 10) ?? "");
  const [yearly, setYearly] = useState(existing?.yearly ?? false);
  const [who, setWho] = useState<string[]>(existing?.person_ids ?? event?.person_ids ?? []);
  const [busy, setBusy] = useState(false);
  const [sugg] = useData((a) => a.countdownSuggestions(today()), ["countdowns", "settings"], []);
  const fixedDate = existing?.kind === "special" || existing?.kind === "event" || !!event;
  const valid = title.trim() !== "" && (fixedDate || date !== "");

  async function run(fn: () => Promise<unknown>, done: string) {
    setBusy(true);
    try { await fn(); toast(done); onClose(); } catch (e) { toast(e instanceof ApiError ? e.message : "Couldn't save the countdown"); } finally { setBusy(false); }
  }
  const save = () => {
    const body: CountdownIn = { title: title.trim(), emoji, person_ids: who, ...(fixedDate ? {} : { date, yearly }) };
    if (existing) return run(() => api.updateCountdown(existing.id, body), "Countdown saved");
    return run(() => api.createCountdown(event ? { ...body, event_id: event.id } : body), "Countdown added");
  };
  const addSpecial = (s: CountdownSuggestion) => run(() => api.createCountdown({ special: s.special }), `Counting down to ${s.title}`);

  return (
    <Sheet title={existing ? "Countdown" : "Add countdown"} onClose={onClose} footer={tab === "own" ? <>
      {existing && <button className="btn ghost danger" disabled={busy} onClick={() => run(() => api.deleteCountdown(existing.id), "Countdown removed")}><IconTrash size={20} /> Remove</button>}
      {!existing && <button className="btn ghost" onClick={onClose}>Cancel</button>}
      <span style={{ flex: 1 }} />
      <button className="btn" disabled={!valid || busy} onClick={save}>{existing ? "Save" : "Add countdown"}</button>
    </> : undefined}>
      <div className="form">
        {!existing && !event && <Segmented value={tab} onChange={setTab} options={[{ value: "special", label: "Special days" }, { value: "own", label: "Your own" }]} />}
        {tab === "special" && (
          <div className="cd-list">
            {!sugg && <p className="muted">Loading…</p>}
            {sugg?.map((s) => (
              <button key={s.special} className="cd-row" disabled={s.taken || busy} onClick={() => addSpecial(s)}>
                <span className="cd-row-emoji">{s.emoji}</span>
                <span className="cd-row-main"><b>{s.title}</b><span>{fmtFull(s.date)}</span></span>
                <span className="cd-row-add">{s.taken ? <><IconCheck size={18} /> Added</> : <><IconPlus size={18} /> {daysText(s.days)}</>}</span>
              </button>
            ))}
            <p className="muted form-note">Birthdays count down by themselves once they're set in Settings › Family. Any event can count down too: open it and tap Count down.</p>
          </div>
        )}
        {tab === "own" && (<>
          <input className="input big" placeholder="What are you counting down to?" value={title} onChange={(e) => setTitle(e.target.value)} autoFocus={!existing && !event} />
          <label className="field-label">Emoji</label>
          <div className="cd-emojis">
            {QUICK_EMOJI.map((e) => (
              <button key={e} type="button" className={"cd-emoji-btn" + (emoji === e ? " on" : "")} onClick={() => setEmoji(e)} aria-pressed={emoji === e}>{e}</button>
            ))}
            <input className="input cd-emoji-input" value={QUICK_EMOJI.includes(emoji) ? "" : emoji} placeholder="Other" maxLength={8}
              onChange={(e) => setEmoji(e.target.value.trim())} aria-label="Another emoji" />
          </div>
          {fixedDate
            ? <p className="muted form-note">{existing?.kind === "special"
                ? `The date is worked out each year: next ${fmtFull(existing.date)}.`
                : `Follows the event “${event?.title ?? existing?.title}” on the calendar, so it moves if the event does${existing ? ` (next ${fmtDayMonth(existing.date)})` : ""}.`}</p>
            : <div className="form-row">
                <div><label className="field-label">Date</label><input className="input" type="date" value={date} onChange={(e) => setDate(e.target.value)} /></div>
                <div>
                  <label className="field-label">Every year</label>
                  <button className={"toggle" + (yearly ? " on" : "")} onClick={() => setYearly(!yearly)} aria-pressed={yearly}><span /></button>
                </div>
              </div>}
          {people.length > 0 && <><label className="field-label">Who's it for</label><PersonPicker people={people} value={who} onChange={setWho} /></>}
        </>)}
      </div>
    </Sheet>
  );
}

/** On an event's details: count down to it, or stop. */
export function EventCountdownButton({ occ, onAdd }: { occ: Occurrence; onAdd: () => void }) {
  const { api, toast } = useApp();
  const list = useCountdowns();
  const mine = list?.find((c) => c.event_id === occ.id);
  if (!list) return null;
  return (
      <button className={"btn ghost" + (mine ? " on" : "")} style={mine ? { color: "var(--accent)" } as CSSProperties : undefined}
        onClick={async () => {
          if (!mine) return onAdd();
          try { await api.deleteCountdown(mine.id); toast("Countdown removed"); } catch { toast("Couldn't remove the countdown"); }
        }}>
        {mine ? <><IconCheck size={20} /> Counting down</> : <>{EMOJI} Count down</>}
      </button>
  );
}

/** The screensaver's countdowns: the soonest two. */
export function ScreensaverCountdowns() {
  const list = useCountdowns();
  if (!list?.length) return null;
  return (
    <div className="ss-cds">
      {list.slice(0, 2).map((c) => <div key={c.id} className="ss-cd"><span>{c.emoji || EMOJI}</span> {c.days > 1 ? <><b>{c.days}</b> days to <b>{c.title}</b></> : <b>{countdownSentence(c)}</b>}</div>)}
    </div>
  );
}
