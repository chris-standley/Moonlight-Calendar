import { useMemo, useState } from "react";
import { ApiError, Recipe, Slot } from "../../api/types";
import { useApp } from "../../state";
import { Segmented, Sheet } from "../../components/ui";
import { IconCalendar, IconCart, IconLeft } from "../../components/icons";
import { addDays, dayNum, fmtDayMonth, fmtDow, today } from "../../dates";
import { Heart, IngredientRow, RecipePicture, ServingsStepper, Stars, TimeFacts, defaultServings, factorFor } from "./bits";
import { AddToListSheet } from "./AddToListSheet";
import { CookMode } from "./CookMode";
import { RecipeEditor } from "./RecipeEditor";

const SLOT_OPTIONS: { value: Slot; label: string }[] = [
  { value: "breakfast", label: "Breakfast" }, { value: "lunch", label: "Lunch" }, { value: "dinner", label: "Dinner" }, { value: "snack", label: "Snack" },
];

/** A recipe, full screen: picture, scaling, ingredients (with metric), steps, and what to do with it. */
export function RecipePage({ recipe, onClose }: { recipe: Recipe; onClose: () => void }) {
  const { api, toast } = useApp();
  const [servings, setServings] = useState(defaultServings(recipe));
  const factor = factorFor(recipe, servings);
  const [sheet, setSheet] = useState<"edit" | "list" | "plan" | "planned" | "cook" | null>(null);
  const lastMade = useMemo(() => {
    if (!recipe.last_cooked) return null;
    const days = Math.round((Date.parse(today()) - Date.parse(recipe.last_cooked)) / 86400000);
    return days <= 0 ? "today" : days === 1 ? "yesterday" : days < 14 ? `${days} days ago` : days < 60 ? `${Math.round(days / 7)} weeks ago` : `${Math.round(days / 30)} months ago`;
  }, [recipe.last_cooked]);

  async function patch(p: { rating?: number; favourite?: boolean }) {
    try { await api.updateRecipe(recipe.id, p); } catch (e) { toast(e instanceof ApiError ? e.message : "Couldn't save"); }
  }
  const scaled = factor !== 1;

  return (
    <div className="recipe-page" role="dialog" aria-label={recipe.title}>
      <div className="rp-bar">
        <button className="btn ghost small" onClick={onClose}><IconLeft size={18} /> Recipes</button>
        <span style={{ flex: 1 }} />
        <button className="btn ghost small" onClick={() => setSheet("edit")}>Edit</button>
      </div>
      <div className="rp-scroll">
        <div className="rp-hero">
          <RecipePicture recipe={recipe} className="rp-pic" />
          <div className="rp-intro">
            <h1>{recipe.title}</h1>
            <div className="rp-rate">
              <Stars value={recipe.rating} onChange={(rating) => patch({ rating })} size={26} />
              <button className={"heart-btn" + (recipe.favourite ? " on" : "")} onClick={() => patch({ favourite: !recipe.favourite })} aria-pressed={recipe.favourite} aria-label="Favourite"><Heart on={recipe.favourite} size={26} /></button>
            </div>
            {recipe.description && <p className="rp-desc">{recipe.description}</p>}
            <TimeFacts recipe={recipe} />
            <p className="rp-made muted">
              {recipe.cooked_count ? `Made ${recipe.cooked_count} ${recipe.cooked_count === 1 ? "time" : "times"}, last ${lastMade}` : "Not made yet"}
              {recipe.tags.length > 0 && <> · {recipe.tags.join(", ")}</>}
            </p>
            <div className="rp-actions">
              <button className="btn" onClick={() => setSheet("cook")} disabled={!recipe.steps.length}>▶ Start cooking</button>
              <button className="btn ghost" onClick={() => setSheet("list")} disabled={!recipe.ingredients.length}><IconCart size={20} /> Add to list</button>
              <button className="btn ghost" onClick={() => setSheet("plan")}><IconCalendar size={20} /> Plan it</button>
              {recipe.url && <a className="btn ghost" href={recipe.url} target="_blank" rel="noreferrer">Original</a>}
            </div>
          </div>
        </div>
        <div className="rp-cols">
          <section className="rp-ings">
            <div className="rp-sec-head">
              <h2>Ingredients</h2>
              <ServingsStepper recipe={recipe} servings={servings} onChange={setServings} />
            </div>
            {scaled && <p className="rp-scaled">Scaled from {recipe.servings ? `${recipe.servings} servings` : "the original"}. <button className="link" onClick={() => setServings(defaultServings(recipe))}>Reset</button></p>}
            {recipe.ingredients.length ? <ul className="ing-list">{recipe.ingredients.map((i, n) => <IngredientRow key={n} ing={i} factor={factor} />)}</ul>
              : <p className="muted">No ingredients yet.</p>}
          </section>
          <section className="rp-steps">
            <h2>Method</h2>
            {recipe.steps.length ? (
              <ol className="step-list">
                {recipe.steps.map((s, n) => (
                  <li key={n}>
                    <span className="step-n">{n + 1}</span>
                    <div>
                      <p>{s.metric_text ?? s.text}</p>
                      {s.photo_url && <img src={s.photo_url} alt="" loading="lazy" />}
                      {s.timers.length > 0 && <div className="step-timers">{s.timers.map((t) => <span key={t.seconds}>⏱ {t.label}</span>)}</div>}
                    </div>
                  </li>
                ))}
              </ol>
            ) : <p className="muted">No steps yet. Tap Edit to add them.</p>}
            {recipe.notes && <><h2>Notes</h2><p className="rp-notes">{recipe.notes}</p></>}
          </section>
        </div>
      </div>
      {sheet === "edit" && <RecipeEditor recipe={recipe} onClose={() => setSheet(null)} />}
      {sheet === "list" && <AddToListSheet recipe={recipe} servings={servings} onClose={() => setSheet(null)} />}
      {sheet === "plan" && <PlanSheet recipe={recipe} onClose={() => setSheet(null)} onPlanned={() => setSheet(recipe.ingredients.length ? "planned" : null)} />}
      {sheet === "planned" && <AddToListSheet recipe={recipe} servings={servings} title="Add the ingredients to a list?" onClose={() => setSheet(null)} />}
      {sheet === "cook" && <CookMode recipe={recipe} factor={factor} onClose={() => setSheet(null)} />}
    </div>
  );
}

/** Put a recipe on the meal plan: pick a day in the next two weeks and a meal. */
function PlanSheet({ recipe, onClose, onPlanned }: { recipe: Recipe; onClose: () => void; onPlanned: () => void }) {
  const { api, toast } = useApp();
  const days = Array.from({ length: 14 }, (_, i) => addDays(today(), i));
  const [day, setDay] = useState(days[0]);
  const [slot, setSlot] = useState<Slot>("dinner");
  async function plan() {
    try {
      await api.createMeal({ date: day, slot, title: recipe.title, notes: "", recipe_id: recipe.id });
      toast(`${recipe.title} planned for ${fmtDow(day)} ${fmtDayMonth(day)}`);
      onPlanned();
    } catch (e) { toast(e instanceof ApiError ? e.message : "Couldn't plan it"); }
  }
  return (
    <Sheet title={`Plan ${recipe.title}`} onClose={onClose} footer={<>
      <span style={{ flex: 1 }} />
      <button className="btn ghost" onClick={onClose}>Cancel</button>
      <button className="btn" onClick={plan}>Plan it</button>
    </>}>
      <div className="form">
        <Segmented value={slot} onChange={setSlot} options={SLOT_OPTIONS} />
        <div className="plan-days">
          {days.map((d) => (
            <button key={d} type="button" className={"plan-day" + (d === day ? " on" : "")} onClick={() => setDay(d)}>
              <span>{d === today() ? "Today" : fmtDow(d)}</span><b>{dayNum(d)}</b>
            </button>
          ))}
        </div>
      </div>
    </Sheet>
  );
}
