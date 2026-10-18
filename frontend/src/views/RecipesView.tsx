import { useState } from "react";
import { ApiError, Recipe, RecipeBatch, RecipeDraft } from "../api/types";
import { useApp, useData } from "../state";
import { Sheet } from "../components/ui";
import { IconPlus, IconTrash } from "../components/icons";
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
  const [adding, setAdding] = useState<"menu" | "link" | "text" | "photo" | "book" | null>(null);
  const [batches] = useData((api) => api.recipeBatches(), ["recipes"], []);
  const [checking, setChecking] = useState<RecipeDraft | null>(null);
  return (
    <div className="meals">
      <div className="toolbar">
        <div className="toolbar-l"><h1 className="toolbar-title">Recipe box</h1></div>
      </div>
      {(batches ?? []).map((b) => <BatchPanel key={b.id} batch={b} onCheck={setChecking} />)}
      <RecipeBox recipes={recipes ?? []} onOpen={(r) => setOpenId(r.id)} />
      <button className="fab" onClick={() => setAdding("menu")} aria-label="Add a recipe"><IconPlus size={30} /></button>
      {adding === "menu" && (
        <Sheet title="Add a recipe" onClose={() => setAdding(null)}>
          <div className="add-menu">
            <button onClick={() => { setAdding(null); setEditing("new"); }}><span>✍️</span><b>Type it in</b><small>Start from a blank recipe</small></button>
            <button onClick={() => setAdding("link")}><span>🔗</span><b>From a link</b><small>A recipe web page</small></button>
            <button onClick={() => setAdding("photo")}><span>📷</span><b>From photos</b><small>A cookbook or recipe card</small></button>
            <button onClick={() => setAdding("text")}><span>📋</span><b>Paste text</b><small>From a message or a note</small></button>
            <button onClick={() => setAdding("book")}><span>📚</span><b>A whole cookbook</b><small>Many pages, read while you carry on</small></button>
          </div>
        </Sheet>
      )}
      {adding && adding !== "menu" && <ImportSheet start={adding} onClose={() => setAdding(null)} onDraft={(d) => { setAdding(null); setEditing(d); }}
        onScanning={() => setAdding(null)} />}
      {checking && <RecipeEditor recipe={checking.recipe} draftId={checking.id} onClose={() => setChecking(null)} />}
      {open && <RecipePage key={open.id} recipe={open} onClose={() => setOpenId(null)} />}
      {editing && <RecipeEditor recipe={editing === "new" ? undefined : editing} onClose={() => setEditing(null)} onSaved={(r) => setOpenId(r.id)} />}
    </div>
  );
}

/** A cookbook being read: how far Claude has got, pages it couldn't read, and the recipes found to check and save. */
const n = (count: number, word: string) => `${count} ${word}${count === 1 ? "" : "s"}`;

function BatchPanel({ batch, onCheck }: { batch: RecipeBatch; onCheck: (d: RecipeDraft) => void }) {
  const { api, toast } = useApp();
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState(false);
  async function act(work: () => Promise<unknown>, done?: string) {
    setBusy(true);
    try { await work(); if (done) toast(done); }
    catch (e) { toast(e instanceof ApiError ? e.message : "Something went wrong"); }
    finally { setBusy(false); }
  }
  const pages = (d: RecipeDraft) => d.pages.length === 1 ? `Page ${d.pages[0]}` : `Pages ${d.pages[0]}–${d.pages[d.pages.length - 1]}`;
  return (
    <section className="panel batch-panel">
      <div className="batch-head">
        <h2 className="panel-title">Cookbook scan</h2>
        <span style={{ flex: 1 }} />
        {batch.drafts.length > 0 && <button className="btn" disabled={busy} onClick={() => act(() => api.saveAllDrafts(batch.id), "Recipes saved")}>Save all {batch.drafts.length}</button>}
        {batch.failed.length > 0 && <button className="btn ghost" disabled={busy} onClick={() => act(() => api.retryBatch(batch.id))}>Try failed pages again</button>}
        <button className="btn ghost danger" disabled={busy} onClick={() => (confirm ? act(() => api.deleteBatch(batch.id)) : setConfirm(true))}>
          {confirm ? (batch.drafts.length ? `Drop ${batch.drafts.length} unchecked?` : "Tap again to clear") : batch.reading ? "Stop" : "Clear"}
        </button>
      </div>
      {batch.reading && <div className="batch-progress">
        <div className="batch-bar"><span style={{ width: `${(100 * batch.read) / Math.max(1, batch.pages)}%` }} /></div>
        <span className="muted">{batch.cheaper && batch.read < batch.pages
          ? `Cheaper scan: with Anthropic, usually back within the hour (at most a day). ${batch.read} of ${batch.pages} pages read.`
          : `Claude has read ${batch.read} of ${batch.pages} pages`}</span>
      </div>}
      {batch.failed.length > 0 && <p className="connect-error">
        Couldn't read page{batch.failed.length === 1 ? "" : "s"} {batch.failed.map((f) => f.page).join(", ")}. {batch.failed[0].error}
      </p>}
      {batch.drafts.length === 0
        ? <p className="muted">{batch.reading ? (batch.cheaper ? "The recipes will appear here when Anthropic sends them back." : "Recipes will appear here as they're read.") : "Nothing left to check."}</p>
        : <>
          <p className="muted">{batch.drafts.length} to check{batch.saved ? ` · ${batch.saved} saved` : ""}</p>
          <ul className="batch-drafts">
            {batch.drafts.map((d) => (
              <li key={d.id}>
                <button className="batch-draft" onClick={() => onCheck(d)}>
                  <b>{d.recipe.title}</b>
                  <small className="muted">{pages(d)} · {n(d.recipe.ingredients.length, "ingredient")} · {n(d.recipe.steps.length, "step")}</small>
                </button>
                <button className="btn ghost" disabled={busy} onClick={() => act(() => api.saveDraft(d.id), "Recipe saved")}>Save</button>
                <button className="icon-btn" disabled={busy} aria-label="Don't keep" onClick={() => act(() => api.dismissDraft(d.id))}><IconTrash size={20} /></button>
              </li>
            ))}
          </ul>
        </>}
    </section>
  );
}
