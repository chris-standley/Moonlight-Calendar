import { useState } from "react";
import { ApiError, Meal, Recipe, Slot } from "../api/types";
import { addDays, dayNum, fmtDayMonth, fmtDow, today, weekStart } from "../dates";
import { useApp, useData } from "../state";
import { Segmented, Sheet } from "../components/ui";
import { IconCart, IconLeft, IconPlus, IconRight, IconTrash } from "../components/icons";

export const SLOTS: { key: Slot; label: string; icon: string }[] = [
  { key: "breakfast", label: "Breakfast", icon: "🥣" },
  { key: "lunch", label: "Lunch", icon: "🥪" },
  { key: "dinner", label: "Dinner", icon: "🍽️" },
  { key: "snack", label: "Snack", icon: "🍎" },
];

export function MealsView() {
  const { settings } = useApp();
  const [tab, setTab] = useState<"plan" | "recipes">("plan");
  const [start, setStart] = useState(() => weekStart(today(), settings?.week_start ?? "monday"));
  const end = addDays(start, 7);
  const [meals] = useData((api) => api.meals(start, end), ["meals"], [start]);
  const [recipes] = useData((api) => api.recipes(), ["recipes"], []);
  const [edit, setEdit] = useState<{ date: string; slot: Slot; meal?: Meal } | null>(null);
  const [recipe, setRecipe] = useState<Recipe | "new" | null>(null);
  const days = Array.from({ length: 7 }, (_, i) => addDays(start, i));
  return (
    <div className="meals">
      <div className="toolbar">
        <div className="toolbar-l">
          {tab === "plan" ? <>
            <button className="btn ghost" onClick={() => setStart(weekStart(today(), settings?.week_start ?? "monday"))}>This week</button>
            <button className="icon-btn" onClick={() => setStart(addDays(start, -7))} aria-label="Previous week"><IconLeft /></button>
            <button className="icon-btn" onClick={() => setStart(addDays(start, 7))} aria-label="Next week"><IconRight /></button>
            <h1 className="toolbar-title">{fmtDayMonth(start)} – {fmtDayMonth(addDays(end, -1))}</h1>
          </> : <h1 className="toolbar-title">Recipe box</h1>}
        </div>
        <div className="toolbar-r">
          <Segmented value={tab} onChange={setTab} options={[{ value: "plan", label: "Meal plan" }, { value: "recipes", label: "Recipes" }]} />
        </div>
      </div>
      {tab === "plan" ? (
        <div className="meal-grid">
          <div className="mg-corner" />
          {days.map((d) => (
            <div key={d} className={"mg-day" + (d === today() ? " today" : "")}><span>{fmtDow(d)}</span><b>{dayNum(d)}</b></div>
          ))}
          {SLOTS.map((s) => (
            <MealRow key={s.key} slot={s} days={days} meals={meals ?? []} recipes={recipes ?? []} onEdit={(date, meal) => setEdit({ date, slot: s.key, meal })} />
          ))}
        </div>
      ) : (<>
        <RecipeBox recipes={recipes ?? []} onEdit={setRecipe} />
        <button className="fab" onClick={() => setRecipe("new")} aria-label="New recipe"><IconPlus size={30} /></button>
      </>)}
      {recipe && <RecipeSheet recipe={recipe === "new" ? undefined : recipe} onClose={() => setRecipe(null)} />}
      {edit && <MealSheet {...edit} recipes={recipes ?? []} onClose={() => setEdit(null)} />}
    </div>
  );
}

function MealRow({ slot, days, meals, recipes, onEdit }: {
  slot: (typeof SLOTS)[number]; days: string[]; meals: Meal[]; recipes: Recipe[]; onEdit: (d: string, m?: Meal) => void;
}) {
  return (
    <>
      <div className={"mg-slot " + slot.key}><span>{slot.icon}</span>{slot.label}</div>
      {days.map((d) => {
        const m = meals.find((x) => x.date === d && x.slot === slot.key);
        const r = m?.recipe_id ? recipes.find((x) => x.id === m.recipe_id) : undefined;
        return (
          <button key={d} className={"mg-cell " + slot.key + (m ? " filled" : "") + (d === today() ? " today" : "")} onClick={() => onEdit(d, m)}>
            {m ? <>
              {r && <span className="mg-emoji">{r.emoji}</span>}
              <span className="mg-title">{m.title}</span>
              {r?.minutes != null && <span className="mg-sub">{r.minutes} min</span>}
            </> : <IconPlus size={22} className="mg-add" />}
          </button>
        );
      })}
    </>
  );
}

function MealSheet({ date, slot, meal, recipes, onClose }: { date: string; slot: Slot; meal?: Meal; recipes: Recipe[]; onClose: () => void }) {
  const { api, toast } = useApp();
  const [title, setTitle] = useState(meal?.title ?? "");
  const [recipeId, setRecipeId] = useState<string | null>(meal?.recipe_id ?? null);
  const label = SLOTS.find((s) => s.key === slot)!.label;
  async function save() {
    if (meal) await api.updateMeal(meal.id, { title: title.trim(), recipe_id: recipeId });
    else await api.createMeal({ date, slot, title: title.trim(), notes: "", recipe_id: recipeId });
    onClose();
  }
  return (
    <Sheet title={`${label}, ${fmtDow(date)} ${fmtDayMonth(date)}`} onClose={onClose} wide footer={<>
      {meal && <button className="btn ghost danger" onClick={async () => { await api.deleteMeal(meal.id); toast("Meal removed"); onClose(); }}><IconTrash size={20} /> Remove</button>}
      <span style={{ flex: 1 }} />
      <button className="btn" disabled={!title.trim()} onClick={save}>Save</button>
    </>}>
      <div className="form">
        <input className="input big" placeholder="What's cooking?" value={title} onChange={(e) => { setTitle(e.target.value); setRecipeId(null); }} />
        <label className="field-label">Or pick from the recipe box</label>
        <div className="recipe-pick">
          {recipes.map((r) => (
            <button key={r.id} className={"rp" + (recipeId === r.id ? " on" : "")} onClick={() => { setRecipeId(r.id); setTitle(r.title); }}>
              <span>{r.emoji}</span>{r.title}
            </button>
          ))}
        </div>
      </div>
    </Sheet>
  );
}

function RecipeBox({ recipes, onEdit }: { recipes: Recipe[]; onEdit: (r: Recipe) => void }) {
  const { api, toast } = useApp();
  const [lists] = useData((a) => a.lists(), ["lists"], []);
  const grocery = lists?.find((l) => l.kind === "grocery");
  return (
    <div className="recipe-box">
      {recipes.length === 0 && <div className="screens-empty">No recipes yet. Tap + to add one.</div>}
      {recipes.map((r) => (
        <div key={r.id} className="recipe">
          <button className="rc-head" onClick={() => onEdit(r)} aria-label={`Edit ${r.title}`}>
            <span className="rc-emoji">{r.emoji || "🍽️"}</span>
            <b>{r.title}</b>
            <span className="rc-min">{[r.minutes != null && `${r.minutes} min`, `${r.ingredients.length} ingredients`].filter(Boolean).join(" · ")}</span>
          </button>
          <ul>{r.ingredients.map((i, n) => <li key={n}>{i}</li>)}</ul>
          <div className="rc-actions">
            {grocery && r.ingredients.length > 0 && <button className="btn ghost small" onClick={async () => {
              const n = await api.recipeToList(r.id, grocery.id);
              toast(`Added ${n} items to ${grocery.name}`);
            }}><IconCart size={18} /> Add to {grocery.name}</button>}
            {r.url && <a className="btn ghost small" href={r.url} target="_blank" rel="noreferrer">Open recipe</a>}
            <button className="btn ghost small" onClick={() => onEdit(r)}>Edit</button>
          </div>
        </div>
      ))}
    </div>
  );
}

function RecipeSheet({ recipe, onClose }: { recipe?: Recipe; onClose: () => void }) {
  const { api, toast } = useApp();
  const [title, setTitle] = useState(recipe?.title ?? "");
  const [emoji, setEmoji] = useState(recipe?.emoji ?? "");
  const [minutes, setMinutes] = useState(recipe?.minutes != null ? String(recipe.minutes) : "");
  const [ingredients, setIngredients] = useState((recipe?.ingredients ?? []).join("\n"));
  const [url, setUrl] = useState(recipe?.url ?? "");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mins = minutes.trim() === "" ? null : Number(minutes);
  const valid = title.trim() !== "" && (mins === null || (Number.isInteger(mins) && mins >= 0));
  async function save() {
    if (!valid) return;
    const body = { title: title.trim(), emoji: emoji.trim(), minutes: mins, url: url.trim() || null,
      ingredients: ingredients.split("\n").map((i) => i.trim()).filter(Boolean) };
    try {
      if (recipe) await api.updateRecipe(recipe.id, body); else await api.createRecipe(body);
      toast(recipe ? "Recipe saved" : "Recipe added");
      onClose();
    } catch (e) { setError(e instanceof ApiError ? e.message : "Couldn't save"); }
  }
  async function remove() {
    if (!recipe) return;
    if (!confirmDelete) { setConfirmDelete(true); return; }
    try { await api.deleteRecipe(recipe.id); toast("Recipe deleted"); onClose(); }
    catch (e) { setError(e instanceof ApiError ? e.message : "Couldn't delete"); }
  }
  return (
    <Sheet title={recipe ? "Edit recipe" : "New recipe"} onClose={onClose} wide footer={<>
      {recipe && <button className="btn ghost danger" onClick={remove}><IconTrash size={20} /> {confirmDelete ? "Tap again to delete" : "Delete"}</button>}
      <span style={{ flex: 1 }} />
      <button className="btn ghost" onClick={onClose}>Cancel</button>
      <button className="btn" disabled={!valid} onClick={save}>Save</button>
    </>}>
      <form className="form recipe-form" onSubmit={(e) => { e.preventDefault(); save(); }}>
        <div className="rf-top">
          <input className="input big rf-emoji" value={emoji} maxLength={4} onChange={(e) => setEmoji(e.target.value)} placeholder="🍝" aria-label="Emoji" />
          <input className="input big" value={title} maxLength={80} onChange={(e) => setTitle(e.target.value)} placeholder="Recipe name" autoFocus={!recipe} />
        </div>
        <label className="field-label">Minutes</label>
        <input className="input rf-minutes" inputMode="numeric" value={minutes} onChange={(e) => setMinutes(e.target.value.replace(/[^0-9]/g, ""))} placeholder="30" />
        <label className="field-label">Ingredients, one per line</label>
        <textarea className="input rf-ingredients" rows={7} value={ingredients} onChange={(e) => setIngredients(e.target.value)} placeholder={"Spaghetti\nMince\nChopped tomatoes"} />
        <label className="field-label">Link (optional)</label>
        <input className="input" type="url" inputMode="url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…" />
        {error && <div className="connect-error" role="alert">{error}</div>}
        <button type="submit" hidden />
      </form>
    </Sheet>
  );
}
