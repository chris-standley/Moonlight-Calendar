import { useEffect, useMemo, useState } from "react";
import { ApiError, Cookbook, Recipe } from "../../api/types";
import { useApp, useData } from "../../state";
import { Segmented, Sheet } from "../../components/ui";
import { IconCamera, IconClose, IconPhotos } from "../../components/icons";
import { shrinkImage } from "../../recipes/images";
import { canStream, hasCamera } from "../../recipes/barcode";
import { BookFinder } from "./BookFinder";
import { PageCamera } from "./PageCamera";

type Mode = "link" | "text" | "photo" | "book";

const MAX_BOOK_PAGES = 200;
const MAX_RECIPE_PAGES = 6;

/** Bring a recipe in from a web page, pasted text or photos of a cookbook. Hands back a draft to check and save. */
/** "book" reads a whole cookbook in the background instead: `onScanning` is called once the pages are sent. */
export function ImportSheet({ onDraft, onScanning, onClose, start = "link" }: {
  onDraft: (r: Recipe) => void; onScanning?: () => void; onClose: () => void; start?: Mode;
}) {
  const { api, go } = useApp();
  const [reader] = useData((a) => a.recipeReader(), ["settings"], []);
  const [mode, setMode] = useState<Mode>(start);
  const [url, setUrl] = useState("");
  const [text, setText] = useState("");
  const [useReader, setUseReader] = useState(true);
  const [cheaper, setCheaper] = useState(false);
  const [book, setBook] = useState("");
  const [cookbook, setCookbook] = useState<Cookbook | null>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [camera, setCamera] = useState(false);
  const [shooting, setShooting] = useState(false);
  useEffect(() => { void hasCamera().then(setCamera); }, []);

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
      } else if (mode === "book") {
        const ids: string[] = [];
        for (const [i, f] of files.entries()) {
          setBusy(`Sending page ${i + 1} of ${files.length}…`);
          ids.push((await api.uploadImage(await shrinkImage(f, 2000, 0.85))).id);
        }
        await api.scanCookbook(ids, cheaper, book.trim(), cookbook?.isbn);
        onScanning?.();
        return;
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
  const photos = mode === "photo" || mode === "book";
  const max = mode === "book" ? MAX_BOOK_PAGES : MAX_RECIPE_PAGES;
  // New pages go after the ones already taken or chosen, so a cookbook can be done in several goes.
  const add = (more: File[]) => setFiles((f) => [...f, ...more].slice(0, max));
  const thumbs = useMemo(() => files.map((f) => URL.createObjectURL(f)), [files]);
  useEffect(() => () => thumbs.forEach((u) => URL.revokeObjectURL(u)), [thumbs]);

  return (
    <>
    <Sheet title="Add a recipe from…" onClose={onClose} footer={<>
      <span style={{ flex: 1 }} />
      <button className="btn ghost" onClick={onClose}>Cancel</button>
      <button className="btn" disabled={!ready || !!busy || (photos && !reader?.configured)} onClick={run}>
        {busy ?? (mode === "book" ? `Read ${files.length} page${files.length === 1 ? "" : "s"}` : "Read recipe")}</button>
    </>}>
      <div className="form">
        <Segmented value={mode} onChange={(m) => { setMode(m); setError(null); setFiles([]); }} options={[
          { value: "link", label: "A link" }, { value: "text", label: "Pasted text" }, { value: "photo", label: "Photos" },
          { value: "book", label: "A cookbook" },
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
        {photos && (reader?.configured ? <>
          <p className="muted connect-note">{mode === "book"
            ? `Take or choose photos of every page you want, in order (up to ${MAX_BOOK_PAGES}). Claude reads them a few at a time while you carry on; the recipes found appear at the top of Recipes to check and save. Recipes that run over two pages are joined up.`
            : "Take or choose photos of the recipe, one per page, in order. Claude reads them; you check everything before it's saved."}</p>
          <div className="import-picks">
            {camera && (canStream()
              ? <button type="button" className="btn ghost import-pick" disabled={!!busy || files.length >= max} onClick={() => setShooting(true)}><IconCamera size={22} /> {files.length ? "Take more photos" : "Take photos"}</button>
              // Not https: the browser's own camera, one page a time. Those pictures aren't kept in the photo library either.
              : <label className={"btn ghost import-pick" + (busy || files.length >= max ? " disabled" : "")}><IconCamera size={22} /> {files.length ? "Take another" : "Take a photo"}
                <input type="file" accept="image/*" capture="environment" hidden onChange={(e) => { add([...(e.target.files ?? [])]); e.target.value = ""; }} />
              </label>)}
            <label className={"btn ghost import-pick" + (busy || files.length >= max ? " disabled" : "")}><IconPhotos size={22} /> Choose photos
              <input type="file" accept="image/*" multiple hidden onChange={(e) => { add([...(e.target.files ?? [])]
                .sort((a, b) => (mode === "book" ? a.name.localeCompare(b.name, undefined, { numeric: true }) : 0))); e.target.value = ""; }} />
            </label>
          </div>
          {files.length > 0 && <>
            <div className="import-thumbs">{thumbs.slice(0, 24).map((u, i) => (
              <span key={u}>
                <img src={u} alt={`Page ${i + 1}`} />
                <button type="button" disabled={!!busy} onClick={() => setFiles((f) => f.filter((_, j) => j !== i))} aria-label={`Take out page ${i + 1}`}><IconClose size={14} /></button>
              </span>
            ))}
              {files.length > 24 && <span className="muted">+{files.length - 24} more</span>}</div>
            <button type="button" className="link import-clear" disabled={!!busy} onClick={() => setFiles([])}>Remove all {files.length} page{files.length === 1 ? "" : "s"}</button>
          </>}
          {mode === "book" && <>
            <label className="field-label">Which cookbook? (optional)</label>
            <BookFinder book={book} setBook={setBook} cookbook={cookbook} setCookbook={setCookbook} disabled={!!busy} />
          </>}
          {mode === "book" && (
            <div className="set-row"><span>Cheaper, slower<br /><small className="muted" style={{ fontWeight: 400 }}>Half the price. Anthropic reads the pages when it has room: usually within the hour, at most a day.</small></span>
              <button type="button" className={"toggle" + (cheaper ? " on" : "")} onClick={() => setCheaper(!cheaper)} aria-pressed={cheaper} aria-label="Cheaper, slower"><span /></button>
            </div>
          )}
        </> : (
          <div className="import-noreader">
            <p>Reading photos here needs Claude, Anthropic's AI. Add an Anthropic API key in <button type="button" className="link" onClick={() => { onClose(); go("settings"); }}>Settings › Recipes</button>.</p>
            <p className="muted">The Moonlight iPhone app reads recipe photos on the phone itself, with no key needed.</p>
          </div>
        ))}
        {error && <div className="connect-error" role="alert">{error}</div>}
      </div>
    </Sheet>
    {shooting && <PageCamera room={max - files.length} onClose={() => setShooting(false)} onDone={(pages) => { add(pages); setShooting(false); }} />}
    </>
  );
}
