// Demo-mode notifications and timers: kept in memory on this device, with the add-on's rules (see alerts.py).
import { AlertIn, Api, ApiError, ScreenAlert, Topic } from "./types";

type Extras = Pick<Api, "alerts" | "createAlert" | "dismissAlert">;

export function demoAlerts(emit: (...t: Topic[]) => void): Extras {
  let shown: ScreenAlert[] = [];
  let n = 0;
  const prune = () => {
    const now = Date.now();
    shown = shown.filter((a) => a.expires_at === null || a.expires_at > now);
  };
  return {
    async alerts() { prune(); return { server_time: Date.now(), alerts: shown.map((a) => ({ ...a })) }; },
    async createAlert(b: AlertIn) {
      const now = Date.now();
      const kind = b.kind ?? "notification";
      const style = b.style ?? (kind === "notification" ? "fullscreen" : "toast");
      const a: ScreenAlert = {
        id: b.id || `al_demo${++n}`, kind, style, screens: b.screens?.length ? b.screens : ["all"], icon: b.icon ?? "",
        dismissible: b.dismissible ?? true, chime: b.chime ?? kind === "timer", created_at: now, expires_at: null,
      };
      if (kind === "notification") {
        if (!b.title && !b.message) throw new ApiError(400, "A notification needs a title or a message");
        const secs = b.duration ?? (style === "toast" ? 10 : 0);
        Object.assign(a, { title: b.title ?? "", message: b.message ?? "", image: b.image || null, expires_at: secs ? now + secs * 1000 : null });
      } else if (b.since) {
        if (!b.label) throw new ApiError(400, "label is required");
        if (b.until) throw new ApiError(400, "A timer counts down to until or up from since, not both");
        const from = b.since === "now" ? now : Math.min(now, new Date(b.since).getTime());
        if (!Number.isFinite(from)) throw new ApiError(400, "since must be an ISO date and time, like 2026-12-25T07:00");
        Object.assign(a, { label: b.label, description: b.description ?? "", count_up: true, started_at: from, ends_at: null,
          finished: false, finished_for: null, chime: b.chime ?? false, expires_at: b.duration ? from + b.duration * 1000 : null });
      } else {
        if (!b.label) throw new ApiError(400, "label is required");
        const ends = b.until ? new Date(b.until).getTime() : now + (b.duration ?? 0) * 1000;
        if (!(ends > now)) throw new ApiError(400, "A timer needs either duration (seconds) or until (a date and time)");
        const after = b.finished_for || null;
        Object.assign(a, { label: b.label, description: b.description ?? "", count_up: false, started_at: now, ends_at: ends, finished: false,
          finished_for: after, expires_at: after ? ends + after * 1000 : null });
      }
      shown = [...shown.filter((x) => x.id !== a.id), a];
      emit("alerts");
      return { ...a };
    },
    async dismissAlert(id) {
      const a = shown.find((x) => x.id === id);
      if (!a) throw new ApiError(404, "Already gone");
      if (!a.dismissible) throw new ApiError(409, "This one can only be cleared from Home Assistant");
      shown = shown.filter((x) => x.id !== id);
      emit("alerts");
    },
  };
}
