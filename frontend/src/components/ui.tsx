import { ReactNode, useEffect, useState } from "react";
import { Person } from "../api/types";
import { IconClose } from "./icons";

export function tint(hex: string, alpha: number): string {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
}

export function Avatar({ person, size = 2.4, ring, dim, onClick, label }: {
  person: Person; size?: number; ring?: boolean; dim?: boolean; onClick?: () => void; label?: boolean;
}) {
  const el = (
    <span
      className={"avatar" + (dim ? " dim" : "")}
      style={{
        width: `${size}rem`, height: `${size}rem`, fontSize: `${size * 0.4}rem`,
        background: person.color,
        boxShadow: ring ? `0 0 0 0.18rem var(--bg), 0 0 0 0.34rem ${person.color}` : undefined,
      }}
    >
      {person.initials}
    </span>
  );
  if (!onClick && !label) return el;
  return (
    <button className="avatar-btn" onClick={onClick} aria-pressed={!dim}>
      {el}
      {label && <span className="avatar-label">{person.name}</span>}
    </button>
  );
}

export function Sheet({ title, onClose, children, footer, wide }: {
  title: ReactNode; onClose: () => void; children: ReactNode; footer?: ReactNode; wide?: boolean;
}) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  return (
    <div className="scrim" onClick={onClose}>
      <div className={"sheet" + (wide ? " wide" : "")} onClick={(e) => e.stopPropagation()} role="dialog">
        <div className="sheet-head">
          <h2>{title}</h2>
          <button className="icon-btn" onClick={onClose} aria-label="Close"><IconClose /></button>
        </div>
        <div className="sheet-body">{children}</div>
        {footer && <div className="sheet-foot">{footer}</div>}
      </div>
    </div>
  );
}

export function Segmented<T extends string>({ value, options, onChange }: {
  value: T; options: { value: T; label: ReactNode }[]; onChange: (v: T) => void;
}) {
  return (
    <div className="segmented" role="tablist">
      {options.map((o) => (
        <button type="button" key={o.value} role="tab" aria-selected={o.value === value} className={o.value === value ? "on" : ""} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function PersonPicker({ people, value, onChange, multi = true }: {
  people: Person[]; value: string[]; onChange: (v: string[]) => void; multi?: boolean;
}) {
  return (
    <div className="person-picker">
      {people.map((p) => {
        const on = value.includes(p.id);
        return (
          <button key={p.id} className={"pp" + (on ? " on" : "")} style={{ "--pc": p.color } as React.CSSProperties}
            onClick={() => onChange(multi ? (on ? value.filter((v) => v !== p.id) : [...value, p.id]) : [p.id])}>
            <Avatar person={p} size={2.2} />
            <span>{p.name}</span>
          </button>
        );
      })}
    </div>
  );
}

export function PinPad({ why, onDone, error }: { why: string; onDone: (pin: string | null) => void; error?: string }) {
  const [pin, setPin] = useState("");
  useEffect(() => { if (pin.length === 4) { onDone(pin); setPin(""); } }, [pin, onDone]);
  const keys = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "", "0", "⌫"];
  return (
    <div className="scrim" onClick={() => onDone(null)}>
      <div className="pinpad" onClick={(e) => e.stopPropagation()}>
        <div className="pin-why">{why}</div>
        <div className="pin-dots">{[0, 1, 2, 3].map((i) => <span key={i} className={i < pin.length ? "on" : ""} />)}</div>
        <div className="pin-err">{error ?? " "}</div>
        <div className="pin-keys">
          {keys.map((k, i) => k === "" ? <span key={i} /> : (
            <button key={i} onClick={() => setPin((p) => (k === "⌫" ? p.slice(0, -1) : (p + k).slice(0, 4)))}>{k}</button>
          ))}
        </div>
        <button className="btn ghost" onClick={() => onDone(null)}>Cancel</button>
      </div>
    </div>
  );
}

export function Ring({ value, size = 3, stroke = 0.32, color, children }: {
  value: number; size?: number; stroke?: number; color: string; children?: ReactNode;
}) {
  const r = 50 - stroke * 10;
  const c = 2 * Math.PI * r;
  return (
    <div className="ring" style={{ width: `${size}rem`, height: `${size}rem` }}>
      <svg viewBox="0 0 100 100">
        <circle cx="50" cy="50" r={r} fill="none" stroke={tint(color, 0.18)} strokeWidth={stroke * 20} />
        <circle cx="50" cy="50" r={r} fill="none" stroke={color} strokeWidth={stroke * 20} strokeLinecap="round"
          strokeDasharray={c} strokeDashoffset={c * (1 - Math.max(0, Math.min(1, value)))} transform="rotate(-90 50 50)"
          style={{ transition: "stroke-dashoffset .6s ease" }} />
      </svg>
      <div className="ring-inner">{children}</div>
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

const DAY_ORDER = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"];
const DAY_LETTER: Record<string, string> = { MO: "M", TU: "T", WE: "W", TH: "T", FR: "F", SA: "S", SU: "S" };
const DAY_FULL: Record<string, string> = { MO: "Monday", TU: "Tuesday", WE: "Wednesday", TH: "Thursday", FR: "Friday", SA: "Saturday", SU: "Sunday" };
export const WEEKDAYS = ["MO", "TU", "WE", "TH", "FR"];
export const WEEKENDS = ["SA", "SU"];

/** Seven round day buttons (RFC 5545 codes, MO..SU), plus Weekdays / Weekends shortcuts. Never leaves none chosen. */
export function DayPicker({ value, onChange, weekStart = "monday" }: {
  value: string[]; onChange: (days: string[]) => void; weekStart?: "monday" | "sunday";
}) {
  const order = weekStart === "sunday" ? ["SU", ...DAY_ORDER.slice(0, 6)] : DAY_ORDER;
  const same = (a: string[]) => a.length === value.length && a.every((d) => value.includes(d));
  const flip = (d: string) => {
    const next = value.includes(d) ? value.filter((x) => x !== d) : [...value, d];
    if (next.length) onChange(DAY_ORDER.filter((x) => next.includes(x)));
  };
  return (
    <div className="day-picker">
      <div className="days" role="group" aria-label="Days">
        {order.map((d) => (
          <button type="button" key={d} className={value.includes(d) ? "on" : ""} aria-pressed={value.includes(d)} aria-label={DAY_FULL[d]} onClick={() => flip(d)}>
            {DAY_LETTER[d]}
          </button>
        ))}
      </div>
      <div className="day-presets">
        <button type="button" className={same(WEEKDAYS) ? "on" : ""} onClick={() => onChange(WEEKDAYS)}>Weekdays</button>
        <button type="button" className={same(WEEKENDS) ? "on" : ""} onClick={() => onChange(WEEKENDS)}>Weekends</button>
      </div>
    </div>
  );
}

/** "Skip public holidays" switch; `region` names where they come from (Settings › Display). */
export function HolidaySwitch({ value, onChange, region }: { value: boolean; onChange: (v: boolean) => void; region: string }) {
  return (
    <>
      <div className="set-row"><span>Skip public holidays</span>
        <button type="button" className={"toggle" + (value ? " on" : "")} onClick={() => onChange(!value)} aria-pressed={value} aria-label="Skip public holidays"><span /></button>
      </div>
      {value && <p className="muted connect-note">{region ? `Skips ${region} public holidays. Change the region in Settings › Display.` : "No region chosen yet: pick one in Settings › Display."}</p>}
    </>
  );
}
