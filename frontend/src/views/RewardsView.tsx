import { CSSProperties, useState } from "react";
import { ApiError, Person, Reward } from "../api/types";
import { fmtDayMonth, fmtTime, relativeDay, diffDays, today } from "../dates";
import { useApp, useData } from "../state";
import { Avatar, Sheet, tint } from "../components/ui";
import { IconPlus, IconStar, IconTrash } from "../components/icons";
import { FamilyPrompt } from "./FamilySettings";

export function RewardsView() {
  const { people } = useApp();
  const kids = people.filter((p) => p.role === "child");
  const [rewards] = useData((api) => api.rewards(), ["rewards"], []);
  const [points] = useData((api) => api.points(), ["points"], []);
  const [adding, setAdding] = useState(false);
  return (
    <div className="rewards">
      <div className="toolbar">
        <div className="toolbar-l"><h1 className="toolbar-title">Rewards</h1></div>
        <div className="toolbar-r"><button className="btn ghost" onClick={() => setAdding(true)}><IconPlus size={20} /> New reward</button></div>
      </div>
      {kids.length === 0 ? (
        people.length === 0 ? <FamilyPrompt>Children earn stars for chores and spend them here. Add your family in Settings › Family to get started.</FamilyPrompt>
          : <FamilyPrompt kids />
      ) : (
        <div className="reward-cols" style={{ "--cols": kids.length } as CSSProperties}>
          {kids.map((k) => (
            <KidRewards key={k.id} kid={k} balance={points?.find((b) => b.person_id === k.id)?.balance ?? 0}
              rewards={(rewards ?? []).filter((r) => !r.person_id || r.person_id === k.id).sort((a, b) => a.cost - b.cost)} />
          ))}
        </div>
      )}
      {adding && <RewardForm onClose={() => setAdding(false)} />}
    </div>
  );
}

function KidRewards({ kid, balance, rewards }: { kid: Person; balance: number; rewards: Reward[] }) {
  const { api, askPin, toast, celebrate } = useApp();
  const [ledger] = useData((a) => a.ledger(kid.id), ["points"], [kid.id]);
  const [bonus, setBonus] = useState(false);
  const [editing, setEditing] = useState<Reward | null>(null);
  async function redeem(r: Reward, ev: React.MouseEvent) {
    const { clientX, clientY } = ev;
    const pin = await askPin(`${kid.name} wants “${r.title}” for ${r.cost} stars`);
    if (!pin) return;
    try {
      await api.redeem(r.id, kid.id, pin);
      celebrate(clientX, clientY, kid.color);
      toast(`${r.emoji} Enjoy, ${kid.name}!`);
    } catch (e) { toast(e instanceof ApiError ? e.message : "Something went wrong"); }
  }
  return (
    <div className="kid-rewards" style={{ "--pc": kid.color, "--pbg": tint(kid.color, 0.1) } as CSSProperties}>
      <header className="kr-head">
        <Avatar person={kid} size={3.4} />
        <div><b>{kid.name}</b><span className="kr-bal"><IconStar size={30} filled /> {balance}</span></div>
        <button className="btn ghost small" onClick={() => setBonus(true)}>+ Bonus</button>
      </header>
      <div className="kr-list">
        {rewards.map((r) => {
          const pct = Math.min(1, balance / r.cost);
          const can = balance >= r.cost;
          return (
            <div key={r.id} className={"reward" + (can ? " can" : "")}>
              <button className="rw-emoji" onClick={() => setEditing(r)} aria-label={`Edit ${r.title}`}>{r.emoji}</button>
              <div className="rw-main">
                <button className="rw-title" onClick={() => setEditing(r)}>{r.title}</button>
                <div className="rw-bar"><i style={{ width: `${pct * 100}%` }} /></div>
                <span className="rw-cost"><IconStar size={14} filled /> {can ? `${r.cost}` : `${balance} / ${r.cost}`}</span>
              </div>
              <button className="btn small" disabled={!can} onClick={(e) => redeem(r, e)}>{can ? "Redeem" : `${r.cost - balance} to go`}</button>
            </div>
          );
        })}
      </div>
      <div className="kr-history">
        <div className="cc-group-label">Recent stars</div>
        {(ledger ?? []).slice(0, 6).map((l) => (
          <div key={l.id} className="lg-row">
            <span className="lg-reason">{l.reason}</span>
            <span className="lg-when">{Math.abs(diffDays(l.at, today())) <= 1 ? `${relativeDay(l.at.slice(0, 10))} ${fmtTime(l.at)}` : fmtDayMonth(l.at.slice(0, 10))}</span>
            <span className={"lg-change" + (l.change < 0 ? " neg" : "")}>{l.change > 0 ? "+" : ""}{l.change}</span>
          </div>
        ))}
      </div>
      {bonus && <BonusSheet kid={kid} onClose={() => setBonus(false)} />}
      {editing && <RewardForm reward={editing} onClose={() => setEditing(null)} />}
    </div>
  );
}

function BonusSheet({ kid, onClose }: { kid: Person; onClose: () => void }) {
  const { api, askPin, toast } = useApp();
  const [n, setN] = useState(5);
  const [reason, setReason] = useState("Being helpful");
  async function give() {
    const pin = await askPin(`Give ${kid.name} ${n} bonus stars`);
    if (!pin) return;
    try { await api.adjustPoints(kid.id, n, `💛 ${reason}`, pin); toast(`+${n} stars for ${kid.name}`); onClose(); }
    catch (e) { toast(e instanceof ApiError ? e.message : "Something went wrong"); }
  }
  return (
    <Sheet title={`Bonus stars for ${kid.name}`} onClose={onClose} footer={<><span style={{ flex: 1 }} /><button className="btn" onClick={give}>Give {n} stars</button></>}>
      <div className="form">
        <div className="stepper big">
          <button className="icon-btn" onClick={() => setN(Math.max(1, n - 1))}>−</button>
          <span><IconStar size={28} filled /> {n}</span>
          <button className="icon-btn" onClick={() => setN(n + 1)}>+</button>
        </div>
        <label className="field-label">What for?</label>
        <input className="input" value={reason} onChange={(e) => setReason(e.target.value)} />
      </div>
    </Sheet>
  );
}

const REWARD_EMOJI = ["🎁", "📱", "🍦", "🎬", "🌙", "🧱", "⛺", "🎮", "🍕", "🎨", "⚽", "🛝", "🍫", "🎟️"];
/** New reward, or edit / delete one (tap a reward's name). Changing or deleting needs the PIN. */
function RewardForm({ reward, onClose }: { reward?: Reward; onClose: () => void }) {
  const { api, people, askPin, toast } = useApp();
  const [title, setTitle] = useState(reward?.title ?? "");
  const [emoji, setEmoji] = useState(reward?.emoji || "🎁");
  const [cost, setCost] = useState(reward?.cost ?? 20);
  const [pid, setPid] = useState<string | null>(reward?.person_id ?? null);
  const [confirm, setConfirm] = useState(false);
  const emojis = REWARD_EMOJI.includes(emoji) ? REWARD_EMOJI : [emoji, ...REWARD_EMOJI];
  async function save() {
    try {
      const fields = { title: title.trim(), emoji, cost, person_id: pid };
      if (reward) {
        const pin = await askPin(`Change “${reward.title}”`);
        if (!pin) return;
        await api.updateReward(reward.id, fields);
        toast("Reward saved");
      } else {
        await api.createReward(fields);
        toast("Reward added");
      }
      onClose();
    } catch (e) { toast(e instanceof ApiError ? e.message : "Couldn't save"); }
  }
  async function remove() {
    if (!reward) return;
    if (!confirm) { setConfirm(true); return; }
    const pin = await askPin(`Delete “${reward.title}”?`);
    if (!pin) return;
    try { await api.deleteReward(reward.id); toast("Reward deleted"); onClose(); }
    catch (e) { toast(e instanceof ApiError ? e.message : "Couldn't delete"); }
  }
  return (
    <Sheet title={reward ? "Edit reward" : "New reward"} onClose={onClose} footer={<>
      {reward ? <button className="btn ghost danger" onClick={remove}><IconTrash size={18} /> {confirm ? "Tap again to delete" : "Delete"}</button>
        : <button className="btn ghost" onClick={onClose}>Cancel</button>}
      <span style={{ flex: 1 }} />
      <button className="btn" disabled={!title.trim()} onClick={save}>{reward ? "Save" : "Add reward"}</button></>}>
      <div className="form">
        <input className="input big" placeholder="e.g. Trip to the park" value={title} onChange={(e) => setTitle(e.target.value)} autoFocus={!reward} />
        <div className="emoji-grid">{emojis.map((e) => <button key={e} className={e === emoji ? "on" : ""} onClick={() => setEmoji(e)}>{e}</button>)}</div>
        <label className="field-label">Cost</label>
        <div className="stepper">
          <button className="icon-btn" onClick={() => setCost(Math.max(1, cost - 5))}>−</button>
          <span><IconStar size={20} filled /> {cost}</span>
          <button className="icon-btn" onClick={() => setCost(cost + 5)}>+</button>
        </div>
        <label className="field-label">For</label>
        <div className="chip-row">
          <button className={"chip-btn" + (pid === null ? " on" : "")} onClick={() => setPid(null)}>All kids</button>
          {people.filter((p) => p.role === "child").map((p) => (
            <button key={p.id} className={"chip-btn" + (pid === p.id ? " on" : "")} onClick={() => setPid(p.id)}>{p.name}</button>
          ))}
        </div>
      </div>
    </Sheet>
  );
}
