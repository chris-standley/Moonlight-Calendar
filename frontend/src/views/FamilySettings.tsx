import { CSSProperties, ReactNode, useState } from "react";
import { ApiError, Person, Role } from "../api/types";
import { useApp } from "../state";
import { Avatar, Segmented, Sheet } from "../components/ui";
import { IconDown, IconPlus, IconRight, IconTrash, IconUp } from "../components/icons";

/** Profile colours: bright enough to read white initials on, distinct side by side. */
export const PERSON_COLORS = [
  "#4F7CEC", "#9B6BE0", "#F0679A", "#2FB58A", "#FF8A3D", "#E0475B",
  "#1BADF8", "#14A3A3", "#D99A0B", "#A2845E", "#6C7BF0", "#7A8599",
];
const NAME_MAX = 40;

/** Same rule as the server: first letter, or first + last initials. */
function initialsOf(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return "?";
  return (parts.length === 1 ? parts[0][0] : parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

const roleLabel = (r: Role) => (r === "child" ? "Child" : "Adult");

/** Settings > Family: family name, people (tap to edit), add, reorder. `first` moves it to the top (new install). */
export function FamilyPanel({ first }: { first?: boolean }) {
  const { api, people, settings, toast } = useApp();
  const [editing, setEditing] = useState<Person | "new" | null>(null);
  const [naming, setNaming] = useState(false);
  const [moving, setMoving] = useState(false);

  async function move(i: number, dir: -1 | 1) {
    const j = i + dir;
    if (moving || j < 0 || j >= people.length) return;
    const order = [...people];
    [order[i], order[j]] = [order[j], order[i]];
    setMoving(true);
    try {
      // Renumber 0..n-1 so the order is stable even if sorts were equal or had gaps.
      for (const [k, p] of order.entries()) if (p.sort !== k) await api.updatePerson(p.id, { sort: k });
    } catch (e) { toast(e instanceof ApiError ? e.message : "Couldn't reorder"); }
    finally { setMoving(false); }
  }

  return (
    <section className={"panel family-panel" + (first ? " first" : "")}>
      <div className="panel-head">
        <h2 className="panel-title">Family</h2>
        <button className="btn small" onClick={() => setEditing("new")}><IconPlus size={18} /> Add person</button>
      </div>
      <button className="set-row family-name" onClick={() => setNaming(true)}>
        <span>Name</span><b>{settings?.family_name}</b><IconRight size={18} />
      </button>
      {people.length === 0 && (
        <p className="muted family-empty">
          Add everyone who lives here. Each person gets a colour for their events, their own chore chart,
          and children collect stars for rewards.
        </p>
      )}
      <div className="people-list">
        {people.map((p, i) => (
          <div key={p.id} className="set-person">
            <button className="sp-main" onClick={() => setEditing(p)} aria-label={`Edit ${p.name}`}>
              <Avatar person={p} size={2.4} />
              <b>{p.name}</b>
              <span>{roleLabel(p.role)}</span>
              <i style={{ background: p.color }} />
            </button>
            {people.length > 1 && (
              <span className="sp-order">
                <button className="icon-btn subtle" disabled={moving || i === 0} onClick={() => move(i, -1)} aria-label={`Move ${p.name} up`}><IconUp size={20} /></button>
                <button className="icon-btn subtle" disabled={moving || i === people.length - 1} onClick={() => move(i, 1)} aria-label={`Move ${p.name} down`}><IconDown size={20} /></button>
              </span>
            )}
          </div>
        ))}
      </div>
      {people.length > 1 && <p className="muted family-note">The order here is the order of columns and avatars everywhere.</p>}
      {editing && <PersonSheet person={editing === "new" ? undefined : editing} onClose={() => setEditing(null)} />}
      {naming && <FamilyNameSheet onClose={() => setNaming(false)} />}
    </section>
  );
}

function PersonSheet({ person, onClose }: { person?: Person; onClose: () => void }) {
  const { api, people, askPin, toast } = useApp();
  const used = new Set(people.filter((p) => p.id !== person?.id).map((p) => p.color.toUpperCase()));
  const [name, setName] = useState(person?.name ?? "");
  const [color, setColor] = useState(person?.color ?? PERSON_COLORS.find((c) => !used.has(c)) ?? PERSON_COLORS[0]);
  const [role, setRole] = useState<Role>(person?.role ?? (people.some((p) => p.role === "adult") ? "child" : "adult"));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<{ chores: number; stars: number } | null>(null);
  const own = person?.color.toUpperCase();
  const colors = !own || PERSON_COLORS.includes(own) ? PERSON_COLORS : [own, ...PERSON_COLORS.slice(0, -1)];
  const valid = !!name.trim();
  const preview: Person = { id: "preview", name: name || "?", initials: initialsOf(name), color, role, sort: 0 };

  async function save() {
    if (!valid || busy) return;
    setBusy(true); setError(null);
    try {
      if (person) {
        await api.updatePerson(person.id, { name: name.trim(), color, role });
        toast("Saved");
      } else {
        const p = await api.createPerson({ name: name.trim(), color, role });
        toast(`${p.name} added`);
      }
      onClose();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't save. Check the network and try again.");
    } finally { setBusy(false); }
  }

  async function askRemove() {
    if (!person) return;
    try {
      const [chores, points] = await Promise.all([api.allChores(), api.points()]);
      setConfirm({
        chores: chores.filter((c) => c.person_id === person.id).length,
        stars: points.find((b) => b.person_id === person.id)?.balance ?? 0,
      });
    } catch { setConfirm({ chores: 0, stars: 0 }); }
  }

  async function remove() {
    if (!person || busy) return;
    const pin = await askPin(`Remove ${person.name}`);
    if (!pin) return;
    setBusy(true);
    try { await api.deletePerson(person.id, pin); toast(`${person.name} removed`); onClose(); }
    catch (e) { setError(e instanceof ApiError ? e.message : "Couldn't remove"); setConfirm(null); }
    finally { setBusy(false); }
  }

  const title = person ? (confirm ? `Remove ${person.name}?` : `Edit ${person.name}`) : "Add a person";
  let footer: ReactNode;
  if (confirm) {
    footer = <>
      <button className="btn ghost" onClick={() => setConfirm(null)}>Keep {person!.name}</button>
      <span style={{ flex: 1 }} />
      <button className="btn danger-fill" disabled={busy} onClick={remove}><IconTrash size={20} /> Remove</button>
    </>;
  } else {
    footer = <>
      {person ? <button className="btn ghost danger" onClick={askRemove}><IconTrash size={20} /> Remove</button>
        : <button className="btn ghost" onClick={onClose}>Cancel</button>}
      <span style={{ flex: 1 }} />
      <button className="btn" disabled={!valid || busy} onClick={save}>{person ? "Save" : "Add person"}</button>
    </>;
  }

  return (
    <Sheet title={title} onClose={onClose} footer={footer}>
      {confirm && person ? (
        <div className="form">
          <div className="remove-who"><Avatar person={person} size={3.4} /><b>{person.name}</b></div>
          <div className="remove-warn" role="alert">
            <p>This can't be undone.</p>
            <ul>
              <li>{confirm.chores ? `Their ${confirm.chores} chore${confirm.chores === 1 ? "" : "s"} and chore history are deleted.` : "Any chores of theirs are deleted."}</li>
              <li>{confirm.stars ? `Their ${confirm.stars} star${confirm.stars === 1 ? "" : "s"} and star history are deleted, ` : "Their star history is deleted, "}along with rewards just for them.</li>
              <li>Events, list items and calendars stay, without {person.name}.</li>
            </ul>
          </div>
          {error && <div className="connect-error" role="alert">{error}</div>}
          <p className="muted connect-note">A PIN is needed to remove someone.</p>
        </div>
      ) : (
        <form className="form" onSubmit={(e) => { e.preventDefault(); save(); }}>
          <div className="person-preview" style={{ "--pc": color } as CSSProperties}>
            <Avatar person={preview} size={4.4} />
          </div>
          <label className="field-label" htmlFor="person-name">Name</label>
          <input id="person-name" className="input big" placeholder="e.g. Mia" value={name} maxLength={NAME_MAX}
            onChange={(e) => setName(e.target.value)} autoFocus={!person} autoComplete="off" />
          <label className="field-label">Colour</label>
          <div className="swatches" title="A dot means someone else already has that colour">
            {colors.map((c) => (
              <button type="button" key={c} className={"swatch" + (c.toUpperCase() === color.toUpperCase() ? " on" : "") + (used.has(c.toUpperCase()) ? " taken" : "")}
                style={{ background: c }} onClick={() => setColor(c)} aria-label={c + (used.has(c.toUpperCase()) ? " (used by someone else)" : "")}
                aria-pressed={c.toUpperCase() === color.toUpperCase()} />
            ))}
          </div>
          <label className="field-label">Role</label>
          <Segmented value={role} onChange={setRole} options={[{ value: "adult", label: "Adult" }, { value: "child", label: "Child" }]} />
          <p className="muted connect-note">
            {role === "child" ? "Children earn stars for chores and appear on the Rewards screen." : "Adults have chores and events but don't collect stars."}
          </p>
          {error && <div className="connect-error" role="alert">{error}</div>}
          <button type="submit" hidden />
        </form>
      )}
    </Sheet>
  );
}

function FamilyNameSheet({ onClose }: { onClose: () => void }) {
  const { api, settings, askPin, toast } = useApp();
  const [name, setName] = useState(settings?.family_name ?? "");
  const [error, setError] = useState<string | null>(null);
  async function save() {
    if (!name.trim()) return;
    // With no PIN yet, the first PIN entered becomes the household PIN (see PATCH /api/settings).
    const pin = await askPin(settings?.pin_set ? "Rename the family" : "Choose a 4-digit parent PIN");
    if (!pin) return;
    try { await api.updateSettings({ family_name: name.trim(), pin }); toast("Saved"); onClose(); }
    catch (e) { setError(e instanceof ApiError ? e.message : "Couldn't save"); }
  }
  return (
    <Sheet title="Family name" onClose={onClose} footer={<>
      <button className="btn ghost" onClick={onClose}>Cancel</button>
      <span style={{ flex: 1 }} />
      <button className="btn" disabled={!name.trim()} onClick={save}>Save</button>
    </>}>
      <form className="form" onSubmit={(e) => { e.preventDefault(); save(); }}>
        <input className="input big" value={name} maxLength={60} onChange={(e) => setName(e.target.value)} autoFocus placeholder="The Parkers" />
        <p className="muted connect-note">Shown at the top of the wall screens.{settings?.pin_set ? "" : " No parent PIN is set yet: the PIN you enter now becomes it."}</p>
        {error && <div className="connect-error" role="alert">{error}</div>}
        <button type="submit" hidden />
      </form>
    </Sheet>
  );
}

/** Friendly pointer to Settings > Family, for views that need people (or children) to show anything. */
export function FamilyPrompt({ kids, children }: { kids?: boolean; children?: ReactNode }) {
  const { go, layout } = useApp();
  return (
    <div className="family-prompt">
      <div className="fp-faces" aria-hidden>
        {PERSON_COLORS.slice(0, 4).map((c, i) => <span key={c} style={{ background: c, zIndex: 4 - i }} />)}
      </div>
      <b>{kids ? "No children yet" : "Who's in your family?"}</b>
      <p>{children ?? (kids ? "Add a child in Settings › Family to give them stars and rewards." : "Add everyone in Settings › Family to get colour-coded calendars, chore charts and rewards.")}</p>
      <button className={"btn" + (layout === "kitchen" ? " small" : "")} onClick={() => go("settings")}>Set up family</button>
    </div>
  );
}
