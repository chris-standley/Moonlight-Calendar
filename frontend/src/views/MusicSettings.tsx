import { useEffect, useState } from "react";
import { ApiError, Layout, MediaPlayerOption } from "../api/types";
import { useApp } from "../state";
import { Sheet } from "../components/ui";

const LABEL: Record<Layout, string> = { kitchen: "Kitchen screen", hallway: "Hallway screen", phone: "Phones" };
const WHERE: Record<Layout, string> = {
  kitchen: "Card on Today, album art on the screensaver",
  hallway: "Small player in the top bar",
  phone: "Small player in the top bar",
};

/** Settings > Music: which Home Assistant speaker each kind of screen shows and controls. */
export function MusicPanel() {
  const { settings, api } = useApp();
  const [picking, setPicking] = useState<Layout | null>(null);
  const [players, setPlayers] = useState<MediaPlayerOption[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.mediaPlayers().then((p) => { setPlayers(p); setError(null); })
      .catch((e) => setError(e instanceof ApiError ? e.message : "Couldn't reach Home Assistant"));
  }, [api]);
  const chosen = { kitchen: "", hallway: "", phone: "", ...settings?.media_players };
  const nameOf = (id: string) => players?.find((p) => p.entity_id === id)?.name ?? id;
  return (
    <section className="panel music-panel">
      <h2 className="panel-title">Music</h2>
      <p className="muted screens-help">
        Show what's playing on a speaker and control it from the screen. Speakers come from Home Assistant; with
        Music Assistant, Sonos and other speakers appear as <code>media_player</code> entities.
      </p>
      {(["kitchen", "hallway", "phone"] as Layout[]).map((l) => (
        <div key={l} className="music-row">
          <div className="music-main">
            <b>{LABEL[l]}</b>
            <span>{chosen[l] ? `${nameOf(chosen[l])} · ${WHERE[l]}` : "No speaker"}</span>
          </div>
          <button className="btn ghost small" onClick={() => setPicking(l)}>{chosen[l] ? "Change" : "Choose"}</button>
        </div>
      ))}
      {picking && <PlayerPicker layout={picking} current={chosen[picking]} players={players} error={error} onClose={() => setPicking(null)} />}
    </section>
  );
}

function PlayerPicker({ layout, current, players, error, onClose }: {
  layout: Layout; current: string; players: MediaPlayerOption[] | null; error: string | null; onClose: () => void;
}) {
  const { api, askPin, toast } = useApp();
  async function choose(entity: string) {
    if (entity === current) { onClose(); return; }
    const pin = await askPin(`Change the speaker for the ${LABEL[layout].toLowerCase()}`);
    if (!pin) return;
    try {
      await api.updateSettings({ media_players: { [layout]: entity }, pin });
      toast("Saved");
      onClose();
    } catch (e) { toast(e instanceof ApiError ? e.message : "Couldn't save"); }
  }
  return (
    <Sheet title={`Speaker for the ${LABEL[layout].toLowerCase()}`} onClose={onClose}>
      {error && <div className="form-error">{error}</div>}
      {!players && !error && <div className="screens-empty">Asking Home Assistant…</div>}
      <div className="player-list">
        <button className={"player-row" + (current === "" ? " on" : "")} onClick={() => choose("")}>
          <span className="player-main"><b>None</b><span>No Now playing on this screen</span></span>
        </button>
        {(players ?? []).map((p) => (
          <button key={p.entity_id} className={"player-row" + (current === p.entity_id ? " on" : "")} onClick={() => choose(p.entity_id)}>
            <span className="player-main"><b>{p.name}</b><span>{p.entity_id} · {p.state}</span></span>
            {p.music_assistant && <span className="tag ma">Music Assistant</span>}
          </button>
        ))}
        {players && players.length === 0 && <div className="screens-empty">Home Assistant has no media players yet.</div>}
      </div>
    </Sheet>
  );
}
