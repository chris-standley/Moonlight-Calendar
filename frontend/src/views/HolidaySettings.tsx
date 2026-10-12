import { useEffect, useState } from "react";
import { ApiError, Holiday } from "../api/types";
import { useApp } from "../state";
import { Sheet } from "../components/ui";
import { useHolidayCountries } from "../components/holidays";
import { addDays, fmtFull, today } from "../dates";

/** Settings > Display > Public holidays: the country (and region) whose holidays repeats can skip. */
export function HolidayPicker({ onClose }: { onClose: () => void }) {
  const { api, settings, askPin, toast } = useApp();
  const countries = useHolidayCountries();
  const [country, setCountry] = useState(settings?.holidays?.country ?? "");
  const [subdiv, setSubdiv] = useState(settings?.holidays?.subdiv ?? "");
  const [next, setNext] = useState<Holiday[] | null>(null);
  const subdivs = countries.find((c) => c.code === country)?.subdivs ?? [];
  useEffect(() => {
    let live = true;
    setNext(null);
    if (!country) { setNext([]); return; }
    api.holidays(today(), addDays(today(), 365), { country, subdiv })
      .then((h) => { if (live) setNext(h.slice(0, 4)); }).catch(() => { if (live) setNext([]); });
    return () => { live = false; };
  }, [api, country, subdiv]);
  async function save() {
    const pin = await askPin("Change public holidays");
    if (!pin) return;
    try { await api.updateSettings({ holidays: { country, subdiv }, pin }); toast("Saved"); onClose(); }
    catch (e) { toast(e instanceof ApiError ? e.message : "Couldn't save"); }
  }
  return (
    <Sheet title="Public holidays" onClose={onClose} footer={<>
      <button className="btn ghost" onClick={onClose}>Cancel</button>
      <span style={{ flex: 1 }} />
      <button className="btn" onClick={save}>Save</button>
    </>}>
      <div className="form">
        <p className="muted connect-note">Repeating events and chores set to “Skip public holidays” leave these days out.</p>
        <label className="field-label">Country</label>
        <select className="input" value={country} onChange={(e) => { setCountry(e.target.value); setSubdiv(""); }}>
          <option value="">None</option>
          {countries.map((c) => <option key={c.code} value={c.code}>{c.name}</option>)}
        </select>
        {subdivs.length > 0 && (<>
          <label className="field-label">Region</label>
          <select className="input" value={subdiv} onChange={(e) => setSubdiv(e.target.value)}>
            <option value="">Whole country</option>
            {subdivs.map((s) => <option key={s.code} value={s.code}>{s.name}</option>)}
          </select>
        </>)}
        {country && (<>
          <label className="field-label">Coming up</label>
          {next === null ? <p className="muted">…</p>
            : next.length === 0 ? <p className="muted">None in the next year.</p>
            : next.map((h) => <div key={h.date} className="set-row"><span>{h.name}</span><b>{fmtFull(h.date)}</b></div>)}
        </>)}
      </div>
    </Sheet>
  );
}
