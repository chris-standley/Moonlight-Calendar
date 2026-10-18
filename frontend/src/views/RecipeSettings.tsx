import { useState } from "react";
import { ApiError, RecipeExportFormat } from "../api/types";
import { useApp, useData } from "../state";
import { Sheet } from "../components/ui";

/** Settings › Recipes: the Anthropic API key Moonlight uses to read recipe photos (and pages without recipe data), and
 * sending the recipe box to, or bringing recipes in from, other recipe apps. */
export function RecipesPanel() {
  const { api, askPin, toast } = useApp();
  const [reader] = useData((a) => a.recipeReader(), ["settings"], []);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  async function exportAs(f: RecipeExportFormat) {
    setBusy(f);
    try {
      const { file, name } = await api.exportRecipes(f);
      const a = document.createElement("a");
      a.href = URL.createObjectURL(file);
      a.download = name;
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 60_000);
    } catch (e) { toast(e instanceof ApiError ? e.message : "Couldn't make the file"); }
    finally { setBusy(null); }
  }
  async function importFile(f: File) {
    setBusy("import");
    try {
      const r = await api.importRecipes(f);
      toast([`${r.added} recipe${r.added === 1 ? "" : "s"} added`,
        r.skipped.length ? `${r.skipped.length} already in the box` : "",
        r.failed.length ? `${r.failed.length} couldn't be read` : ""].filter(Boolean).join(" · "));
    } catch (e) { toast(e instanceof ApiError ? e.message : "Couldn't bring that file in"); }
    finally { setBusy(null); }
  }
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
      <div className="set-row"><span>Send to another app</span>
        <span className="set-pin">
          {(["mela", "paprika", "schema"] as RecipeExportFormat[]).map((f) => (
            <button key={f} className="btn ghost small" disabled={!!busy} onClick={() => exportAs(f)}>{EXPORT_NAMES[f]}</button>
          ))}
        </span>
      </div>
      <div className="set-row"><span>Bring in from another app<br /><small className="muted" style={{ fontWeight: 400 }}>
        A Mela, Paprika or schema.org recipe file, or a saved recipe page. Recipes already in the box are skipped.</small></span>
        <label className={"btn ghost small" + (busy ? " disabled" : "")}>{busy === "import" ? "Bringing in…" : "Choose file"}
          <input type="file" hidden disabled={!!busy} onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) void importFile(f); }} />
        </label>
      </div>
      {editing && <KeySheet model={reader?.model ?? "claude-opus-5-5"} onClose={() => setEditing(false)} />}
    </section>
  );
}

const EXPORT_NAMES: Record<RecipeExportFormat, string> = { mela: "Mela", paprika: "Paprika", schema: "schema.org JSON" };

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
