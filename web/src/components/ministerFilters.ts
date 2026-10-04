import type { Minister } from "../types";

/** Formal office_type enum order — single source for court/ministry lists. */
export const COURT_OFFICE_TYPE_ORDER = [
  "内阁",
  "吏部",
  "户部",
  "礼部",
  "兵部",
  "刑部",
  "工部",
] as const;

const MINISTRY_OFFICE_TYPES = new Set<string>(
  COURT_OFFICE_TYPE_ORDER.filter((officeType) => officeType !== "内阁"),
);

function officeTypeRank(officeType: string): number {
  const index = (COURT_OFFICE_TYPE_ORDER as readonly string[]).indexOf(officeType);
  return index >= 0 ? index : COURT_OFFICE_TYPE_ORDER.length;
}

export function filterMinisters(ministers: Minister[], group: string) {
  const courtMinisters = ministers.filter((m) => (m.power_id || "ming") === "ming");
  if (group === "内阁+六部" || group === "内阁" || group === "六部") {
    return courtMinisters
      .filter((m) =>
        (m.office_type === "内阁" || MINISTRY_OFFICE_TYPES.has(m.office_type || ""))
        && m.status === "active"
        && !!(m.office || "").trim()
      )
      .sort(
        (a, b) =>
          officeTypeRank(a.office_type || "") - officeTypeRank(b.office_type || ""),
      );
  }
  if (group === "在职") return courtMinisters.filter((m) => m.status === "active");
  if (group === "收藏") return courtMinisters.filter((minister) => minister.favorite);
  return courtMinisters;
}

export function filterConsorts(consorts: Minister[], group: string) {
  const mingConsorts = consorts.filter((c) => (c.power_id || "ming") === "ming");
  if (group === "收藏") return mingConsorts.filter((c) => c.favorite);
  return mingConsorts;
}
