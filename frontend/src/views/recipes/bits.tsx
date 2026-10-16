import { CSSProperties, ReactNode } from "react";
import { Ingredient, Recipe, Step } from "../../api/types";
import { IconStar } from "../../components/icons";
import { fmtMinutes, fmtNumber, ingredientLine, metricAmount } from "../../recipes/recipeText";

/** Five stars; tap one to set the rating, tap the same again to clear it. Read-only without onChange. */
export function Stars({ value, onChange, size = 22 }: { value: number; onChange?: (v: number) => void; size?: number }) {
  return (
    <span className={"stars" + (onChange ? " edit" : "")} role={onChange ? "radiogroup" : "img"} aria-label={`${value} of 5 stars`}>
      {[1, 2, 3, 4, 5].map((n) => onChange ? (
        <button key={n} type="button" role="radio" aria-checked={value === n} aria-label={`${n} star${n > 1 ? "s" : ""}`}
          className={n <= value ? "on" : ""} onClick={() => onChange(value === n ? 0 : n)}>
          <IconStar size={size} filled={n <= value} />
        </button>
      ) : <span key={n} className={n <= value ? "on" : ""}><IconStar size={size} filled={n <= value} /></span>)}
    </span>
  );
}

export function Heart({ on, size = 22 }: { on: boolean; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill={on ? "currentColor" : "none"} stroke="currentColor" strokeWidth={2} strokeLinejoin="round">
      <path d="M12 20s-7.5-4.6-7.5-10.2A4.3 4.3 0 0112 7a4.3 4.3 0 017.5 2.8C19.5 15.4 12 20 12 20z" />
    </svg>
  );
}

const TILE_COLORS = ["#FFE7C2", "#FFD9D2", "#DDEBD7", "#DCE3FB", "#EDE0FA", "#FCE7F1", "#D8EFEF"];
/** The recipe's photo, or its emoji on a soft colour picked from the title. */
export function RecipePicture({ recipe, className = "", children }: { recipe: Pick<Recipe, "title" | "emoji" | "photo_url">; className?: string; children?: ReactNode }) {
  const hue = TILE_COLORS[[...recipe.title].reduce((a, c) => a + c.charCodeAt(0), 0) % TILE_COLORS.length];
  return (
    <div className={"rc-pic " + className} style={{ "--tile": hue } as CSSProperties}>
      {recipe.photo_url ? <img src={recipe.photo_url} alt="" loading="lazy" draggable={false} /> : <span className="rc-pic-emoji">{recipe.emoji || "🍽️"}</span>}
      {children}
    </div>
  );
}

/** "−  4 servings  +" (or "1×" when the recipe doesn't say how many it serves). */
export function ServingsStepper({ recipe, servings, onChange }: { recipe: Recipe; servings: number; onChange: (n: number) => void }) {
  const base = recipe.servings;
  const step = base ? 1 : 0.5;
  const min = base ? 1 : 0.5;
  return (
    <div className="stepper" role="group" aria-label="Servings">
      <button type="button" onClick={() => onChange(Math.max(min, servings - step))} disabled={servings <= min} aria-label="Fewer">−</button>
      <span>{base ? <><b>{servings}</b> {servings === 1 ? "serving" : "servings"}</> : <><b>{fmtNumber(servings)}×</b> recipe</>}</span>
      <button type="button" onClick={() => onChange(Math.min(base ? 100 : 10, servings + step))} aria-label="More">+</button>
    </div>
  );
}

/** Scale factor for a chosen number of servings (or a multiplier when the recipe has no servings). */
export const factorFor = (recipe: Recipe, servings: number) => (recipe.servings ? servings / recipe.servings : servings);
export const defaultServings = (recipe: Recipe) => recipe.servings ?? 1;

/** One ingredient: the line (scaled) and its metric amount when the recipe uses cups, ounces and the like. */
export function IngredientRow({ ing, factor }: { ing: Ingredient; factor: number }) {
  if (ing.heading) return <li className="ing-head">{ing.name}</li>;
  return <li className="ing"><IngredientText ing={ing} factor={factor} /></li>;
}

export function IngredientText({ ing, factor }: { ing: Ingredient; factor: number }) {
  const metric = metricAmount(ing, factor);
  return <><span>{ingredientLine(ing, factor)}</span>{metric && <span className="ing-metric">{metric}</span>}</>;
}

export function TimeFacts({ recipe }: { recipe: Recipe }) {
  const parts: [string, number | null][] = [["Prep", recipe.prep_minutes], ["Cook", recipe.cook_minutes], ["Total", recipe.minutes]];
  const shown = parts.filter(([, v]) => v != null);
  if (!shown.length) return null;
  return (
    <div className="rc-facts">
      {shown.map(([k, v]) => <div key={k}><span>{k}</span><b>{fmtMinutes(v)}</b></div>)}
    </div>
  );
}

/** The amounts of the ingredients a step mentions ("225 g butter · 2 eggs"), scaled, with metric where it helps. */
export function StepAmounts({ recipe, step, factor, big }: { recipe: Recipe; step: Step; factor: number; big?: boolean }) {
  const ings = (step.uses ?? []).map((n) => recipe.ingredients[n]).filter(Boolean);
  if (!ings.length) return null;
  return (
    <div className={"step-amounts" + (big ? " big" : "")}>
      {ings.map((ing, n) => {
        const m = metricAmount(ing, factor);
        return <span key={n}>{ingredientLine(ing, factor, false)}{m && <em> ({m})</em>}</span>;
      })}
    </div>
  );
}
