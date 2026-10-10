// Household-local date helpers. Dates are "YYYY-MM-DD", datetimes "YYYY-MM-DDTHH:MM" (no zone).

export const DAY_CODES = ["SU", "MO", "TU", "WE", "TH", "FR", "SA"];

const pad = (n: number) => String(n).padStart(2, "0");

export function iso(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}
export function isoDT(d: Date): string {
  return `${iso(d)}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
export function parse(s: string): Date {
  const [date, time = "00:00"] = s.split("T");
  const [y, m, d] = date.split("-").map(Number);
  const [hh, mm] = time.split(":").map(Number);
  return new Date(y, m - 1, d, hh, mm);
}
export function addDays(s: string, n: number): string {
  const d = parse(s);
  d.setDate(d.getDate() + n);
  return iso(d);
}
export function today(): string {
  return iso(new Date());
}
export function dayCode(s: string): string {
  return DAY_CODES[parse(s).getDay()];
}
export function diffDays(a: string, b: string): number {
  // whole days from b to a
  const pa = parse(a.slice(0, 10)), pb = parse(b.slice(0, 10));
  return Math.round((pa.getTime() - pb.getTime()) / 86400000);
}
export function weekStart(s: string, start: "monday" | "sunday"): string {
  const dow = parse(s).getDay();
  const back = start === "monday" ? (dow + 6) % 7 : dow;
  return addDays(s, -back);
}
export function monthStart(s: string): string {
  return s.slice(0, 8) + "01";
}
export function addMonths(s: string, n: number): string {
  const d = parse(s);
  return iso(new Date(d.getFullYear(), d.getMonth() + n, 1));
}
export function timeOf(s: string): string {
  return s.slice(11, 16);
}
export function fmtTime(s: string): string {
  const [h, m] = timeOf(s).split(":").map(Number);
  const ap = h < 12 ? "am" : "pm";
  const h12 = h % 12 === 0 ? 12 : h % 12;
  return m === 0 ? `${h12}${ap}` : `${h12}:${pad(m)}${ap}`;
}
export function minutesOf(s: string): number {
  const [h, m] = timeOf(s).split(":").map(Number);
  return h * 60 + m;
}

const fmt = (o: Intl.DateTimeFormatOptions) => new Intl.DateTimeFormat("en-GB", o);
const F = {
  dow: fmt({ weekday: "short" }),
  dowLong: fmt({ weekday: "long" }),
  dm: fmt({ day: "numeric", month: "short" }),
  dml: fmt({ day: "numeric", month: "long" }),
  my: fmt({ month: "long", year: "numeric" }),
  full: fmt({ weekday: "long", day: "numeric", month: "long" }),
};
export const fmtDow = (s: string) => F.dow.format(parse(s));
export const fmtDowLong = (s: string) => F.dowLong.format(parse(s));
export const fmtDayMonth = (s: string) => F.dm.format(parse(s));
export const fmtDayMonthLong = (s: string) => F.dml.format(parse(s));
export const fmtMonthYear = (s: string) => F.my.format(parse(s));
export const fmtFull = (s: string) => F.full.format(parse(s));
export const dayNum = (s: string) => parse(s).getDate();

export function relativeDay(s: string): string {
  const d = diffDays(s, today());
  if (d === 0) return "Today";
  if (d === 1) return "Tomorrow";
  if (d === -1) return "Yesterday";
  return fmtDowLong(s);
}
