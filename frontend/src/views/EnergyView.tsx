import { CSSProperties, ReactNode } from "react";
import { EnergyOverview, EnergyTariff, EnergyWindow } from "../api/types";
import { useApp, useData } from "../state";
import { Empty } from "../components/ui";
import { WeatherIcon } from "../components/icons";
import { fmtTime } from "../dates";

/** "774 W", "2.45 kW", "12.3 kW". */
export function fmtW(w: number | null | undefined): string {
  if (w == null) return "–";
  const a = Math.abs(w);
  if (a < 1000) return `${Math.round(a)} W`;
  return `${(a / 1000).toFixed(a < 10_000 ? 2 : 1)} kW`;
}
export const fmtKwh = (v: number | null | undefined) => (v == null ? "–" : `${v.toFixed(v < 100 ? 1 : 0)} kWh`);
const fmtT = (v: number | null | undefined) => (v == null ? null : `${Math.round(v)}°`);

const IDLE = 30;
/** Seconds for a dot to travel one gap: faster with more power. */
const speed = (w: number) => Math.max(0.35, 3.2 / (1 + Math.abs(w) / 1000));

/** A line the power runs along: dots moving from the start of `d` to its end (or back when `back`). */
function Flow({ d, w, color, back }: { d: string; w: number | null | undefined; color: string; back?: boolean }) {
  const live = w != null && Math.abs(w) >= IDLE;
  return (
    <g className="en-flow" style={{ "--c": color } as CSSProperties}>
      <path d={d} className="en-wire" />
      {live && <path d={d} className={"en-dots" + (back ? " back" : "")} style={{ animationDuration: `${speed(w!)}s` }} />}
    </g>
  );
}

/** Where a label sits on the picture: x/y in the picture's 1000 × 600 units. */
function Chip({ x, y, cls, title, value, lines, align = "center" }: {
  x: number; y: number; cls: string; title: string; value: ReactNode; lines?: (ReactNode | null | false)[]; align?: "center" | "left" | "right";
}) {
  const shift = align === "center" ? "-50%" : align === "left" ? "0" : "-100%";
  return (
    <div className={`en-chip ${cls}`} style={{ left: `${x / 10}%`, top: `${y / 6}%`, transform: `translate(${shift}, -50%)` }}>
      <span className="en-chip-title">{title}</span>
      <b className="en-chip-value">{value}</b>
      {lines?.filter(Boolean).map((l, i) => <span key={i} className="en-chip-line">{l}</span>)}
    </div>
  );
}

/** "34.7p", "£1.66"; other currencies as the sensor gives them. */
export function fmtMoney(v: number | null | undefined, unit: string | null | undefined): string {
  if (v == null) return "–";
  if (unit === "p") return Math.abs(v) >= 100 ? `£${(v / 100).toFixed(2)}` : `${+v.toFixed(1)}p`;
  if (unit === "£" || unit === "GBP") return `£${v.toFixed(2)}`;
  return `${+v.toFixed(2)}${unit ? ` ${unit}` : ""}`;
}
const fmtCop = (v: number | null | undefined) => (v == null ? null : v.toFixed(1));
const fmtDeg = (v: number | null | undefined) => (v == null ? "–" : `${+v.toFixed(1)}°`);

/** Where the sun is in the day: before the panels start, producing, or done for today (from the forecast). */
export function solarPhase(solar: NonNullable<EnergyOverview["solar"]>, now = Date.now()): "before" | "day" | "after" {
  if ((solar.power ?? 0) >= IDLE) return "day";
  if (solar.starts && now < Date.parse(solar.starts)) return "before";
  if (solar.ends && now >= Date.parse(solar.ends)) return "after";
  if (!solar.starts && solar.forecast_tomorrow != null && new Date(now).getHours() >= 15) return "after";
  return "day";
}

const COLORS = { solar: "#f2a33a", battery: "#2fb58a", grid: "#8b7cf0", car: "#4f7cec", heat: "#e8674f", home: "var(--accent)" };

/** Energy: the house with solar on the roof, the battery inside, the grid, the car and the heat pump around it, and
 * the power running between them. */
export function EnergyView() {
  const { layout } = useApp();
  const [data] = useData((a) => a.energy(), ["energy", "settings"], []);
  const [weather] = useData((a) => a.weather(), ["settings"], []);
  if (!data) return <div className="energy" />;
  const nothing = !data.solar && !data.battery && !data.grid && !data.home && !data.car && !data.heat_pump;
  return (
    <div className="energy">
      <div className="toolbar">
        <div className="toolbar-l"><h1 className="toolbar-title">Energy</h1></div>
        <div className="toolbar-r">
          {data.configured && !data.reachable && <span className="sec-offline">Can't reach Home Assistant</span>}
        </div>
      </div>
      {!data.configured ? (
        <Empty>Energy shows your solar, battery, car and heat pump from Home Assistant. Run Moonlight as the Home Assistant add-on to use it.</Empty>
      ) : nothing ? (
        <Empty>Nothing to show yet. Pick your solar, battery, grid, car and heat pump sensors in Settings › Energy.</Empty>
      ) : (
        <div className={"en-body" + (data.plan ? " with-plan" : "")}>
          <House data={data} small={layout === "phone"} sky={weather?.current ?? null} />
          {(data.plan || data.tariff) && <Plan plan={data.plan} tariff={data.tariff} />}
          {layout === "phone" && <Details data={data} />}
        </div>
      )}
    </div>
  );
}

/** Predbat's plan along the bottom: what it's doing, the price now, today's cost and the next cheap charge. */
function Plan({ plan, tariff }: { plan: EnergyOverview["plan"]; tariff: EnergyTariff | null }) {
  const unit = plan?.rate_unit ?? "p";
  const span = (w: { start: string; end: string }) => `${fmtTime(w.start)}–${fmtTime(w.end)}`;
  const soon = (w: EnergyWindow | null) => (w && (!w.end || Date.parse(w.end) > Date.now()) ? w : null);
  const charge = soon(plan?.charge ?? null);
  const cheap = soon(plan?.cheap ?? null);
  const items: [string, string][] = [];
  if (plan?.status) items.push(["Predbat", plan.status]);
  if (plan?.rate_now != null) items.push(["Price now", fmtMoney(plan.rate_now, unit)]);
  if (plan?.rate_export != null) items.push(["Export", fmtMoney(plan.rate_export, unit)]);
  if (plan?.cost_today != null) items.push(["Cost today", fmtMoney(plan.cost_today, plan.cost_unit ?? unit)]);
  if (plan?.battery_hours != null && plan.battery_hours > 0) items.push(["Battery lasts", `${plan.battery_hours < 10 ? plan.battery_hours.toFixed(1) : Math.round(plan.battery_hours)} h`]);
  if (tariff?.cheap_now) items.push(["Cheap rate", tariff.cheap_until ? `now until ${fmtTime(tariff.cheap_until)}` : "now"]);
  else if (tariff?.next) items.push(["Next cheap", span(tariff.next)]);
  tariff?.bonus.slice(0, 2).forEach((b) => items.push(["Bonus slot", span(b)]));
  if (charge) items.push(["Charging battery", `${fmtTime(charge.start)}${charge.end ? `–${fmtTime(charge.end)}` : ""}${charge.rate != null ? ` at ${fmtMoney(charge.rate, unit)}` : ""}`]);
  if (!tariff && cheap && cheap.start !== charge?.start) items.push(["Cheap rate", `${Date.parse(cheap.start) <= Date.now() ? "now" : `from ${fmtTime(cheap.start)}`}${cheap.rate != null ? ` at ${fmtMoney(cheap.rate, unit)}` : ""}`]);
  if (!items.length) return null;
  return (
    <div className="en-plan">
      {items.map(([k, v], i) => <span key={i} className="en-plan-item"><span>{k}</span><b>{v}</b></span>)}
    </div>
  );
}

/** "Charging to 80% by 7am". */
function carTarget(car: NonNullable<EnergyOverview["car"]>): string | null {
  if (car.limit == null && !car.ready) return null;
  return [car.limit != null && `Charging to ${car.limit}%`, car.ready && `by ${fmtTime(car.ready)}`].filter(Boolean).join(" ").replace(/^by/, "Ready by");
}

/** A small reading on the picture: a title over a value. */
function Tag({ x, y, title, value, cls }: { x: number; y: number; title: string; value: string; cls?: string }) {
  return (
    <div className={"en-tag " + (cls ?? "")} style={{ left: `${x / 10}%`, top: `${y / 6}%` }}>
      <span>{title}</span><b>{value}</b>
    </div>
  );
}

// The house from its long side: walls 330–690 across and 320–500 down, the roof a slope above them with the panels on.
const PANELS = Array.from({ length: 12 }, (_, i) => ({ x: 384 + (i % 6) * 44, y: i < 6 ? 198 : 254 }));

export function House({ data, small, sky }: { data: EnergyOverview; small?: boolean; sky?: { temp: number; condition: string } | null }) {
  const { solar, battery, grid, home, car, heat_pump: hp, temperatures: temps } = data;
  const sunny = (solar?.power ?? 0) >= IDLE;
  const batt = battery?.soc ?? null;
  const battColor = batt != null && batt < 20 ? "#e2902b" : COLORS.battery;
  const plugged = car?.plugged_in || car?.charging;
  const gridW = grid?.power ?? null;
  const drawnSun = !sky || sky.condition === "sunny";
  const phase = solar ? solarPhase(solar) : "day";
  const tank = temps?.tank ?? null;
  const tankColor = tank == null ? "var(--en-glass)" : tank >= 45 ? "#e8674f" : tank >= 35 ? "#f2a33a" : "#6aa6e8";
  return (
    <div className={"en-house" + (small ? " small" : "") + (data.sun?.night ? " night" : "")}>
      <svg viewBox="0 0 1000 600" className="en-scene" aria-hidden="true">
        <defs>
          <linearGradient id="en-sky" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" className="en-sky-top" /><stop offset="1" className="en-sky-bottom" />
          </linearGradient>
        </defs>
        <rect width="1000" height="600" fill="url(#en-sky)" />
        <path d="M0 500 H1000 V600 H0 Z" className="en-grass" />

        {/* Sun, when the weather says sunny (or there's no weather) */}
        {drawnSun && (
          <g className={"en-sun" + (sunny || (!solar && !!sky) ? " on" : "")} transform="translate(120 96)">
            {Array.from({ length: 12 }, (_, i) => (
              <path key={i} d="M0 -58 V-74" transform={`rotate(${i * 30})`} className="en-ray" />
            ))}
            <circle r="42" />
          </g>
        )}

        {/* Grid pylon, its cable running under the garden into the house */}
        {grid && (
          <g className="en-pylon" transform="translate(60 0)">
            <path d="M890 500 L915 250 L940 500 M897 430 H933 M903 360 H927 M908 300 H922 M890 500 L927 360 M940 500 L903 360 M897 430 L922 300 M933 430 L908 300" />
            <path d="M875 268 H955 M882 290 H948" />
          </g>
        )}

        {/* House */}
        <path d="M330 320 V500 H690 V320" className="en-wall" />
        <path d="M300 322 L365 182 H655 L720 322 Z" className="en-roof" />

        {/* Solar panels on the roof */}
        {solar && (
          <g className={"en-panels" + (sunny ? " on" : "")}>
            {PANELS.map((p, i) => <rect key={i} x={p.x} y={p.y} width="40" height="50" rx="3" />)}
          </g>
        )}

        {/* Hot water tank */}
        {tank != null && <rect x="612" y="378" width="60" height="104" rx="16" className="en-tank" style={{ fill: tankColor }} />}

        {/* Flows: all through the home */}
        {solar && <Flow d="M520 304 V429" w={solar.power} color={COLORS.solar} />}
        {battery && <Flow d="M395 440 H509" w={battery.power} color={COLORS.battery} back={(battery.power ?? 0) < 0} />}
        {grid && <Flow d="M958 500 Q956 524 930 524 H548 L526 451" w={gridW} color={COLORS.grid} back={(gridW ?? 0) < 0} />}
        {car && <Flow d="M510 448 L478 490 H300 L262 470" w={car.charging ? car.power ?? 2000 : 0} color={COLORS.car} />}
        {car && plugged && <Flow d="M262 470 Q240 500 205 476" w={car.charging ? car.power ?? 2000 : 0} color={COLORS.car} />}
        {hp && <Flow d="M530 449 L556 488 H728" w={hp.running ? hp.power ?? 500 : 0} color={COLORS.heat} />}
        <circle cx="520" cy="440" r="11" className="en-hub" />

        {/* Battery, inside on the left */}
        {battery && (
          <g transform="translate(350 404)">
            <rect x="9" y="-8" width="18" height="10" rx="3" className="en-batt-cap" />
            <rect x="0" y="0" width="36" height="76" rx="7" className="en-batt" />
            {batt != null && <rect x="4" y={4 + 68 * (1 - Math.min(100, Math.max(0, batt)) / 100)} width="28"
              height={68 * Math.min(100, Math.max(0, batt)) / 100} rx="4" fill={battColor} />}
            {battery.state === "charging" && <path d="M20 18 L12 40 H19 L15 58 L26 32 H19 Z" className="en-bolt" />}
          </g>
        )}

        {/* Car and charger */}
        {car && (
          <g>
            <g transform="translate(250 418)" className="en-charger">
              <rect x="0" y="0" width="26" height="52" rx="6" />
              <rect x="6" y="9" width="14" height="10" rx="2" className={"en-charger-led" + (car.charging ? " on" : plugged ? " ready" : "")} />
              <path d="M13 52 V82" />
            </g>
            <g transform="translate(40 418)" className={"en-car" + (plugged ? " in" : "")}>
              <path d="M8 68 V48 Q8 40 18 38 L46 34 L70 12 Q76 7 86 7 H130 Q142 7 150 16 L168 36 Q186 40 186 54 V68 Z" />
              <path d="M78 18 H106 V36 H60 Z M114 18 H134 L150 36 H114 Z" className="en-car-glass" />
              <circle cx="46" cy="70" r="15" className="en-wheel" /><circle cx="148" cy="70" r="15" className="en-wheel" />
              {car.soc != null && <>
                <rect x="60" y="46" width="72" height="10" rx="5" className="en-car-bar" />
                <rect x="60" y="46" width={72 * Math.min(100, Math.max(0, car.soc)) / 100} height="10" rx="5" fill={COLORS.car} className="en-car-fill" />
              </>}
            </g>
          </g>
        )}

        {/* Heat pump outside on the right */}
        {hp && (
          <g transform="translate(728 430)" className={"en-hp" + (hp.running ? " on" : "")}>
            <rect x="0" y="0" width="112" height="70" rx="8" />
            <circle cx="40" cy="35" r="24" className="en-hp-grille" />
            <g transform="translate(40 35)"><g className="en-fan">
              <path d="M0 0 C6 -10 4 -18 0 -20 C-4 -18 -6 -10 0 0 Z" /><path d="M0 0 C6 -10 4 -18 0 -20 C-4 -18 -6 -10 0 0 Z" transform="rotate(120)" />
              <path d="M0 0 C6 -10 4 -18 0 -20 C-4 -18 -6 -10 0 0 Z" transform="rotate(240)" />
            </g></g>
            <path d="M80 18 H100 M80 30 H100 M80 42 H100 M80 54 H100" className="en-hp-vent" />
          </g>
        )}
      </svg>

      {/* The weather in place of the sun */}
      {!drawnSun && sky && <div className="en-weather"><WeatherIcon condition={sky.condition} size={24} /></div>}

      {/* Temperatures (outside is in the top bar already) */}
      {!small && temps?.inside != null && <Tag x={642} y={346} title="Inside" value={fmtDeg(temps.inside)} />}
      {!small && tank != null && <Tag x={642} y={430} title="Tank" value={fmtDeg(tank)} cls="t-tank" />}

      {/* Labels over the picture */}
      {solar && <Chip x={185} y={96} align="left" cls="c-solar" title="Solar"
        value={phase === "before" && solar.starts ? `${small ? "From" : "Starts"} ${fmtTime(solar.starts)}` : phase === "after" && !sunny ? (small ? fmtW(solar.power) : "Done for today") : fmtW(solar.power)}
        lines={phase === "before"
          ? [!small && solar.forecast_today != null && `${fmtKwh(solar.forecast_today)} expected today`]
          : phase === "after"
            ? [!small && solar.today != null && `${fmtKwh(solar.today)} today`, !small && solar.forecast_tomorrow != null && `Tomorrow ${fmtKwh(solar.forecast_tomorrow)} expected`]
            : [!small && solar.today != null && (solar.forecast_today != null ? `${solar.today.toFixed(1)} of ${fmtKwh(solar.forecast_today)} today` : `${fmtKwh(solar.today)} today`)]} />}
      {battery && <Chip x={small ? 338 : 342} y={small ? 352 : 362} align="left" cls="c-battery" title="Battery"
        value={batt != null ? `${batt}%` : "–"}
        lines={[!small && battery.power != null && (battery.state === "idle" ? "Resting" : `${battery.state === "charging" ? "Charging" : "Powering the house"} ${fmtW(battery.power)}`)]} />}
      {home && <Chip x={small ? 610 : 510} y={small ? 125 : 128} cls="c-home" title={small ? "Home" : "Home is using"} value={fmtW(home.power)}
        lines={[!small && home.today != null && `${fmtKwh(home.today)} today`]} />}
      {grid && <Chip x={small ? 990 : 985} y={small ? 160 : 150} align="right" cls="c-grid" title="Grid"
        value={gridW == null ? "–" : grid.state === "idle" ? (small ? "0 W" : "Nothing in or out") : `${grid.state === "importing" ? (small ? "In" : "Buying") : (small ? "Out" : "Selling")} ${fmtW(gridW)}`}
        lines={[!small && grid.import_today != null && `${fmtKwh(grid.import_today)} bought today`, !small && grid.export_today != null && `${fmtKwh(grid.export_today)} sold today`]} />}
      {car && <Chip x={small ? 120 : 135} y={small ? 300 : 330} cls="c-car" title="Car"
        value={car.charging ? (car.power != null ? fmtW(car.power) : "Charging") : plugged ? "Plugged in" : car.plugged_in === false ? "Not plugged in" : car.status ?? "–"}
        lines={[
          car.soc != null && `${car.soc}%${!small && car.range != null ? ` · ${car.range} ${car.range_unit ?? ""}` : ""}`,
          !small && car.charging && "Charging",
          !small && !car.charging && plugged && car.status && car.status !== "Plugged in" ? car.status.replace(/^Plugged in · /, "").replace(/^./, (c) => c.toUpperCase()) : null,
          !small && car.session != null && car.session > 0 && `${fmtKwh(car.session)} added`,
          !small && carTarget(car),
        ]} />}
      {hp && <Chip x={small ? 800 : 712} y={small ? 375 : 370} align={small ? "center" : "left"} cls="c-heat" title="Heat pump"
        value={small ? (hp.running ? (hp.power != null ? fmtW(hp.power) : "On") : "Idle") : hp.running ? hp.doing : "Idle"}
        lines={small
          ? [hp.cop != null ? `COP ${fmtCop(hp.cop)}` : hp.running && hp.doing !== "Running" && hp.doing.replace("Heating the house", "Heating").replace("Heating hot water", "Hot water")]
          : [
            [hp.power != null && fmtW(hp.power), hp.cop != null && `COP ${fmtCop(hp.cop)} now`].filter(Boolean).join(" · "),
            [hp.flow_temp != null && `Flow ${fmtT(hp.flow_temp)}`, hp.today != null && `${fmtKwh(hp.today)} today`].filter(Boolean).join(" · "),
            hp.cop_today?.overall != null && `COP today ${fmtCop(hp.cop_today.overall)}`,
            hp.cop_today && [hp.cop_today.heating != null && `Heat ${fmtCop(hp.cop_today.heating)}`, hp.cop_today.hot_water != null && `Water ${fmtCop(hp.cop_today.hot_water)}`].filter(Boolean).join(" · "),
          ]} />}
    </div>
  );
}

/** On a phone the picture keeps the headline numbers and the rest goes in cards below. */
function Details({ data }: { data: EnergyOverview }) {
  const { solar, battery, grid, home, car, heat_pump: hp, temperatures: temps } = data;
  const card = (cls: string, title: string, value: string, rows: (string | null | false | undefined)[]) => (
    <section className={`panel en-card ${cls}`}>
      <span className="en-chip-title">{title}</span>
      <b>{value}</b>
      {rows.filter(Boolean).map((r, i) => <span key={i}>{r}</span>)}
    </section>
  );
  const phase = solar ? solarPhase(solar) : "day";
  return (
    <div className="en-cards">
      {solar && card("c-solar", "Solar", phase === "before" && solar.starts ? `Starts ${fmtTime(solar.starts)}` : fmtW(solar.power),
        [solar.today != null && `${fmtKwh(solar.today)} today`, solar.forecast_today != null && `${fmtKwh(solar.forecast_today)} expected today`,
          phase === "after" && solar.forecast_tomorrow != null && `${fmtKwh(solar.forecast_tomorrow)} expected tomorrow`])}
      {battery && card("c-battery", "Battery", battery.soc != null ? `${battery.soc}%` : "–",
        [battery.power != null && (battery.state === "idle" ? "Resting" : `${battery.state === "charging" ? "Charging" : "Powering the house"} ${fmtW(battery.power)}`)])}
      {home && card("c-home", "Home", fmtW(home.power), [home.today != null && `${fmtKwh(home.today)} today`])}
      {grid && card("c-grid", "Grid", grid.state === "idle" ? "Nothing in or out" : `${grid.state === "importing" ? "Buying" : "Selling"} ${fmtW(grid.power)}`,
        [grid.import_today != null && `${fmtKwh(grid.import_today)} bought today`, grid.export_today != null && `${fmtKwh(grid.export_today)} sold today`])}
      {car && card("c-car", "Car", car.charging ? "Charging" : car.plugged_in ? "Plugged in" : car.plugged_in === false ? "Not plugged in" : car.status ?? "–",
        [car.charging && car.power != null && fmtW(car.power), car.soc != null && `${car.soc}%${car.range != null ? ` · ${car.range} ${car.range_unit ?? ""}` : ""}`,
          car.session != null && car.session > 0 && `${fmtKwh(car.session)} added`, carTarget(car)])}
      {hp && card("c-heat", "Heat pump", hp.running ? hp.doing : "Idle",
        [hp.power != null && fmtW(hp.power), hp.cop != null && `COP ${fmtCop(hp.cop)} now`, hp.flow_temp != null && `Flow ${fmtT(hp.flow_temp)}`,
          hp.today != null && `${fmtKwh(hp.today)} today`, hp.cop_today?.overall != null && `COP today ${fmtCop(hp.cop_today.overall)}`,
          hp.cop_today?.heating != null && `Heating ${fmtCop(hp.cop_today.heating)}`, hp.cop_today?.hot_water != null && `Hot water ${fmtCop(hp.cop_today.hot_water)}`])}
      {(temps?.inside != null || temps?.tank != null) && card("c-temp", "Temperatures", `${fmtDeg(temps?.inside ?? null)} inside`,
        [temps?.tank != null && `Hot water tank ${fmtDeg(temps.tank)}`])}
    </div>
  );
}
