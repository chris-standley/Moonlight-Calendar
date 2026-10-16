import { useEffect, useRef, useState } from "react";
import { ApiError, Recipe, RecipeIn } from "../../api/types";
import { useApp } from "../../state";
import { Sheet } from "../../components/ui";
import { IconDown, IconPhotos, IconPlus, IconTrash, IconUp } from "../../components/icons";
import { shrinkImage } from "../../recipes/images";
import { metricAmount } from "../../recipes/recipeText";
import { Heart, Stars } from "./bits";

interface StepDraft { key: number; text: string; minutes: string; photo: { id: string; url: string } | null }
let keys = 0;

/** Add or change a recipe, or check one that was just imported (`recipe.id` null) before saving it. */
export function RecipeEditor({ recipe, onSaved, onClose }: { recipe?: Recipe; onSaved?: (r: Recipe) => void; onClose: () => void }) {
  const { api, toast } = useApp();
  const saved = !!recipe?.id;
  const [title, setTitle] = useState(recipe?.title ?? "");
  const [emoji, setEmoji] = useState(recipe?.emoji ?? "");
  const [description, setDescription] = useState(recipe?.description ?? "");
  const [photo, setPhoto] = useState<{ id: string; url: string } | null>(recipe?.photo && recipe.photo_url ? { id: recipe.photo, url: recipe.photo_url } : null);
  const [rating, setRating] = useState(recipe?.rating ?? 0);
  const [favourite, setFavourite] = useState(recipe?.favourite ?? false);
  const [servings, setServings] = useState(recipe?.servings != null ? String(recipe.servings) : "");
  const [prep, setPrep] = useState(recipe?.prep_minutes != null ? String(recipe.prep_minutes) : "");
  const [cook, setCook] = useState(recipe?.cook_minutes != null ? String(recipe.cook_minutes) : "");
  const [tags, setTags] = useState((recipe?.tags ?? []).join(", "));
  const [ingredients, setIngredients] = useState((recipe?.ingredients ?? []).map((i) => i.text).join("\n"));
  const [steps, setSteps] = useState<StepDraft[]>(() => (recipe?.steps ?? []).map((s) => ({
    key: keys++, text: s.text, minutes: s.minutes != null ? String(s.minutes) : "", photo: s.photo && s.photo_url ? { id: s.photo, url: s.photo_url } : null,
  })));
  const [notes, setNotes] = useState(recipe?.notes ?? "");
  const [url, setUrl] = useState(recipe?.url ?? "");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState(0);

  const num = (s: string) => (s.trim() === "" ? null : Number(s));
  const body = (): RecipeIn => ({
    title: title.trim(), emoji: emoji.trim(), description: description.trim(), photo: photo?.id ?? null, rating, favourite,
    servings: num(servings), prep_minutes: num(prep), cook_minutes: num(cook),
    // A saved total was for the old times; let it follow prep + cook unless only the total was known.
    minutes: recipe?.minutes != null && recipe.prep_minutes == null && recipe.cook_minutes == null && !prep && !cook ? recipe.minutes : null,
    tags: tags.split(",").map((t) => t.trim()).filter(Boolean),
    ingredients: ingredients.split("\n").map((l) => l.trim()).filter(Boolean),
    steps: steps.filter((s) => s.text.trim() || s.photo).map((s) => ({ text: s.text.trim(), minutes: num(s.minutes), photo: s.photo?.id ?? null })),
    notes: notes.trim(), url: url.trim() || null,
  });

  // How the lines read (amounts, metric, timers), a moment after typing stops.
  const [preview, setPreview] = useState<Recipe | null>(null);
  useEffect(() => {
    const b = body();
    const t = setTimeout(() => { api.previewRecipe({ ingredients: b.ingredients, steps: b.steps }).then(setPreview).catch(() => {}); }, 500);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, ingredients, steps]);

  async function upload(file: File | undefined, set: (p: { id: string; url: string }) => void) {
    if (!file) return;
    setUploading((n) => n + 1);
    try { set(await api.uploadImage(await shrinkImage(file))); }
    catch (e) { setError(e instanceof ApiError ? e.message : "Couldn't upload that picture"); }
    finally { setUploading((n) => n - 1); }
  }
  const setStep = (key: number, patch: Partial<StepDraft>) => setSteps((ss) => ss.map((s) => (s.key === key ? { ...s, ...patch } : s)));
  const move = (idx: number, d: number) => setSteps((ss) => {
    const n = [...ss]; const [x] = n.splice(idx, 1); n.splice(Math.max(0, Math.min(n.length, idx + d)), 0, x); return n;
  });

  const valid = title.trim() !== "" && [servings, prep, cook].every((v) => v.trim() === "" || /^\d+$/.test(v.trim()))
    && steps.every((s) => s.minutes.trim() === "" || /^\d+(\.\d+)?$/.test(s.minutes.trim()));
  async function save() {
    if (!valid || busy) return;
    setBusy(true);
    setError(null);
    try {
      const r = saved ? await api.updateRecipe(recipe!.id, body()) : await api.createRecipe(body());
      toast(saved ? "Recipe saved" : "Recipe added");
      onSaved?.(r);
      onClose();
    } catch (e) { setError(e instanceof ApiError ? e.message : "Couldn't save"); setBusy(false); }
  }
  async function remove() {
    if (!saved) return;
    if (!confirmDelete) { setConfirmDelete(true); return; }
    try { await api.deleteRecipe(recipe!.id); toast("Recipe deleted"); onClose(); }
    catch (e) { setError(e instanceof ApiError ? e.message : "Couldn't delete"); }
  }
  const picFile = useRef<HTMLInputElement>(null);

  return (
    <Sheet title={saved ? "Edit recipe" : recipe ? "Check the recipe" : "New recipe"} onClose={onClose} wide footer={<>
      {saved && <button className="btn ghost danger" onClick={remove}><IconTrash size={20} /> {confirmDelete ? "Tap again to delete" : "Delete"}</button>}
      <span style={{ flex: 1 }} />
      <button className="btn ghost" onClick={onClose}>Cancel</button>
      <button className="btn" disabled={!valid || busy || uploading > 0} onClick={save}>{uploading ? "Uploading…" : "Save"}</button>
    </>}>
      <form className="form recipe-form" onSubmit={(e) => { e.preventDefault(); save(); }}>
        {recipe && !saved && <p className="muted connect-note">Check what was read, change anything that's wrong, then save.</p>}
        <div className="rf-head">
          <button type="button" className={"rf-photo" + (photo ? " has" : "")} onClick={() => picFile.current?.click()} aria-label={photo ? "Change photo" : "Add a photo"}>
            {photo ? <img src={photo.url} alt="" /> : <><IconPhotos size={30} /><span>Add photo</span></>}
          </button>
          <input ref={picFile} type="file" accept="image/*" hidden onChange={(e) => { void upload(e.target.files?.[0], setPhoto); e.target.value = ""; }} />
          <div className="rf-head-main">
            <div className="rf-top">
              <input className="input big rf-emoji" value={emoji} maxLength={4} onChange={(e) => setEmoji(e.target.value)} placeholder="🍝" aria-label="Emoji" />
              <input className="input big" value={title} maxLength={120} onChange={(e) => setTitle(e.target.value)} placeholder="Recipe name" autoFocus={!recipe} />
            </div>
            <div className="rf-rate">
              <Stars value={rating} onChange={setRating} size={26} />
              <button type="button" className={"heart-btn" + (favourite ? " on" : "")} onClick={() => setFavourite(!favourite)} aria-pressed={favourite} aria-label="Favourite"><Heart on={favourite} size={26} /></button>
              {photo && <button type="button" className="btn ghost small" onClick={() => setPhoto(null)}>Remove photo</button>}
            </div>
          </div>
        </div>
        <textarea className="input rf-text" rows={2} value={description} onChange={(e) => setDescription(e.target.value)} placeholder="A line or two about it (optional)" aria-label="Description" />
        <div className="rf-nums">
          <label><span className="field-label">Serves</span><input className="input" inputMode="numeric" value={servings} onChange={(e) => setServings(e.target.value.replace(/[^0-9]/g, ""))} placeholder="4" /></label>
          <label><span className="field-label">Prep, min</span><input className="input" inputMode="numeric" value={prep} onChange={(e) => setPrep(e.target.value.replace(/[^0-9]/g, ""))} placeholder="15" /></label>
          <label><span className="field-label">Cook, min</span><input className="input" inputMode="numeric" value={cook} onChange={(e) => setCook(e.target.value.replace(/[^0-9]/g, ""))} placeholder="30" /></label>
        </div>
        <label className="field-label">Ingredients, one per line</label>
        <div className="rf-ings">
          <textarea className="input rf-ingredients" rows={8} value={ingredients} onChange={(e) => setIngredients(e.target.value)}
            placeholder={"500g beef mince\n2 cups chopped tomatoes\nFor the topping:\n100g cheddar, grated"} />
          {preview && preview.ingredients.length > 0 && (
            <ul className="rf-reads" aria-label="How the ingredients read">
              {preview.ingredients.map((i, n) => i.heading ? <li key={n} className="ing-head">{i.name}</li> : (
                <li key={n}>
                  {i.quantity != null ? <b>{[i.quantity, i.quantity_max].filter((x) => x != null).join("–")}{i.unit ? ` ${i.unit}` : ""}</b> : <i>no amount</i>}
                  <span>{i.name}</span>
                  {metricAmount(i) && <span className="ing-metric">{metricAmount(i)}</span>}
                </li>
              ))}
            </ul>
          )}
        </div>
        <label className="field-label">Steps</label>
        <ol className="rf-steps">
          {steps.map((s, idx) => {
            const p = preview?.steps[steps.filter((x) => x.text.trim() || x.photo).indexOf(s)];
            return (
              <li key={s.key} className="rf-step">
                <span className="rf-step-n">{idx + 1}</span>
                <div className="rf-step-main">
                  <textarea className="input" rows={2} value={s.text} onChange={(e) => setStep(s.key, { text: e.target.value })} placeholder="What to do" aria-label={`Step ${idx + 1}`} />
                  <div className="rf-step-tools">
                    <label className="rf-min"><input className="input" inputMode="decimal" value={s.minutes} onChange={(e) => setStep(s.key, { minutes: e.target.value.replace(/[^0-9.]/g, "") })} placeholder="–" aria-label="Timer minutes" /> min timer</label>
                    {p?.timers.filter((t) => !s.minutes || t.seconds !== Math.round(Number(s.minutes) * 60)).map((t) => <span key={t.seconds} className="rf-chip">⏱ {t.label}</span>)}
                    {p?.metric_text && <span className="rf-chip metric" title={p.metric_text}>Metric shown</span>}
                    <span style={{ flex: 1 }} />
                    <label className="btn ghost small rf-step-pic">
                      {s.photo ? <img src={s.photo.url} alt="" /> : <IconPhotos size={18} />}{s.photo ? "Change" : "Photo"}
                      <input type="file" accept="image/*" hidden onChange={(e) => { void upload(e.target.files?.[0], (ph) => setStep(s.key, { photo: ph })); e.target.value = ""; }} />
                    </label>
                    {s.photo && <button type="button" className="btn ghost small" onClick={() => setStep(s.key, { photo: null })}>No photo</button>}
                    <button type="button" className="icon-btn" onClick={() => move(idx, -1)} disabled={idx === 0} aria-label="Move up"><IconUp size={20} /></button>
                    <button type="button" className="icon-btn" onClick={() => move(idx, 1)} disabled={idx === steps.length - 1} aria-label="Move down"><IconDown size={20} /></button>
                    <button type="button" className="icon-btn danger" onClick={() => setSteps((ss) => ss.filter((x) => x.key !== s.key))} aria-label="Remove step"><IconTrash size={20} /></button>
                  </div>
                </div>
              </li>
            );
          })}
        </ol>
        <button type="button" className="btn ghost small rf-add-step" onClick={() => setSteps((ss) => [...ss, { key: keys++, text: "", minutes: "", photo: null }])}><IconPlus size={18} /> Add a step</button>
        <label className="field-label">Tags, separated by commas</label>
        <input className="input" value={tags} onChange={(e) => setTags(e.target.value)} placeholder="pasta, quick, kids" />
        <label className="field-label">Notes</label>
        <textarea className="input rf-text" rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Swaps, tips, what the kids thought" />
        <label className="field-label">Link (optional)</label>
        <input className="input" type="url" inputMode="url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…" />
        {error && <div className="connect-error" role="alert">{error}</div>}
        <button type="submit" hidden />
      </form>
    </Sheet>
  );
}
