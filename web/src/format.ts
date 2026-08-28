import React from "react";
import MarkdownIt from "markdown-it";
import type Token from "markdown-it/lib/token.mjs";
import type StateInline from "markdown-it/lib/rules_inline/state_inline.mjs";
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

// #321 P7：formatArmyArrears / arrearsToneFromText 已随 drawer/map 直显拆除删除。
// morale/loyalty 二次词表已删；仅保留仍吃 numeric 的轴（training/equipment/supply/mobility）。
const ARMY_QUALITATIVE_WORDS: Record<string, [string, string, string, string, string]> = {
  supply: ["断绝", "匮乏", "吃紧", "尚可", "充足"],
  training: ["散漫", "生疏", "粗疏", "尚可", "精熟"],
  equipment: ["残破", "简陋", "短缺", "尚可", "精良"],
  mobility: ["迟滞", "缓慢", "受限", "尚可", "灵便"],
};

export const qualitativeArmyStat = (field: string, value: number) => {
  const words = ARMY_QUALITATIVE_WORDS[field] || ["极低", "偏低", "中等", "尚可", "优良"];
  const n = Number(value || 0);
  if (n >= 80) return words[4];
  if (n >= 60) return words[3];
  if (n >= 40) return words[2];
  if (n >= 20) return words[1];
  return words[0];
};

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


// 玩家面板会收到英文 id（region_id/army_id/power_id）或编号；统一映射为中文名。
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


// extractor 偶尔吐出的英文枚举值，统一翻中文。
export const EN_VALUE_CN: Record<string, string> = {
  ...POWER_ID_CN,
  appoint: "新进朝堂", promote: "升迁", transfer: "调任", demote: "贬", reinstate: "起复",
  resolved: "已了", failed: "崩坏", dropped: "撤销",
  situation: "时局", initiative: "举措", crisis: "危机", reform: "改革", decree: "诏令",
  done: "办结", pending: "在办", active: "进行中",
  draft: "草案", rejected: "已驳回", cancelled: "已取消",
};

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
  army_needed: "月饷", // #173：军「月饷」呈现取引擎实扣 army_needed（维护费列已删）
  station: "驻地", commander: "统帅", controller: "主管", troop_type: "兵种", owner_power: "归属",
  // 势力
  cohesion: "凝聚", 威望: "威望", leverage: "威望", 实力: "实力",
  military_strength: "实力", 经济: "经济",
  // 阶级
  satisfaction: "满意度",
};

export const cnField = (k: string) => EN_FIELD_CN[k] || k;

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
const markdown = new MarkdownIt({ html: false, linkify: false, typographer: false });

type InlineRule = (state: StateInline, silent: boolean) => boolean;

const markdownBacktickRule = (markdown.inline.ruler as unknown as {
  __rules__: Array<{ name: string; fn: InlineRule }>;
}).__rules__.find((rule) => rule.name === "backticks")?.fn;

if (!markdownBacktickRule) throw new Error("markdown-it backticks rule is unavailable");

markdown.inline.ruler.at("backticks", (state, silent) => {
  const start = state.pos;
  const tokenCount = state.tokens.length;
  const parsed = markdownBacktickRule(state, silent);
  if (!parsed || silent) return parsed;

  const token = state.tokens.slice(tokenCount).find((candidate) => candidate.type === "code_inline");
  if (token) {
    const contentStart = start + token.markup.length;
    const contentEnd = state.pos - token.markup.length;
    token.meta = { ...token.meta, literalContent: state.src.slice(contentStart, contentEnd) };
  }
  return parsed;
});

const inlineText = (tokens: Token[]): string => {
  const render = (token: Token): string => {
    switch (token.type) {
      case "text":
      case "html_inline":
        return token.content;
      case "code_inline":
        return token.meta?.literalContent ?? token.content;
      case "image":
        return (token.children || []).map(render).join("");
      case "softbreak":
      case "hardbreak":
        return "\n";
      default:
        return "";
    }
  };
  return tokens.map(render).join("");
};

const appendBlockSeparator = (result: string, previousEndLine: number | undefined, startLine: number | undefined): string => {
  if (previousEndLine === undefined || startLine === undefined) return result;
  return result + "\n".repeat(Math.max(1, startLine - previousEndLine + 1));
};

/** 切出领头舞台指示（全角括号段）；其余为正文 content。显示链真源侧。 */
export function parseLeadingStageDirection(source: string): { action: string | null; content: string } {
  const match = source.match(/^（[^（）\r\n]+）/);
  return match
    ? { action: match[0], content: source.slice(match[0].length) }
    : { action: null, content: source };
}

// Streaming may briefly display unfinished markdown; that transient state is acceptable as
// long as the completed message is clean (ADR 0045's display-text contract).
export const stripOrganicMarkdown = (text: string): string => {
  const tokens = markdown.parse(text, {});
  let result = "";
  let previousEndLine: number | undefined;
  let tableEndLine: number | undefined;

  for (const token of tokens) {
    const [startLine, endLine] = token.map || [];
    switch (token.type) {
      case "inline":
        result = appendBlockSeparator(result, previousEndLine, startLine);
        result += inlineText(token.children || []);
        if (endLine !== undefined) previousEndLine = endLine;
        break;
      case "fence":
      case "code_block":
      case "html_block":
        result = appendBlockSeparator(result, previousEndLine, startLine) + token.content;
        if (endLine !== undefined) previousEndLine = endLine;
        break;
      case "hr":
        if (endLine !== undefined) previousEndLine = endLine;
        break;
      case "table_open":
        result = appendBlockSeparator(result, previousEndLine, startLine);
        tableEndLine = endLine;
        break;
      case "td_close":
      case "th_close":
        result += "\t";
        break;
      case "tr_close":
        result = result.replace(/\t$/, "") + "\n";
        break;
      case "table_close":
        result = result.replace(/\n$/, "");
        previousEndLine = tableEndLine;
        tableEndLine = undefined;
        break;
      default:
        break;
    }
  }

  return result;
};
