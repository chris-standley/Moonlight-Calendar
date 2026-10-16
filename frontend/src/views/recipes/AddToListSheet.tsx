import { useEffect, useMemo, useState } from "react";
import { ApiError, Recipe } from "../../api/types";
import { useApp, useData } from "../../state";
import { Segmented, Sheet } from "../../components/ui";
import { IconCart, IconCheck } from "../../components/icons";
import { metricAmount, ingredientLine, shoppingLine } from "../../recipes/recipeText";
import { ServingsStepper, defaultServings, factorFor } from "./bits";

/** Things most kitchens already have: left unticked so they don't clutter the shopping list. */
const STAPLES = /^(salt|pepper|black pepper|salt and pepper|salt & pepper|sea salt|water|cold water|boiling water|warm water|oil|olive oil|vegetable oil|sunflower oil|cooking spray|ice)$/i;

/** Pick which ingredients go on a list. Opened from a recipe ("Add to list") and after planning a meal with one. */
export function AddToListSheet({ recipe, servings: startServings, title, onClose }: {
  recipe: Recipe; servings?: number; title?: string; onClose: () => void;
}) {
  const { api, toast } = useApp();
  const [lists] = useData((a) => a.lists(), ["lists"], []);
  const ordered = useMemo(() => [...(lists ?? [])].sort((a, b) => (a.kind === "grocery" ? 0 : 1) - (b.kind === "grocery" ? 0 : 1) || a.sort - b.sort), [lists]);
  const [listId, setListId] = useState<string | null>(null);
  const list = ordered.find((l) => l.id === listId) ?? ordered[0];
  const [loaded] = useData(async (a) => (list ? { lid: list.id, items: await a.items(list.id) } : null), ["lists"], [list?.id]);
  // Only trust items that belong to the list now shown (the previous list's stay around while the next loads).
  const items = loaded && loaded.lid === list?.id ? loaded.items : undefined;
  const [servings, setServings] = useState(startServings ?? defaultServings(recipe));
  const factor = factorFor(recipe, servings);
  const rows = recipe.ingredients.map((ing, i) => ({ ing, i })).filter(({ ing }) => !ing.heading);
  const onList = (name: string) => {
    const n = name.toLowerCase().replace(/s$/, "");
    return n.length >= 3 && (items ?? []).some((it) => !it.done && it.title.toLowerCase().includes(n));
  };
  const [picked, setPicked] = useState<Set<number> | null>(null);
  // Untick staples and anything already waiting on the list, once that list's items have loaded.
  useEffect(() => {
    if (items === undefined) return;
    setPicked(new Set(rows.filter(({ ing }) => !STAPLES.test(ing.name.trim()) && !onList(ing.name)).map(({ i }) => i)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items === undefined, list?.id]);
  const chosen = picked ?? new Set<number>();
  const flip = (i: number) => setPicked((p) => { const n = new Set(p ?? []); if (n.has(i)) n.delete(i); else n.add(i); return n; });
  const [busy, setBusy] = useState(false);
  async function add() {
    if (!list) return;
    setBusy(true);
    try {
      const lines = rows.filter(({ i }) => chosen.has(i)).map(({ ing }) => shoppingLine(ing, factor));
      const n = await api.recipeToList(recipe.id, list.id, lines);
      toast(`Added ${n} ${n === 1 ? "item" : "items"} to ${list.name}`);
      onClose();
    } catch (e) { toast(e instanceof ApiError ? e.message : "Couldn't add them"); setBusy(false); }
  }
  return (
    <Sheet title={title ?? `Add ${recipe.title} to a list`} onClose={onClose} footer={<>
      <button className="btn ghost small" onClick={() => setPicked(new Set(rows.map(({ i }) => i)))}>All</button>
      <button className="btn ghost small" onClick={() => setPicked(new Set())}>None</button>
      <span style={{ flex: 1 }} />
      <button className="btn ghost" onClick={onClose}>{title ? "Skip" : "Cancel"}</button>
      <button className="btn" disabled={!list || chosen.size === 0 || busy} onClick={add}><IconCart size={20} /> Add {chosen.size}</button>
    </>}>
      {!lists ? <div className="screens-empty">Loading…</div> : !ordered.length ? (
        <div className="screens-empty">There are no lists yet. Make a shopping list in Lists first.</div>
      ) : <>
        <div className="atl-top">
          {ordered.length > 1 && ordered.length <= 4
            ? <Segmented value={list!.id} onChange={setListId} options={ordered.map((l) => ({ value: l.id, label: <>{l.emoji} {l.name}</> }))} />
            : ordered.length > 4
              ? <select className="input" value={list!.id} onChange={(e) => setListId(e.target.value)} aria-label="List">{ordered.map((l) => <option key={l.id} value={l.id}>{l.emoji} {l.name}</option>)}</select>
              : <b>{list!.emoji} {list!.name}</b>}
          <ServingsStepper recipe={recipe} servings={servings} onChange={setServings} />
        </div>
        <ul className="atl-items">
          {recipe.ingredients.map((ing, i) => ing.heading ? <li key={i} className="atl-head">{ing.name}</li> : (
            <li key={i}>
              <button type="button" className={"atl-row" + (chosen.has(i) ? " on" : "")} onClick={() => flip(i)} aria-pressed={chosen.has(i)}>
                <span className="atl-box">{chosen.has(i) && <IconCheck size={18} />}</span>
                <span className="atl-text">{ingredientLine(ing, factor, false)}{metricAmount(ing, factor) && <span className="ing-metric">{metricAmount(ing, factor)}</span>}</span>
                {onList(ing.name) ? <span className="atl-tag">On the list</span> : STAPLES.test(ing.name.trim()) ? <span className="atl-tag">Usually in</span> : null}
              </button>
            </li>
          ))}
        </ul>
      </>}
    </Sheet>
  );
}
