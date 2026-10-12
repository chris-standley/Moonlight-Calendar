import { useEffect, useState } from "react";
import { HolidayCountry, HolidayRegion } from "../api/types";
import { useApp } from "../state";

let cached: Promise<HolidayCountry[]> | null = null;

/** Countries and regions with public holidays, fetched once per page. */
export function useHolidayCountries(): HolidayCountry[] {
  const { api } = useApp();
  const [list, setList] = useState<HolidayCountry[]>([]);
  useEffect(() => {
    cached ??= api.holidayCountries().catch(() => { cached = null; return []; });
    let live = true;
    cached.then((l) => { if (live) setList(l); });
    return () => { live = false; };
  }, [api]);
  return list;
}

/** "England" / "France" for the household's holiday region, "" when none is chosen. */
export function regionName(r: HolidayRegion | undefined, countries: HolidayCountry[]): string {
  if (!r?.country) return "";
  const c = countries.find((x) => x.code === r.country);
  const sub = c?.subdivs.find((s) => s.code === r.subdiv);
  return sub?.name ?? c?.name ?? r.country;
}

export function useHolidayRegionName(): string {
  const { settings } = useApp();
  return regionName(settings?.holidays, useHolidayCountries());
}
