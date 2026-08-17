import type { SecretOrder } from "./types";

export const shouldAutoOpenSecretOrdersAfterSettlement = (
  orders: SecretOrder[], currentTurn: number,
) => orders.some((order) =>
  (order.dossier_progress || []).some((report) => report.turn === currentTurn - 1),
);

export const shouldAutoOpenClosedIssuesAfterSettlement = () => false;

/** #1234：年月核账态标 —— 全由服务端 settlement_display 下发驱动，客户端不自判。 */
export function yearMonthLabel(turn: {
  year: number;
  period: number;
  settlement_display?: boolean;
}): string {
  const base = `${turn.year} 年 ${turn.period} 月`;
  return turn.settlement_display ? `${base} · 核账` : base;
}

/**
 * #1236 T3：核账逐面门控 key（审计 §0）。
 * 组归属机械清单见 FACE_GROUP；唯一谓词 = turn.settlement_display。
 */
export type SettlementFaceKey =
  | "situation"            // 局势
  | "region"               // 省
  | "army"                 // 兵
  | "node_intel"           // 地图节点详情 / 点选开详
  | "secret_orders"        // 密令（含角标+自动弹出）
  | "edict"                // 拟诏·退朝
  | "chat_entry"           // 召对写入口（朝堂/吏部/后宫/任免行）
  | "court_roster"         // 朝堂名册
  | "appointment_roster"   // 吏部名册
  | "harem_roster"         // 后宫名册
  | "building"             // 工部建筑
  | "economy"              // 户部抽屉
  | "memorials"            // 奏疏
  | "gazette"              // 邸报(上月)
  | "audience_archive"     // 起居注
  | "history"              // 史册
  | "closed_issues"        // 上月已结
  | "legacies"             // 顶栏帝国修正
  | "menu"                 // 菜单（存档允许；读档/重置=离局）
  | "decision_modal"       // DecisionModal
  | "decision_recovery"    // DecisionRecoveryPanel
  | "settle_resume"        // settling 续跑入口
  | "wang_slip"            // 王承恩核账递话条
  | "cheat_console"        // 排除
  | "ending";              // 排除（终局既有行为）

/** 核账期面门结果。 */
export type FaceAccess =
  | "open"       // 非核账：正常可达
  | "closed"     // 核账：不可达
  | "readonly"   // 核账：可读、无写入口
  | "must"       // 核账：必达（门控不得误关）
  | "present"    // 核账：呈现（递话条）
  | "excluded";  // 本票不设核账门

/** 组归属机械清单（票面 r2；不缩表）。 */
export const FACE_GROUP: Record<SettlementFaceKey, Exclude<FaceAccess, "open">> = {
  situation: "closed",
  region: "closed",
  army: "closed",
  node_intel: "closed",
  secret_orders: "closed",
  edict: "closed",
  chat_entry: "closed",
  court_roster: "readonly",
  appointment_roster: "readonly",
  harem_roster: "readonly",
  building: "readonly",
  economy: "readonly",
  memorials: "readonly",
  gazette: "readonly",
  audience_archive: "readonly",
  history: "readonly",
  closed_issues: "readonly",
  legacies: "readonly",
  menu: "readonly",
  decision_modal: "must",
  decision_recovery: "must",
  settle_resume: "must",
  wang_slip: "present",
  cheat_console: "excluded",
  ending: "excluded",
};

/** 唯一谓词：状态口 settlement_display（T1；客户端不自判 phase/busy）。 */
export function isSettlementDisplay(turn: { settlement_display?: boolean } | null | undefined): boolean {
  return Boolean(turn?.settlement_display);
}

/**
 * 逐面门控：仅吃 settlement_display。
 * - 非核账：closed/readonly/must/present → open（正常盘面）；excluded 仍 excluded
 * - 核账：返回组归属本身
 */
export function settlementFaceAccess(
  key: SettlementFaceKey,
  settlementDisplay: boolean,
): FaceAccess {
  const group = FACE_GROUP[key];
  if (group === "excluded") return "excluded";
  if (!settlementDisplay) return "open";
  return group;
}

/** 可达 = 非 closed（must/readonly/open/present/excluded 均视为门控不挡）。 */
export function isFaceReachable(key: SettlementFaceKey, settlementDisplay: boolean): boolean {
  return settlementFaceAccess(key, settlementDisplay) !== "closed";
}

/** 关闭组入口的戏内理由（王承恩口吻一句）。 */
export const SETTLEMENT_CLOSED_REASON = "档房正在核账，此簿暂不呈御前。";

/**
 * 王承恩核账递话条正文（P4：一句正向奏疏口吻；无进度条/百分比/秒数）。
 * 显隐唯一谓词 = settlement_display。
 */
export const WANG_SETTLEMENT_SLIP = "奴婢正在督办各部核账，事情在办，请皇爷稍候。";

export function wangSettlementSlipVisible(settlementDisplay: boolean): boolean {
  return settlementFaceAccess("wang_slip", settlementDisplay) === "present";
}
