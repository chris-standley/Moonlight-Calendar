import { addTime, secondsLeft, stopTimer, togglePause, useTimers } from "../../recipes/timers";
import { fmtClock } from "../../recipes/recipeText";
import { IconClose, IconPause, IconPlay } from "../../components/icons";

/** Running kitchen timers. In cook mode they sit under the step; elsewhere a small stack in the corner. */
export function TimerTray({ docked }: { docked?: boolean }) {
  const timers = useTimers();
  if (!timers.length) return null;
  return (
    <div className={"timer-tray" + (docked ? " docked" : "")} aria-live="polite">
      {timers.map((t) => {
        const left = secondsLeft(t);
        return (
          <div key={t.id} className={"ktimer" + (t.ringing ? " ringing" : "") + (t.pausedLeft != null ? " paused" : "")}
            style={{ ["--done" as string]: `${Math.min(100, Math.max(0, 100 - (left / t.total) * 100))}%` }}>
            <div className="kt-main">
              <b>{t.ringing ? "Time's up" : fmtClock(left)}</b>
              <span>{t.label}{!docked && t.recipe ? ` · ${t.recipe}` : ""}</span>
            </div>
            <button className="kt-btn" onClick={() => addTime(t.id, 60)} aria-label="One more minute">+1</button>
            {!t.ringing && <button className="kt-btn" onClick={() => togglePause(t.id)} aria-label={t.pausedLeft != null ? "Carry on" : "Pause"}>
              {t.pausedLeft != null ? <IconPlay size={18} /> : <IconPause size={18} />}</button>}
            <button className="kt-btn" onClick={() => stopTimer(t.id)} aria-label={t.ringing ? "Stop" : "Cancel timer"}><IconClose size={18} /></button>
          </div>
        );
      })}
    </div>
  );
}
