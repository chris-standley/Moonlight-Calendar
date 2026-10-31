// Countdowns for the preview, worked out the same way as the add-on's countdowns.py.
import { Countdown, CountdownIn, CountdownSuggestion, Person } from "./types";
import { ApiError } from "./types";
import { addDays, diffDays, iso } from "../dates";

/** A stored countdown, as the add-on keeps it. */
export interface CountdownRow {
  id: string; title: string; emoji: string; date: string; yearly: boolean;
  special: string | null; event_id: string | null; person_ids: string[];
}

const HOLIDAY = "holiday:";

function easter(y: number): Date { // anonymous Gregorian algorithm
  const a = y % 19, b = Math.floor(y / 100), c = y % 100, d = Math.floor(b / 4), e = b % 4;
  const f = Math.floor((b + 8) / 25), g = Math.floor((b - f + 1) / 3), h = (19 * a + b - d - g + 15) % 30;
  const i = Math.floor(c / 4), k = c % 4, l = (32 + 2 * e + 2 * i - h - k) % 7, m = Math.floor((a + 11 * h + 22 * l) / 451);
  const month = Math.floor((h + l - 7 * m + 114) / 31), day = ((h + l - 7 * m + 114) % 31) + 1;
  return new Date(y, month - 1, day);
}
const shift = (d: Date, days: number) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + days);
/** nth (1-based) weekday (0 = Sunday) of a month. */
function nth(y: number, m: number, wd: number, n: number): Date {
  const first = new Date(y, m - 1, 1);
  return new Date(y, m - 1, 1 + ((wd - first.getDay() + 7) % 7) + 7 * (n - 1));
}

type Rule = [title: string, emoji: string, when: (y: number, country: string) => Date, where?: string[]];
export const SPECIAL_DAYS: Record<string, Rule> = {
  christmas: ["Christmas", "🎄", (y) => new Date(y, 11, 25)],
  christmas_eve: ["Christmas Eve", "🎅", (y) => new Date(y, 11, 24)],
  new_years_eve: ["New Year's Eve", "🎆", (y) => new Date(y, 11, 31)],
  halloween: ["Halloween", "🎃", (y) => new Date(y, 9, 31)],
  bonfire_night: ["Bonfire Night", "🎇", (y) => new Date(y, 10, 5), ["GB"]],
  valentines: ["Valentine's Day", "❤️", (y) => new Date(y, 1, 14)],
  pancake_day: ["Pancake Day", "🥞", (y) => shift(easter(y), -47), ["GB", "IE"]],
  st_patricks: ["St Patrick's Day", "☘️", (y) => new Date(y, 2, 17), ["IE", "GB", "US"]],
  easter: ["Easter", "🐣", (y) => easter(y)],
  mothers_day: ["Mother's Day", "💐", (y, c) => (c === "GB" || c === "IE" ? shift(easter(y), -21) : nth(y, 5, 0, 2))],
  fathers_day: ["Father's Day", "👔", (y) => nth(y, 6, 0, 3)],
  thanksgiving: ["Thanksgiving", "🦃", (y) => nth(y, 11, 4, 4), ["US"]],
};

export function demoCountdowns(rows: () => CountdownRow[], people: () => Person[], country: () => string,
  holidays: (start: string, end: string) => { date: string; name: string }[],
  nextOfEvent: (id: string, today: string) => string | null, emit: () => void) {
  function specialDate(key: string, y: number): string | null {
    if (key.startsWith(HOLIDAY)) return holidays(`${y}-01-01`, `${y}-12-31`).find((h) => h.name === key.slice(HOLIDAY.length))?.date ?? null;
    const r = SPECIAL_DAYS[key];
    return r ? iso(r[2](y, country())) : null;
  }
  function nextSpecial(key: string, t: string): string | null {
    const y = Number(t.slice(0, 4));
    for (let yy = y; yy <= y + 2; yy++) { const d = specialDate(key, yy); if (d && d >= t) return d; }
    return null;
  }
  const onYear = (md: string, y: number) => (md === "02-29" && !(y % 4 === 0 && (y % 100 !== 0 || y % 400 === 0)) ? `${y}-02-28` : `${y}-${md}`);
  const nextYearly = (md: string, t: string) => { const y = Number(t.slice(0, 4)); const d = onYear(md, y); return d >= t ? d : onYear(md, y + 1); };
  const base = (o: Partial<Countdown> & Pick<Countdown, "id" | "kind" | "title" | "emoji" | "date">, t: string): Countdown =>
    ({ person_ids: [], yearly: false, special: null, event_id: null, turns: null, ...o, days: diffDays(o.date, t) });

  function list(t: string): Countdown[] {
    const known = new Set(people().map((p) => p.id));
    const out: Countdown[] = [];
    for (const r of rows()) {
      let kind: Countdown["kind"] = "custom", date = r.date;
      if (r.event_id) { kind = "event"; date = nextOfEvent(r.event_id, t) ?? r.date; }
      else if (r.special) { kind = "special"; date = nextSpecial(r.special, t) ?? r.date; }
      else if (r.yearly) date = nextYearly(r.date.slice(5), t);
      if (date < t) continue;
      out.push(base({ ...r, kind, date, person_ids: r.person_ids.filter((p) => known.has(p)) }, t));
    }
    for (const p of people()) {
      if (!p.birthday) continue;
      const md = p.birthday.slice(-5), year = p.birthday.length === 10 ? Number(p.birthday.slice(0, 4)) : null;
      const date = nextYearly(md, t), y = Number(date.slice(0, 4));
      out.push(base({ id: `birthday:${p.id}`, kind: "birthday", title: `${p.name}'s birthday`, emoji: "🎂", date,
        person_ids: [p.id], yearly: true, turns: year && y > year ? y - year : null }, t));
    }
    return out.sort((a, b) => a.date.localeCompare(b.date) || Number(a.kind === "birthday") - Number(b.kind === "birthday") || a.title.localeCompare(b.title));
  }

  function apply(row: CountdownRow, c: CountdownIn, creating: boolean): CountdownRow {
    const t = iso(new Date());
    if (c.special) {
      if (!SPECIAL_DAYS[c.special] && !(c.special.startsWith(HOLIDAY) && c.special.length > HOLIDAY.length)) throw new ApiError(400, "special must be one of the well-known days");
      const d = nextSpecial(c.special, t);
      if (!d) throw new ApiError(400, "That day isn't coming up in the next two years");
      row = { ...row, special: c.special, event_id: null, date: d, yearly: true };
      if (creating) { const r = SPECIAL_DAYS[c.special]; row.title = r ? r[0] : c.special.slice(HOLIDAY.length); row.emoji = r ? r[1] : "🗓️"; }
    } else if (c.special === null) row.special = null;
    if (c.event_id) {
      const d = nextOfEvent(c.event_id, t);
      row = { ...row, event_id: c.event_id, special: null, date: d ?? row.date ?? t };
    } else if (c.event_id === null) row.event_id = null;
    if (c.title !== undefined) {
      const title = c.title.trim();
      if (!title) throw new ApiError(400, "title is required");
      if (title.length > 60) throw new ApiError(400, "title must be at most 60 characters");
      row.title = title;
    }
    if (c.emoji !== undefined) row.emoji = c.emoji.trim();
    if (c.date !== undefined && !row.special) row.date = c.date;
    if (c.yearly !== undefined && !row.special) row.yearly = c.yearly;
    if (c.person_ids) row.person_ids = c.person_ids;
    if (creating && !row.title) throw new ApiError(400, "title is required");
    if (creating && !row.date) throw new ApiError(400, "date is required");
    return row;
  }
  const find = (id: string) => { const r = rows().find((x) => x.id === id); if (!r) throw new ApiError(404, "Countdown not found"); return r; };
  const one = (id: string) => {
    const t = iso(new Date());
    return list(t).find((x) => x.id === id) ?? (() => { const r = find(id); return base({ ...r, kind: "custom" }, t); })();
  };

  return {
    countdowns: async (t: string) => list(t),
    async countdownSuggestions(t: string): Promise<CountdownSuggestion[]> {
      const taken = new Set(rows().map((r) => r.special).filter(Boolean));
      const out: CountdownSuggestion[] = [], dates = new Set<string>();
      for (const [key, [title, emoji, , where]] of Object.entries(SPECIAL_DAYS)) {
        if (where && !where.includes(country())) continue;
        const d = nextSpecial(key, t);
        if (!d) continue;
        dates.add(d);
        out.push({ special: key, title, emoji, date: d, days: diffDays(d, t), taken: taken.has(key) });
      }
      const seen = new Set<string>();
      for (const h of holidays(t, addDays(t, 366))) {
        const key = HOLIDAY + h.name;
        if (dates.has(h.date) || seen.has(key) || h.name.includes("(observed)")) continue;
        seen.add(key);
        out.push({ special: key, title: h.name, emoji: "🗓️", date: h.date, days: diffDays(h.date, t), taken: taken.has(key) });
      }
      return out.sort((a, b) => a.date.localeCompare(b.date));
    },
    async createCountdown(c: CountdownIn) {
      const row = apply({ id: `cd_${Date.now().toString(36)}`, title: "", emoji: "", date: "", yearly: false, special: null, event_id: null, person_ids: [] }, c, true);
      rows().push(row); emit(); return one(row.id);
    },
    async updateCountdown(id: string, patch: CountdownIn) {
      const r = find(id);
      Object.assign(r, apply({ ...r }, patch, false)); emit(); return one(id);
    },
    async deleteCountdown(id: string) {
      find(id);
      const all = rows(); all.splice(all.findIndex((x) => x.id === id), 1); emit();
    },
  };
}
