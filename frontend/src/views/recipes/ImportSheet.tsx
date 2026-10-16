import { useState } from "react";
import { ApiError, Recipe } from "../../api/types";
import { useApp, useData } from "../../state";
import { Segmented, Sheet } from "../../components/ui";
import { IconPhotos } from "../../components/icons";
import { shrinkImage } from "../../recipes/images";

type Mode = "link" | "text" | "photo";

/** Bring a recipe in from a web page, pasted text or photos of a cookbook. Hands back a draft to check and save. */
export function ImportSheet({ onDraft, onClose, start = "link" }: { onDraft: (r: Recipe) => void; onClose: () => void; start?: Mode }) {
  const { api, go } = useApp();
  const [reader] = useData((a) => a.recipeReader(), ["settings"], []);
  const [mode, setMode] = useState<Mode>(start);
  const [url, setUrl] = useState("");
  const [text, setText] = useState("");
  const [useReader, setUseReader] = useState(true);
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    setError(null);
    try {
      let draft: Recipe;
      if (mode === "link") {
        setBusy("Opening the page…");
        draft = await api.importRecipe({ url: url.trim() });
      } else if (mode === "text") {
        setBusy(reader?.configured && useReader ? "Claude is reading it…" : "Reading…");
        draft = await api.importRecipe({ text, use_reader: !!reader?.configured && useReader });
      } else {
        setBusy("Uploading…");
        const ids: string[] = [];
        for (const f of files) ids.push((await api.uploadImage(await shrinkImage(f, 2000, 0.9))).id);
        setBusy("Claude is reading the photos…");
        draft = await api.importRecipe({ images: ids });
      }
      onDraft(draft);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Something went wrong. Try again.");
    } finally { setBusy(null); }
  }
  const ready = mode === "link" ? /^https?:\/\/\S+$/i.test(url.trim()) : mode === "text" ? text.trim().length > 10 : files.length > 0;

  return (
    <Sheet title="Add a recipe from…" onClose={onClose} footer={<>
      <span style={{ flex: 1 }} />
      <button className="btn ghost" onClick={onClose}>Cancel</button>
      <button className="btn" disabled={!ready || !!busy || (mode === "photo" && !reader?.configured)} onClick={run}>{busy ?? "Read recipe"}</button>
    </>}>
      <div className="form">
        <Segmented value={mode} onChange={(m) => { setMode(m); setError(null); }} options={[
          { value: "link", label: "A link" }, { value: "text", label: "Pasted text" }, { value: "photo", label: "Photos" },
        ]} />
        {mode === "link" && <>
          <p className="muted connect-note">Paste the address of a recipe page. Most recipe sites mark out the ingredients, steps, times and picture, so they come straight in.</p>
          <input className="input big" type="url" inputMode="url" autoFocus value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…" onKeyDown={(e) => { if (e.key === "Enter" && ready) void run(); }} />
        </>}
        {mode === "text" && <>
          <p className="muted connect-note">Paste or type the whole recipe: the name on the first line, then the ingredients and the method.</p>
          <textarea className="input rf-ingredients" rows={10} autoFocus value={text} onChange={(e) => setText(e.target.value)}
            placeholder={"Lemon drizzle cake\nServes 8\nIngredients\n225g butter\n…\nMethod\n1. Heat the oven…"} />
          {reader?.configured && (
            <div className="set-row"><span>Let Claude read it (better with messy text)</span>
              <button type="button" className={"toggle" + (useReader ? " on" : "")} onClick={() => setUseReader(!useReader)} aria-pressed={useReader} aria-label="Let Claude read it"><span /></button>
            </div>
          )}
        </>}
        {mode === "photo" && (reader?.configured ? <>
          <p className="muted connect-note">Take or choose photos of the recipe, one per page, in order. Claude reads them; you check everything before it's saved.</p>
          <label className="btn ghost import-pick"><IconPhotos size={22} /> {files.length ? `${files.length} photo${files.length > 1 ? "s" : ""} chosen` : "Choose photos"}
            <input type="file" accept="image/*" multiple hidden onChange={(e) => setFiles([...(e.target.files ?? [])].slice(0, 6))} />
          </label>
          {files.length > 0 && <div className="import-thumbs">{files.map((f, i) => <img key={i} src={URL.createObjectURL(f)} alt={`Page ${i + 1}`} />)}</div>}
        </> : (
          <div className="import-noreader">
            <p>Reading photos here needs Claude, Anthropic's AI. Add an Anthropic API key in <button type="button" className="link" onClick={() => { onClose(); go("settings"); }}>Settings › Recipes</button>.</p>
            <p className="muted">The Moonlight iPhone app reads recipe photos on the phone itself, with no key needed.</p>
          </div>
        ))}
        {error && <div className="connect-error" role="alert">{error}</div>}
      </div>
    </Sheet>
  );
}
