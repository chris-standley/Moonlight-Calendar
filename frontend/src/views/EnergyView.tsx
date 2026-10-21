import { CSSProperties, ReactNode } from "react";
import { EnergyOverview } from "../api/types";
import { useApp, useData } from "../state";
import { Empty } from "../components/ui";

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

const COLORS = { solar: "#f2a33a", battery: "#2fb58a", grid: "#8b7cf0", car: "#4f7cec", heat: "#e8674f", home: "var(--accent)" };

/** Energy: the house with solar on the roof, the battery inside, the grid, the car and the heat pump around it, and
 * the power running between them. */
export function EnergyView() {
  const { layout, go } = useApp();
  const [data] = useData((a) => a.energy(), ["energy", "settings"], []);
  if (!data) return <div className="energy" />;
  const nothing = !data.solar && !data.battery && !data.grid && !data.home && !data.car && !data.heat_pump;
  return (
    <div className="energy">
      <div className="toolbar">
        <div className="toolbar-l"><h1 className="toolbar-title">Energy</h1></div>
        <div className="toolbar-r">
          {data.configured && !data.reachable && <span className="sec-offline">Can't reach Home Assistant</span>}
          <button className="btn ghost small" onClick={() => go("settings")}>Settings</button>
        </div>
      </div>
      {!data.configured ? (
        <Empty>Energy shows your solar, battery, car and heat pump from Home Assistant. Run Moonlight as the Home Assistant add-on to use it.</Empty>
      ) : nothing ? (
        <Empty>Nothing to show yet. Pick your solar, battery, grid, car and heat pump sensors in Settings › Energy.</Empty>
      ) : (
        <div className="en-body">
          <House data={data} small={layout === "phone"} />
          {layout === "phone" && <Details data={data} />}
        </div>
      )}
    </div>
  );
}

export function House({ data, small }: { data: EnergyOverview; small?: boolean }) {
  const { solar, battery, grid, home, car, heat_pump: hp } = data;
  const sunny = (solar?.power ?? 0) >= IDLE;
  const batt = battery?.soc ?? null;
  const battColor = batt != null && batt < 20 ? "#e2902b" : COLORS.battery;
  const plugged = car?.plugged_in || car?.charging;
  const gridW = grid?.power ?? null;
  return (
    <div className={"en-house" + (small ? " small" : "")}>
      <svg viewBox="0 0 1000 600" className="en-scene" aria-hidden="true">
        <defs>
          <linearGradient id="en-sky" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" className="en-sky-top" /><stop offset="1" className="en-sky-bottom" />
          </linearGradient>
        </defs>
        <rect width="1000" height="600" fill="url(#en-sky)" />
        <path d="M0 500 H1000 V600 H0 Z" className="en-grass" />

        {/* Sun */}
        {solar && (
          <g className={"en-sun" + (sunny ? " on" : "")} transform="translate(120 96)">
            {Array.from({ length: 12 }, (_, i) => (
              <path key={i} d="M0 -58 V-74" transform={`rotate(${i * 30})`} className="en-ray" />
            ))}
            <circle r="42" />
          </g>
        )}

        {/* Grid pylon and its wire to the house */}
        {grid && (
          <g className="en-pylon">
            <path d="M890 500 L915 250 L940 500 M897 430 H933 M903 360 H927 M908 300 H922 M890 500 L927 360 M940 500 L903 360 M897 430 L922 300 M933 430 L908 300" />
            <path d="M875 268 H955 M882 290 H948" />
            <path d="M882 290 Q790 305 690 312" className="en-cable" />
          </g>
        )}

        {/* House */}
        <path d="M330 305 V500 H690 V305" className="en-wall" />
        <path d="M300 312 L510 150 L720 312" className="en-roof" />
        <rect x="585" y="178" width="34" height="62" className="en-wall" />
        <rect x="560" y="410" width="58" height="90" rx="6" className="en-door" />
        <rect x="610" y="335" width="52" height="45" rx="6" className={"en-window" + ((home?.power ?? 0) > 0 ? " lit" : "")} />

        {/* Solar panels on the roof */}
        {solar && (
          <g transform="translate(338 284) rotate(-37.6)" className="en-panels">
            <rect x="0" y="-34" width="170" height="30" rx="3" />
            <path d="M42 -34 V-4 M85 -34 V-4 M128 -34 V-4 M0 -19 H170" />
          </g>
        )}

        {/* Flows: all through the home */}
        {solar && <Flow d="M420 230 L475 330 L500 420" w={solar.power} color={COLORS.solar} />}
        {battery && <Flow d="M395 440 L520 440" w={battery.power} color={COLORS.battery} back={(battery.power ?? 0) < 0} />}
        {grid && <Flow d="M882 290 Q790 305 690 312 L620 380 L560 440" w={gridW} color={COLORS.grid} back={(gridW ?? 0) < 0} />}
        {car && <Flow d="M500 455 L330 470 L262 470" w={car.charging ? car.power ?? 2000 : 0} color={COLORS.car} />}
        {car && plugged && <Flow d="M262 470 Q240 500 205 476" w={car.charging ? car.power ?? 2000 : 0} color={COLORS.car} />}
        {hp && <Flow d="M560 470 L690 470 L728 470" w={hp.running ? hp.power ?? 500 : 0} color={COLORS.heat} />}
        <circle cx="530" cy="440" r="11" className="en-hub" />

        {/* Battery, inside on the left */}
        {battery && (
          <g transform="translate(350 395)">
            <rect x="9" y="-8" width="18" height="10" rx="3" className="en-batt-cap" />
            <rect x="0" y="0" width="36" height="96" rx="7" className="en-batt" />
            {batt != null && <rect x="4" y={4 + 88 * (1 - Math.min(100, Math.max(0, batt)) / 100)} width="28"
              height={88 * Math.min(100, Math.max(0, batt)) / 100} rx="4" fill={battColor} />}
            {battery.state === "charging" && <path d="M20 30 L12 52 H19 L15 70 L26 44 H19 Z" className="en-bolt" />}
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

      {/* Labels over the picture */}
      {solar && <Chip x={185} y={96} align="left" cls="c-solar" title="Solar" value={fmtW(solar.power)}
        lines={[!small && solar.today != null && `${fmtKwh(solar.today)} today`]} />}
      {battery && <Chip x={small ? 370 : 380} y={small ? 300 : 340} cls="c-battery" title="Battery"
        value={batt != null ? `${batt}%` : "–"}
        lines={[!small && battery.power != null && (battery.state === "idle" ? "Resting" : `${battery.state === "charging" ? "Charging" : "Powering the house"} ${fmtW(battery.power)}`)]} />}
      {home && <Chip x={small ? 515 : 545} y={small ? 245 : 268} cls="c-home" title={small ? "Home" : "Home is using"} value={fmtW(home.power)}
        lines={[!small && home.today != null && `${fmtKwh(home.today)} today`]} />}
      {grid && <Chip x={small ? 990 : 980} y={small ? 150 : 150} align="right" cls="c-grid" title="Grid"
        value={gridW == null ? "–" : grid.state === "idle" ? (small ? "0 W" : "Nothing in or out") : `${grid.state === "importing" ? (small ? "In" : "Buying") : (small ? "Out" : "Selling")} ${fmtW(gridW)}`}
        lines={[!small && grid.import_today != null && `${fmtKwh(grid.import_today)} bought today`, !small && grid.export_today != null && `${fmtKwh(grid.export_today)} sold today`]} />}
      {car && <Chip x={small ? 120 : 135} y={small ? 300 : 330} cls="c-car" title="Car"
        value={car.charging ? (car.power != null ? fmtW(car.power) : "Charging") : plugged ? "Plugged in" : car.plugged_in === false ? "Not plugged in" : car.status ?? "–"}
        lines={[
          car.soc != null && `${car.soc}%${!small && car.range != null ? ` · ${car.range} ${car.range_unit ?? ""}` : ""}`,
          !small && car.charging && "Charging",
          !small && !car.charging && plugged && car.status && car.status !== "Plugged in" ? car.status.replace(/^Plugged in · /, "").replace(/^./, (c) => c.toUpperCase()) : null,
          !small && car.session != null && car.session > 0 && `${fmtKwh(car.session)} added`,
        ]} />}
      {hp && <Chip x={small ? 790 : 790} y={small ? 375 : 372} cls="c-heat" title="Heat pump"
        value={small ? (hp.running ? (hp.power != null ? fmtW(hp.power) : "On") : "Idle") : hp.running ? hp.doing : "Idle"}
        lines={[
          small ? hp.running && hp.doing !== "Running" && hp.doing.replace("Heating the house", "Heating").replace("Heating hot water", "Hot water")
            : hp.power != null && fmtW(hp.power),
          !small && [hp.flow_temp != null && `Flow ${fmtT(hp.flow_temp)}`, hp.tank_temp != null && `Tank ${fmtT(hp.tank_temp)}`].filter(Boolean).join(" · "),
          !small && [hp.outdoor_temp != null && `Outside ${fmtT(hp.outdoor_temp)}`, hp.today != null && `${fmtKwh(hp.today)} today`].filter(Boolean).join(" · "),
        ]} />}
    </div>
  );
}

/** On a phone the picture keeps the headline numbers and the rest goes in cards below. */
function Details({ data }: { data: EnergyOverview }) {
  const { solar, battery, grid, home, car, heat_pump: hp } = data;
  const card = (cls: string, title: string, value: string, rows: (string | null | false)[]) => (
    <section className={`panel en-card ${cls}`}>
      <span className="en-chip-title">{title}</span>
      <b>{value}</b>
      {rows.filter(Boolean).map((r, i) => <span key={i}>{r}</span>)}
    </section>
  );
  return (
    <div className="en-cards">
      {solar && card("c-solar", "Solar", fmtW(solar.power), [solar.today != null && `${fmtKwh(solar.today)} today`])}
      {battery && card("c-battery", "Battery", battery.soc != null ? `${battery.soc}%` : "–",
        [battery.power != null && (battery.state === "idle" ? "Resting" : `${battery.state === "charging" ? "Charging" : "Powering the house"} ${fmtW(battery.power)}`)])}
      {home && card("c-home", "Home", fmtW(home.power), [home.today != null && `${fmtKwh(home.today)} today`])}
      {grid && card("c-grid", "Grid", grid.state === "idle" ? "Nothing in or out" : `${grid.state === "importing" ? "Buying" : "Selling"} ${fmtW(grid.power)}`,
        [grid.import_today != null && `${fmtKwh(grid.import_today)} bought today`, grid.export_today != null && `${fmtKwh(grid.export_today)} sold today`])}
      {car && card("c-car", "Car", car.charging ? "Charging" : car.plugged_in ? "Plugged in" : car.plugged_in === false ? "Not plugged in" : car.status ?? "–",
        [car.charging && car.power != null && fmtW(car.power), car.soc != null && `${car.soc}%${car.range != null ? ` · ${car.range} ${car.range_unit ?? ""}` : ""}`,
          car.session != null && car.session > 0 && `${fmtKwh(car.session)} added`])}
      {hp && card("c-heat", "Heat pump", hp.running ? hp.doing : "Idle",
        [hp.power != null && fmtW(hp.power), hp.flow_temp != null && `Flow ${fmtT(hp.flow_temp)}`, hp.tank_temp != null && `Hot water tank ${fmtT(hp.tank_temp)}`,
          hp.outdoor_temp != null && `Outside ${fmtT(hp.outdoor_temp)}`, hp.today != null && `${fmtKwh(hp.today)} today`])}
    </div>
  );
}
