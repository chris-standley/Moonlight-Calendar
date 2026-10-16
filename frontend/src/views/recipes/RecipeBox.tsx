import { useMemo, useState } from "react";
import { Recipe } from "../../api/types";
import { fmtMinutes } from "../../recipes/recipeText";
import { Heart, RecipePicture, Stars } from "./bits";

type Sort = "az" | "rated" | "recent";

/** The recipe box: search, quick filters (favourites, quick, tags) and a card per recipe. */
export function RecipeBox({ recipes, onOpen }: { recipes: Recipe[]; onOpen: (r: Recipe) => void }) {
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState<string>("all");
  const [sort, setSort] = useState<Sort>("az");
  const tags = useMemo(() => {
    const n = new Map<string, number>();
    for (const r of recipes) for (const t of r.tags) n.set(t, (n.get(t) ?? 0) + 1);
    return [...n.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).slice(0, 8).map(([t]) => t);
  }, [recipes]);
  const shown = useMemo(() => {
    const words = q.toLowerCase().split(/\s+/).filter(Boolean);
    const hay = (r: Recipe) => [r.title, r.description, ...r.tags, ...r.ingredients.map((i) => i.name)].join(" ").toLowerCase();
    return recipes
      .filter((r) => words.every((w) => hay(r).includes(w)))
      .filter((r) => filter === "all" || (filter === "fav" ? r.favourite : filter === "quick" ? r.minutes != null && r.minutes <= 30 : r.tags.includes(filter)))
      .sort((a, b) => sort === "rated" ? b.rating - a.rating || a.title.localeCompare(b.title)
        : sort === "recent" ? (b.last_cooked ?? "").localeCompare(a.last_cooked ?? "") || a.title.localeCompare(b.title)
          : a.title.localeCompare(b.title));
  }, [recipes, q, filter, sort]);
  const chip = (key: string, label: string) => (
    <button key={key} className={"chip-btn" + (filter === key ? " on" : "")} onClick={() => setFilter(filter === key ? "all" : key)}>{label}</button>
  );
  return (
    <div className="rbox">
      <div className="rbox-filters">
        <input className="input rbox-search" type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search recipes or ingredients" aria-label="Search recipes" />
        <div className="chip-row">
          {chip("fav", "♥ Favourites")}
          {chip("quick", "30 min or less")}
          {tags.map((t) => chip(t, t))}
        </div>
        <select className="input rbox-sort" value={sort} onChange={(e) => setSort(e.target.value as Sort)} aria-label="Sort">
          <option value="az">A to Z</option><option value="rated">Best rated</option><option value="recent">Recently made</option>
        </select>
      </div>
      <div className="recipe-grid">
        {recipes.length === 0 && <div className="screens-empty">No recipes yet. Tap + to add one, or bring one in from a link or a photo.</div>}
        {recipes.length > 0 && shown.length === 0 && <div className="screens-empty">Nothing matches. Try another word or filter.</div>}
        {shown.map((r) => (
          <button key={r.id} className="rcard" onClick={() => onOpen(r)}>
            <RecipePicture recipe={r} className="rcard-pic">{r.favourite && <span className="rcard-fav"><Heart on size={20} /></span>}</RecipePicture>
            <div className="rcard-body">
              <b>{r.title}</b>
              <span className="rcard-meta">
                {r.rating > 0 && <Stars value={r.rating} size={15} />}
                {[r.minutes != null && fmtMinutes(r.minutes), r.servings && `serves ${r.servings}`].filter(Boolean).join(" · ")}
              </span>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}
