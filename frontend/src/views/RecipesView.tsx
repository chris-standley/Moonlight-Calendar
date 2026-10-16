import { useState } from "react";
import { Recipe } from "../api/types";
import { useData } from "../state";
import { Sheet } from "../components/ui";
import { IconPlus } from "../components/icons";
import { RecipeBox } from "./recipes/RecipeBox";
import { RecipePage } from "./recipes/RecipePage";
import { RecipeEditor } from "./recipes/RecipeEditor";
import { ImportSheet } from "./recipes/ImportSheet";

/** The recipe box: browse, open, add (typed, from a link, photos or pasted text). */
export function RecipesView() {
  const [recipes] = useData((api) => api.recipes(), ["recipes"], []);
  const [openId, setOpenId] = useState<string | null>(null);
  const open = recipes?.find((r) => r.id === openId);
  const [editing, setEditing] = useState<Recipe | "new" | null>(null);
  const [adding, setAdding] = useState<"menu" | "link" | "text" | "photo" | null>(null);
  return (
    <div className="meals">
      <div className="toolbar">
        <div className="toolbar-l"><h1 className="toolbar-title">Recipe box</h1></div>
      </div>
      <RecipeBox recipes={recipes ?? []} onOpen={(r) => setOpenId(r.id)} />
      <button className="fab" onClick={() => setAdding("menu")} aria-label="Add a recipe"><IconPlus size={30} /></button>
      {adding === "menu" && (
        <Sheet title="Add a recipe" onClose={() => setAdding(null)}>
          <div className="add-menu">
            <button onClick={() => { setAdding(null); setEditing("new"); }}><span>✍️</span><b>Type it in</b><small>Start from a blank recipe</small></button>
            <button onClick={() => setAdding("link")}><span>🔗</span><b>From a link</b><small>A recipe web page</small></button>
            <button onClick={() => setAdding("photo")}><span>📷</span><b>From photos</b><small>A cookbook or recipe card</small></button>
            <button onClick={() => setAdding("text")}><span>📋</span><b>Paste text</b><small>From a message or a note</small></button>
          </div>
        </Sheet>
      )}
      {adding && adding !== "menu" && <ImportSheet start={adding} onClose={() => setAdding(null)} onDraft={(d) => { setAdding(null); setEditing(d); }} />}
      {open && <RecipePage key={open.id} recipe={open} onClose={() => setOpenId(null)} />}
      {editing && <RecipeEditor recipe={editing === "new" ? undefined : editing} onClose={() => setEditing(null)} onSaved={(r) => setOpenId(r.id)} />}
    </div>
  );
}
