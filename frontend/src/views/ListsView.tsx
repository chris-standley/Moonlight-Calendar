import { CSSProperties, FormEvent, useEffect, useState } from "react";
import { Item, TaskList } from "../api/types";
import { diffDays, fmtDayMonth, relativeDay, today } from "../dates";
import { useApp, useData } from "../state";
import { Avatar, Empty, Sheet, tint } from "../components/ui";
import { IconCheck, IconPlus, IconTrash } from "../components/icons";

export function ListsView() {
  const [lists] = useData((api) => api.lists(), ["lists"], []);
  const [sel, setSel] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  useEffect(() => { if (!sel && lists?.length) setSel(lists[0].id); }, [lists, sel]);
  const list = lists?.find((l) => l.id === sel);
  return (
    <div className="lists">
      <div className="toolbar">
        <div className="toolbar-l"><h1 className="toolbar-title">Lists</h1></div>
        <div className="toolbar-r"><button className="btn ghost" onClick={() => setAdding(true)}><IconPlus size={20} /> New list</button></div>
      </div>
      <div className="lists-body">
        <nav className="list-nav">
          {(lists ?? []).map((l) => (
            <button key={l.id} className={"list-tab" + (l.id === sel ? " on" : "")} style={{ "--lc": l.color, "--lbg": tint(l.color, 0.14) } as CSSProperties} onClick={() => setSel(l.id)}>
              <span className="lt-emoji">{l.emoji}</span>
              <span className="lt-name">{l.name}</span>
              <span className="lt-count">{l.open_count}</span>
            </button>
          ))}
        </nav>
        {list ? <ListPanel list={list} /> : <Empty>No lists yet</Empty>}
      </div>
      {adding && <NewList onClose={() => setAdding(false)} onCreated={setSel} />}
    </div>
  );
}

export function ListPanel({ list, compact }: { list: TaskList; compact?: boolean }) {
  const { api, people, personById } = useApp();
  const [items] = useData((a) => a.items(list.id), ["lists"], [list.id]);
  const [text, setText] = useState("");
  const [assignee, setAssignee] = useState<string | null>(null);
  async function add(e: FormEvent) {
    e.preventDefault();
    if (!text.trim()) return;
    await api.addItem(list.id, text.trim(), assignee);
    setText("");
  }
  const open = (items ?? []).filter((i) => !i.done);
  const done = (items ?? []).filter((i) => i.done);
  return (
    <div className={"list-panel" + (compact ? " compact" : "")} style={{ "--lc": list.color } as CSSProperties}>
      <form className="add-row" onSubmit={add}>
        <input className="input" placeholder={list.kind === "grocery" ? "Add an item…" : "Add a to-do…"} value={text} onChange={(e) => setText(e.target.value)} />
        {!compact && list.kind === "todo" && (
          <div className="assign">
            {people.map((p) => <Avatar key={p.id} person={p} size={1.9} dim={assignee !== p.id} onClick={() => setAssignee(assignee === p.id ? null : p.id)} />)}
          </div>
        )}
        <button className="btn" type="submit" disabled={!text.trim()}><IconPlus size={20} />{!compact && " Add"}</button>
      </form>
      <div className="items">
        {open.length === 0 && <Empty>All clear ✨</Empty>}
        {open.map((i) => <ItemRow key={i.id} item={i} person={personById(i.person_id)} />)}
        {done.length > 0 && (
          <div className="done-head">
            <span>Done ({done.length})</span>
            <button className="btn ghost small" onClick={() => api.clearDone(list.id)}>Clear</button>
          </div>
        )}
        {done.slice(0, compact ? 3 : 20).map((i) => <ItemRow key={i.id} item={i} person={personById(i.person_id)} />)}
      </div>
    </div>
  );
}

function ItemRow({ item, person }: { item: Item; person?: ReturnType<ReturnType<typeof useApp>["personById"]> }) {
  const { api } = useApp();
  const overdue = item.due && !item.done && item.due < today();
  return (
    <div className={"item" + (item.done ? " done" : "")}>
      <button className="item-check" onClick={() => api.updateItem(item.id, { done: !item.done })} aria-label={item.done ? "Mark not done" : "Mark done"}>
        {item.done && <IconCheck size={20} />}
      </button>
      <span className="item-title">{item.title}</span>
      {item.due && <span className={"item-due" + (overdue ? " late" : "")}>{Math.abs(diffDays(item.due, today())) <= 1 ? relativeDay(item.due) : fmtDayMonth(item.due)}</span>}
      {person && <Avatar person={person} size={1.7} />}
      <button className="icon-btn subtle" onClick={() => api.deleteItem(item.id)} aria-label="Delete"><IconTrash size={18} /></button>
    </div>
  );
}

const COLORS = ["#2FB58A", "#4F7CEC", "#F5A524", "#F0679A", "#9B6BE0", "#14A3B8"];
const LIST_EMOJI = ["📝", "🛒", "🏠", "🎁", "✈️", "📦", "🧳", "🎄", "🍂", "💡"];
function NewList({ onClose, onCreated }: { onClose: () => void; onCreated: (id: string) => void }) {
  const { api } = useApp();
  const [name, setName] = useState("");
  const [emoji, setEmoji] = useState("📝");
  const [color, setColor] = useState(COLORS[1]);
  const create = async () => {
    const l = await api.createList({ name: name.trim(), emoji, color, kind: "todo" });
    onCreated(l.id);
    onClose();
  };
  return (
    <Sheet title="New list" onClose={onClose} footer={<><button className="btn ghost" onClick={onClose}>Cancel</button><span style={{ flex: 1 }} /><button className="btn" disabled={!name.trim()} onClick={create}>Create</button></>}>
      <div className="form">
        <input className="input big" placeholder="List name" value={name} onChange={(e) => setName(e.target.value)} autoFocus />
        <div className="emoji-grid">{LIST_EMOJI.map((e) => <button key={e} className={e === emoji ? "on" : ""} onClick={() => setEmoji(e)}>{e}</button>)}</div>
        <div className="chip-row">{COLORS.map((c) => <button key={c} className={"swatch" + (c === color ? " on" : "")} style={{ background: c }} onClick={() => setColor(c)} />)}</div>
      </div>
    </Sheet>
  );
}
