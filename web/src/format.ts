import React from "react";
import { ExtractionView } from "./components/extraction";
import type { GameState, LegacyEffect, MapNode } from "./types";

export const scoreTone = (value: number, inverse = false) => {
  const danger = inverse ? value >= 65 : value <= 38;
  const warn = inverse ? value >= 45 : value <= 52;
  if (danger) return "danger";
  if (warn) return "warn";
  return "good";
};

export const formatMoney = (value: number) => `${value}万两`;

export const formatSignedMoney = (value: number) => `${value > 0 ? "+" : ""}${formatMoney(value)}`;

export const monthlyAmount = (value: number) => Math.max(0, Math.round(value / 3));

export const issueTone = (value: number) => {
  if (value <= 28) return "danger";
  if (value <= 58) return "warn";
  return "good";
};

export const signedNumber = (value: number) => `${value > 0 ? "+" : ""}${value}`;

export const numericEffectValue = (value: any): number | null => {
  if (typeof value === "number") return value;
  if (typeof value === "string" && /^-?\d+$/.test(value.trim())) return Number(value);
  return null;
};

export const appendScopedEffect = (
  parts: string[],
  block: any,
  labelEntity: (id: any) => string,
) => {
  if (!block || typeof block !== "object" || Array.isArray(block)) return;
  for (const [entity, fields] of Object.entries(block)) {
    if (!fields || typeof fields !== "object" || Array.isArray(fields)) continue;
    for (const [field, raw] of Object.entries(fields)) {
      const n = numericEffectValue(raw);
      if (!n) continue;
      parts.push(`${labelEntity(entity)}·${cnField(field)}${signedNumber(n)}`);
    }
  }
};

export const formatEffectSummary = (effect: any) => {
  if (!effect || typeof effect !== "object") return "无直接数值影响";
  const parts: string[] = [];

  const metrics = effect.metrics || {};
  for (const [k, v] of Object.entries(metrics)) {
    const n = Number(v);
    if (!n) continue;
    parts.push(`${k}${signedNumber(n)}`);
  }

  const econ = Array.isArray(effect.economy) ? effect.economy : [];
  for (const e of econ) {
    const n = Number(e?.delta);
    if (!n) continue;
    parts.push(`${e.account || "钱粮"}${signedNumber(n)}万`);
  }

  const factions = effect.factions || {};
  for (const [k, v] of Object.entries(factions)) {
    if (v && typeof v === "object") {
      const sub: string[] = [];
      for (const [kk, vv] of Object.entries(v as any)) {
        const n = Number(vv);
        if (!n) continue;
        sub.push(`${SAT_LEV_CN[kk] || cnField(kk)}${signedNumber(n)}`);
      }
      if (sub.length) parts.push(`${k}（${sub.join("、")}）`);
    } else {
      const n = Number(v);
      if (n) parts.push(`${k}${signedNumber(n)}`);
    }
  }

  appendScopedEffect(parts, effect.classes, labelClass);
  appendScopedEffect(parts, effect.regions, labelRegion);
  appendScopedEffect(parts, effect.armies, labelArmy);
  appendScopedEffect(parts, effect.powers, labelPower);

  if (effect.legacy && typeof effect.legacy === "object") {
    const legacyName = String(effect.legacy.name || "帝国修正");
    const duration = effect.legacy.duration ? `，${effect.legacy.duration}` : "";
    const modifiers = formatLegacyEffect(effect.legacy.modifiers || {});
    parts.push(`帝国修正：${legacyName}${duration}${modifiers ? `（${modifiers}）` : ""}`);
  }

  for (const [key, value] of Object.entries(effect)) {
    if (["metrics", "economy", "factions", "classes", "regions", "armies", "powers", "legacy", "buildings"].includes(key)) continue;
    const n = numericEffectValue(value);
    if (n) parts.push(`${cnField(key)}${signedNumber(n)}`);
  }

  return parts.length ? parts.join("、") : "无直接数值影响";
};

export const formatIssueEffect = formatEffectSummary;

export const formatClosedEffect = formatEffectSummary;

export const splitReportItems = (text: string, prefix: string) => {
  const cleaned = text.replace(prefix, "").trim();
  const totalMatch = cleaned.match(/(两京十三省账面[月]税合计[^。]+|建档兵力合计[^。]+)。?$/);
  const itemsPart = totalMatch ? cleaned.slice(0, totalMatch.index).replace(/。$/, "") : cleaned.replace(/。$/, "");
  return {
    items: itemsPart.split("；").map((item) => item.replace(/^。+|。+$/g, "").trim()).filter(Boolean),
    tail: totalMatch?.[1] || "",
  };
};


// 邸报详明里 extractor 常输出英文 id（region_id/army_id/power_id）或编号。
// 这里建一份 id→中文名 的全局映射，每次拉 state 时刷新，供 ExtractionView 各 block 翻译。
export const labelMaps = {
  region: new Map<string, string>(),
  army: new Map<string, string>(),
  power: new Map<string, string>(),
  issue: new Map<number, string>(),
};

export const POWER_ID_CN: Record<string, string> = {
  ming: "大明",
  houjin: "后金",
  mongol: "蒙古",
  korea: "朝鲜",
  bandits: "流寇",
  dutch: "荷兰东印度公司",
  japan: "日本",
};

export function refreshLabelMaps(state: GameState) {
  labelMaps.region.clear();
  labelMaps.army.clear();
  labelMaps.power.clear();
  labelMaps.issue.clear();
  for (const r of state.regions || []) labelMaps.region.set(r.id, r.name);
  for (const a of state.armies || []) labelMaps.army.set(a.id, a.name);
  for (const p of state.powers || []) labelMaps.power.set(p.id, p.name);
  for (const it of state.issues || []) labelMaps.issue.set(it.id, it.title);
  for (const it of state.closed_this_turn || []) labelMaps.issue.set(it.id, it.title);
}


// 把 id 翻成中文名；查不到（如本月新增/已离场）就回退原值，至少不空。
export const labelRegion = (id: any) => labelMaps.region.get(String(id)) || String(id ?? "");

export const labelArmy = (id: any) => labelMaps.army.get(String(id)) || String(id ?? "");

export const labelPower = (id: any) => labelMaps.power.get(String(id)) || POWER_ID_CN[String(id)] || String(id ?? "");

export const labelIssue = (id: any) => {
  const t = labelMaps.issue.get(Number(id));
  return t ? `#${id} ${t}` : `#${id}`;
};


// extractor 偶尔吐出的英文枚举值，统一翻中文。
export const EN_VALUE_CN: Record<string, string> = {
  ...POWER_ID_CN,
  appoint: "新进朝堂", promote: "升迁", transfer: "调任", demote: "贬", reinstate: "起复",
  resolved: "已了", failed: "崩坏", dropped: "撤销",
  situation: "时局", initiative: "举措", crisis: "危机", reform: "改革", decree: "诏令",
  done: "办结", pending: "在办", pending_review: "待核议", active: "进行中",
  draft: "草案", rejected: "已驳回", cancelled: "已取消",
};

export const cnValue = (v: any) => (v == null ? "" : (EN_VALUE_CN[String(v)] || String(v)));


// extractor 吐的是英文字段名（region/army/class/power 的列名），这里统一翻中文。
// 查不到的回退原值，至少不空。
export const EN_FIELD_CN: Record<string, string> = {
  // 地区
  public_support: "民心", unrest: "动乱", grain_security: "粮食安全",
  gentry_resistance: "士绅阻力", military_pressure: "边防压力", corruption: "腐败度",
  population: "人口", registered_land: "在册田亩", hidden_land: "隐田",
  tax_per_turn: "月税", natural_disaster: "天灾", human_disaster: "人祸",
  status: "状态", controlled_by: "控制者", 控制: "控制者", kind: "类型",
  // 军队
  supply: "补给", morale: "士气", training: "操练", equipment: "军械",
  arrears: "欠饷", mobility: "机动", loyalty: "忠诚", manpower: "兵力",
  maintenance_quarter: "月饷", maintenance_per_turn: "月饷",
  station: "驻地", commander: "统帅", controller: "主管", troop_type: "兵种", owner_power: "归属",
  // 势力
  cohesion: "凝聚", 威望: "威望", leverage: "威望", 实力: "实力",
  military_strength: "实力", 经济: "经济",
  // 阶级
  satisfaction: "满意度",
};

export const cnField = (k: string) => EN_FIELD_CN[k] || k;

export const fiscalKeyLabel = (key: any): string => {
  const raw = String(key ?? "");
  const match = raw.match(/^(.+)_(base|rate)$/);
  if (!match) return cnField(raw);
  return `${match[1]}${match[2] === "base" ? "基数" : "系数"}`;
};

export const briefTreasury = (state: GameState) => [
  `固定预算：国库月净${formatSignedMoney(state.budget["国库"].net)}，内库月净${formatSignedMoney(state.budget["内库"].net)}。`,
  `账面余银：国库${formatMoney(state.budget["国库"].balance)}，内库${formatMoney(state.budget["内库"].balance)}。`,
];

export const briefRegionWarnings = (text: string) => {
  const { items, tail } = splitReportItems(text, "地区警讯：");
  return [...items.slice(0, 3), tail].filter(Boolean);
};

export const briefArmyWarnings = (text: string) => {
  const { items, tail } = splitReportItems(text, "军队警讯：");
  return [...items.slice(0, 3), tail].filter(Boolean);
};

export const getMapIntelStyle = (node: MapNode): React.CSSProperties => {
  const left = Math.min(82, Math.max(18, node.x));
  const horizontal = node.x > 66 ? "-100%" : node.x < 34 ? "0" : "-50%";
  const style: React.CSSProperties = {
    left: `${left}%`,
    transform: `translateX(${horizontal})`,
    maxHeight: "calc(100vh - 24px)",
  };
  if (node.y > 50) {
    style.bottom = "12px";
    style.top = "auto";
  } else {
    style.top = "12px";
    style.bottom = "auto";
  }
  return style;
};

export const LEGACY_FIELD_LABELS: Record<string, string> = {
  public_support: "民心", unrest: "动乱", gentry_resistance: "士绅阻力", military_pressure: "边防压力",
  tax_per_turn: "月税", grain_security: "粮食", corruption: "腐败度",
  morale: "士气", training: "训练", loyalty: "忠诚", supply: "补给", equipment: "装备",
  arrears: "欠饷", mobility: "机动",
};

export function pctStr(v: number): string {
  return `${v > 0 ? "+" : ""}${v}%`;
}


// modifiers = {国库?:pct, 内库?:pct, regions?:{rid:{field:pct}}, armies?:{aid:{field:pct}}}
export function formatLegacyEffect(eff: LegacyEffect): string {
  const parts: string[] = [];
  for (const acc of ["国库", "内库", "民心", "皇威"] as const) {
    const v = eff[acc];
    if (typeof v === "number") parts.push(`${acc}${pctStr(v)}`);
  }
  for (const scope of ["regions", "armies"] as const) {
    const block = eff[scope];
    if (!block || typeof block !== "object") continue;
    for (const [entity, fields] of Object.entries(block)) {
      for (const [field, pct] of Object.entries(fields)) {
        const entityLabel = scope === "regions" ? labelRegion(entity) : labelArmy(entity);
        const label = LEGACY_FIELD_LABELS[field] || cnField(field);
        parts.push(`${entityLabel}·${label}${pctStr(pct as number)}`);
      }
    }
  }
  return parts.join("、");
}

// 阶级变化：key=阶级名 或 阶级@region_id；region 后缀翻中文名。value={满意,影响力} 增量。
export const SAT_LEV_CN: Record<string, string> = { satisfaction: "满意", leverage: "影响力", 满意: "满意", 影响力: "影响力" };

export function labelClass(key: string): string {
  const at = key.indexOf("@");
  if (at < 0) return key;
  return `${key.slice(0, at)}（${labelRegion(key.slice(at + 1))}）`;
}
