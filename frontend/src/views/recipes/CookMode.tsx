import { useEffect, useRef, useState } from "react";
import { Recipe } from "../../api/types";
import { useApp } from "../../state";
import { IconCheck, IconClose, IconLeft, IconRight } from "../../components/icons";
import { startTimer, useTimers } from "../../recipes/timers";
import { IngredientRow, IngredientText } from "./bits";
import { TimerTray } from "./TimerTray";

/** Step by step: the current step large in the middle, its timers one tap away, ingredients to tick off at the side.
 *  The screen stays on while it's open. */
export function CookMode({ recipe, factor, onClose }: { recipe: Recipe; factor: number; onClose: () => void }) {
  const { api, toast, layout } = useApp();
  const [i, setI] = useState(0);
  const [showIngs, setShowIngs] = useState(layout === "large");
  const [ticked, setTicked] = useState<Set<number>>(new Set());
  const timers = useTimers();
  const steps = recipe.steps;
  const last = steps.length; // one past the steps: the "done" page
  const step = steps[i];

  // Keep the screen awake while cooking (where the browser supports it).
  useEffect(() => {
    let lock: { release(): Promise<void> } | null = null;
    const nav = navigator as Navigator & { wakeLock?: { request(t: "screen"): Promise<{ release(): Promise<void> }> } };
    const get = () => nav.wakeLock?.request("screen").then((l) => { lock = l; }).catch(() => { /* not allowed */ });
    void get();
    const again = () => { if (document.visibilityState === "visible") void get(); };
    document.addEventListener("visibilitychange", again);
    return () => { document.removeEventListener("visibilitychange", again); void lock?.release().catch(() => {}); };
  }, []);

  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      if (e.key === "ArrowRight" || e.key === " ") setI((n) => Math.min(last, n + 1));
      if (e.key === "ArrowLeft") setI((n) => Math.max(0, n - 1));
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [last, onClose]);

  // Swipe left / right to move between steps.
  const touch = useRef<number | null>(null);
  const onTouchStart = (e: React.TouchEvent) => { touch.current = e.touches[0].clientX; };
  const onTouchEnd = (e: React.TouchEvent) => {
    if (touch.current == null) return;
    const dx = e.changedTouches[0].clientX - touch.current;
    touch.current = null;
    if (Math.abs(dx) > 60) setI((n) => Math.max(0, Math.min(last, n + (dx < 0 ? 1 : -1))));
  };

  async function made() {
    try { await api.recipeCooked(recipe.id); toast("Marked as made. Enjoy!"); } catch { /* still close */ }
    onClose();
  }
  const running = (seconds: number) => timers.some((t) => t.total === seconds && t.recipe === recipe.title && !t.ringing);

  return (
    <div className="cook" role="dialog" aria-label={`Cooking ${recipe.title}`}>
      <header className="cook-top">
        <button className="icon-btn" onClick={onClose} aria-label="Close cook mode"><IconClose /></button>
        <div className="cook-title"><b>{recipe.title}</b><span>{i < last ? `Step ${i + 1} of ${steps.length}` : "All done"}</span></div>
        <button className={"btn ghost small" + (showIngs ? " on" : "")} onClick={() => setShowIngs(!showIngs)}>Ingredients</button>
      </header>
      <div className="cook-progress"><span style={{ width: `${(Math.min(i + 1, last) / Math.max(1, last)) * 100}%` }} /></div>
      <div className={"cook-body" + (showIngs ? " with-ings" : "")}>
        {showIngs && (
          <aside className="cook-ings">
            <h3>Ingredients</h3>
            <ul>
              {recipe.ingredients.map((ing, n) => ing.heading ? <IngredientRow key={n} ing={ing} factor={factor} /> : (
                <li key={n}>
                  <button type="button" className={"cook-ing" + (ticked.has(n) ? " done" : "")} aria-pressed={ticked.has(n)}
                    onClick={() => setTicked((t) => { const s = new Set(t); if (s.has(n)) s.delete(n); else s.add(n); return s; })}>
                    <span className="atl-box">{ticked.has(n) && <IconCheck size={16} />}</span>
                    <span className="ing"><IngredientText ing={ing} factor={factor} /></span>
                  </button>
                </li>
              ))}
            </ul>
          </aside>
        )}
        <main className="cook-stage" onTouchStart={onTouchStart} onTouchEnd={onTouchEnd}>
          {i < last ? <>
            <div className="cook-num">{i + 1}</div>
            {step.photo_url && <img className="cook-photo" src={step.photo_url} alt="" draggable={false} />}
            <p className="cook-text">{step.metric_text ?? step.text}</p>
            {step.timers.length > 0 && (
              <div className="cook-timers">
                {step.timers.map((t) => (
                  <button key={t.seconds} className="btn timer-btn" disabled={running(t.seconds)}
                    onClick={() => { startTimer(`Step ${i + 1}: ${t.label}`, t.seconds, recipe.title); toast(`Timer set for ${t.label}`); }}>
                    ⏱ {running(t.seconds) ? "Running" : `Start ${t.label} timer`}
                  </button>
                ))}
              </div>
            )}
          </> : (
            <div className="cook-done">
              <div className="cook-done-emoji">{recipe.emoji || "🎉"}</div>
              <h2>That's everything</h2>
              <p className="muted">{recipe.cooked_count ? `Made ${recipe.cooked_count} ${recipe.cooked_count === 1 ? "time" : "times"} before.` : "First time making this one."}</p>
              <button className="btn" onClick={made}><IconCheck size={20} /> Mark as made</button>
            </div>
          )}
          <TimerTray docked />
        </main>
      </div>
      <footer className="cook-nav">
        <button className="btn ghost big" onClick={() => setI(Math.max(0, i - 1))} disabled={i === 0}><IconLeft /> Back</button>
        <div className="cook-dots">{steps.map((_, n) => <button key={n} className={n === i ? "on" : n < i ? "past" : ""} onClick={() => setI(n)} aria-label={`Step ${n + 1}`} />)}</div>
        {i < last ? <button className="btn big" onClick={() => setI(i + 1)}>{i === last - 1 ? "Finish" : "Next"} <IconRight /></button>
          : <button className="btn ghost big" onClick={onClose}>Close</button>}
      </footer>
    </div>
  );
}
