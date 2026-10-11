import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { Api, Person, Settings, Topic } from "./api/types";

export type Layout = "hallway" | "kitchen" | "phone";

interface Ctx {
  api: Api;
  layout: Layout;
  people: Person[];
  settings: Settings | null;
  personById: (id: string | null | undefined) => Person | undefined;
  /** Shows the PIN pad. It checks the entered PIN unless `check` is false (choosing a new PIN). */
  askPin: (why: string, opts?: { check?: boolean }) => Promise<string | null>;
  toast: (msg: string) => void;
  celebrate: (x: number, y: number, color: string) => void;
  /** Switch to another tab ("settings", "chores", ...). */
  go: (tab: string) => void;
}
const AppCtx = createContext<Ctx>(null as unknown as Ctx);
export const useApp = () => useContext(AppCtx);
export const AppProvider = AppCtx.Provider;

/** Fetch data and refetch whenever one of `topics` changes (from this screen or another, via WebSocket). */
export function useData<T>(fn: (api: Api) => Promise<T>, topics: Topic[], deps: unknown[]): [T | undefined, () => void] {
  const { api } = useApp();
  const [data, setData] = useState<T>();
  const fnRef = useRef(fn);
  fnRef.current = fn;
  const seq = useRef(0);
  const load = useCallback(() => {
    const my = ++seq.current;
    fnRef.current(api).then((d) => { if (my === seq.current) setData(d); }).catch((e) => console.error(e));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, ...deps]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => api.subscribe((t) => { if (topics.includes(t)) load(); }), [api, load, topics.join()]);
  return [data, load];
}

export function useNow(intervalMs = 15000): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), intervalMs);
    return () => clearInterval(t);
  }, [intervalMs]);
  return now;
}

