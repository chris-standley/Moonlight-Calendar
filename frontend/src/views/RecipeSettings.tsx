import { useState } from "react";
import { ApiError } from "../api/types";
import { useApp, useData } from "../state";
import { Sheet } from "../components/ui";

/** Settings › Recipes: the Anthropic API key Moonlight uses to read recipe photos (and pages without recipe data). */
export function RecipesPanel() {
  const { api, askPin, toast } = useApp();
  const [reader] = useData((a) => a.recipeReader(), ["settings"], []);
  const [editing, setEditing] = useState(false);
  async function remove() {
    const pin = await askPin("Remove the Anthropic key");
    if (!pin) return;
    try { await api.removeRecipeReader(pin); toast("Key removed"); }
    catch (e) { toast(e instanceof ApiError ? e.message : "Couldn't remove it"); }
  }
  return (
    <section className="panel">
      <h2 className="panel-title">Recipes</h2>
      <p className="muted connect-note">Links from most recipe sites and pasted text are read by Moonlight itself. To read photos of cookbook pages
        here, Moonlight asks Claude, Anthropic's AI, using your own API key (each photo costs a few pence). The iPhone app reads photos on the phone, without a key.</p>
      <div className="set-row"><span>Reading photos with Claude</span>
        <span className="set-pin"><b>{reader?.configured ? `On (key ${reader.key_hint})` : "Off"}</b>
          <button className="btn ghost small" onClick={() => setEditing(true)}>{reader?.configured ? "Change" : "Add key"}</button>
          {reader?.configured && <button className="btn ghost small danger" onClick={remove}>Remove</button>}</span>
      </div>
      {editing && <KeySheet model={reader?.model ?? "claude-opus-5-5"} onClose={() => setEditing(false)} />}
    </section>
  );
}

function KeySheet({ model: startModel, onClose }: { model: string; onClose: () => void }) {
  const { api, askPin, toast } = useApp();
  const [key, setKey] = useState("");
  const [model, setModel] = useState(startModel);
  const [error, setError] = useState<string | null>(null);
  async function save() {
    const pin = await askPin("Save the Anthropic key");
    if (!pin) return;
    try {
      await api.saveRecipeReader({ ...(key.trim() ? { api_key: key.trim() } : {}), model: model.trim() || null, pin });
      toast("Saved");
      onClose();
    } catch (e) { setError(e instanceof ApiError ? e.message : "Couldn't save"); }
  }
  return (
    <Sheet title="Anthropic API key" onClose={onClose} footer={<>
      <span style={{ flex: 1 }} />
      <button className="btn ghost" onClick={onClose}>Cancel</button>
      <button className="btn" onClick={save} disabled={!key.trim() && model.trim() === startModel}>Save</button>
    </>}>
      <div className="form">
        <p className="muted connect-note">Make a key at console.anthropic.com under API keys, then paste it here. Moonlight keeps it on your Home Assistant and never shows it again.</p>
        <input className="input big" type="password" autoComplete="off" value={key} onChange={(e) => setKey(e.target.value)} placeholder="sk-ant-…" aria-label="API key" />
        <label className="field-label">Model</label>
        <input className="input" value={model} onChange={(e) => setModel(e.target.value)} aria-label="Model" />
        {error && <div className="connect-error" role="alert">{error}</div>}
      </div>
    </Sheet>
  );
}
