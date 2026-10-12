import { useState } from "react";
import { ApiError, CalEvent, EventIn, Freq, Occurrence, pickCalendar } from "../api/types";
import { addDays, dayCode, fmtFull, fmtTime } from "../dates";
import { useApp, useData } from "../state";
import { IconCloud } from "./CalendarsSettings";
import { evTitle } from "./CalendarView";
import { Avatar, DayPicker, HolidaySwitch, PersonPicker, Segmented, Sheet } from "../components/ui";
import { useHolidayRegionName } from "../components/holidays";
import { IconPin, IconRepeat, IconTrash } from "../components/icons";

/** Summaries free/busy publishing uses instead of titles (same list as the backend's freebusy.py). */
const PLACEHOLDER = /^(busy|tentative|free|away|oof|out of (the )?office|working elsewhere)$/i;
const REPEAT_LABEL: Record<string, string> = { none: "Never", daily: "Daily", weekly: "Weekly", monthly: "Monthly" };

export function EventDetail({ occ, onClose, onEdit }: { occ: Occurrence; onClose: () => void; onEdit: () => void }) {
  const { api, people, askPin, toast } = useApp();
  const [cals] = useData((a) => a.calendars(), ["accounts"], []);
  const cal = occ.calendar_id ? cals?.find((c) => c.id === occ.calendar_id) : undefined;
  const readOnly = !!(occ.read_only || cal?.read_only);
  const title = evTitle(occ, people);
  const who = occ.person_ids.map((id) => people.find((p) => p.id === id)).filter(Boolean);
  const lastDay = occ.all_day ? addDays(occ.end.slice(0, 10), -1) : occ.end.slice(0, 10);
  async function del() {
    const pin = await askPin(`Delete “${occ.title}”${occ.recurring ? " and all its repeats" : ""}?`);
    if (!pin) return;
    try {
      await api.deleteEvent(occ.id);
      toast("Event deleted");
      onClose();
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Couldn't delete");
      if (e instanceof ApiError && e.status === 409) onClose();
    }
  }
  return (
    <Sheet title={title} onClose={onClose} footer={<>
      {!readOnly && <button className="btn ghost danger" onClick={del}><IconTrash size={20} /> Delete</button>}
      <span style={{ flex: 1 }} />
      {!readOnly && <button className="btn" onClick={onEdit}>Edit</button>}
    </>}>
      <div className="detail">
        <div className="detail-when">
          <strong>{fmtFull(occ.start.slice(0, 10))}{lastDay !== occ.start.slice(0, 10) ? ` – ${fmtFull(lastDay)}` : ""}</strong>
          <span>{occ.all_day ? "All day" : `${fmtTime(occ.start)} – ${fmtTime(occ.end)}`}</span>
        </div>
        {occ.location && <div className="detail-row"><IconPin size={20} /> {occ.location}</div>}
        {occ.custom_repeat && <div className="detail-row"><IconRepeat size={20} /> Repeats (custom pattern set in {occ.source === "icloud" ? "iCloud" : occ.source === "ics" ? "the published calendar" : occ.source === "ha" ? "Home Assistant" : "the calendar app"})</div>}
        {occ.repeat && <div className="detail-row"><IconRepeat size={20} /> Repeats {REPEAT_LABEL[occ.repeat.freq].toLowerCase()}{occ.repeat.byday?.length ? ` on ${occ.repeat.byday.map((d) => d[0] + d[1].toLowerCase()).join(", ")}` : ""}{occ.repeat.skip_holidays ? ", not on public holidays" : ""}</div>}
        <div className="detail-people">
          {who.map((p) => <span key={p!.id} className="chip" style={{ background: p!.color + "22" }}><Avatar person={p!} size={1.6} /> {p!.name}</span>)}
        </div>
        {occ.busy && (PLACEHOLDER.test(occ.title.trim())
          ? <p className="muted connect-note">This calendar only shares when {who.length === 1 ? who[0]!.name + " is" : "they're"} busy, not what's on.</p>
          : <div className="detail-row">{occ.title}</div>)}
        {occ.notes && <p className="detail-notes">{occ.notes}</p>}
        {occ.source && (
          <div className="detail-source"><IconCloud size={18} /> {occ.source === "icloud" ? "iCloud" : occ.source === "ics" ? "Calendar link" : occ.source === "ha" ? "Home Assistant" : "CalDAV"}{cal ? ` · ${cal.name}` : ""}{readOnly ? " · read-only" : ""}</div>
        )}
      </div>
    </Sheet>
  );
}

export function EventForm({ initial, id, onClose }: { initial: EventIn; id?: string; onClose: () => void }) {
  const { api, people, settings, toast } = useApp();
  const [cals] = useData((a) => a.calendars(), ["accounts"], []);
  const custom = !!(initial as Partial<CalEvent>).custom_repeat;
  // undefined = follow the default (first visible, writable calendar mapped to the first person).
  const [calChoice, setCalChoice] = useState<string | null | undefined>(id ? initial.calendar_id ?? null : undefined);
  const [title, setTitle] = useState(initial.title);
  const [who, setWho] = useState<string[]>(initial.person_ids);
  const [date, setDate] = useState(initial.start.slice(0, 10));
  const [allDay, setAllDay] = useState(initial.all_day);
  const [start, setStart] = useState(initial.all_day ? "09:00" : initial.start.slice(11, 16));
  const [end, setEnd] = useState(initial.all_day ? "10:00" : initial.end.slice(11, 16));
  const [repeat, setRepeat] = useState<Freq | "none">(initial.repeat?.freq ?? "none");
  const [days, setDays] = useState<string[]>(initial.repeat?.byday?.length ? initial.repeat.byday : [dayCode(initial.start.slice(0, 10))]);
  const [skipHolidays, setSkipHolidays] = useState(!!initial.repeat?.skip_holidays);
  const region = useHolidayRegionName();
  const [location, setLocation] = useState(initial.location ?? "");
  const [busy, setBusy] = useState(false);
  // Before any people exist (or if everyone on it was removed) an event can be saved for nobody.
  const valid = title.trim() && (who.length || people.length === 0) && (allDay || end > start);
  const writable = (cals ?? []).filter((c) => !c.read_only && (c.visible || c.id === initial.calendar_id));
  const autoCal = pickCalendar(writable, who);
  const calendarId = calChoice === undefined ? autoCal : calChoice;

  // A weekly repeat on just the old date's weekday follows the date to its new weekday.
  function pickDate(d: string) {
    if (d && days.length === 1 && days[0] === dayCode(date)) setDays([dayCode(d)]);
    setDate(d);
  }

  async function save() {
    if (!valid) return;
    setBusy(true);
    // A weekly series starts on its first chosen day on or after the date picked.
    let first = date;
    if (repeat === "weekly") while (!days.includes(dayCode(first))) first = addDays(first, 1);
    const body: EventIn = {
      title: title.trim(), person_ids: who, all_day: allDay, location,
      start: allDay ? `${first}T00:00` : `${first}T${start}`,
      end: allDay ? `${addDays(first, 1)}T00:00` : `${first}T${end}`,
      repeat: repeat === "none" ? null : {
        freq: repeat, interval: 1, byday: repeat === "weekly" ? days : undefined, until: null,
        ...(skipHolidays ? { skip_holidays: true } : {}),
      },
    };
    if (writable.length || (cals ?? []).length) body.calendar_id = calendarId;
    const patch: Partial<EventIn> = { ...body };
    if (custom) delete patch.repeat; // keep iCloud's own rule (exceptions, moved dates...)
    if (custom && first === initial.start.slice(0, 10) && allDay === initial.all_day && (allDay || (start === initial.start.slice(11, 16) && end === initial.end.slice(11, 16)))) {
      delete patch.start; delete patch.end; // don't move the series to this occurrence
    }
    try {
      if (id) await api.updateEvent(id, patch); else await api.createEvent(body);
      toast(id ? "Event updated" : "Event added");
      onClose();
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Couldn't save the event");
      if (e instanceof ApiError && e.status === 409) onClose(); // the latest version is on screen now
    } finally { setBusy(false); }
  }

  return (
    <Sheet title={id ? "Edit event" : "New event"} onClose={onClose} footer={<>
      <button className="btn ghost" onClick={onClose}>Cancel</button>
      <span style={{ flex: 1 }} />
      <button className="btn" disabled={!valid || busy} onClick={save}>{id ? "Save" : "Add event"}</button>
    </>}>
      <div className="form">
        <input className="input big" placeholder="What's happening?" value={title} onChange={(e) => setTitle(e.target.value)} autoFocus />
        <label className="field-label">Who</label>
        <PersonPicker people={people} value={who} onChange={setWho} />
        {people.length === 0 && <p className="muted form-note">Add your family in Settings › Family to colour-code events by person.</p>}
        <div className="form-row">
          <div><label className="field-label">Date</label><input className="input" type="date" value={date} onChange={(e) => pickDate(e.target.value)} /></div>
          <div>
            <label className="field-label">All day</label>
            <button className={"toggle" + (allDay ? " on" : "")} onClick={() => setAllDay(!allDay)} aria-pressed={allDay}><span /></button>
          </div>
        </div>
        {!allDay && (
          <div className="form-row">
            <div><label className="field-label">Starts</label><input className="input" type="time" step={300} value={start} onChange={(e) => setStart(e.target.value)} /></div>
            <div><label className="field-label">Ends</label><input className="input" type="time" step={300} value={end} onChange={(e) => setEnd(e.target.value)} /></div>
          </div>
        )}
        <label className="field-label">Repeats</label>
        {custom
          ? <p className="muted form-note">Custom pattern from iCloud. Change how it repeats on a phone or Mac.</p>
          : <Segmented value={repeat} onChange={setRepeat} options={(["none", "daily", "weekly", "monthly"] as const).map((v) => ({ value: v, label: REPEAT_LABEL[v] }))} />}
        {!custom && repeat === "weekly" && <DayPicker value={days} onChange={setDays} weekStart={settings?.week_start} />}
        {!custom && repeat !== "none" && <HolidaySwitch value={skipHolidays} onChange={setSkipHolidays} region={region} />}
        {writable.length > 0 && (<>
          <label className="field-label">Calendar</label>
          <div className="chip-row cal-chooser">
            {writable.map((c) => (
              <button key={c.id} className={"chip-btn" + (calendarId === c.id ? " on" : "")} onClick={() => setCalChoice(c.id)}>
                <i className="cal-dot" style={{ background: c.color }} />{c.name}
              </button>
            ))}
            <button className={"chip-btn" + (calendarId === null ? " on" : "")} onClick={() => setCalChoice(null)}>Only on Moonlight</button>
          </div>
        </>)}
        <label className="field-label">Location</label>
        <input className="input" placeholder="Optional" value={location} onChange={(e) => setLocation(e.target.value)} />
      </div>
    </Sheet>
  );
}

export function newEventDefaults(date: string, personIds: string[], hour = 9): EventIn {
  const hh = String(hour).padStart(2, "0"), hh2 = String(Math.min(hour + 1, 23)).padStart(2, "0");
  return { title: "", person_ids: personIds, start: `${date}T${hh}:00`, end: `${date}T${hh2}:00`, all_day: false, location: "", repeat: null };
}
