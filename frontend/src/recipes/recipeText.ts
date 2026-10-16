// Showing recipe amounts (scaled, with metric alongside), and the same reading of recipe text the add-on does
// (backend/moonlight/recipe_text.py), which the in-browser demo needs. Keep the two in step.
import { Ingredient, StepTimer } from "../api/types";

// ---------------------------------------------------------------- showing amounts

const FRACTIONS: [number, string][] = [[1 / 8, "⅛"], [1 / 4, "¼"], [1 / 3, "⅓"], [3 / 8, "⅜"], [1 / 2, "½"], [5 / 8, "⅝"], [2 / 3, "⅔"], [3 / 4, "¾"], [7 / 8, "⅞"]];
const PLURAL: Record<string, string> = {
  cup: "cups", pint: "pints", quart: "quarts", gallon: "gallons", stick: "sticks", pinch: "pinches", dash: "dashes",
  clove: "cloves", can: "cans", tin: "tins", jar: "jars", pack: "packs", slice: "slices", bunch: "bunches",
  handful: "handfuls", sprig: "sprigs", piece: "pieces",
};
const METRIC_UNITS = new Set(["g", "kg", "mg", "ml", "l", "cl", "dl"]);

/** Kitchen-friendly rounding of grams and millilitres: 7.5 g, 45 g, 225 g, 1.2 kg. */
export function roundMetric(v: number, unit: string): [number, string] {
  if ((unit === "g" || unit === "ml") && v >= 1000) return [Math.round(v / (v < 10000 ? 10 : 100)) / (v < 10000 ? 100 : 10), unit === "g" ? "kg" : "l"];
  if (v < 10) return [Math.round(v * 2) / 2, unit];
  if (v < 100) return [Math.round(v), unit];
  return [Math.round(v / 5) * 5, unit];
}

/** 2.5 -> "2½", 0.333 -> "⅓", 12.4 -> "12", 1.15 -> "1.2". */
export function fmtNumber(v: number): string {
  if (v >= 20) return String(Math.round(v));
  const whole = Math.floor(v);
  const frac = v - whole;
  if (frac < 0.04) return String(whole);
  if (frac > 0.96) return String(whole + 1);
  const near = FRACTIONS.find(([f]) => Math.abs(frac - f) < 0.04);
  if (near) return (whole ? String(whole) : "") + near[1];
  return String(Math.round(v * 10) / 10);
}

function amount(q: number, qmax: number | null, unit: string): string {
  if (METRIC_UNITS.has(unit) && (unit === "g" || unit === "ml")) {
    const [a, u] = roundMetric(q, unit);
    const b = qmax != null ? roundMetric(qmax, unit)[0] : null;
    return `${fmtNumber(a)}${b != null ? `–${fmtNumber(b)}` : ""} ${u}`;
  }
  const n = `${fmtNumber(q)}${qmax != null ? `–${fmtNumber(qmax)}` : ""}`;
  if (!unit) return n;
  return `${n} ${(qmax ?? q) > 1 && PLURAL[unit] ? PLURAL[unit] : unit}`;
}

/** The amount in metric, scaled, or null when the line is already metric (or has no amount). */
export function metricAmount(ing: Ingredient, factor = 1): string | null {
  const m = ing.metric;
  if (!m || ing.quantity == null) return null;
  return amount(m.quantity * factor, m.quantity_max != null ? m.quantity_max * factor : null, m.unit);
}

/** An ingredient as shown: scaled ("2½ cups plain flour, sifted"), or the saved line when it has no amount. */
export function ingredientLine(ing: Ingredient, factor = 1, withNote = true): string {
  if (ing.heading) return ing.name;
  if (ing.quantity == null) return ing.text;
  if (factor === 1 && withNote) return ing.text;
  const amt = amount(ing.quantity * factor, ing.quantity_max != null ? ing.quantity_max * factor : null, ing.unit);
  return `${amt} ${ing.name}${withNote && ing.note ? `, ${ing.note}` : ""}`.trim();
}

/** What goes on the shopping list: the scaled amount, with metric in brackets, without preparation notes. */
export function shoppingLine(ing: Ingredient, factor = 1): string {
  if (ing.quantity == null) return ing.text.replace(/,.*$/, "").trim() || ing.text;
  const m = metricAmount(ing, factor);
  return ingredientLine(ing, factor, false) + (m ? ` (${m})` : "");
}

/** "1 h 20 min", "45 min". */
export function fmtMinutes(m: number | null | undefined): string {
  if (m == null) return "";
  const h = Math.floor(m / 60), mm = Math.round(m % 60);
  return h ? (mm ? `${h} h ${mm} min` : `${h} h`) : `${mm} min`;
}

export function fmtDuration(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
  if (h) return m ? `${h} h ${m} min` : `${h} h`;
  if (m) return r ? `${m} min ${r} sec` : `${m} min`;
  return `${r} sec`;
}

/** Countdown clock: "4:05", "1:02:00". */
export function fmtClock(seconds: number): string {
  const s = Math.max(0, Math.ceil(seconds));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  return h ? `${h}:${pad(m)}:${pad(r)}` : `${m}:${pad(r)}`;
}

// ---------------------------------------------------------------- reading (demo only; the add-on does this itself)

const UF: Record<string, number> = { "½": 1 / 2, "⅓": 1 / 3, "⅔": 2 / 3, "¼": 1 / 4, "¾": 3 / 4, "⅕": 1 / 5, "⅖": 2 / 5, "⅗": 3 / 5, "⅘": 4 / 5, "⅙": 1 / 6, "⅚": 5 / 6, "⅛": 1 / 8, "⅜": 3 / 8, "⅝": 5 / 8, "⅞": 7 / 8 };
const UFC = Object.keys(UF).join("");
const NUM = `(?:\\d+\\s*[${UFC}]|\\d+\\s+\\d+\\s*/\\s*\\d+|\\d+\\s*/\\s*\\d+|\\d+(?:[.,]\\d+)?|[${UFC}])`;
const RANGE_SEP = "\\s*(?:-|–|—|to|or)\\s*";

export function toNumber(s: string): number | null {
  let t = s.trim(), total = 0;
  for (const [ch, v] of Object.entries(UF)) if (t.includes(ch)) { total += v; t = t.split(ch).join(" "); }
  t = t.trim().replace(/\s+/g, " ");
  const m = t.match(/^(?:(\d+)\s+)?(\d+)\s*\/\s*(\d+)$/);
  if (m) {
    if (+m[3] === 0) return null;
    total += (+(m[1] ?? 0)) + (+m[2]) / (+m[3]);
  } else if (t) {
    const n = Number(t.replace(",", "."));
    if (Number.isNaN(n)) return null;
    total += n;
  }
  return Math.round(total * 10000) / 10000;
}

const UNIT_ALIASES: Record<string, string[]> = {
  g: ["g", "gr", "grs", "gram", "grams", "gramme", "grammes"], kg: ["kg", "kgs", "kilo", "kilos", "kilogram", "kilograms"],
  mg: ["mg"], ml: ["ml", "mls", "millilitre", "millilitres", "milliliter", "milliliters"], cl: ["cl"], dl: ["dl"],
  l: ["l", "ltr", "litre", "litres", "liter", "liters"], tsp: ["tsp", "tsps", "teaspoon", "teaspoons", "tspn"],
  tbsp: ["tbsp", "tbsps", "tbs", "tbl", "tbls", "tablespoon", "tablespoons", "tblsp"], cup: ["cup", "cups"],
  "fl oz": ["fl oz", "fl. oz", "fl.oz", "floz", "fluid ounce", "fluid ounces"], oz: ["oz", "ozs", "ounce", "ounces"],
  lb: ["lb", "lbs", "pound", "pounds"], pint: ["pint", "pints", "pt", "pts"], quart: ["quart", "quarts", "qt", "qts"],
  gallon: ["gallon", "gallons", "gal"], stick: ["stick", "sticks"], pinch: ["pinch", "pinches"], dash: ["dash", "dashes"],
  clove: ["clove", "cloves"], can: ["can", "cans"], tin: ["tin", "tins"], jar: ["jar", "jars"],
  pack: ["pack", "packs", "packet", "packets"], slice: ["slice", "slices"], bunch: ["bunch", "bunches"],
  handful: ["handful", "handfuls"], sprig: ["sprig", "sprigs"], piece: ["piece", "pieces"],
};
const ALIAS: Record<string, string> = {};
for (const [u, as] of Object.entries(UNIT_ALIASES)) for (const a of as) ALIAS[a] = u;
const esc = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const UNIT_RE = Object.keys(ALIAS).sort((a, b) => b.length - a.length).map((a) => esc(a).replace(/ /g, "\\s*")).join("|");
const METRIC: Record<string, ["g" | "ml", number]> = {
  cup: ["ml", 240], "fl oz": ["ml", 29.57], pint: ["ml", 568], quart: ["ml", 946], gallon: ["ml", 3785],
  oz: ["g", 28.35], lb: ["g", 453.6], stick: ["g", 113],
};
const INGREDIENT_RE = new RegExp(
  `^\\s*(?:[-•*·▪●]\\s*)?(?<q>${NUM})(?:${RANGE_SEP}(?<q2>${NUM}))?\\s*(?:\\((?<paren>[^)]{1,40})\\)\\s*)?` +
  `(?:(?<unit>${UNIT_RE})\\.?(?![\\w]))?\\s*(?:of\\s+)?(?<rest>.*)$`, "i");
const HEADING_RE = /^(?:for\s+(?:the\s+)?[\w\s,&'-]{2,40}|[\w\s,&'-]{2,40}):\s*$/i;

function canonUnit(raw: string): string {
  const key = raw.toLowerCase().replace(/[\s.]+/g, " ").trim();
  return ALIAS[key] ?? ALIAS[key.replace(/ /g, "")] ?? key;
}
const round1 = (v: number) => Math.round(v * 10) / 10;
function metricOf(q: number | null, qmax: number | null, unit: string): Ingredient["metric"] {
  if (q == null || !METRIC[unit]) return null;
  const [to, f] = METRIC[unit];
  return { quantity: round1(q * f), quantity_max: qmax == null ? null : round1(qmax * f), unit: to };
}

export function parseIngredient(line: string): Ingredient {
  const text = (line ?? "").trim().replace(/\s+/g, " ");
  const out: Ingredient = { text, quantity: null, quantity_max: null, unit: "", name: text, note: "", heading: false, metric: null };
  if (!text) return out;
  if (HEADING_RE.test(text) && !new RegExp(`^\\s*${NUM}`).test(text)) return { ...out, heading: true, name: text.replace(/:\s*$/, "").trim() };
  const m = text.match(INGREDIENT_RE);
  let rest = text;
  if (m?.groups) {
    const q = toNumber(m.groups.q);
    const q2 = m.groups.q2 ? toNumber(m.groups.q2) : null;
    if (q != null) {
      out.quantity = q;
      out.quantity_max = q2 != null && q2 > q ? q2 : null;
      out.unit = m.groups.unit ? canonUnit(m.groups.unit) : "";
      rest = m.groups.rest.trim();
      if (m.groups.paren) out.note = m.groups.paren.trim();
    }
  }
  const comma = rest.indexOf(",");
  const name = (comma >= 0 ? rest.slice(0, comma) : rest).trim();
  const note = comma >= 0 ? rest.slice(comma + 1).trim() : "";
  if (note) out.note = [out.note, note].filter(Boolean).join(", ");
  out.name = name || rest || text;
  out.metric = metricOf(out.quantity, out.quantity_max, out.unit);
  return out;
}

const WORD_NUM: Record<string, number> = { a: 1, an: 1, one: 1, two: 2, three: 3, four: 4, five: 5, six: 6, seven: 7, eight: 8, nine: 9, ten: 10, fifteen: 15, twenty: 20, thirty: 30, forty: 40, sixty: 60 };
const DUR_NUM = `(?:${NUM}|a|an|one|two|three|four|five|six|seven|eight|nine|ten|fifteen|twenty|thirty|forty|sixty)`;
const DURATION_RE = new RegExp(
  `(?<![\\w/])(?:(?<half>half\\s+an?\\s+hour)|(?<n>${DUR_NUM})(?:${RANGE_SEP}(?<n2>${NUM}))?\\s*` +
  `(?<u>hours?|hrs?\\b|h\\b|minutes?|mins?\\b|m\\b|seconds?|secs?\\b|s\\b)` +
  `(?:\\s*(?:and\\s+)?(?<extra>${NUM})\\s*(?:minutes?|mins?\\b|m\\b))?)`, "gi");

export function findDurations(text: string): number[] {
  const found: number[] = [];
  for (const m of (text ?? "").matchAll(DURATION_RE)) {
    const g = m.groups!;
    let secs: number;
    if (g.half) secs = 1800;
    else {
      const n = g.n, u = g.u.toLowerCase();
      if (u.length === 1 && /\s/.test(m[0].charAt(n.length))) continue;
      const v = /^[a-z]+$/i.test(n.trim()) ? WORD_NUM[n.trim().toLowerCase()] : toNumber(n);
      if (v == null) continue;
      secs = Math.round(v * (u.startsWith("h") ? 3600 : u.startsWith("m") ? 60 : 1));
      if (g.extra && u.startsWith("h")) secs += Math.round((toNumber(g.extra) ?? 0) * 60);
    }
    if (secs >= 5 && secs <= 86400 && !found.includes(secs)) found.push(secs);
  }
  return found;
}

export function stepTimers(text: string, minutes: number | null | undefined): StepTimer[] {
  const secs = findDurations(text);
  if (minutes) {
    const own = Math.round(minutes * 60);
    if (!secs.includes(own)) secs.unshift(own);
  }
  return secs.map((s) => ({ seconds: s, label: fmtDuration(s) }));
}

// Words that describe an ingredient rather than name it ("2 large free-range eggs" is "eggs" in the method).
const FILLER = new Set(["large", "small", "medium", "big", "fresh", "dried", "frozen", "ripe", "chopped", "sliced", "diced",
  "minced", "grated", "crushed", "ground", "whole", "tin", "tins", "can", "cans", "jar", "pack", "packet",
  "of", "and", "or", "the", "a", "an", "free", "range", "organic", "unsalted", "salted", "plain", "extra",
  "virgin", "light", "dark", "finely", "roughly", "thinly", "boneless", "skinless", "good", "quality",
  "heaped", "level", "about", "approx", "x"]);

function singular(word: string): string {
  if (word.endsWith("ies") && word.length > 4) return word.slice(0, -3) + "y";
  if (word.endsWith("oes") || word.endsWith("ches") || word.endsWith("shes")) return word.slice(0, -2);
  if (word.endsWith("s") && !word.endsWith("ss") && word.length > 3) return word.slice(0, -1);
  return word;
}

/** A word in the singular or plural: egg / eggs, tomato / tomatoes, berry / berries. */
function forms(word: string): string {
  const stem = singular(word);
  if (stem.endsWith("y")) return `(?:${esc(stem)}|${esc(stem.slice(0, -1))}ies)`;
  return `${esc(stem)}(?:e?s)?`;
}

/** Which ingredients a step mentions, in the order it mentions them (indexes), so screens can show their amounts. */
export function stepUses(text: string, ingredients: Ingredient[]): number[] {
  // "Season with salt and pepper" isn't about the peppers on the list.
  const low = (text ?? "").toLowerCase().replace(/salt\s*(?:and|&)\s*(?:black\s+)?pepper/g, (m) => " ".repeat(m.length));
  const words = new Map<number, string[]>();
  ingredients.forEach((ing, i) => {
    if (!ing.heading && ing.quantity != null) words.set(i, ((ing.name ?? "").toLowerCase().match(/[a-z]+/g) ?? []).filter((w) => !FILLER.has(w)));
  });
  const heads = [...words.values()].filter((ws) => ws.length).map((ws) => singular(ws[ws.length - 1]));
  const found: [number, number][] = [];
  for (const [i, ws] of words) {
    if (!ws.length) continue;
    const last = ws[ws.length - 1];
    const pats: string[] = [];
    if (ws.length > 1) pats.push([...ws.slice(0, -1).map(esc), forms(last)].join("\\s+"));
    if (last.length >= 3 && heads.filter((h) => h === singular(last)).length === 1) pats.push(forms(last));
    let best: number | null = null;
    for (const pat of pats) {
      const m = new RegExp(`(?<![a-z])${pat}(?![a-z])`).exec(low);
      if (m && (best == null || m.index < best)) best = m.index;
    }
    if (best != null) found.push([best, i]);
  }
  return found.sort((a, b) => a[0] - b[0] || a[1] - b[1]).map(([, i]) => i);
}

const nice = (v: number) => (Number.isInteger(v) ? String(v) : v.toFixed(1).replace(/\.?0+$/, ""));
const TEMP_RE = /(\d{2,3})\s*(?:°|º|˚|degrees?\s*)\s*F(?:ahrenheit)?\b|(\d{3})\s*F\b/g;
const INCH_RE = /(\d+(?:\.\d+)?)(?:\s*[x×]\s*(\d+(?:\.\d+)?))?(?:\s*-\s*|\s*)(?:inch(?:es)?\b|in\.(?!\w)|″|")/g;
const AMOUNT_RE = new RegExp(`(${NUM})\\s*(cups?|fl\\.?\\s*oz|fluid\\s+ounces?|oz|ounces?|lbs?|pounds?|pints?|quarts?)\\b(?!\\s*\\()`, "gi");

export function metricNote(text: string): string | null {
  let changed = false;
  let out = (text ?? "").replace(TEMP_RE, (all, a, b) => {
    const f = Number(a ?? b);
    if (f < 150 || f > 550) return all;
    changed = true;
    return `${all} (${Math.round((f - 32) * 5 / 9 / 5) * 5}°C)`;
  });
  out = out.replace(INCH_RE, (all, a, b) => {
    if (Number(a) > 40) return all;
    changed = true;
    const cm = (x: number) => nice(Math.round(x * 2.54 * 2) / 2);
    return b ? `${all} (${cm(Number(a))} x ${cm(Number(b))} cm)` : `${all} (${cm(Number(a))} cm)`;
  });
  out = out.replace(AMOUNT_RE, (all, q, u) => {
    const met = metricOf(toNumber(q), null, canonUnit(u));
    if (!met) return all;
    changed = true;
    const [v, unit] = roundMetric(met.quantity, met.unit);
    return `${all} (${nice(v)} ${unit})`;
  });
  return changed ? out : null;
}

export function isoMinutes(v: unknown): number | null {
  if (typeof v !== "string") return null;
  const m = v.trim().match(/^P(?:(\d+)D)?(?:T(?:(\d+(?:\.\d+)?)H)?(?:(\d+(?:\.\d+)?)M)?(?:(\d+(?:\.\d+)?)S)?)?$/i);
  if (!m || !m.slice(1).some(Boolean)) return null;
  const [d, h, mi, s] = m.slice(1).map((x) => (x ? Number(x) : 0));
  return Math.round(d * 1440 + h * 60 + mi + s / 60) || null;
}

const ING_HEAD = /^\s*(ingredients?|you(?:'ll)? need|what you need|shopping list)\s*:?\s*$/i;
const STEP_HEAD = /^\s*(method|directions?|instructions?|preparation|steps?|how to make(?: it)?|to make)\s*:?\s*$/i;
const NOTES_HEAD = /^\s*(notes?|tips?|cook'?s notes?)\s*:?\s*$/i;
const SERVES_RE = /\b(?:serves|servings|portions|makes|yield|feeds)\s*:?\s*(?:about\s+)?(\d+)/i;
const TIME_LINE_RE = /\b(prep(?:aration)?|cook(?:ing)?|total|ready in)(?:\s*time)?\s*:?\s*(.+)/i;
const STEP_NUM_RE = /^\s*(?:step\s*)?(\d{1,2})\s*[.):]?\s+(?=\S)/i;
const looksLikeIngredient = (ln: string) => new RegExp(`^\\s*(?:[-•*·▪●]\\s*)?${NUM}`).test(ln) && ln.length < 90;

export interface TextDraft {
  title: string; description: string; servings: number | null; prep_minutes: number | null; cook_minutes: number | null;
  minutes: number | null; ingredients: string[]; steps: { text: string; minutes: number | null }[]; notes: string;
}

/** Same rules as the add-on's parse_text: title, Ingredients/Method headings, numbered steps, serves, times. */
export function parseText(text: string): TextDraft {
  const lines = (text ?? "").replace(/\r/g, "\n").split("\n").map((l) => l.replace(/\s+/g, " ").trim());
  const out: TextDraft = { title: "", description: "", servings: null, prep_minutes: null, cook_minutes: null, minutes: null, ingredients: [], steps: [], notes: "" };
  let section: "intro" | "ingredients" | "steps" | "notes" = "intro";
  const intro: string[] = [], ings: string[] = [], notes: string[] = [];
  const stepLines: [string, boolean][] = [];
  let blank = false;
  for (const ln of lines) {
    if (!ln) { blank = true; continue; }
    if (ING_HEAD.test(ln)) section = "ingredients";
    else if (STEP_HEAD.test(ln)) section = "steps";
    else if (NOTES_HEAD.test(ln) && section === "steps") section = "notes";
    else {
      let meta = false;
      if (section === "intro" || section === "ingredients") {
        const sv = ln.match(SERVES_RE);
        if (sv && ln.length < 60) { out.servings ??= Number(sv[1]); meta = true; }
        for (const part of ln.split(/(?=\b(?:prep|cook|total)\b)/i)) {
          const tm = part.match(TIME_LINE_RE);
          const secs = tm && ln.length < 80 ? findDurations(tm[2]) : [];
          const mins = secs.length ? Math.round(secs[0] / 60) || null : null;
          if (tm && mins) {
            const k = tm[1].toLowerCase();
            const field = k.startsWith("prep") ? "prep_minutes" : k.startsWith("cook") ? "cook_minutes" : "minutes";
            out[field] ??= mins;
            meta = true;
          }
        }
      }
      if (!meta) {
        if (section === "intro") {
          if (!out.title) out.title = ln.slice(0, 120);
          else if (looksLikeIngredient(ln) && !ings.length) { section = "ingredients"; ings.push(ln); }
          else intro.push(ln);
        } else if (section === "ingredients") {
          const last = ings[ings.length - 1];
          if (last && !looksLikeIngredient(ln) && (/^[a-z]/.test(ln) || /(,|-|and|or)$/.test(last))) ings[ings.length - 1] = `${last} ${ln}`;
          else if (ln.length > 110 && !looksLikeIngredient(ln)) { section = "steps"; stepLines.push([ln, true]); }
          else ings.push(ln);
        } else if (section === "steps") stepLines.push([ln, STEP_NUM_RE.test(ln) || blank]);
        else notes.push(ln);
      }
    }
    blank = false;
  }
  if (!stepLines.length) while (ings.length && ings[ings.length - 1].length > 70 && !looksLikeIngredient(ings[ings.length - 1])) stepLines.unshift([ings.pop()!, true]);
  const numbered = stepLines.some(([t]) => STEP_NUM_RE.test(t));
  const steps: string[] = [];
  for (const [t0, isNew] of stepLines) {
    const starts = numbered ? STEP_NUM_RE.test(t0) : isNew || /[.!)]$/.test(steps[steps.length - 1] ?? "");
    const t = numbered ? t0.replace(STEP_NUM_RE, "") : t0;
    if (starts || !steps.length) steps.push(t); else steps[steps.length - 1] += " " + t;
  }
  out.description = intro.join(" ").slice(0, 1000);
  out.ingredients = ings.map((i) => i.replace(/^[-•*·▪● ]+/, "").trim()).filter(Boolean);
  out.steps = steps.map((s) => ({ text: s.trim(), minutes: null })).filter((s) => s.text);
  out.notes = notes.join("\n");
  return out;
}
