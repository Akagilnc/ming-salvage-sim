import React from "react";
import { createRoot } from "react-dom/client";
import {
  Check,
  Crown,
  Edit3,
  Landmark,
  Loader2,
  Lock,
  LogOut,
  ChevronLeft,
  ChevronRight,
  MapPinned,
  Menu,
  MessageSquare,
  Power,
  RotateCcw,
  Save,
  Send,
  Settings,
  ScrollText,
  Shield,
  Star,
  Target,
  Trash2,
  Swords,
  Upload,
  X,
  Pencil,
  Eraser,
  Move,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import { EXTERNAL_PATH_GROUPS, MAP_VIEW_BOX, REGION_PATH_GROUPS } from "./mapPaths";
import "./styles.css";

type Metrics = Record<string, number>;

type Region = {
  id: string;
  name: string;
  kind: string;
  population: number;
  public_support: number;
  unrest: number;
  natural_disaster: string;
  human_disaster: string;
  registered_land: number;
  hidden_land: number;
  tax_per_turn: number;
  grain_security: number;
  gentry_resistance: number;
  military_pressure: number;
  status: string;
  controlled_by?: string;
};

type Army = {
  id: string;
  name: string;
  station: string;
  theater: string;
  commander: string;
  controller: string;
  troop_type: string;
  manpower: number;
  maintenance_per_turn: number;
  supply: number;
  morale: number;
  training: number;
  equipment: number;
  arrears: number;
  mobility: number;
  loyalty: number;
  status: string;
  owner_power?: string;
};

type Power = {
  id: string;
  name: string;
  kind: string;
  leader: string;
  stance: string;
  leverage: number;
  satisfaction: number;
  military_strength: number;
  cohesion: number;
  supply: number;
  agenda: string;
  status: string;
  last_action: string;
};

type Building = {
  id: string;
  region_id: string;
  name: string;
  category: string;
  level: number;
  condition: number;
  maintenance: number;
  risk: number;
  output_metric: string;
  output_amount: number;
  status: string;
  origin: string;
};

type MapNode = {
  id: string;
  kind: "region" | "theater" | "external";
  x: number;
  y: number;
  label?: string;
  risk: number;
  region?: Region;
  armies: Army[];
  buildings?: Building[];
  power?: Power;
};

type RegionPathRenderItem = {
  id: string;
  name: string;
  controlledBy: string;
  unrest: number;
  risk: number;
  labelX: number;
  labelY: number;
  paths: Array<{ id: string; d: string }>;
};

type ExternalPathRenderItem = {
  id: string;
  name: string;
  powerId: string;
  labelX: number;
  labelY: number;
  paths: Array<{ id: string; d: string }>;
};

type SvgLabelPosition = {
  svgX: number;
  svgY: number;
};

type Minister = {
  id?: string;
  name: string;
  office: string;  // 去职者已清空，可能为空串
  office_type: string;
  faction: string;
  style: string;
  status: string;  // active/dismissed/imprisoned/exiled/retired/dead/offstage
  status_reason?: string;
  status_label: string;  // 中文：在朝/已罢黜/下狱/流放/致仕…
  summary: string;
  favorite: boolean;
  portrait_id?: string;  // 空/undefined=无专属，前端 fallback 到池
  power_id?: string;     // 大明=ming, 后金=houjin, 流寇=bandits 等
  skills: Array<{ id: string; name: string; sources: string[]; description: string }>;
};

type EventItem = {
  id: string;
  title: string;
  kind: string;
  summary: string;
  urgency: number;
  severity: number;
  credibility: number;
  interests: string[];
  audiences: string[];
};

type Directive = {
  id: number;
  event_id: string;
  event_title: string;
  actor: string;
  skill_id: string;
  skill_name: string;
  text: string;
  source: string;
  status: string; // pending（待核定大臣拟旨）| draft（颁诏候选）
  notes: string;
  authority: string;
};

type Issue = {
  id: number;
  kind: "situation" | "initiative";
  title: string;
  bar_value: number;
  bar_good_meaning: string;
  bar_bad_meaning: string;
  phase: string;
  stage_text: string;
  severity: number;
  tags: string[];
  inertia: number;
  resolve_condition: string;
  fail_condition: string;
  ongoing_text: string;
  effect_on_resolve: Record<string, number>;
  effect_on_fail: Record<string, number>;
};

type LegacyEffect = {
  国库?: number;
  内库?: number;
  民心?: number;
  皇威?: number;
  regions?: Record<string, Record<string, number>>;
  armies?: Record<string, Record<string, number>>;
};

type Legacy = {
  id: number;
  name: string;
  narrative_hint: string;
  modifiers: LegacyEffect;
  effect_text: string;
  remaining_months: number;  // -1 = 永久
  clear_condition: string;
};

type ClosedIssue = {
  id: number;
  kind: "situation" | "initiative";
  title: string;
  status: "resolved" | "failed" | "dropped";
  bar_value: number;
  bar_good_meaning: string;
  bar_bad_meaning: string;
  closed_turn: number;
  stage_text: string;
  effect: any;
};

type BudgetItem = {
  name: string;
  amount: number;
  note: string;
};

type BudgetMovement = {
  delta: number;
  balance_after: number;
  category: string;
  reason: string;
};

type BudgetAccount = {
  balance: number;
  income: BudgetItem[];
  expense: BudgetItem[];
  income_total: number;
  expense_total: number;
  net: number;
  movements: BudgetMovement[];
  movements_total: number;
};

type Budget = Record<"国库" | "内库", BudgetAccount>;

type GameState = {
  turn: { year: number; period: number; turn: number };
  metrics: Metrics;
  previous_summary: string;
  treasury: string;
  issues: Issue[];
  legacies: Legacy[];
  closed_this_turn: ClosedIssue[];
  budget: Budget;
  region_warning: string;
  army_warning: string;
  power_warning: string;
  powers: Power[];
  victory_status: { status: string; summary: string };
  ending: EndingPayload | null;
  events: EventItem[];
  regions: Region[];
  armies: Army[];
  map_nodes: MapNode[];
  ministers: Minister[];
  consorts: Minister[];
  directives: Directive[];
  pending_count: number;
  last_decree: string;
  last_report: string;
};

type EndingTimelineItem = {
  turn: number; year: number; period: number;
  decree_brief: string; effect_brief: string; chapter: string;
};
type EndingPayload = {
  status: string; label: string; summary: string; timeline: EndingTimelineItem[];
};
type ChatMessage = { role: "user" | "minister"; content: string };
type ChatDisplayMessage = ChatMessage & { pending?: boolean };
type Suggestion = { label: string; text: string; prefix?: boolean };
type ModalName = "none" | "state" | "chat" | "edict" | "report" | "extraction" | "history" | "menu" | "secret_orders" | "ending" | "long_goals";
type SaveEntry = { name: string; size: number; mtime: number };
type LLMConfigInfo = {
  base_url: string;
  model: string;
  max_tokens: number;
  timeout_seconds: number;
  thinking_level: string;
  advanced_model: string;
  advanced_base_url: string;
  has_advanced_api_key: boolean;
  advanced_thinking_level: string;
  has_api_key: boolean;
  persisted: {
    base_url: string;
    model: string;
    has_api_key: boolean;
    max_tokens: number;
    timeout_seconds: number;
    thinking_level: string;
    advanced_model: string;
    advanced_base_url: string;
    has_advanced_api_key: boolean;
    advanced_thinking_level: string;
  };
};
type SecretOrder = {
  id: number;
  turn_issued: number;
  due_turn: number;
  year_issued: number;
  period_issued: number;
  minister_name: string;
  title: string;
  content: string;
  tags: string[];
  importance: number;
  status: "active" | "pending_review" | "done" | "failed" | "cancelled";
  result: string;
  sim_note: string;
  turn_closed: number | null;
};

type ProposedDirective = { id: number; text: string; status: string; notes: string };
type ChatResponse = {
  answer: string;
  history: ChatMessage[];
  suggestions: Suggestion[];
  directives: Directive[];
  pending_count?: number;
  can_undo_last_chat?: boolean;
  court_action?: string;
  next_minister?: string;
  registered_minister?: string;
  proposed_directive?: ProposedDirective | null;
  secret_order_id?: number;
};

type ChatUndoResponse = {
  history: ChatMessage[];
  suggestions: Suggestion[];
  directives: Directive[];
  pending_count: number;
  secret_orders: SecretOrder[];
  can_undo_last_chat: boolean;
};

type ApiErrorDetail = {
  code?: string;
  message?: string;
  provider_message?: string;
  status_code?: number | null;
};

class ApiRequestError extends Error {
  detail: ApiErrorDetail;

  constructor(detail: ApiErrorDetail, fallback: string) {
    const message = detail.message || fallback;
    super(detail.code ? `[${detail.code}] ${message}` : message);
    this.name = "ApiRequestError";
    this.detail = detail;
  }
}

const normalizeApiError = (error: any, fallback: string): ApiErrorDetail => {
  const detail = error?.detail ?? error;
  if (detail && typeof detail === "object") {
    return {
      code: detail.code,
      message: detail.message || detail.detail || fallback,
      provider_message: detail.provider_message,
      status_code: detail.status_code,
    };
  }
  return { message: String(detail || fallback) };
};

const formatApiError = (error: any, fallback: string) => {
  const detail = error instanceof ApiRequestError ? error.detail : normalizeApiError(error, fallback);
  return detail.code ? `[${detail.code}] ${detail.message || fallback}` : detail.message || fallback;
};

const api = async <T,>(path: string, options?: RequestInit): Promise<T> => {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options?.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new ApiRequestError(normalizeApiError(error, response.statusText), response.statusText);
  }
  return response.json();
};

const parseSseMessage = (raw: string): { event: string; data: string } | null => {
  const lines = raw.split(/\r?\n/);
  let event = "message";
  const dataLines: string[] = [];
  for (const line of lines) {
    if (line.startsWith("event:")) {
      event = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trimStart());
    }
  }
  if (!dataLines.length) return null;
  return { event, data: dataLines.join("\n") };
};

const streamChat = async (
  ministerName: string,
  message: string,
  onDelta: (delta: string) => void,
): Promise<ChatResponse> => {
  const response = await fetch(`/api/ministers/${encodeURIComponent(ministerName)}/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new ApiRequestError(normalizeApiError(error, response.statusText), response.statusText);
  }
  if (!response.body) {
    throw new Error("浏览器不支持流式回复。");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const messages = buffer.split("\n\n");
    buffer = messages.pop() || "";

    for (const messageBlock of messages) {
      const parsed = parseSseMessage(messageBlock);
      if (!parsed) continue;
      const payload = JSON.parse(parsed.data);
      if (parsed.event === "delta") {
        onDelta(String(payload.content || ""));
      } else if (parsed.event === "done") {
        return payload as ChatResponse;
      } else if (parsed.event === "error") {
        throw new ApiRequestError(normalizeApiError(payload, "流式回复失败。"), "流式回复失败。");
      }
    }

    if (done) break;
  }

  throw new Error("流式回复中断，未收到完成事件。");
};

const scoreTone = (value: number, inverse = false) => {
  const danger = inverse ? value >= 65 : value <= 38;
  const warn = inverse ? value >= 45 : value <= 52;
  if (danger) return "danger";
  if (warn) return "warn";
  return "good";
};

const formatMoney = (value: number) => `${value}万两`;

const formatSignedMoney = (value: number) => `${value > 0 ? "+" : ""}${formatMoney(value)}`;

const monthlyAmount = (value: number) => Math.max(0, Math.round(value / 3));

const issueTone = (value: number) => {
  if (value <= 28) return "danger";
  if (value <= 58) return "warn";
  return "good";
};

const signedNumber = (value: number) => `${value > 0 ? "+" : ""}${value}`;

const numericEffectValue = (value: any): number | null => {
  if (typeof value === "number") return value;
  if (typeof value === "string" && /^-?\d+$/.test(value.trim())) return Number(value);
  return null;
};

const appendScopedEffect = (
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

const formatEffectSummary = (effect: any) => {
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

const formatIssueEffect = formatEffectSummary;
const formatClosedEffect = formatEffectSummary;

const splitReportItems = (text: string, prefix: string) => {
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
const labelMaps = {
  region: new Map<string, string>(),
  army: new Map<string, string>(),
  power: new Map<string, string>(),
  issue: new Map<number, string>(),
};

const POWER_ID_CN: Record<string, string> = {
  ming: "大明",
  houjin: "后金",
  mongol: "蒙古",
  korea: "朝鲜",
  bandits: "流寇",
  dutch: "荷兰东印度公司",
  japan: "日本",
};

function refreshLabelMaps(state: GameState) {
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
const labelRegion = (id: any) => labelMaps.region.get(String(id)) || String(id ?? "");
const labelArmy = (id: any) => labelMaps.army.get(String(id)) || String(id ?? "");
const labelPower = (id: any) => labelMaps.power.get(String(id)) || POWER_ID_CN[String(id)] || String(id ?? "");
const labelIssue = (id: any) => {
  const t = labelMaps.issue.get(Number(id));
  return t ? `#${id} ${t}` : `#${id}`;
};

// extractor 偶尔吐出的英文枚举值，统一翻中文。
const EN_VALUE_CN: Record<string, string> = {
  ...POWER_ID_CN,
  appoint: "新进朝堂", promote: "升迁", transfer: "调任", demote: "贬", reinstate: "起复",
  resolved: "已了", failed: "崩坏", dropped: "撤销",
  situation: "时局", initiative: "举措", crisis: "危机", reform: "改革", decree: "诏令",
  done: "办结", pending: "在办", pending_review: "待核议", active: "进行中",
  draft: "草案", rejected: "已驳回", cancelled: "已取消",
};
const cnValue = (v: any) => (v == null ? "" : (EN_VALUE_CN[String(v)] || String(v)));

// extractor 吐的是英文字段名（region/army/class/power 的列名），这里统一翻中文。
// 查不到的回退原值，至少不空。
const EN_FIELD_CN: Record<string, string> = {
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
const cnField = (k: string) => EN_FIELD_CN[k] || k;

const fiscalKeyLabel = (key: any): string => {
  const raw = String(key ?? "");
  const match = raw.match(/^(.+)_(base|rate)$/);
  if (!match) return cnField(raw);
  return `${match[1]}${match[2] === "base" ? "基数" : "系数"}`;
};

const briefTreasury = (state: GameState) => [
  `固定预算：国库月净${formatSignedMoney(state.budget["国库"].net)}，内库月净${formatSignedMoney(state.budget["内库"].net)}。`,
  `账面余银：国库${formatMoney(state.budget["国库"].balance)}，内库${formatMoney(state.budget["内库"].balance)}。`,
];

const briefRegionWarnings = (text: string) => {
  const { items, tail } = splitReportItems(text, "地区警讯：");
  return [...items.slice(0, 3), tail].filter(Boolean);
};

const briefArmyWarnings = (text: string) => {
  const { items, tail } = splitReportItems(text, "军队警讯：");
  return [...items.slice(0, 3), tail].filter(Boolean);
};


const getMapIntelStyle = (node: MapNode): React.CSSProperties => {
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

type AppView = "menu" | "game";

type MenuSave = {
  name: string;
  size: number;
  mtime: number;
  campaign_id?: string;
  kind?: "auto" | "manual";
  label?: string;
  year?: number;
  period?: number;
  turn?: number;
  tag?: string;
};

type MenuCampaign = {
  campaign_id: string;
  kind: "auto" | "manual";
  current: boolean;
  saves: MenuSave[];
  latest_mtime: number;
};

type MenuStatus = {
  has_api_key: boolean;
  has_running_game: boolean;
  has_main_db: boolean;
  saves: MenuSave[];
  campaigns?: MenuCampaign[];
  current_campaign?: string;
  llm: {
    base_url: string;
    model: string;
    has_api_key: boolean;
    max_tokens: number;
    timeout_seconds: number;
    thinking_level: string;
    advanced_model: string;
    advanced_base_url: string;
    has_advanced_api_key: boolean;
    advanced_thinking_level: string;
  };
};

function App() {
  const [appView, setAppView] = React.useState<AppView>("menu");
  const [menuStatus, setMenuStatus] = React.useState<MenuStatus | null>(null);
  // 新 HUD stage 实际像素尺寸（matrix3d 透视需要 px 基准）
  const hudStageRef = React.useRef<HTMLDivElement | null>(null);
  const [hudStageSize, setHudStageSize] = React.useState({ w: 0, h: 0 });
  // 用 callback ref：stage 一挂载就接 ResizeObserver，避免 effect 时机竞态导致尺寸永远 0
  const hudStageCbRef = React.useCallback((el: HTMLDivElement | null) => {
    hudStageRef.current = el;
    if (!el) return;
    const measure = () => setHudStageSize({ w: el.clientWidth, h: el.clientHeight });
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    (el as any).__ro = ro;
  }, []);
  const [state, setState] = React.useState<GameState | null>(null);
  const [selectedNodeId, setSelectedNodeId] = React.useState<string>("");
  const [mapIntelOpen, setMapIntelOpen] = React.useState(false);
  const [drawerOpen, setDrawerOpen] = React.useState(false);
  const [haremDrawerOpen, setHaremDrawerOpen] = React.useState(false);
  const [armyDrawerOpen, setArmyDrawerOpen] = React.useState(false);
  const [regionDrawerOpen, setRegionDrawerOpen] = React.useState(false);
  const [buildingDrawerOpen, setBuildingDrawerOpen] = React.useState(false);
  const [economyDrawerOpen, setEconomyDrawerOpen] = React.useState(false);
  const [appointmentDrawerOpen, setAppointmentDrawerOpen] = React.useState(false);
  const [selectedRegionId, setSelectedRegionId] = React.useState<string>("");
  const [selectedArmyId, setSelectedArmyId] = React.useState<string>("");
  const [ministerGroup, setMinisterGroup] = React.useState("内阁+六部");
  const [haremGroup, setHaremGroup] = React.useState("全部");
  const [selectedMinister, setSelectedMinister] = React.useState<string>("");
  const [temporaryActiveMinister, setTemporaryActiveMinister] = React.useState<Minister | null>(null);
  const [activeModal, setActiveModal] = React.useState<ModalName>("none");
  const [chat, setChat] = React.useState<ChatMessage[]>([]);
  const [suggestions, setSuggestions] = React.useState<Suggestion[]>([]);
  const [pendingUserMessage, setPendingUserMessage] = React.useState("");
  const [streamingMinisterMessage, setStreamingMinisterMessage] = React.useState("");
  const [chatNotice, setChatNotice] = React.useState("");
  const [canUndoLastChat, setCanUndoLastChat] = React.useState(false);
  const [composerHint, setComposerHint] = React.useState("");
  const [input, setInput] = React.useState("");
  const [directiveText, setDirectiveText] = React.useState("");
  const [editingDirectiveId, setEditingDirectiveId] = React.useState<number | null>(null);
  const [editingDirectiveText, setEditingDirectiveText] = React.useState("");
  const [decree, setDecree] = React.useState("");
  const [report, setReport] = React.useState("");
  const [gazetteReport, setGazetteReport] = React.useState("");
  const [busy, setBusy] = React.useState("");
  const [error, setError] = React.useState("");
  const [settleStage, setSettleStage] = React.useState("");
  const [settleThinking, setSettleThinking] = React.useState("");
  const [settleNarrative, setSettleNarrative] = React.useState("");
  const [closedShown, setClosedShown] = React.useState<number>(() => {
    const raw = sessionStorage.getItem("closedShownTurn");
    return raw ? Number(raw) : -1;
  });
  const [closedModal, setClosedModal] = React.useState<ClosedIssue[]>([]);
  const [gazetteShown, setGazetteShown] = React.useState<number>(-1);
  // 结局页本次加载是否已被玩家关掉（关掉后让位邸报，刷新复位重弹）。
  const [endingDismissed, setEndingDismissed] = React.useState(false);
  const [secretOrders, setSecretOrders] = React.useState<SecretOrder[]>([]);
  const [secretOrderShown, setSecretOrderShown] = React.useState<number>(-1);
  // 作弊控制台（Ctrl+~）：cheatDirective 暂存强制结算项，下次颁诏随结算一次性穿入。
  const [cheatOpen, setCheatOpen] = React.useState(false);
  const [cheatDirective, setCheatDirective] = React.useState("");

  const loadState = React.useCallback(async () => {
    const data = await api<GameState>("/api/game/state");
    refreshLabelMaps(data);
    setState(data);
    setSelectedNodeId((current) => current || data.map_nodes[0]?.id || "");
    setDecree(data.last_decree || "");
    setReport(data.last_report || "");
  }, [selectedMinister]);

  const loadMinisterChat = React.useCallback(async (ministerName: string) => {
    const data = await api<{ minister: Minister; history: ChatMessage[]; suggestions: Suggestion[]; can_undo_last_chat: boolean }>(`/api/ministers/${encodeURIComponent(ministerName)}/chat`);
    const allKnown = [
      ...(state?.ministers || []),
      ...(state?.consorts || []),
    ];
    setTemporaryActiveMinister(allKnown.some((m) => m.name === data.minister.name) ? null : data.minister);
    setChat(data.history);
    setSuggestions(data.suggestions);
    setCanUndoLastChat(!!data.can_undo_last_chat);
  }, [state]);

  const uploadPortrait = React.useCallback(async (ministerName: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    const resp = await fetch(`/api/consorts/${encodeURIComponent(ministerName)}/portrait`, {
      method: "POST",
      body: form,
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: resp.statusText }));
      throw new Error(err.detail || resp.statusText);
    }
    await loadState();  // 重新拉 state，新 portrait_id 流回卡片
  }, [loadState]);

  const refreshMenuStatus = React.useCallback(async () => {
    const s = await api<MenuStatus>("/api/menu/status");
    setMenuStatus(s);
    return s;
  }, []);

  React.useEffect(() => {
    refreshMenuStatus()
      .then((s) => {
        if (s.has_running_game) {
          setAppView("game");
          loadState().catch((err) => setError(err.message));
        }
      })
      .catch((err) => setError(err.message));
  }, [refreshMenuStatus, loadState]);

  const enterGameAfterMenu = React.useCallback(async () => {
    setAppView("game");
    await loadState();
  }, [loadState]);

  const exitToMenu = React.useCallback(async () => {
    await fetch("/api/menu/exit_to_menu", { method: "POST" });
    setState(null);
    setAppView("menu");
    await refreshMenuStatus();
  }, [refreshMenuStatus]);

  React.useEffect(() => {
    if (!state) return;
    const closed = state.closed_this_turn || [];
    const currentTurn = state.turn.turn;
    if (closed.length && currentTurn !== closedShown) {
      setClosedModal(closed);
      setClosedShown(currentTurn);
      sessionStorage.setItem("closedShownTurn", String(currentTurn));
    }
  }, [state, closedShown]);

  // 新回合进入时拉取全部密令，有 active 密令则弹密令进度弹窗（邸报关闭后显示）
  React.useEffect(() => {
    if (!state) return;
    const currentTurn = state.turn.turn;
    if (currentTurn === secretOrderShown) return;
    api<{ orders: SecretOrder[] }>("/api/secret_orders")
      .then(({ orders }) => {
        setSecretOrders(orders);
        if (orders.some(o => o.status === "active" || o.status === "pending_review")) {
          // 延迟 400ms，避免与邸报弹窗争抢
          setTimeout(() => setActiveModal("secret_orders"), 400);
        }
        setSecretOrderShown(currentTurn);
      })
      .catch(() => {/* 失败静默 */});
  }, [state?.turn.turn]);

  // 结局已触发：每次进页面/刷新都自动弹结局结算页。玩家点关闭后（endingDismissed）
  // 本次加载让位给盘面/邸报，可继续看局；刷新即复位重弹。
  React.useEffect(() => {
    if (!state || !state.ending) return;
    if (endingDismissed) return;
    setActiveModal("ending");
  }, [state, endingDismissed]);

  // 每次进入页面/换回合都弹上回合邸报。不持久化记录——刷新即重新弹。
  // 同一加载周期内同一回合不重复弹（gazetteShown 用 React state，刷新后回到 -1）。
  React.useEffect(() => {
    if (!state) return;
    // 结局页未关掉时让位给它；玩家关掉后（endingDismissed）邸报照常。
    if (state.ending && !endingDismissed) return;
    const currentTurn = state.turn.turn;
    const summary = (state.previous_summary || "").trim();
    if (!summary) return;
    if (summary.startsWith("登基伊始")) return;
    if (currentTurn === gazetteShown) return;
    setGazetteReport(summary);
    setActiveModal("report");
    setGazetteShown(currentTurn);
  }, [state, gazetteShown, endingDismissed]);

  React.useEffect(() => {
    if (!selectedMinister) {
      setChat([]);
      setSuggestions([]);
      setPendingUserMessage("");
      setStreamingMinisterMessage("");
      setChatNotice("");
      setCanUndoLastChat(false);
      setComposerHint("");
      return;
    }
    setChat([]);
    setSuggestions([]);
    setPendingUserMessage("");
    setStreamingMinisterMessage("");
    setCanUndoLastChat(false);
    setComposerHint("");
    loadMinisterChat(selectedMinister).catch((err) => setError(err.message));
  }, [selectedMinister, loadMinisterChat]);

  // 全局 ESC：按 z-index 优先级，最前面的弹窗先关
  React.useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (activeModal === "chat" || activeModal === "edict" || activeModal === "state" || activeModal === "history" || activeModal === "report" || activeModal === "secret_orders" || activeModal === "long_goals") {
        // 召对/诏书等全屏弹窗最优先
        setActiveModal("none");
      } else if (drawerOpen) {
        setDrawerOpen(false);
      } else if (haremDrawerOpen) {
        setHaremDrawerOpen(false);
      } else if (armyDrawerOpen) {
        setArmyDrawerOpen(false);
      } else if (regionDrawerOpen) {
        setRegionDrawerOpen(false);
      } else if (buildingDrawerOpen) {
        setBuildingDrawerOpen(false);
      } else if (economyDrawerOpen) {
        setEconomyDrawerOpen(false);
      } else if (appointmentDrawerOpen) {
        setAppointmentDrawerOpen(false);
      } else if (mapIntelOpen) {
        setMapIntelOpen(false);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [activeModal, drawerOpen, haremDrawerOpen, mapIntelOpen]);

  // 作弊控制台：Ctrl+~（或 Ctrl+`）切换显隐。强制结算唯一入口。
  React.useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (event.ctrlKey && (event.key === "~" || event.key === "`")) {
        event.preventDefault();
        setCheatOpen((v) => !v);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  if (appView === "menu") {
    return (
      <MenuPage
        status={menuStatus}
        onRefresh={refreshMenuStatus}
        onEnterGame={enterGameAfterMenu}
        error={error}
        setError={setError}
      />
    );
  }

  if (!state) {
    return (
      <div className="loading-screen">
        <div className="loading-panel">
          <Crown size={28} />
          <p>正在启封奏牍与山河舆图...</p>
        </div>
      </div>
    );
  }

  const powerById = new Map((state.powers || []).map((power) => [power.id, power]));
  const mapNodes = state.map_nodes.map((node) => {
    const powerId = node.region?.controlled_by;
    return powerId ? { ...node, power: powerById.get(powerId) } : node;
  });
  const selectedNode = mapNodes.find((node) => node.id === selectedNodeId) || mapNodes[0];
  const ministers = filterMinisters(state.ministers, ministerGroup);
  const consorts = filterConsorts(state.consorts || [], haremGroup);
  const allCharacters = [...state.ministers, ...(state.consorts || [])];
  const activeMinister = selectedMinister
    ? allCharacters.find((m) => m.name === selectedMinister) || temporaryActiveMinister
    : null;
  const mapIntelStyle = selectedNode ? getMapIntelStyle(selectedNode) : undefined;

  const openChat = (minister: Minister) => {
    if (minister.status && minister.status !== "active") {
      setError(`${minister.name}已${minister.status_label}${minister.status_reason ? "（" + minister.status_reason + "）" : ""}，无法召见。`);
      return;
    }
    const switchingMinister = selectedMinister !== minister.name;
    if (switchingMinister) {
      setChat([]);
      setSuggestions([]);
      setTemporaryActiveMinister(null);
      setCanUndoLastChat(false);
    }
    setSelectedMinister(minister.name);
    setActiveModal("chat");
    setError("");
    setComposerHint("");
    setChatNotice("");
    setCanUndoLastChat(false);
    setPendingUserMessage("");
    setStreamingMinisterMessage("");
    loadMinisterChat(minister.name).catch((err) => setError(err.message));
  };

  const selectMapNode = (nodeId: string) => {
    setSelectedNodeId(nodeId);
    setMapIntelOpen(true);
  };

  const sendChat = async (text = input) => {
    if (busy) return;
    if (!activeMinister) return;
    const message = text.trim();
    if (!message) {
      setComposerHint("请先问话或点一个奏对题目");
      return;
    }

    const fromComposer = text === input;
    setPendingUserMessage(message);
    setStreamingMinisterMessage("");
    setBusy("大臣思索中");
    setError("");
    setComposerHint("");
    setChatNotice("");
    if (fromComposer) {
      setInput("");
    }
    try {
      const data = await streamChat(activeMinister.name, message, (delta) => {
        setStreamingMinisterMessage((current) => current + delta);
      });
      setPendingUserMessage("");
      setStreamingMinisterMessage("");
      setChat(data.history);
      setSuggestions(data.suggestions);
      setCanUndoLastChat(!!data.can_undo_last_chat);
      setState((current) => (current ? { ...current, directives: data.directives, pending_count: data.pending_count ?? current.pending_count } : current));
      await loadState();
      // 刷新密令列表（含历史，大臣可能调了 issue_secret_order tool）
      api<{ orders: SecretOrder[] }>("/api/secret_orders")
        .then(({ orders }) => setSecretOrders(orders))
        .catch(() => {});
      if (data.secret_order_id) {
        setChatNotice(`密令已秘密交付${activeMinister.name}，编号 #${data.secret_order_id}。`);
      }
      if (data.proposed_directive) {
        setChatNotice(`${activeMinister.name}已拟旨一道，待陛下在「诏书草案」核定（准/驳）。`);
      }
      if (data.next_minister) {
        setChat([]);
        setSuggestions([]);
        setStreamingMinisterMessage("");
        setCanUndoLastChat(false);
        setSelectedMinister(data.next_minister);
        setActiveModal("chat");
        setChatNotice(`已传${data.next_minister}入殿。`);
        loadMinisterChat(data.next_minister).catch((err) => setError(err.message));
      }
      if (data.court_action === "dismiss") {
        setPendingUserMessage("");
        setChatNotice(`${activeMinister.name}已退下。请从左侧召见下一位大臣。`);
      }
    } catch (err) {
      if (fromComposer) {
        setInput(message);
      }
      setPendingUserMessage("");
      setStreamingMinisterMessage("");
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("");
    }
  };

  const undoLastChat = async () => {
    if (busy || !activeMinister || !canUndoLastChat) return;
    const ok = window.confirm("将撤回最近一轮召对及其政务影响，是否继续？");
    if (!ok) return;
    setBusy("撤回召对");
    setError("");
    setChatNotice("");
    setComposerHint("");
    setPendingUserMessage("");
    setStreamingMinisterMessage("");
    try {
      const data = await api<ChatUndoResponse>(`/api/ministers/${encodeURIComponent(activeMinister.name)}/chat/undo`, {
        method: "POST",
      });
      setChat(data.history);
      setSuggestions(data.suggestions);
      setCanUndoLastChat(!!data.can_undo_last_chat);
      setSecretOrders(data.secret_orders || []);
      setState((current) => (current ? { ...current, directives: data.directives, pending_count: data.pending_count } : current));
      await loadState();
      setChatNotice("已撤回最近一轮召对。");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("");
    }
  };

  const createDirective = async () => {
    if (!directiveText.trim()) return;
    setBusy("登记诏书草案");
    setError("");
    try {
      const data = await api<{ directives: Directive[] }>("/api/directives", {
        method: "POST",
        body: JSON.stringify({
          text: directiveText.trim(),
        }),
      });
      setDirectiveText("");
      setState((current) => (current ? { ...current, directives: data.directives } : current));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("");
    }
  };

  const toggleFavorite = async (minister: Minister) => {
    setBusy(minister.favorite ? "移出收藏" : "加入收藏");
    setError("");
    try {
      await api<{ favorites: string[] }>(`/api/favorites/${encodeURIComponent(minister.name)}`, {
        method: minister.favorite ? "DELETE" : "POST",
      });
      await loadState();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("");
    }
  };

  const startEditDirective = (directive: Directive) => {
    setEditingDirectiveId(directive.id);
    setEditingDirectiveText(directive.text);
  };

  const cancelEditDirective = () => {
    setEditingDirectiveId(null);
    setEditingDirectiveText("");
  };

  const saveDirective = async (directive: Directive) => {
    if (!editingDirectiveText.trim()) return;
    setBusy("修改草案");
    setError("");
    try {
      const data = await api<{ directives: Directive[] }>(`/api/directives/${directive.id}`, {
        method: "PATCH",
        body: JSON.stringify({ text: editingDirectiveText.trim() }),
      });
      setState((current) => (current ? { ...current, directives: data.directives } : current));
      cancelEditDirective();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("");
    }
  };

  const deleteDirective = async (directiveId: number) => {
    setBusy("删除草案");
    setError("");
    try {
      const data = await api<{ directives: Directive[] }>(`/api/directives/${directiveId}`, { method: "DELETE" });
      setState((current) => (current ? { ...current, directives: data.directives } : current));
      if (editingDirectiveId === directiveId) {
        cancelEditDirective();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("");
    }
  };

  const confirmDirective = async (directiveId: number) => {
    setBusy("核定大臣拟旨");
    setError("");
    try {
      const data = await api<{ directives: Directive[]; pending_count: number }>(`/api/directives/${directiveId}/confirm`, { method: "POST" });
      setState((current) => (current ? { ...current, directives: data.directives, pending_count: data.pending_count } : current));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("");
    }
  };

  const rejectDirective = async (directiveId: number) => {
    setBusy("驳回大臣拟旨");
    setError("");
    try {
      const data = await api<{ directives: Directive[]; pending_count: number }>(`/api/directives/${directiveId}/reject`, { method: "POST" });
      setState((current) => (current ? { ...current, directives: data.directives, pending_count: data.pending_count } : current));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("");
    }
  };

  const writeDecree = async () => {
    setBusy("拟写正式诏书");
    setError("");
    try {
      const data = await api<{ decree: string }>("/api/decree/write", { method: "POST" });
      setDecree(data.decree);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("");
    }
  };

  const saveDecree = async (text: string) => {
    setBusy("存改诏书");
    setError("");
    try {
      const data = await api<{ decree: string }>("/api/decree", {
        method: "PATCH",
        body: JSON.stringify({ decree: text }),
      });
      setDecree(data.decree);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("");
    }
  };

  const resetDecree = () => {
    // 返工：丢弃当前诏文回到御案理政幕。后端旧诏文留着无妨，重新生成即覆盖。
    setDecree("");
    setError("");
  };

  const issueDecree = async () => {
    setBusy("月末结算");
    setSettleStage("");
    setSettleThinking("");
    setSettleNarrative("");
    setError("");
    try {
      // 作弊强制结算项随颁诏一次性穿入；发出即清空，绝不跨回合。
      const cheatPayload = cheatDirective.trim();
      const response = await fetch("/api/decree/issue/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ cheat: cheatPayload }),
      });
      if (cheatPayload) {
        setCheatDirective("");
      }
      if (!response.ok || !response.body) {
        throw new Error(`颁诏失败：HTTP ${response.status}`);
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let done = false;
      let failed = "";
      while (!done) {
        const { value, done: streamDone } = await reader.read();
        if (streamDone) break;
        buffer += decoder.decode(value, { stream: true });
        // SSE 事件以空行分隔
        const blocks = buffer.split("\n\n");
        buffer = blocks.pop() || "";
        for (const block of blocks) {
          let evName = "";
          let dataRaw = "";
          for (const line of block.split("\n")) {
            if (line.startsWith("event: ")) evName = line.slice(7).trim();
            else if (line.startsWith("data: ")) dataRaw += line.slice(6);
          }
          if (!evName || !dataRaw) continue;
          let data: { content?: string; message?: string } = {};
          try { data = JSON.parse(dataRaw); } catch { continue; }
          if (evName === "stage") {
            setSettleStage(data.content || "");
          } else if (evName === "thinking") {
            setSettleThinking((prev) => prev + (data.content || ""));
          } else if (evName === "text") {
            setSettleNarrative((prev) => prev + (data.content || ""));
          } else if (evName === "error") {
            failed = data.message || "颁诏失败。";
            done = true;
          } else if (evName === "done") {
            done = true;
          }
        }
      }
      if (failed) {
        setError(failed);
        setBusy("");
        return;
      }
      // 结算完成：强制整页刷新，草案/对话/局势/closed 弹窗全部按新 state 重新初始化
      window.location.reload();
      return;
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy("");
    }
  };

  const settling = busy === "月末结算";
  const guardClose = (fn: () => void) => () => {
    if (settling) return;
    fn();
  };

  const activeDrawerKey =
    drawerOpen ? "court" :
    haremDrawerOpen ? "harem" :
    armyDrawerOpen ? "army" :
    regionDrawerOpen ? "region" :
    buildingDrawerOpen ? "building" :
    economyDrawerOpen ? "economy" :
    appointmentDrawerOpen ? "appointment" : "";
  const navHandlers = {
    court: () => setDrawerOpen((v) => !v),
    harem: () => setHaremDrawerOpen((v) => !v),
    army: () => setArmyDrawerOpen((v) => !v),
    region: () => setRegionDrawerOpen((v) => !v),
    building: () => setBuildingDrawerOpen((v) => !v),
    economy: () => setEconomyDrawerOpen((v) => !v),
    appointment: () => setAppointmentDrawerOpen((v) => !v),
    goal: () => setActiveModal("long_goals"),
  };
  const sz = hudStageSize;
  const ready = sz.w > 0 && sz.h > 0;

  return (
    <main className="game-shell">
      <div className="hud2-stage" ref={hudStageCbRef}>
        <img className="hud2-bg" src={HUD_BG} alt="" />

        {/* 地图：透视梯形（GrandMap 已改 transform pan，兼容 matrix3d）。?flat=1 关透视调试 */}
        {ready ? (
          (typeof window !== "undefined" && new URLSearchParams(window.location.search).has("flat")) ? (
            <div className="hud2-map-quad" style={{
              position: "absolute",
              left: `${HUD_SLOTS.地图四角.tl[0]}%`, top: `${HUD_SLOTS.地图四角.tl[1]}%`,
              width: `${HUD_SLOTS.地图四角.tr[0] - HUD_SLOTS.地图四角.tl[0]}%`,
              height: `${HUD_SLOTS.地图四角.bl[1] - HUD_SLOTS.地图四角.tl[1]}%`,
            }}>
              <GrandMap nodes={mapNodes} selectedId={mapIntelOpen ? selectedNode?.id || "" : ""} onSelect={selectMapNode} />
            </div>
          ) : (
            <QuadFrame className="hud2-map-quad" quad={HUD_SLOTS.地图四角}
              stageW={sz.w} stageH={sz.h} baseW={2560} baseH={1440}>
              <GrandMap nodes={mapNodes} selectedId={mapIntelOpen ? selectedNode?.id || "" : ""} onSelect={selectMapNode} />
            </QuadFrame>
          )
        ) : null}

        {/* 局势进度：塞进左卡透视梯形 */}
        {ready ? (
          <QuadFrame className="hud2-issue-quad" quad={HUD_SLOTS.局势四角}
            stageW={sz.w} stageH={sz.h} baseW={2560} baseH={1440}>
            <SituationPanel
              issues={state.issues}
              closedIssues={state.closed_this_turn || []}
              hasLegacies={(state.legacies || []).length > 0}
            />
          </QuadFrame>
        ) : null}

        {/* 顶栏：年月 + 国库/内库 + 民心/皇威，各按坑位绝对定位 */}
        <button className="hud2-slot hud2-year" style={HUD_SLOTS.顶栏.年月}
          onClick={() => setActiveModal("state")}>
          <span className="hud2-lab">大明</span>
          <span className="hud2-val">{state.turn.year} 年 {state.turn.period} 月</span>
        </button>
        <div className="hud2-slot" style={HUD_SLOTS.顶栏.国库}>
          <BudgetHover accountName="国库" budget={state.budget["国库"]} />
        </div>
        <div className="hud2-slot" style={HUD_SLOTS.顶栏.内库}>
          <BudgetHover accountName="内库" budget={state.budget["内库"]} />
        </div>
        <div className={`hud2-slot hud2-metric ${scoreTone(state.metrics["民心"], false)}`} style={HUD_SLOTS.顶栏.民心}>
          <span className="hud2-lab">民心</span><span className="hud2-val">{state.metrics["民心"]}</span>
        </div>
        <div className={`hud2-slot hud2-metric ${scoreTone(state.metrics["皇威"], false)}`} style={HUD_SLOTS.顶栏.皇威}>
          <span className="hud2-lab">皇威</span><span className="hud2-val">{state.metrics["皇威"]}</span>
        </div>

        {/* 右侧竖排部院导航 */}
        {([
          ["政", "court", "朝堂·召见大臣"],
          ["吏", "appointment", "官员任免"],
          ["省", "region", "省份列表"],
          ["兵", "army", "军队列表"],
          ["户", "economy", "经济面板"],
          ["工", "building", "建筑列表"],
          ["礼", "court", "礼部"],
          ["后", "harem", "后宫"],
          ["目", "goal", "长期目标"],
        ] as const).map(([label, key, title], idx) => {
          const slotKey = (["政","吏部","省份","兵部","户部","工部","礼部","后宫","菜单"] as const)[idx];
          return (
            <button key={slotKey} className={`hud2-slot hud2-nav${activeDrawerKey === key ? " active" : ""}`}
              style={HUD_SLOTS.导航[slotKey]} title={title} aria-label={title}
              onClick={(navHandlers as any)[key]}>
              {label}
            </button>
          );
        })}

        {/* 底部 5 命令物件（扣图填进木牌） */}
        <CommandSlot slotKey="奏疏" img="奏疏" badge={state.events.length}
          caption="奏疏" sub={`${state.events.length} 件待览`} onClick={() => setActiveModal("state")} />
        <CommandSlot slotKey="邸报" img="邸报"
          caption="邸报详明" sub="数项加减/账目明细" onClick={() => setActiveModal("extraction")} />
        <CommandSlot slotKey="密令" img="密令"
          badge={secretOrders.filter((o) => o.status === "active" || o.status === "pending_review").length}
          caption="密令" sub="进行中密令" onClick={() => setActiveModal("secret_orders")} />
        <CommandSlot slotKey="史册" img="史册"
          caption="史册" sub="历代奏报/诏书" onClick={() => setActiveModal("history")} />
        <CommandSlot slotKey="拟诏" img="拟诏" badge={state.directives.length}
          caption="拟诏/结束回合" sub={state.directives.length ? `${state.directives.length} 道` : "本回合"}
          onClick={() => setActiveModal("edict")} />
      </div>

      <CourtDrawer
        state={state}
        ministers={ministers}
        ministerGroup={ministerGroup}
        selectedMinister={selectedMinister}
        open={drawerOpen}
        onGroupChange={setMinisterGroup}
        onClose={guardClose(() => setDrawerOpen(false))}
        onOpenChat={openChat}
        onUploadPortrait={uploadPortrait}
      />

      <HaremDrawer
        consorts={consorts}
        haremGroup={haremGroup}
        selectedMinister={selectedMinister}
        open={haremDrawerOpen}
        onGroupChange={setHaremGroup}
        onClose={guardClose(() => setHaremDrawerOpen(false))}
        onOpenChat={openChat}
        onUploadPortrait={uploadPortrait}
      />

      <ArmyDrawer
        armies={state.armies}
        open={armyDrawerOpen}
        selectedArmyId={selectedArmyId}
        onSelectArmy={setSelectedArmyId}
        onClose={guardClose(() => setArmyDrawerOpen(false))}
      />

      <RegionDrawer
        regions={state.regions}
        open={regionDrawerOpen}
        selectedRegionId={selectedRegionId}
        onSelectRegion={setSelectedRegionId}
        onClose={guardClose(() => setRegionDrawerOpen(false))}
      />

      <BuildingDrawer
        regions={state.regions}
        mapNodes={mapNodes}
        open={buildingDrawerOpen}
        onClose={guardClose(() => setBuildingDrawerOpen(false))}
      />

      <EconomyDrawer
        state={state}
        open={economyDrawerOpen}
        onClose={guardClose(() => setEconomyDrawerOpen(false))}
      />

      <AppointmentDrawer
        ministers={state.ministers}
        open={appointmentDrawerOpen}
        onOpenChat={openChat}
        onClose={guardClose(() => setAppointmentDrawerOpen(false))}
      />

      {mapIntelOpen && selectedNode ? (
        <section className="map-intel-panel overlay-panel" style={mapIntelStyle}>
          <button className="icon-button panel-close" aria-label="关闭地区详情" onClick={() => setMapIntelOpen(false)}>
            <X size={16} />
          </button>
          <NodeIntel node={selectedNode} />
        </section>
      ) : null}

      {activeModal === "state" ? (
        <FullscreenModal title="国势与奏报" subtitle={`${state.turn.year} 年 ${state.turn.period} 月`} bgClass="modal-bg-state" onClose={guardClose(() => setActiveModal("none"))}>
          <StateModal state={state} />
        </FullscreenModal>
      ) : null}

      {activeModal === "long_goals" ? (
        <LongGoalsModal onClose={guardClose(() => setActiveModal("none"))} />
      ) : null}

      {activeModal === "chat" && activeMinister ? (
        <FullscreenModal title={`召对：${activeMinister.name}`} subtitle={activeMinister.office} bgClass="modal-bg-chat" onClose={guardClose(() => setActiveModal("none"))}>
          <ChatModal
            minister={activeMinister}
            portraitPrefix={(state.consorts || []).some((c) => c.name === activeMinister.name) ? "consort_" : "minister_"}
            chat={chat}
            suggestions={suggestions}
            pendingUserMessage={pendingUserMessage}
            streamingMinisterMessage={streamingMinisterMessage}
            chatNotice={chatNotice}
            canUndoLastChat={canUndoLastChat}
            composerHint={composerHint}
            input={input}
            busy={busy}
            error={error}
            secretOrders={secretOrders.filter((o) => o.minister_name === activeMinister.name && (o.status === "active" || o.status === "pending_review"))}
            onInput={setInput}
            onSend={sendChat}
            onUndo={undoLastChat}
            onHint={setComposerHint}
            onFavorite={() => toggleFavorite(activeMinister)}
            onOpenEdict={() => setActiveModal("edict")}
            onClose={guardClose(() => setActiveModal("none"))}
          />
        </FullscreenModal>
      ) : null}

      {activeModal === "edict" ? (
        <FullscreenModal title="诏书草案" subtitle="本月指令、拟诏与颁布" bgClass="modal-bg-edict" onClose={guardClose(() => setActiveModal("none"))}>
          <EdictModal
            state={state}
            directiveText={directiveText}
            editingDirectiveId={editingDirectiveId}
            editingDirectiveText={editingDirectiveText}
            decree={decree}
            report={report}
            busy={busy}
            error={error}
            onDirectiveTextChange={setDirectiveText}
            onEditingTextChange={setEditingDirectiveText}
            onCreateDirective={createDirective}
            onStartEdit={startEditDirective}
            onCancelEdit={cancelEditDirective}
            onSaveDirective={saveDirective}
            onDeleteDirective={deleteDirective}
            onWriteDecree={writeDecree}
            onSaveDecree={saveDecree}
            onResetDecree={resetDecree}
            onIssueDecree={issueDecree}
            onConfirmDirective={confirmDirective}
            onRejectDirective={rejectDirective}
          />
        </FullscreenModal>
      ) : null}

      {activeModal === "report" && (gazetteReport || report) ? (
        <ReportModal report={gazetteReport || report} onClose={guardClose(() => setActiveModal("none"))} />
      ) : null}

      {activeModal === "ending" && state.ending ? (
        <EndingModal ending={state.ending} onClose={() => { setEndingDismissed(true); setActiveModal("none"); }} />
      ) : null}

      {activeModal === "extraction" ? (
        <ExtractionModal onClose={guardClose(() => setActiveModal("none"))} />
      ) : null}

      {activeModal === "history" ? (
        <HistoryModal onClose={guardClose(() => setActiveModal("none"))} />
      ) : null}

      {activeModal === "menu" ? (
        <GameMenuModal
          onClose={guardClose(() => setActiveModal("none"))}
          onAfterLoad={() => {
            setActiveModal("none");
            window.location.reload();
          }}
          onExitToMenu={async () => {
            await exitToMenu();
            setActiveModal("none");
          }}
        />
      ) : null}

      {closedModal.length ? (
        <ClosedIssuesModal items={closedModal} onClose={() => setClosedModal([])} />
      ) : null}

      {activeModal === "secret_orders" ? (
        <SecretOrdersModal
          orders={secretOrders}
          onClose={() => setActiveModal("none")}
          onOpenMinister={(name) => {
            setActiveModal("chat");
            setSelectedMinister(name);
          }}
        />
      ) : null}

      {settling ? (
        <SettlementLock
          stage={settleStage}
          thinking={settleThinking}
          narrative={settleNarrative}
        />
      ) : null}

      {cheatOpen ? (
        <CheatConsole
          directive={cheatDirective}
          onCommit={setCheatDirective}
          onClose={() => setCheatOpen(false)}
        />
      ) : null}
    </main>
  );
}

// 作弊控制台：terminal UI。强制结算唯一入口（Ctrl+~ 唤出）。输入的指令暂存于
// cheatDirective，下次颁诏时随结算穿入 extractor 当既成事实落库。
function CheatConsole({
  directive,
  onCommit,
  onClose,
}: {
  directive: string;
  onCommit: (text: string) => void;
  onClose: () => void;
}) {
  const [draft, setDraft] = React.useState("");
  const [history, setHistory] = React.useState<string[]>([]);
  const inputRef = React.useRef<HTMLTextAreaElement>(null);
  const bodyRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    inputRef.current?.focus();
  }, []);
  React.useEffect(() => {
    if (bodyRef.current) bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
  }, [history]);

  const submit = () => {
    const text = draft.trim();
    if (!text) return;
    onCommit(text);
    setHistory((h) => [...h, `> ${text}`, "  已挂载强制结算项，下次颁诏随结算生效（一次性）。"]);
    setDraft("");
  };

  const clearMounted = () => {
    onCommit("");
    setHistory((h) => [...h, "  已清空强制结算项。"]);
  };

  return (
    <div className="cheat-console" role="dialog" aria-label="天命控制台" onClick={onClose}>
      <div className="cheat-console-window" onClick={(e) => e.stopPropagation()}>
        <div className="cheat-console-titlebar">
          <span>tianming@ming-salvage:~$ 天命控制台</span>
          <button className="cheat-console-x" onClick={onClose} aria-label="关闭">×</button>
        </div>
        <div className="cheat-console-body" ref={bodyRef}>
          <div className="cheat-console-line cheat-console-dim">
            强制结算控制台。输入的指令将在下次颁诏时作为「既成事实」穿入结算，无视合理性与史实。
          </div>
          <div className="cheat-console-line cheat-console-dim">
            Enter 提交 · Shift+Enter 换行 · Ctrl+~ 关闭
          </div>
          {directive ? (
            <div className="cheat-console-line cheat-console-armed">
              ● 当前已挂载：{directive}
            </div>
          ) : (
            <div className="cheat-console-line cheat-console-dim">○ 当前无挂载项</div>
          )}
          {history.map((line, i) => (
            <div className="cheat-console-line" key={i}>{line}</div>
          ))}
        </div>
        <div className="cheat-console-prompt">
          <span className="cheat-console-caret">&gt;</span>
          <textarea
            ref={inputRef}
            className="cheat-console-input"
            value={draft}
            rows={1}
            placeholder="例：国库增至九千万两，后金军覆灭，皇太极暴毙"
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
          />
        </div>
        <div className="cheat-console-actions">
          <button className="cheat-console-btn" onClick={submit}>挂载</button>
          <button className="cheat-console-btn cheat-console-btn-ghost" onClick={clearMounted}>清空挂载</button>
        </div>
      </div>
    </div>
  );
}

function SettlementLock({
  stage,
  thinking,
  narrative,
}: {
  stage: string;
  thinking: string;
  narrative: string;
}) {
  const thinkRef = React.useRef<HTMLDivElement>(null);
  const narrRef = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => {
    const block = (event: KeyboardEvent) => {
      event.preventDefault();
      event.stopPropagation();
    };
    window.addEventListener("keydown", block, true);
    return () => window.removeEventListener("keydown", block, true);
  }, []);
  // 流式内容到达时自动滚到底
  React.useEffect(() => {
    if (thinkRef.current) thinkRef.current.scrollTop = thinkRef.current.scrollHeight;
  }, [thinking]);
  React.useEffect(() => {
    if (narrRef.current) narrRef.current.scrollTop = narrRef.current.scrollHeight;
  }, [narrative]);
  return (
    <div className="settlement-lock" role="alertdialog" aria-modal="true" aria-label="月末结算">
      <div className="settlement-lock-card">
        <Loader2 className="settlement-spin" size={28} />
        <h2>月末结算中</h2>
        <p>{stage === "数值推演结算" ? "档房核账中，钱粮、地方、军务落账，请稍候。" : stage ? `当前：${stage}` : "朝廷推演钱粮、地方、军务，请勿操作。"}</p>
        {thinking && (
          <div className="settlement-stream-block">
            <div className="settlement-stream-label">邸报房推敲</div>
            <div className="settlement-stream-text settlement-thinking" ref={thinkRef}>
              {thinking}
            </div>
          </div>
        )}
        {narrative && (
          <div className="settlement-stream-block">
            <div className="settlement-stream-label">月末奏章</div>
            <div className="settlement-stream-text settlement-narrative" ref={narrRef}>
              {narrative}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function MinisterPortrait({ primary, fallback, name }: { primary: string; fallback?: string; name: string }) {
  // 两级 fallback：primary（专属）→ fallback（pool 预设）→ 占位符
  const [stage, setStage] = React.useState<"primary" | "fallback" | "placeholder">(
    fallback ? "primary" : (primary ? "primary" : "placeholder")
  );
  const src = stage === "primary" ? primary : stage === "fallback" ? (fallback ?? "") : "";
  if (stage === "placeholder") {
    return <div className="minister-card-portrait-placeholder">臣</div>;
  }
  return (
    <img
      className="minister-card-portrait"
      src={src}
      alt={name}
      onError={() => {
        if (stage === "primary" && fallback) setStage("fallback");
        else setStage("placeholder");
      }}
    />
  );
}

// 朝班两条透视线（百分比锚点，由用户拖定）
// 左列：韩爌(外) → 黄立极(内)；右列：张瑞图(外) → 施凤来(内)
const LEFT_ANCHOR  = { near: { px: 0.077, py: 0.532 }, far: { px: 0.377, py: 0.066 } };
const RIGHT_ANCHOR = { near: { px: 0.862, py: 0.532 }, far: { px: 0.558, py: 0.045 } };

// 每列槽位数
const COURT_SLOTS_PER_ROW = 10;

// 生成两列所有槽位坐标（百分比）
function courtSlots(): { px: number; py: number; side: "left" | "right"; slot: number }[] {
  const slots = [];
  for (let i = 0; i < COURT_SLOTS_PER_ROW; i++) {
    const t = i / (COURT_SLOTS_PER_ROW - 1);
    slots.push({
      px: LEFT_ANCHOR.near.px + t * (LEFT_ANCHOR.far.px - LEFT_ANCHOR.near.px),
      py: LEFT_ANCHOR.near.py + t * (LEFT_ANCHOR.far.py - LEFT_ANCHOR.near.py),
      side: "left" as const, slot: i,
    });
    slots.push({
      px: RIGHT_ANCHOR.near.px + t * (RIGHT_ANCHOR.far.px - RIGHT_ANCHOR.near.px),
      py: RIGHT_ANCHOR.near.py + t * (RIGHT_ANCHOR.far.py - RIGHT_ANCHOR.near.py),
      side: "right" as const, slot: i,
    });
  }
  return slots;
}

// 找最近槽位（已被占用的跳过，但允许同名覆盖）
function snapToSlot(px: number, py: number, occupied: Set<string>, selfKey: string): { px: number; py: number } {
  const slots = courtSlots();
  let best = null as { px: number; py: number } | null;
  let bestDist = Infinity;
  for (const s of slots) {
    const key = `${s.side}:${s.slot}`;
    if (occupied.has(key) && key !== selfKey) continue;
    const d = Math.hypot(s.px - px, s.py - py);
    if (d < bestDist) { bestDist = d; best = s; }
  }
  return best ?? { px, py };
}

// 默认坐标：从 near 开始，每人占一格，紧挨着排不留空
const COURT_SLOT_STEP = 1 / (COURT_SLOTS_PER_ROW - 1);  // 相邻槽间距（百分比t）

function defaultCourtPct(index: number, total: number): { px: number; py: number } {
  const leftCount = Math.ceil(total / 2);
  const isLeft = index < leftCount;
  const posInRow = isLeft ? index : index - leftCount;
  const anchor = isLeft ? LEFT_ANCHOR : RIGHT_ANCHOR;
  const t = posInRow * COURT_SLOT_STEP;  // 从槽0开始连续，不跳格
  return {
    px: anchor.near.px + t * (anchor.far.px - anchor.near.px),
    py: anchor.near.py + t * (anchor.far.py - anchor.near.py),
  };
}

// 坐标存百分比（0-1），持久化到服务端 db（按存档隔离）
async function loadCourtPos(): Promise<Record<string, { px: number; py: number }>> {
  try {
    const r = await fetch("/api/court_layout");
    if (!r.ok) return {};
    const d = await r.json();
    return JSON.parse(d.layout || "{}");
  } catch { return {}; }
}
function saveCourtPos(pos: Record<string, { px: number; py: number }>) {
  fetch("/api/court_layout", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ layout: JSON.stringify(pos) }),
  }).catch(() => {});
}

function MinisterCardList({
  list,
  portraitPrefix,
  selectedMinister,
  emptyNote,
  onOpenChat,
  onUploadPortrait,
  courtMode = false,
}: {
  list: Minister[];
  portraitPrefix: string;
  selectedMinister: string;
  emptyNote: string;
  onOpenChat: (minister: Minister) => void;
  onUploadPortrait?: (ministerName: string, file: File) => Promise<void>;
  courtMode?: boolean;
}) {
  const containerRef = React.useRef<HTMLDivElement>(null);
  const [positions, setPositions] = React.useState<Record<string, { px: number; py: number }>>({});
  const savedPosRef = React.useRef<Record<string, { px: number; py: number }> | null>(null);
  const dragging = React.useRef<{ name: string; startMX: number; startMY: number; startPX: number; startPY: number } | null>(null);
  const didDrag = React.useRef(false);

  // 固定职位 → 固定槽位（由 office 文字推导：office 逗号分项里命中即占该槽）
  const FIXED_SLOTS: { role: string; side: "left" | "right"; slot: number }[] = [
    { role: "首辅",    side: "left",  slot: 0 },
    { role: "次辅",    side: "right", slot: 0 },
    { role: "吏部尚书", side: "left",  slot: 1 },
    { role: "户部尚书", side: "right", slot: 1 },
    { role: "礼部尚书", side: "left",  slot: 2 },
    { role: "兵部尚书", side: "right", slot: 2 },
    { role: "刑部尚书", side: "left",  slot: 3 },
    { role: "工部尚书", side: "right", slot: 3 },
  ];

  // 从 office 字符串推导固定席位：逗号切分，任一分项精确等于某固定职名即占该槽。
  // 南京XX尚书是留都缺，不占京职槽——精确匹配自然排除（分项是「南京兵部尚书」≠「兵部尚书」）。
  function roleFromOffice(office: string): string {
    const parts = (office || "").split(",").map((s) => s.trim());
    const fs = FIXED_SLOTS.find((f) => parts.includes(f.role));
    return fs ? fs.role : "";
  }

  function fixedSlotFor(role: string): { px: number; py: number } | null {
    if (!role) return null;
    const allSlots = courtSlots();
    const fs = FIXED_SLOTS.find((f) => f.role === role);
    if (!fs) return null;
    const s = allSlots.find((sl) => sl.side === fs.side && sl.slot === fs.slot);
    return s ? { px: s.px, py: s.py } : null;
  }

  // 拖动覆盖坐标只加载一次。list 变化只重排，不重 fetch。
  const listKey = list.map((m) => m.name).join("|");
  React.useEffect(() => {
    let cancelled = false;
    const arrange = (saved: Record<string, { px: number; py: number }>) => {
      if (cancelled) return;
      const allSlots = courtSlots();
      const next: Record<string, { px: number; py: number }> = {};
      const usedSlots = new Set<string>();

      list.forEach((m) => {
        const role = roleFromOffice(m.office || "");
        const fixed = fixedSlotFor(role);
        if (fixed) {
          next[m.name] = fixed;
          const fs = FIXED_SLOTS.find((f) => f.role === role);
          if (fs) usedSlots.add(`${fs.side}:${fs.slot}`);
        }
      });

      list.forEach((m) => {
        if (next[m.name]) return;
        if (saved[m.name]) {
          const cur = saved[m.name];
          let best = allSlots.find((s) => !usedSlots.has(`${s.side}:${s.slot}`)) ?? allSlots[0];
          let bestD = Infinity;
          for (const s of allSlots) {
            if (usedSlots.has(`${s.side}:${s.slot}`)) continue;
            const d = Math.hypot(s.px - cur.px, s.py - cur.py);
            if (d < bestD) { bestD = d; best = s; }
          }
          usedSlots.add(`${best.side}:${best.slot}`);
          next[m.name] = { px: best.px, py: best.py };
        } else {
          const slot = allSlots.find((s) => !usedSlots.has(`${s.side}:${s.slot}`));
          if (slot) {
            usedSlots.add(`${slot.side}:${slot.slot}`);
            next[m.name] = { px: slot.px, py: slot.py };
          } else {
            next[m.name] = { px: 0.5, py: 0.532 };
          }
        }
      });
      setPositions(next);
    };

    if (savedPosRef.current !== null) {
      arrange(savedPosRef.current);
    } else {
      loadCourtPos().then((saved) => {
        savedPosRef.current = saved;
        arrange(saved);
      });
    }
    return () => { cancelled = true; };
  }, [listKey]);

  const onMouseDown = (e: React.MouseEvent, name: string) => {
    if ((e.target as HTMLElement).closest(".portrait-upload-btn")) return;
    e.preventDefault();
    const pos = positions[name] || { px: 0.5, py: 0.8 };
    dragging.current = { name, startMX: e.clientX, startMY: e.clientY, startPX: pos.px, startPY: pos.py };
    didDrag.current = false;

    const onMove = (ev: MouseEvent) => {
      if (!dragging.current) return;
      const dx = ev.clientX - dragging.current.startMX;
      const dy = ev.clientY - dragging.current.startMY;
      if (Math.abs(dx) > 3 || Math.abs(dy) > 3) didDrag.current = true;
      const el = containerRef.current;
      if (!el) return;
      const { width, height } = el.getBoundingClientRect();
      // 拖动增量转百分比
      const npx = Math.max(0, Math.min(1, dragging.current.startPX + dx / width));
      const npy = Math.max(0, Math.min(1, dragging.current.startPY + dy / height));
      setPositions((prev) => {
        const next = { ...prev, [dragging.current!.name]: { px: npx, py: npy } };
        savedPosRef.current = next;
        saveCourtPos(next);
        return next;
      });
    };
    const onUp = () => {
      if (dragging.current && didDrag.current) {
        // 松手时吸附到最近槽位
        const dragName = dragging.current.name;
        setPositions((prev) => {
          const cur = prev[dragName];
          if (!cur) return prev;
          // 已占槽位（其他大臣）
          const occupied = new Set<string>();
          // 找吸附目标
          const snapped = snapToSlot(cur.px, cur.py, occupied, "");
          const next = { ...prev, [dragName]: snapped };
          savedPosRef.current = next;
          saveCourtPos(next);
          return next;
        });
      }
      dragging.current = null;
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  };

  if (!list.length) return <div className={courtMode ? "minister-list minister-list-court" : "minister-list"}><div className="empty-note">{emptyNote}</div></div>;

  // 非朝班模式（全部tab）：普通网格
  if (!courtMode) {
    return (
      <div className="minister-list">
        {list.map((minister) => {
          const isCustom = minister.portrait_id?.startsWith("custom:");
          const dedicated = isCustom
            ? `/portraits/custom/${encodeURIComponent(minister.name)}?t=${cacheBust(minister.portrait_id!)}`
            : `/portraits/${portraitPrefix}${minister.id ?? minister.name}.png`;
          const poolFallback = !isCustom && minister.portrait_id ? `/portraits/${minister.portrait_id}.png` : undefined;
          const ousted = minister.status !== "active";
          return (
            <button key={minister.name}
              className={`minister-card ${selectedMinister === minister.name ? "selected" : ""} ${ousted ? "ousted" : ""}`}
              onClick={() => onOpenChat(minister)}>
              <div className="minister-card-portrait-wrap">
                <MinisterPortrait primary={dedicated} fallback={poolFallback} name={minister.name} />
                {onUploadPortrait && <PortraitUploadButton ministerName={minister.name} onUpload={onUploadPortrait} />}
              </div>
              <div className="minister-card-info">
                <div className="minister-card-top">
                  <span className="minister-name">{minister.name}</span>
                  {ousted && <span className={`minister-status status-${minister.status}`}>{minister.status_label}</span>}
                  {minister.office && <span className="minister-office">{minister.office}</span>}
                </div>
                <span className="minister-bio">{minister.summary}</span>
              </div>
              {minister.favorite && <Star className="favorite-mark" size={13} />}
            </button>
          );
        })}
      </div>
    );
  }

  return (
    <div className="minister-list minister-list-court" ref={containerRef}>
      {list.map((minister) => {
        const isCustom = minister.portrait_id?.startsWith("custom:");
        const dedicated = isCustom
          ? `/portraits/custom/${encodeURIComponent(minister.name)}?t=${cacheBust(minister.portrait_id!)}`
          : `/portraits/${portraitPrefix}${minister.id ?? minister.name}.png`;
        const poolFallback = !isCustom && minister.portrait_id
          ? `/portraits/${minister.portrait_id}.png`
          : undefined;
        const ousted = minister.status !== "active";
        const pct = positions[minister.name];
        // 透视缩放：py=0最远最小，py=1最近最大
        const perspScale = pct ? 0.38 + 0.62 * pct.py : 1;
        // 卡片宽用 vh 单位（CSS），这里只控制 scale
        return (
          <button
            key={minister.name}
            className={`minister-card ${selectedMinister === minister.name ? "selected" : ""} ${ousted ? "ousted" : ""}`}
            style={pct ? {
              position: "absolute",
              left: `${pct.px * 100}%`,
              top: `${pct.py * 100}%`,
              cursor: "grab",
              transform: `scale(${perspScale.toFixed(3)})`,
              transformOrigin: "bottom center",
              zIndex: Math.round(pct.py * 1000),
            } : { visibility: "hidden" }}
            onMouseDown={(e) => onMouseDown(e, minister.name)}
            onClick={(e) => { if (didDrag.current) { e.preventDefault(); return; } onOpenChat(minister); }}
          >
            <div className="minister-card-portrait-wrap">
              <MinisterPortrait primary={dedicated} fallback={poolFallback} name={minister.name} />
              {onUploadPortrait && (
                <PortraitUploadButton ministerName={minister.name} onUpload={onUploadPortrait} />
              )}
            </div>
            <div className="minister-card-info">
              <div className="minister-card-top">
                <span className="minister-name">{minister.name}</span>
                {ousted && <span className={`minister-status status-${minister.status}`}>{minister.status_label}</span>}
                {minister.office && <span className="minister-office">{minister.office}</span>}
              </div>
              <span className="minister-bio">{minister.summary}</span>
            </div>
            {minister.favorite && <Star className="favorite-mark" size={13} />}
          </button>
        );
      })}
    </div>
  );
}

// 自定义立绘文件名固定（一人一图），故按 portrait_id 之外另用上传时间戳刷缓存。
const _portraitBust: Record<string, number> = {};
function cacheBust(key: string): number {
  if (!_portraitBust[key]) _portraitBust[key] = Date.now();
  return _portraitBust[key];
}

function PortraitUploadButton({
  ministerName,
  onUpload,
}: {
  ministerName: string;
  onUpload: (ministerName: string, file: File) => Promise<void>;
}) {
  const inputRef = React.useRef<HTMLInputElement>(null);
  const [busy, setBusy] = React.useState(false);
  return (
    <>
      <button
        type="button"
        className="portrait-upload-btn"
        title="上传立绘"
        disabled={busy}
        onClick={(e) => {
          e.stopPropagation();  // 别触发卡片的召见
          inputRef.current?.click();
        }}
      >
        <Upload size={13} />
      </button>
      <input
        ref={inputRef}
        type="file"
        accept="image/png,image/jpeg,image/webp"
        style={{ display: "none" }}
        onClick={(e) => e.stopPropagation()}
        onChange={async (e) => {
          const file = e.target.files?.[0];
          e.target.value = "";  // 允许重选同一文件
          if (!file) return;
          setBusy(true);
          try {
            // 立即刷该人物缓存键，loadState 回来后新图不被旧缓存挡住。
            _portraitBust[`custom:${ministerName}`] = Date.now();
            await onUpload(ministerName, file);
          } catch (err) {
            window.alert(`上传失败：${(err as Error).message}`);
          } finally {
            setBusy(false);
          }
        }}
      />
    </>
  );
}

function RightNavBar({
  onToggleCourt,
  onToggleHarem,
  onToggleArmy,
  onToggleRegion,
  onToggleBuilding,
  onToggleEconomy,
  onToggleAppointment,
  onOpenLongGoals,
  activeDrawer,
}: {
  onToggleCourt: () => void;
  onToggleHarem: () => void;
  onToggleArmy: () => void;
  onToggleRegion: () => void;
  onToggleBuilding: () => void;
  onToggleEconomy: () => void;
  onToggleAppointment: () => void;
  onOpenLongGoals: () => void;
  activeDrawer: string;
}) {
  const items = [
    { key: "court", label: "政", title: "朝堂·召见大臣", onClick: onToggleCourt },
    { key: "harem", label: "内", title: "后宫", onClick: onToggleHarem },
    { key: "army", label: "兵", title: "军队列表", onClick: onToggleArmy },
    { key: "region", label: "省", title: "省份列表", onClick: onToggleRegion },
    { key: "building", label: "工", title: "建筑列表", onClick: onToggleBuilding },
    { key: "economy", label: "户", title: "经济面板", onClick: onToggleEconomy },
    { key: "appointment", label: "吏", title: "官员任免", onClick: onToggleAppointment },
  ];
  return (
    <nav className="right-nav-bar" aria-label="六部入口">
      {items.map((item) => (
        <button
          key={item.key}
          className={`right-nav-btn${activeDrawer === item.key ? " active" : ""}`}
          title={item.title}
          aria-label={item.title}
          onClick={item.onClick}
        >
          {item.label}
        </button>
      ))}
      <button
        className="right-nav-btn right-nav-btn-goal"
        title="长期目标"
        aria-label="大明长期目标"
        onClick={onOpenLongGoals}
      >
        目
      </button>
    </nav>
  );
}

function RightDrawer({
  open,
  onClose,
  title,
  icon,
  children,
  extraClass,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  icon: React.ReactNode;
  children: React.ReactNode;
  extraClass?: string;
}) {
  return (
    <>
      {open && <button className="drawer-scrim" aria-label="收起" onClick={onClose} />}
      <aside className={`right-drawer ${extraClass || ""} ${open ? "open" : ""}`}>
        <div className="right-drawer-brand">
          <div className="panel-title">
            {icon}
            <span>{title}</span>
          </div>
          <button className="icon-button" aria-label="收起" onClick={onClose}><X size={16} /></button>
        </div>
        <div className="right-drawer-body">
          {children}
        </div>
      </aside>
    </>
  );
}

function ArmyDrawer({
  armies,
  open,
  selectedArmyId,
  onSelectArmy,
  onClose,
}: {
  armies: Army[];
  open: boolean;
  selectedArmyId: string;
  onSelectArmy: (id: string) => void;
  onClose: () => void;
}) {
  const [q, setQ] = React.useState("");
  const mingArmies = armies.filter((a) => (a.owner_power || "ming") === "ming");
  const filtered = q ? mingArmies.filter((a) => a.name.includes(q) || a.station.includes(q) || a.commander.includes(q)) : mingArmies;
  const selected = mingArmies.find((a) => a.id === selectedArmyId) || null;
  const arrearsTone = (army: Army) => {
    const maint = army.maintenance_per_turn || 1;
    const months = army.arrears / maint;
    if (months >= 3) return "danger";
    if (months >= 1) return "warn";
    return "";
  };
  return (
    <RightDrawer open={open} onClose={onClose} title="军队" icon={<Swords size={17} />} extraClass="right-drawer-army">
      <div className="right-drawer-search">
        <input className="right-drawer-search-input" placeholder="搜索番号/驻地/统帅…" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      <div className="right-drawer-list">
        {filtered.map((army) => (
          <button
            key={army.id}
            className={`right-drawer-row${selectedArmyId === army.id ? " selected" : ""} ${arrearsTone(army)}`}
            onClick={() => onSelectArmy(army.id === selectedArmyId ? "" : army.id)}
          >
            <span className="right-drawer-row-name">{army.name}</span>
            <span className="right-drawer-row-meta">
              {army.manpower}兵 · {army.station}
            </span>
          </button>
        ))}
        {!filtered.length && <div className="empty-note">{q ? "无匹配结果。" : "暂无大明军队记录。"}</div>}
      </div>
      {selected && (
        <div className="right-drawer-detail">
          <div className="right-drawer-detail-title">
            {selected.name}
            <button className="right-drawer-detail-close" onClick={() => onSelectArmy("")} aria-label="关闭详情"><X size={14} /></button>
          </div>
          <table className="intel-table">
            <tbody>
              <tr><th>驻地</th><td>{selected.station}</td><th>战区</th><td>{selected.theater}</td></tr>
              <tr><th>统帅</th><td>{selected.commander || "—"}</td><th>兵种</th><td>{selected.troop_type}</td></tr>
              <tr><th>兵力</th><td>{selected.manpower}</td><th>月饷</th><td>{selected.maintenance_per_turn}万</td></tr>
              <tr><th>士气</th><td>{selected.morale}</td><th>操练</th><td>{selected.training}</td></tr>
              <tr><th>军械</th><td>{selected.equipment}</td><th>补给</th><td>{selected.supply}</td></tr>
              <tr><th>机动</th><td>{selected.mobility}</td><th>忠诚</th><td>{selected.loyalty}</td></tr>
              <tr><th>欠饷</th><td colSpan={3}>
                {selected.arrears > 0
                  ? `${selected.arrears}万两（≈${(selected.arrears / (selected.maintenance_per_turn || 1)).toFixed(1)}月）`
                  : "无欠饷"}
              </td></tr>
              <tr><th>状态</th><td colSpan={3}>{selected.status}</td></tr>
            </tbody>
          </table>
        </div>
      )}
    </RightDrawer>
  );
}

function RegionDrawer({
  regions,
  open,
  selectedRegionId,
  onSelectRegion,
  onClose,
}: {
  regions: Region[];
  open: boolean;
  selectedRegionId: string;
  onSelectRegion: (id: string) => void;
  onClose: () => void;
}) {
  const [q, setQ] = React.useState("");
  const mingRegions = regions.filter((r) => (r.controlled_by || "ming") === "ming");
  const filtered = q ? mingRegions.filter((r) => r.name.includes(q)) : mingRegions;
  const selected = mingRegions.find((r) => r.id === selectedRegionId) || null;
  const regionTone = (r: Region) => {
    if (r.unrest >= 70) return "danger";
    if (r.unrest >= 45) return "warn";
    return "";
  };
  return (
    <RightDrawer open={open} onClose={onClose} title="省份" icon={<MapPinned size={17} />} extraClass="right-drawer-region">
      <div className="right-drawer-search">
        <input className="right-drawer-search-input" placeholder="搜索省份名…" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      <div className="right-drawer-list">
        {filtered.map((r) => (
          <button
            key={r.id}
            className={`right-drawer-row${selectedRegionId === r.id ? " selected" : ""} ${regionTone(r)}`}
            onClick={() => onSelectRegion(r.id === selectedRegionId ? "" : r.id)}
          >
            <span className="right-drawer-row-name">{r.name}</span>
            <span className="right-drawer-row-meta">
              动乱{r.unrest} · 月税{r.tax_per_turn}万
            </span>
          </button>
        ))}
        {!filtered.length && <div className="empty-note">{q ? "无匹配结果。" : "暂无大明省份记录。"}</div>}
      </div>
      {selected && (
        <div className="right-drawer-detail">
          <div className="right-drawer-detail-title">
            {selected.name}
            <button className="right-drawer-detail-close" onClick={() => onSelectRegion("")} aria-label="关闭详情"><X size={14} /></button>
          </div>
          <table className="intel-table">
            <tbody>
              <tr><th>人口</th><td>{selected.population}万</td><th>田亩</th><td>{selected.registered_land}万亩</td></tr>
              <tr><th>民心</th><td>{selected.public_support}</td><th>动乱</th><td>{selected.unrest}</td></tr>
              <tr><th>粮食</th><td>{selected.grain_security}</td><th>月税</th><td>{selected.tax_per_turn}万</td></tr>
              <tr><th>士绅阻力</th><td>{selected.gentry_resistance}</td><th>边防压力</th><td>{selected.military_pressure}</td></tr>
              <tr><th>天灾</th><td colSpan={3}>{selected.natural_disaster}</td></tr>
              <tr><th>人祸</th><td colSpan={3}>{selected.human_disaster}</td></tr>
              <tr><th>状况</th><td colSpan={3}>{selected.status}</td></tr>
            </tbody>
          </table>
        </div>
      )}
    </RightDrawer>
  );
}

function BuildingDrawer({
  regions,
  mapNodes,
  open,
  onClose,
}: {
  regions: Region[];
  mapNodes: MapNode[];
  open: boolean;
  onClose: () => void;
}) {
  const allBuildings: (Building & { regionName: string })[] = [];
  for (const node of mapNodes) {
    if (!node.buildings) continue;
    const regionName = node.region?.name || node.label || node.id;
    for (const b of node.buildings) {
      allBuildings.push({ ...b, regionName });
    }
  }
  const [filterRegion, setFilterRegion] = React.useState("");
  const [q, setQ] = React.useState("");
  const regionNames = Array.from(new Set(allBuildings.map((b) => b.regionName)));
  const filtered = allBuildings
    .filter((b) => !filterRegion || b.regionName === filterRegion)
    .filter((b) => !q || b.name.includes(q) || b.category.includes(q));
  return (
    <RightDrawer open={open} onClose={onClose} title="建筑" icon={<Landmark size={17} />} extraClass="right-drawer-building">
      <div className="right-drawer-search">
        <input className="right-drawer-search-input" placeholder="搜索建筑名/类别…" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      <div className="right-drawer-filter">
        <select
          value={filterRegion}
          onChange={(e) => setFilterRegion(e.target.value)}
          className="right-drawer-select"
        >
          <option value="">全部省份</option>
          {regionNames.map((n) => <option key={n} value={n}>{n}</option>)}
        </select>
      </div>
      <div className="right-drawer-list">
        {filtered.map((b) => (
          <div key={b.id} className="right-drawer-row right-drawer-row-building">
            <span className="right-drawer-row-name">{b.name}</span>
            <span className="right-drawer-row-meta">{b.regionName} · {b.category} Lv{b.level}</span>
            <span className="right-drawer-row-sub">
              完好{b.condition} · 维护{b.maintenance}万/月
              {b.output_metric ? ` · ${b.output_metric}+${b.output_amount}` : ""}
            </span>
          </div>
        ))}
        {!filtered.length && <div className="empty-note">{q || filterRegion ? "无匹配结果。" : "暂无建筑记录。"}</div>}
      </div>
    </RightDrawer>
  );
}

function EconomyDrawer({
  state,
  open,
  onClose,
}: {
  state: GameState;
  open: boolean;
  onClose: () => void;
}) {
  const [tab, setTab] = React.useState<"国库" | "内库">("国库");
  const [q, setQ] = React.useState("");
  const budget = state.budget[tab];
  const matchItem = (name: string) => !q || name.includes(q);
  return (
    <RightDrawer open={open} onClose={onClose} title="经济" icon={<ScrollText size={17} />} extraClass="right-drawer-economy">
      <div className="segmented right-drawer-segmented">
        {(["国库", "内库"] as const).map((t) => (
          <button key={t} className={tab === t ? "active" : ""} onClick={() => setTab(t)}>{t}</button>
        ))}
      </div>
      <div className="right-drawer-search">
        <input className="right-drawer-search-input" placeholder="搜索收支项…" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      <div className="right-drawer-economy-summary">
        <span>余额 <b>{formatMoney(budget.balance)}</b></span>
        <span className={budget.net >= 0 ? "income" : "expense"}>
          月净 <b>{formatSignedMoney(budget.net)}</b>
        </span>
      </div>
      <div className="right-drawer-list">
        <div className="right-drawer-section-title">固定收入</div>
        {budget.income.filter((item) => matchItem(item.name)).map((item) => (
          <div key={`in-${item.name}`} className="right-drawer-budget-row">
            <span>{item.name}</span>
            <b className="income">+{formatMoney(item.amount)}</b>
          </div>
        ))}
        <div className="right-drawer-section-title">固定支出</div>
        {budget.expense.filter((item) => matchItem(item.name)).map((item) => (
          <div key={`ex-${item.name}`} className="right-drawer-budget-row">
            <span>{item.name}</span>
            <b className="expense">-{formatMoney(item.amount)}</b>
          </div>
        ))}
        {budget.movements.filter((m) => matchItem(m.category || m.reason)).length > 0 && (
          <>
            <div className="right-drawer-section-title">本月一次性入账</div>
            {budget.movements.filter((m) => matchItem(m.category || m.reason)).map((m, i) => (
              <div key={`mv-${i}`} className="right-drawer-budget-row">
                <span>{m.category || m.reason}</span>
                <b className={m.delta >= 0 ? "income" : "expense"}>{formatSignedMoney(m.delta)}</b>
              </div>
            ))}
          </>
        )}
      </div>
    </RightDrawer>
  );
}

function AppointmentDrawer({
  ministers,
  open,
  onOpenChat,
  onClose,
}: {
  ministers: Minister[];
  open: boolean;
  onOpenChat: (minister: Minister) => void;
  onClose: () => void;
}) {
  const [q, setQ] = React.useState("");
  const offices = ["内阁", "吏部", "户部", "礼部", "兵部", "刑部", "工部"];
  const byOffice = new Map<string, Minister[]>();
  for (const office of offices) byOffice.set(office, []);
  byOffice.set("其他", []);
  for (const m of ministers) {
    if ((m.power_id || "ming") !== "ming") continue;
    if (m.status !== "active") continue;
    if (q && !m.name.includes(q) && !(m.office || "").includes(q) && !(m.office_type || "").includes(q)) continue;
    const matched = offices.find((o) => (m.office_type || "").includes(o));
    const key = matched || "其他";
    byOffice.get(key)!.push(m);
  }
  return (
    <RightDrawer open={open} onClose={onClose} title="官员任免" icon={<Star size={17} />} extraClass="right-drawer-appointment">
      <div className="right-drawer-search">
        <input className="right-drawer-search-input" placeholder="搜索姓名/职位…" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      <div className="right-drawer-list">
        {[...offices, "其他"].map((office) => {
          const group = byOffice.get(office) || [];
          if (!group.length) return null;
          return (
            <div key={office}>
              <div className="right-drawer-section-title">{office}</div>
              {group.map((m) => (
                <button
                  key={m.name}
                  className="right-drawer-row right-drawer-row-minister"
                  onClick={() => onOpenChat(m)}
                >
                  <div className="right-drawer-minister-row">
                    <span className="right-drawer-row-name">{m.name}</span>
                    <span className="right-drawer-minister-office">{m.office || m.office_type}</span>
                  </div>
                </button>
              ))}
            </div>
          );
        })}
        {[...offices, "其他"].every((o) => !(byOffice.get(o) || []).length) && (
          <div className="empty-note">{q ? "无匹配结果。" : "暂无在职官员。"}</div>
        )}
      </div>
    </RightDrawer>
  );
}

function CourtDrawer({
  state: _state,
  ministers,
  ministerGroup,
  selectedMinister,
  open,
  onGroupChange,
  onClose,
  onOpenChat,
  onUploadPortrait,
}: {
  state: GameState;
  ministers: Minister[];
  ministerGroup: string;
  selectedMinister: string;
  open: boolean;
  onGroupChange: (group: string) => void;
  onClose: () => void;
  onOpenChat: (minister: Minister) => void;
  onUploadPortrait: (ministerName: string, file: File) => Promise<void>;
}) {
  const [q, setQ] = React.useState("");
  const filtered = q ? ministers.filter((m) => m.name.includes(q) || (m.office || "").includes(q)) : ministers;
  return (
    <>
      {open && <button className="drawer-scrim" aria-label="收起" onClick={onClose} />}
      <aside className={`court-drawer ${open ? "open" : ""}`}>
        <div className="drawer-brand">
          <div className="panel-title">
            <Landmark size={17} />
            <span>朝堂</span>
          </div>
          <button className="icon-button" aria-label="收起" onClick={onClose}><X size={16} /></button>
        </div>
        <div className="segmented">
          {["内阁+六部", "收藏", "在职", "全部"].map((group) => (
            <button
              className={ministerGroup === group ? "active" : ""}
              key={group}
              onClick={() => onGroupChange(group)}
            >
              {group}
            </button>
          ))}
        </div>
        <div className="right-drawer-search court-search">
          <input className="right-drawer-search-input" placeholder="搜索姓名/职位…" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <MinisterCardList
          list={filtered}
          portraitPrefix="minister_"
          selectedMinister={selectedMinister}
          emptyNote={q ? "无匹配大臣。" : "此栏暂无可召见大臣。"}
          onOpenChat={onOpenChat}
          courtMode={ministerGroup === "内阁+六部" || ministerGroup === "收藏"}
          onUploadPortrait={onUploadPortrait}
        />
      </aside>
    </>
  );
}

function HaremDrawer({
  consorts,
  haremGroup,
  selectedMinister,
  open,
  onGroupChange,
  onClose,
  onOpenChat,
  onUploadPortrait,
}: {
  consorts: Minister[];
  haremGroup: string;
  selectedMinister: string;
  open: boolean;
  onGroupChange: (group: string) => void;
  onClose: () => void;
  onOpenChat: (minister: Minister) => void;
  onUploadPortrait: (ministerName: string, file: File) => Promise<void>;
}) {
  const [q, setQ] = React.useState("");
  const filtered = q ? consorts.filter((c) => c.name.includes(q)) : consorts;
  return (
    <>
      {open && <button className="drawer-scrim" aria-label="收起" onClick={onClose} />}
      <aside className={`court-drawer harem-drawer overlay-panel ${open ? "open" : ""}`}>
        <div className="drawer-brand">
          <div className="panel-title">
            <Crown size={17} />
            <span>后宫</span>
          </div>
          <button className="icon-button" aria-label="收起" onClick={onClose}><X size={16} /></button>
        </div>
        <div className="segmented">
          {["全部", "收藏"].map((group) => (
            <button
              className={haremGroup === group ? "active" : ""}
              key={group}
              onClick={() => onGroupChange(group)}
            >
              {group}
            </button>
          ))}
        </div>
        <div className="right-drawer-search court-search">
          <input className="right-drawer-search-input" placeholder="搜索姓名…" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <MinisterCardList
          list={filtered}
          portraitPrefix="consort_"
          selectedMinister={selectedMinister}
          emptyNote={q ? "无匹配结果。" : "后宫暂无可召见之人。"}
          onOpenChat={onOpenChat}
          onUploadPortrait={onUploadPortrait}
        />
      </aside>
    </>
  );
}

// ── 新 HUD 底图坑位坐标（相对底图百分比，见 web/public/ui/exact/hud-slots.json）──
const HUD_BG = "/ui/exact/auto-code-image-11685.png";
const HUD_SLOTS = {
  顶栏: {
    年月: { left: "9.6%", top: "6.31%" },
    国库: { left: "25.83%", top: "6.32%" },
    内库: { left: "42.33%", top: "6.35%" },
    民心: { left: "58.63%", top: "6.06%" },
    皇威: { left: "78.07%", top: "6.56%" },
  },
  导航: {
    政: { left: "93.36%", top: "19.46%" },
    吏部: { left: "93.38%", top: "23.85%" },
    省份: { left: "93.55%", top: "33.86%" },
    兵部: { left: "93.71%", top: "38.14%" },
    户部: { left: "94.12%", top: "48.09%" },
    工部: { left: "94.13%", top: "51.64%" },
    礼部: { left: "94.22%", top: "60.33%" },
    后宫: { left: "94.36%", top: "68.81%" },
    菜单: { left: "94.56%", top: "76.32%" },
  },
  命令: {
    奏疏: { left: "7.53%", top: "71.89%", width: "16.78%", height: "15.79%" },
    邸报: { left: "25.78%", top: "70.85%", width: "16.19%", height: "15.78%" },
    密令: { left: "45.75%", top: "70.02%", width: "12.32%", height: "16.13%" },
    史册: { left: "62.51%", top: "69.99%", width: "11.96%", height: "16.43%" },
    拟诏: { left: "76.57%", top: "62.97%", width: "16.29%", height: "27.88%" },
  },
  地图四角: { tl: [17.89, 14.9], tr: [86.95, 14.9], br: [92.13, 76.61], bl: [13.9, 76.61] },
  局势四角: { tl: [3.14, 24.09], tr: [15.06, 24.09], br: [14.36, 47.95], bl: [1.6, 47.95] },
} as const;

// 四角 [x%,y%] → matrix3d，把单位正方形(0..1)映射到任意四边形（透视）
function quadToMatrix3d(
  w: number, h: number,
  tl: readonly number[], tr: readonly number[], br: readonly number[], bl: readonly number[]
): string {
  // 目标点用像素（相对容器 w×h）
  const px = (p: readonly number[]) => [(p[0] / 100) * w, (p[1] / 100) * h];
  const [x0, y0] = px(tl), [x1, y1] = px(tr), [x2, y2] = px(br), [x3, y3] = px(bl);
  // 源单位矩形角: (0,0)(w,0)(w,h)(0,h) → 解 8 参数透视变换
  const src = [[0, 0], [w, 0], [w, h], [0, h]];
  const dst = [[x0, y0], [x1, y1], [x2, y2], [x3, y3]];
  const A: number[][] = [], b: number[] = [];
  for (let i = 0; i < 4; i++) {
    const [sx, sy] = src[i], [dx, dy] = dst[i];
    A.push([sx, sy, 1, 0, 0, 0, -sx * dx, -sy * dx]); b.push(dx);
    A.push([0, 0, 0, sx, sy, 1, -sx * dy, -sy * dy]); b.push(dy);
  }
  const h8 = solve8(A, b);
  const [a, bb, c, d, e, f, g, i] = h8;
  // CSS matrix3d 列主序
  return `matrix3d(${a},${d},0,${g}, ${bb},${e},0,${i}, 0,0,1,0, ${c},${f},0,1)`;
}
function solve8(A: number[][], b: number[]): number[] {
  // 高斯消元 8×8
  const n = 8, M = A.map((row, k) => [...row, b[k]]);
  for (let col = 0; col < n; col++) {
    let piv = col;
    for (let r = col + 1; r < n; r++) if (Math.abs(M[r][col]) > Math.abs(M[piv][col])) piv = r;
    [M[col], M[piv]] = [M[piv], M[col]];
    const pv = M[col][col] || 1e-9;
    for (let c = col; c <= n; c++) M[col][c] /= pv;
    for (let r = 0; r < n; r++) {
      if (r === col) continue;
      const factor = M[r][col];
      for (let c = col; c <= n; c++) M[r][c] -= factor * M[col][c];
    }
  }
  return M.map((row) => row[n]);
}

// 透视梯形容器：内部 stageW×stageH 的正放内容被 matrix3d 压成梯形
function QuadFrame({
  quad, stageW, stageH, baseW, baseH, children, className, style,
}: {
  quad: { tl: readonly number[]; tr: readonly number[]; br: readonly number[]; bl: readonly number[] };
  stageW: number; stageH: number; baseW: number; baseH: number;
  children: React.ReactNode; className?: string; style?: React.CSSProperties;
}) {
  // 正放内容的逻辑尺寸＝四角包围盒像素
  const xs = [quad.tl[0], quad.tr[0], quad.br[0], quad.bl[0]];
  const ys = [quad.tl[1], quad.tr[1], quad.br[1], quad.bl[1]];
  const left = (Math.min(...xs) / 100) * stageW;
  const top = (Math.min(...ys) / 100) * stageH;
  const w = ((Math.max(...xs) - Math.min(...xs)) / 100) * stageW;
  const h = ((Math.max(...ys) - Math.min(...ys)) / 100) * stageH;
  // 四角相对包围盒左上的局部坐标（百分比，喂 matrix3d）
  const rel = (p: readonly number[]) => [
    ((p[0] / 100) * stageW - left) / w * 100,
    ((p[1] / 100) * stageH - top) / h * 100,
  ];
  const m = quadToMatrix3d(w, h, rel(quad.tl), rel(quad.tr), rel(quad.br), rel(quad.bl));
  return (
    <div
      className={className}
      style={{
        position: "absolute", left, top, width: w, height: h,
        transform: m, transformOrigin: "0 0", ...style,
      }}
    >
      {children}
    </div>
  );
}

function TopStatusBar({
  state,
  onOpenState,
  onOpenMenu,
}: {
  state: GameState;
  onOpenState: () => void;
  onOpenMenu: () => void;
}) {
  const scoreKeys = ["民心", "皇威"];
  return (
    <>
    <header className="status-bar" aria-label="国势状态栏">
      <button className="status-emblem" onClick={onOpenState}>
        <img src="/icon_ming_emblem.png" alt="大明" className="emblem-art" />
        <span>{state.turn.year} 年 {state.turn.period} 月</span>
      </button>
      <i className="hud-divider" aria-hidden="true" />
      <div className="status-metrics">
        <BudgetHover accountName="国库" budget={state.budget["国库"]} />
        <BudgetHover accountName="内库" budget={state.budget["内库"]} />
        <i className="hud-divider" aria-hidden="true" />
        {scoreKeys.map((key) => (
          <span className={`status-pill ${scoreTone(state.metrics[key], false)}`} key={key}>
            {key} <b>{state.metrics[key]}</b>
          </span>
        ))}
        <i className="hud-divider" aria-hidden="true" />
        <button className="status-menu" onClick={onOpenMenu} aria-label="游戏菜单">
          <Menu size={16} />
          <span>菜单</span>
        </button>
      </div>
    </header>
    <LegacyBar legacies={state.legacies} />
    </>
  );
}

const LONG_GOAL_POSTERS = [
  { src: "/long_goal_ming.jpg", alt: "长期目标：让大明再续二百年" },
  { src: "/long_goal_tech.jpg", alt: "长期目标：科技树与文明延续" },
  { src: "/long_goal_modernity.jpg", alt: "长期目标：从王朝危机到现代文明" },
];

function LongGoalsModal({ onClose }: { onClose: () => void }) {
  const [index, setIndex] = React.useState(0);
  const goPrev = React.useCallback(() => {
    setIndex((current) => (current + LONG_GOAL_POSTERS.length - 1) % LONG_GOAL_POSTERS.length);
  }, []);
  const goNext = React.useCallback(() => {
    setIndex((current) => (current + 1) % LONG_GOAL_POSTERS.length);
  }, []);

  React.useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (event.key === "ArrowLeft") goPrev();
      if (event.key === "ArrowRight") goNext();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [goPrev, goNext]);

  const poster = LONG_GOAL_POSTERS[index];
  return (
    <section className="long-goal-layer" role="dialog" aria-modal="true" aria-label="大明长期目标">
      <div className="long-goal-scrim" onClick={onClose} />
      <button className="long-goal-close" aria-label="关闭弹窗" onClick={onClose}>
        <X size={30} />
      </button>
      <button className="long-goal-nav long-goal-nav-prev" aria-label="上一张长期目标图" onClick={goPrev}>
        <ChevronLeft size={34} />
      </button>
      <figure className="long-goal-poster">
        <img src={poster.src} alt={poster.alt} />
      </figure>
      <button className="long-goal-nav long-goal-nav-next" aria-label="下一张长期目标图" onClick={goNext}>
        <ChevronRight size={34} />
      </button>
      <div className="long-goal-dots" aria-label="长期目标图切换">
        {LONG_GOAL_POSTERS.map((item, itemIndex) => (
          <button
            key={item.src}
            className={itemIndex === index ? "active" : ""}
            aria-label={`切换到第 ${itemIndex + 1} 张长期目标图`}
            onClick={() => setIndex(itemIndex)}
          />
        ))}
      </div>
    </section>
  );
}

const LEGACY_FIELD_LABELS: Record<string, string> = {
  public_support: "民心", unrest: "动乱", gentry_resistance: "士绅阻力", military_pressure: "边防压力",
  tax_per_turn: "月税", grain_security: "粮食", corruption: "腐败度",
  morale: "士气", training: "训练", loyalty: "忠诚", supply: "补给", equipment: "装备",
  arrears: "欠饷", mobility: "机动",
};

function pctStr(v: number): string {
  return `${v > 0 ? "+" : ""}${v}%`;
}

// modifiers = {国库?:pct, 内库?:pct, regions?:{rid:{field:pct}}, armies?:{aid:{field:pct}}}
function formatLegacyEffect(eff: LegacyEffect): string {
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

function LegacyBar({ legacies }: { legacies: Legacy[] }) {
  const [open, setOpen] = React.useState(false);
  if (!legacies || legacies.length === 0) return null;
  return (
    <>
      <button
        className="legacy-bar"
        aria-label="现行帝国修正"
        onClick={() => setOpen(true)}
      >
        <span className="legacy-bar-label">帝国修正</span>
        <span className="legacy-bar-count">{legacies.length}</span>
      </button>
      {open && (
        <div className="legacy-modal-backdrop" onClick={() => setOpen(false)}>
          <div className="legacy-modal" onClick={(e) => e.stopPropagation()}>
            <div className="legacy-modal-head">
              <h3>现行帝国修正</h3>
              <button className="legacy-modal-close" onClick={() => setOpen(false)} aria-label="关闭">×</button>
            </div>
            <ul className="legacy-list">
              {legacies.map((lg) => (
                <li key={lg.id} className="legacy-item">
                  <div className="legacy-item-top">
                    <b>{lg.name}</b>
                    <span className="legacy-item-meta">
                      <span className="legacy-item-dur">{lg.remaining_months < 0 ? "永久" : `余 ${lg.remaining_months} 月`}</span>
                    </span>
                  </div>
                  <p className="legacy-item-eff">{lg.effect_text || formatLegacyEffect(lg.modifiers)}</p>
                  {lg.clear_condition && <p className="legacy-item-clear">消除条件：{lg.clear_condition}</p>}
                  {lg.narrative_hint && <p className="legacy-item-hint">{lg.narrative_hint}</p>}
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </>
  );
}

function BudgetHover({ accountName, budget }: { accountName: "国库" | "内库"; budget: BudgetAccount }) {
  const [open, setOpen] = React.useState(false);
  return (
    <span
      className={`budget-hover ${open ? "open" : ""}`}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
    >
      <button
        className="status-money budget-trigger"
        type="button"
        aria-label={`查看${accountName}固定收支`}
        onClick={() => setOpen((current) => !current)}
      >
        <span>{accountName} <b>{formatMoney(budget.balance)}</b></span>
        <small className={budget.net >= 0 ? "income" : "expense"}>月 {formatSignedMoney(budget.net)}</small>
      </button>
      <span className="budget-popover" role="tooltip">
        <span className="budget-popover-head">
          <b>{accountName}月度定额</b>
          <span className="budget-summary">
            <span><small>入</small><strong className="income">{formatMoney(budget.income_total)}</strong></span>
            <span><small>出</small><strong className="expense">{formatMoney(budget.expense_total)}</strong></span>
            <span><small>净</small><strong className={budget.net >= 0 ? "income" : "expense"}>{formatSignedMoney(budget.net)}</strong></span>
          </span>
        </span>
        <BudgetList title="固定收入" items={budget.income} />
        <BudgetList title="固定支出" items={budget.expense} expense />
        <BudgetMovementsList movements={budget.movements} total={budget.movements_total} />
      </span>
    </span>
  );
}

function BudgetMovementsList({ movements, total }: { movements: BudgetMovement[]; total: number }) {
  if (!movements.length) {
    return (
      <span className="budget-list">
        <span className="budget-list-title">本月一次性入账（上月末结算）</span>
        <span className="budget-row"><span><b>暂无</b><small>上月末未结算入出</small></span></span>
      </span>
    );
  }
  return (
    <span className="budget-list">
      <span className="budget-list-title">
        本月一次性入账（上月末结算）
        <small className={total >= 0 ? "income" : "expense"}>　合计 {formatSignedMoney(total)}</small>
      </span>
      {movements.map((m, idx) => {
        const sign = m.delta >= 0 ? "+" : "-";
        const cls = m.delta >= 0 ? "income" : "expense";
        return (
          <span className="budget-row" key={`mv-${idx}`}>
            <span>
              <b>{m.category || "—"}</b>
              <small>{m.reason}</small>
            </span>
            <strong className={cls}>{sign}{formatMoney(Math.abs(m.delta))}</strong>
          </span>
        );
      })}
    </span>
  );
}

function BudgetList({ title, items, expense = false }: { title: string; items: BudgetItem[]; expense?: boolean }) {
  return (
    <span className="budget-list">
      <span className="budget-list-title">{title}</span>
      {items.map((item) => (
        <span className="budget-row" key={`${title}-${item.name}`}>
          <span>
            <b>{item.name}</b>
            <small>{item.note}</small>
          </span>
          <strong className={expense ? "expense" : "income"}>{expense ? "-" : "+"}{formatMoney(item.amount)}</strong>
        </span>
      ))}
    </span>
  );
}

// 底部命令物件：透明扣图叠在木牌坑位上，带角标+说明
function CommandSlot({
  slotKey, img, badge, caption, sub, onClick,
}: {
  slotKey: keyof typeof HUD_SLOTS.命令;
  img: string; badge?: number; caption: string; sub: string; onClick: () => void;
}) {
  return (
    <button className="hud2-cmd" style={HUD_SLOTS.命令[slotKey]} onClick={onClick}
      aria-label={`${caption}：${sub}`}>
      <img className="hud2-cmd-img" src={`/ui/exact/cmd/${img}.png`} alt="" />
      {badge ? <span className="hud2-cmd-badge">{badge}</span> : null}
      <span className="hud2-cmd-caption"><b>{caption}</b><small>{sub}</small></span>
    </button>
  );
}

function BottomCommandBar({
  eventsCount,
  directivesCount,
  secretOrdersCount,
  onOpenMemorials,
  onOpenEdict,
  onOpenExtraction,
  onOpenHistory,
  onOpenSecretOrders,
}: {
  eventsCount: number;
  directivesCount: number;
  secretOrdersCount: number;
  onOpenMemorials: () => void;
  onOpenEdict: () => void;
  onOpenExtraction: () => void;
  onOpenHistory: () => void;
  onOpenSecretOrders: () => void;
}) {
  return (
    <div className="ui-stage">
      {/* 案板 + 图标 + 玉玺一体 */}
      <div className="anban-wrap">
        {/* 图标行：底部贴基准线向上生长 */}
        <nav className="bottom-command-bar" aria-label="朝政辅助操作">
          <button className="command-icon" onClick={onOpenMemorials} aria-label={`奏疏 ${eventsCount} 件待览`}>
            <img src="/ui/exact/zoushu.png" alt="" className="command-art" />
            {eventsCount ? <span className="command-badge">{eventsCount}</span> : null}
          </button>
          <button className="command-icon" onClick={onOpenExtraction} aria-label="邸报详明">
            <img src="/ui/exact/mingxi.png" alt="" className="command-art" />
          </button>
          <button className="command-icon" onClick={onOpenSecretOrders} aria-label={`密令 ${secretOrdersCount} 条进行中`}>
            <img src="/ui/exact/miling.png" alt="" className="command-art command-art-secret" />
            {secretOrdersCount ? <span className="command-badge command-badge-secret">{secretOrdersCount}</span> : null}
          </button>
          <button className="command-icon" onClick={onOpenHistory} aria-label="历代奏报">
            <img src="/ui/exact/lishi.png" alt="" className="command-art" />
          </button>
          <button className="edict-turn-button" onClick={onOpenEdict} aria-label={`诏书草案 ${directivesCount} 道待发`}>
            <span className="edict-turn-art">
              <img src="/ui/exact/nizhao.png" alt="" />
              {directivesCount ? <span className="command-badge edict-turn-badge">{directivesCount}</span> : null}
            </span>
          </button>
        </nav>
        {/* 文字行：贴在 bar 下方 */}
        <div className="bottom-caption-bar">
          <span className="command-caption"><b>奏疏</b><small>{eventsCount} 件待览</small></span>
          <span className="command-caption"><b>邸报详明</b><small>数项加减/账目明细</small></span>
          <span className="command-caption"><b>密令</b><small>{secretOrdersCount ? `${secretOrdersCount} 条进行中` : "暂无密令"}</small></span>
          <span className="command-caption"><b>史册</b><small>历代奏报/诏书</small></span>
          <span className="command-caption"><b>拟诏/结束回合</b><small>{directivesCount ? `${directivesCount} 道` : "本回合"}</small></span>
        </div>
      </div>
    </div>
  );
}

function FullscreenModal({
  title,
  subtitle,
  bgClass,
  onClose,
  children,
  headerExtra,
}: {
  title: string;
  subtitle: string;
  bgClass?: string;
  onClose: () => void;
  children: React.ReactNode;
  headerExtra?: React.ReactNode;
}) {
  return (
    <section className="fullscreen-layer" role="dialog" aria-modal="true" aria-label={title}>
      <div className="fullscreen-scrim" onClick={onClose} />
      <div className={`fullscreen-modal ${bgClass || ""}`}>
        <header className="modal-header">
          <div className="modal-title">
            <div>
              <h1>{title}</h1>
              <span>{subtitle}</span>
            </div>
          </div>
          <div className="modal-header-actions">
            {headerExtra}
            <button className="icon-button" aria-label="关闭弹窗" onClick={onClose}>
              <X size={18} />
            </button>
          </div>
        </header>
        {children}
      </div>
    </section>
  );
}

type ExtractionData = {
  turn: number;
  year: number;
  period: number;
  exists: boolean;
  extractor_output?: any;
};

function ReportModal({ report, onClose }: { report: string; onClose: () => void }) {
  return (
    <FullscreenModal title="月末奏疏" subtitle="推演结果" bgClass="modal-bg-state" onClose={onClose}>
      <article className="state-document modal-scroll">
        <div className="document-section">
          <pre className="memorial-text">{report}</pre>
        </div>
      </article>
    </FullscreenModal>
  );
}

function EndingModal({ ending, onClose }: { ending: EndingPayload; onClose: () => void }) {
  const lastTimeline = ending.timeline?.[ending.timeline.length - 1];
  const endingDate = lastTimeline ? `${lastTimeline.year}年${lastTimeline.period}月` : "终局";
  const timelineCount = ending.timeline?.length ?? 0;

  return (
    <FullscreenModal
      title="终章定论"
      subtitle="崇祯一朝，盖棺论定"
      bgClass="modal-bg-state modal-bg-ending"
      onClose={onClose}
    >
      <article className="state-document ending-document modal-scroll">
        <div className="ending-hero">
          <div className="ending-seal" aria-hidden="true">
            <Crown size={34} />
          </div>
          <div className="ending-hero-copy">
            <p>大明国史馆录</p>
            <h2>{ending.label}</h2>
            <span>{endingDate} · 第 {timelineCount || 1} 卷</span>
          </div>
        </div>

        <section className="ending-verdict-card" aria-label="结局总评">
          <div className="ending-section-kicker">
            <ScrollText size={17} />
            <span>国史编纂官总评</span>
          </div>
          <pre className="ending-summary-text">{ending.summary || "（无总评）"}</pre>
        </section>

        {ending.timeline && ending.timeline.length > 0 && (
          <section className="ending-chronicle" aria-label="逐月历程">
            <div className="ending-section-kicker">
              <Landmark size={17} />
              <span>崇祯一朝逐月历程</span>
            </div>
            <ol className="ending-timeline">
              {ending.timeline.map((it) => (
                <li key={it.turn} className="ending-timeline-item">
                  <div className="ending-timeline-date">
                    <b>{it.year}</b>
                    <span>{it.period}月</span>
                  </div>
                  <div className="ending-timeline-body">
                    {it.chapter ? (
                      <p className="ending-timeline-chapter">{it.chapter}</p>
                    ) : null}
                    {it.decree_brief ? (
                      <p className="ending-timeline-decree">诏：{it.decree_brief}</p>
                    ) : null}
                    {it.effect_brief ? (
                      <p className="ending-timeline-effect">效：{it.effect_brief}</p>
                    ) : null}
                  </div>
                </li>
              ))}
            </ol>
          </section>
        )}
      </article>
    </FullscreenModal>
  );
}

function SecretOrdersModal({
  orders,
  onClose,
  onOpenMinister,
}: {
  orders: SecretOrder[];
  onClose: () => void;
  onOpenMinister: (name: string) => void;
}) {
  const [tab, setTab] = React.useState<"active" | "pending_review" | "done" | "failed" | "all">("active");
  const [selectedOrder, setSelectedOrder] = React.useState<SecretOrder | null>(null);
  const statusLabel: Record<string, string> = {
    active: "进行中",
    pending_review: "待核议",
    done: "已完成",
    failed: "已失败",
    cancelled: "已撤销",
  };
  const statusCls: Record<string, string> = {
    active: "so-active",
    pending_review: "so-pending",
    done: "so-done",
    failed: "so-failed",
    cancelled: "so-cancelled",
  };
  const tabs: { key: typeof tab; label: string }[] = [
    { key: "active",         label: `进行中 (${orders.filter(o => o.status === "active").length})` },
    { key: "pending_review", label: `待核议 (${orders.filter(o => o.status === "pending_review").length})` },
    { key: "done",           label: `已完成 (${orders.filter(o => o.status === "done").length})` },
    { key: "failed",         label: `已失败 (${orders.filter(o => o.status === "failed").length})` },
    { key: "all",            label: `全部 (${orders.length})` },
  ];
  const visible = tab === "all" ? orders : orders.filter(o => o.status === tab);
  return (
    <FullscreenModal title="密令进度" subtitle={`共 ${orders.length} 条密令记录`} bgClass="modal-bg-edict" onClose={onClose}>
      <article className="state-document modal-scroll">
        <div className="so-tabs">
          {tabs.map(t => (
            <button key={t.key} className={`so-tab${tab === t.key ? " so-tab-active" : ""}`} onClick={() => setTab(t.key)}>
              {t.label}
            </button>
          ))}
        </div>
        <div className="secret-orders-list">
          {visible.length === 0 && <p className="so-empty">暂无此类密令。</p>}
          {visible.map((o) => (
            <button
              key={o.id}
              type="button"
              className={`secret-order-card secret-order-card-button ${statusCls[o.status] || ""}`}
              onClick={() => setSelectedOrder(o)}
            >
              <div className="so-header">
                <span className="so-title"><Lock size={13} />{o.title}</span>
                <span className={`so-status ${statusCls[o.status] || ""}`}>{statusLabel[o.status] || o.status}</span>
              </div>
              <div className="so-meta">第 {o.year_issued} 年 {o.period_issued} 月下令 · 承办：{o.minister_name}</div>
              <div className="so-open-hint">点击查看密令详情</div>
              {o.status === "active" && (
                <button
                  className="secondary-action so-goto"
                  onClick={(event) => {
                    event.stopPropagation();
                    onClose();
                    onOpenMinister(o.minister_name);
                  }}
                >
                  <MessageSquare size={13} />
                  召见 {o.minister_name}
                </button>
              )}
            </button>
          ))}
        </div>
      </article>
      {selectedOrder ? (
        <SecretOrderDetailDialog
          order={selectedOrder}
          statusLabel={statusLabel}
          statusCls={statusCls}
          onClose={() => setSelectedOrder(null)}
          onOpenMinister={(name) => {
            setSelectedOrder(null);
            onClose();
            onOpenMinister(name);
          }}
        />
      ) : null}
    </FullscreenModal>
  );
}

function SecretOrderDetailDialog({
  order,
  statusLabel,
  statusCls,
  onClose,
  onOpenMinister,
}: {
  order: SecretOrder;
  statusLabel: Record<string, string>;
  statusCls: Record<string, string>;
  onClose: () => void;
  onOpenMinister: (name: string) => void;
}) {
  const deadlineText = order.due_turn
    ? `第 ${order.due_turn} 回合核议${order.due_turn <= order.turn_issued ? "" : `（限 ${order.due_turn - order.turn_issued} 个月）`}`
    : "无硬期限";
  const detailRows = [
    ["编号", `#${order.id}`],
    ["承办", order.minister_name],
    ["下令", `第 ${order.year_issued} 年 ${order.period_issued} 月 · 回合 ${order.turn_issued}`],
    ["期限", deadlineText],
    ["重要", String(order.importance || 0)],
    ["标签", order.tags?.length ? order.tags.join("、") : "无"],
  ];
  return (
    <div className="so-detail-layer" role="dialog" aria-modal="true" aria-label={`密令详情：${order.title}`}>
      <div className="so-detail-scrim" onClick={onClose} />
      <section className="so-detail-dialog">
        <header className="so-detail-header">
          <div>
            <span className={`so-status ${statusCls[order.status] || ""}`}>{statusLabel[order.status] || order.status}</span>
            <h2>{order.title}</h2>
          </div>
          <button className="icon-button" aria-label="关闭密令详情" onClick={onClose}>
            <X size={18} />
          </button>
        </header>
        <div className="so-detail-body">
          <dl className="so-detail-grid">
            {detailRows.map(([label, value]) => (
              <div key={label}>
                <dt>{label}</dt>
                <dd>{value}</dd>
              </div>
            ))}
          </dl>
          <SecretOrderDetailBlock title="密令正文" text={order.content || "未记正文。"} />
          {order.sim_note ? <SecretOrderDetailBlock title="月度动向" text={order.sim_note} tone="green" /> : null}
          {order.result ? (
            <SecretOrderDetailBlock title={order.status === "active" ? "承办回报" : "执行结果"} text={order.result} tone="green" />
          ) : null}
        </div>
        <footer className="so-detail-actions">
          {order.status === "active" ? (
            <button className="secondary-action" onClick={() => onOpenMinister(order.minister_name)}>
              <MessageSquare size={15} />
              召见 {order.minister_name}
            </button>
          ) : null}
          <button className="secondary-action" onClick={onClose}>返回列表</button>
        </footer>
      </section>
    </div>
  );
}

function SecretOrderDetailBlock({ title, text, tone = "default" }: { title: string; text: string; tone?: "default" | "green" }) {
  return (
    <section className={`so-detail-block so-detail-block-${tone}`}>
      <h3>{title}</h3>
      <p>{text}</p>
    </section>
  );
}

function ClosedIssuesModal({ items, onClose }: { items: ClosedIssue[]; onClose: () => void }) {
  const resolved = items.filter((i) => i.status === "resolved");
  const failed = items.filter((i) => i.status === "failed");
  const dropped = items.filter((i) => i.status === "dropped");
  return (
    <FullscreenModal title="局势了结" subtitle={`本月共 ${items.length} 条局势了结`} bgClass="modal-bg-state" onClose={onClose}>
      <article className="state-document modal-scroll">
        {resolved.length ? <ClosedGroup title="已结案" items={resolved} cls="resolved" /> : null}
        {failed.length ? <ClosedGroup title="已崩坏" items={failed} cls="failed" /> : null}
        {dropped.length ? <ClosedGroup title="已撤旨" items={dropped} cls="dropped" /> : null}
      </article>
    </FullscreenModal>
  );
}

function ClosedGroup({ title, items, cls }: { title: string; items: ClosedIssue[]; cls: string }) {
  return (
    <div className="document-section">
      <h3 className={`closed-group-title ${cls}`}>{title}</h3>
      <ul className="closed-list">
        {items.map((it) => (
          <li key={it.id} className={`closed-card ${cls}`}>
            <div className="closed-card-head">
              <b>#{it.id} {it.title}</b>
              <span>{cls === "resolved" ? it.bar_good_meaning : it.bar_bad_meaning}</span>
            </div>
            {it.stage_text ? <p className="closed-card-stage">{it.stage_text}</p> : null}
            <div className="closed-card-effect">{formatClosedEffect(it.effect)}</div>
          </li>
        ))}
      </ul>
    </div>
  );
}

function ExtractionModal({ onClose }: { onClose: () => void }) {
  const [extraction, setExtraction] = React.useState<ExtractionData | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const resp = await fetch("/api/turn_extraction");
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        if (alive) setExtraction(data);
      } catch (e: any) {
        if (alive) setError(e?.message || "加载失败");
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, []);

  return (
    <FullscreenModal title="邸报详明" subtitle="数项加减/账目明细" bgClass="modal-bg-state" onClose={onClose}>
      <article className="state-document modal-scroll">
        <ExtractionView data={extraction} loading={loading} error={error} />
      </article>
    </FullscreenModal>
  );
}

type HistoryTurnItem = {
  turn: number;
  year: number;
  period: number;
  has_report: boolean;
  has_extraction: boolean;
  has_directive: boolean;
};

type HistoryDirective = {
  id: number;
  turn: number;
  year: number;
  period: number;
  event_id: string;
  event_title: string;
  actor: string;
  skill_id: string;
  text: string;
  source: string;
  status: string;
  notes: string;
  created_at: string;
  updated_at: string;
};

type HistoryDetail = {
  turn: number;
  exists: boolean;
  year: number;
  period: number;
  report: string;
  decree_text: string;
  directives: HistoryDirective[];
  extraction: ExtractionData | null;
};

function HistoryModal({ onClose }: { onClose: () => void }) {
  const [turns, setTurns] = React.useState<HistoryTurnItem[]>([]);
  const [listLoading, setListLoading] = React.useState(true);
  const [listError, setListError] = React.useState("");
  const [selectedTurn, setSelectedTurn] = React.useState<number | null>(null);
  const [detail, setDetail] = React.useState<HistoryDetail | null>(null);
  const [detailLoading, setDetailLoading] = React.useState(false);
  const [detailError, setDetailError] = React.useState("");

  React.useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const resp = await fetch("/api/history/turns");
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        if (!alive) return;
        const list: HistoryTurnItem[] = data.turns || [];
        setTurns(list);
        if (list.length) setSelectedTurn(list[list.length - 1].turn);
      } catch (e: any) {
        if (alive) setListError(e?.message || "加载失败");
      } finally {
        if (alive) setListLoading(false);
      }
    })();
    return () => { alive = false; };
  }, []);

  React.useEffect(() => {
    if (selectedTurn == null) return;
    let alive = true;
    setDetailLoading(true);
    setDetailError("");
    (async () => {
      try {
        const resp = await fetch(`/api/history/turn/${selectedTurn}`);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        if (alive) setDetail(data);
      } catch (e: any) {
        if (alive) setDetailError(e?.message || "加载失败");
      } finally {
        if (alive) setDetailLoading(false);
      }
    })();
    return () => { alive = false; };
  }, [selectedTurn]);

  const subtitle = turns.length ? `共 ${turns.length} 月存档` : "尚无存档";

  return (
    <FullscreenModal title="史册：历代奏报与诏书" subtitle={subtitle} bgClass="modal-bg-state" onClose={onClose}>
      <div className="history-modal-body">
        <aside className="history-turn-list">
          {listLoading ? <p className="long-copy">加载中…</p> : null}
          {listError ? <p className="long-copy">加载失败：{listError}</p> : null}
          {!listLoading && !listError && turns.length === 0 ? (
            <p className="long-copy">尚无存档回合。</p>
          ) : null}
          <ul>
            {turns.slice().reverse().map((t) => {
              const active = t.turn === selectedTurn;
              const tags: string[] = [];
              if (t.has_report) tags.push("奏报");
              if (t.has_directive) tags.push("诏");
              if (t.has_extraction) tags.push("册");
              return (
                <li key={t.turn}>
                  <button
                    className={`history-turn-item ${active ? "active" : ""}`}
                    onClick={() => setSelectedTurn(t.turn)}
                  >
                    <b>{t.year} 年 {t.period} 月</b>
                    <small>第 {t.turn} 回合 · {tags.join(" / ") || "—"}</small>
                  </button>
                </li>
              );
            })}
          </ul>
        </aside>
        <article className="history-detail modal-scroll">
          <HistoryDetailView
            loading={detailLoading}
            error={detailError}
            detail={detail}
            selectedTurn={selectedTurn}
          />
        </article>
      </div>
    </FullscreenModal>
  );
}

function GameMenuModal({
  onClose,
  onAfterLoad,
  onExitToMenu,
}: {
  onClose: () => void;
  onAfterLoad: () => void;
  onExitToMenu: () => void;
}) {
  const [tab, setTab] = React.useState<"save" | "load" | "llm" | "reset" | "exit_menu" | "shutdown">("save");
  React.useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <section className="center-layer" role="dialog" aria-modal="true" aria-label="游戏菜单">
      <div className="center-scrim" onClick={onClose} />
      <div className="center-modal">
        <header className="center-modal-header">
          <h1>游戏菜单</h1>
          <button className="icon-button" aria-label="关闭弹窗" onClick={onClose}>
            <X size={18} />
          </button>
        </header>
        <div className="game-menu">
          <nav className="game-menu-tabs">
            <button className={tab === "save" ? "active" : ""} onClick={() => setTab("save")}>
              <Save size={14} /> 保存存档
            </button>
            <button className={tab === "load" ? "active" : ""} onClick={() => setTab("load")}>
              <Upload size={14} /> 加载存档
            </button>
            <button className={tab === "llm" ? "active" : ""} onClick={() => setTab("llm")}>
              <Settings size={14} /> LLM 配置
            </button>
            <button className={tab === "reset" ? "active" : ""} onClick={() => setTab("reset")}>
              <RotateCcw size={14} /> 重开新局
            </button>
            <button className={tab === "exit_menu" ? "active" : ""} onClick={() => setTab("exit_menu")}>
              <LogOut size={14} /> 回到主菜单
            </button>
            <button className={tab === "shutdown" ? "active" : ""} onClick={() => setTab("shutdown")}>
              <Power size={14} /> 退出游戏
            </button>
          </nav>
          <div className="game-menu-body">
            {tab === "save" ? <SaveTab /> : null}
            {tab === "load" ? <LoadTab onAfterLoad={onAfterLoad} /> : null}
            {tab === "llm" ? <LLMConfigTab /> : null}
            {tab === "reset" ? <ResetTab onAfterReset={onAfterLoad} /> : null}
            {tab === "exit_menu" ? <ExitToMenuTab onExit={onExitToMenu} /> : null}
            {tab === "shutdown" ? <ShutdownTab /> : null}
          </div>
        </div>
      </div>
    </section>
  );
}

function SaveTab() {
  const [name, setName] = React.useState("");
  const [saves, setSaves] = React.useState<SaveEntry[]>([]);
  const [busy, setBusy] = React.useState(false);
  const [msg, setMsg] = React.useState("");
  const [err, setErr] = React.useState("");

  const refresh = React.useCallback(async () => {
    try {
      const data = await api<{ saves: SaveEntry[] }>("/api/saves");
      setSaves(data.saves);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }, []);

  React.useEffect(() => {
    refresh();
  }, [refresh]);

  const onSave = async () => {
    if (!name.trim()) {
      setErr("请填存档名。");
      return;
    }
    setBusy(true);
    setErr("");
    setMsg("");
    try {
      await api<{ save: { name: string }; saves: SaveEntry[] }>("/api/saves", {
        method: "POST",
        body: JSON.stringify({ name: name.trim() }),
      });
      setMsg(`已保存为 ${name.trim()}.db`);
      setName("");
      await refresh();
    } catch (e) {
      const detail = e instanceof ApiRequestError ? e.detail : null;
      setErr(detail ? `code: ${detail.code || "unknown"}\nmessage: ${detail.message || (e instanceof Error ? e.message : String(e))}` : e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="menu-section">
      <h3>保存当前局</h3>
      <p className="menu-hint">将当前 DB 热备到 data/saves/&lt;名字&gt;.db。同名直接覆盖。</p>
      <div className="menu-row">
        <input
          className="menu-input"
          placeholder="存档名（字母/数字/._-）"
          value={name}
          onChange={(e) => setName(e.target.value)}
          disabled={busy}
        />
        <button className="menu-btn primary" onClick={onSave} disabled={busy}>
          {busy ? <Loader2 size={14} className="spin" /> : <Save size={14} />} 保存
        </button>
      </div>
      {msg ? <div className="menu-success">{msg}</div> : null}
      {err ? <div className="menu-error">{err}</div> : null}
      <h4>现有存档</h4>
      <SavesList saves={saves} onRefresh={refresh} />
    </section>
  );
}

function LoadTab({ onAfterLoad }: { onAfterLoad: () => void }) {
  const [saves, setSaves] = React.useState<SaveEntry[]>([]);
  const [busy, setBusy] = React.useState("");
  const [err, setErr] = React.useState("");
  const refresh = React.useCallback(async () => {
    try {
      const data = await api<{ saves: SaveEntry[] }>("/api/saves");
      setSaves(data.saves);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }, []);
  React.useEffect(() => {
    refresh();
  }, [refresh]);

  const onLoad = async (n: string) => {
    if (!window.confirm(`确定加载 ${n}.db？当前未保存进度会丢失。`)) return;
    setBusy(n);
    setErr("");
    try {
      await api(`/api/saves/${encodeURIComponent(n)}/load`, { method: "POST" });
      onAfterLoad();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
      setBusy("");
    }
  };

  return (
    <section className="menu-section">
      <h3>加载存档</h3>
      <p className="menu-hint">选一份覆盖回主 DB。加载后页面会自动重新载入。</p>
      {err ? <div className="menu-error">{err}</div> : null}
      <SavesList saves={saves} onRefresh={refresh} action={onLoad} busy={busy} />
    </section>
  );
}

function ResetTab({ onAfterReset }: { onAfterReset: () => void }) {
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState("");
  const [confirmText, setConfirmText] = React.useState("");

  const canReset = confirmText.trim() === "重开";

  const onReset = async () => {
    if (!canReset) return;
    if (!window.confirm("确定重开新局？当前局所有数据将被永久清空（存档目录不动）。")) return;
    setBusy(true);
    setErr("");
    try {
      await api("/api/game/reset", { method: "POST" });
      onAfterReset();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  };

  return (
    <section className="menu-section">
      <h3>重开新局</h3>
      <p className="menu-hint">
        清空主 DB（聊天记录、回合奏报、局势、ledger 全清），重置到天启七年十二月开局。
        <b>不可撤销</b>。要保留当前局，先到「保存存档」存一份。
      </p>
      <p className="menu-hint">输入「重开」二字以解锁按钮：</p>
      <div className="menu-row">
        <input
          className="menu-input"
          placeholder="输入：重开"
          value={confirmText}
          onChange={(e) => setConfirmText(e.target.value)}
          disabled={busy}
        />
        <button className="menu-btn danger" onClick={onReset} disabled={!canReset || busy}>
          {busy ? <Loader2 size={14} className="spin" /> : <RotateCcw size={14} />} 重开新局
        </button>
      </div>
      {err ? <div className="menu-error">{err}</div> : null}
    </section>
  );
}

function ExitToMenuTab({ onExit }: { onExit: () => void | Promise<void> }) {
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState("");
  const onClick = async () => {
    if (!window.confirm("回到主菜单？当前对局会关闭（DB 仍保留，可从「继续上局」回到此处）。")) return;
    setBusy(true);
    setErr("");
    try {
      await onExit();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  };
  return (
    <section className="menu-section">
      <h3>回到主菜单</h3>
      <p className="menu-hint">
        关闭当前游戏会话，回到主菜单。数据库与存档不变；可从主菜单「继续上局」或「加载存档」回到游戏。
      </p>
      <div className="menu-row">
        <button className="menu-btn primary" onClick={onClick} disabled={busy}>
          {busy ? <Loader2 size={14} className="spin" /> : <LogOut size={14} />} 回到主菜单
        </button>
      </div>
      {err ? <div className="menu-error">{err}</div> : null}
    </section>
  );
}

function ShutdownTab() {
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState("");
  const onClick = async () => {
    if (!window.confirm("退出整个游戏？前后端进程都会关闭，未保存的进度会丢失。")) return;
    setBusy(true);
    setErr("");
    try {
      await fetch("/api/menu/shutdown", { method: "POST" });
      // server 已发 SIGTERM 给自己；前端尝试关页面（浏览器可能拦截），否则提示用户。
      setTimeout(() => {
        try { window.close(); } catch { /* noop */ }
      }, 400);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  };
  return (
    <section className="menu-section">
      <h3>退出游戏</h3>
      <p className="menu-hint">
        终止服务进程并尝试关闭浏览器页面。<b>未保存的进度会丢失</b>。要保留当前局，先到「保存存档」。
      </p>
      <div className="menu-row">
        <button className="menu-btn danger" onClick={onClick} disabled={busy}>
          {busy ? <Loader2 size={14} className="spin" /> : <Power size={14} />} 退出游戏
        </button>
      </div>
      {err ? <div className="menu-error">{err}</div> : null}
    </section>
  );
}

function SavesList({
  saves,
  onRefresh,
  action,
  busy,
}: {
  saves: SaveEntry[];
  onRefresh: () => void;
  action?: (name: string) => void;
  busy?: string;
}) {
  const [delErr, setDelErr] = React.useState("");
  const onDelete = async (n: string) => {
    if (!window.confirm(`删除 ${n}.db？`)) return;
    try {
      await api(`/api/saves/${encodeURIComponent(n)}`, { method: "DELETE" });
      onRefresh();
    } catch (e) {
      setDelErr(e instanceof Error ? e.message : String(e));
    }
  };
  if (!saves.length) return <div className="menu-empty">尚无存档。</div>;
  return (
    <ul className="saves-list">
      {delErr ? <div className="menu-error">{delErr}</div> : null}
      {saves.map((s) => (
        <li key={s.name} className="saves-row">
          <div className="saves-name">
            <b>{s.name}</b>
            <small>
              {new Date(s.mtime * 1000).toLocaleString()} · {(s.size / 1024).toFixed(1)} KB
            </small>
          </div>
          <div className="saves-actions">
            {action ? (
              <button className="menu-btn primary" disabled={busy === s.name} onClick={() => action(s.name)}>
                {busy === s.name ? <Loader2 size={14} className="spin" /> : <Upload size={14} />} 加载
              </button>
            ) : null}
            <button className="menu-btn danger" onClick={() => onDelete(s.name)}>
              <Trash2 size={14} /> 删
            </button>
          </div>
        </li>
      ))}
    </ul>
  );
}

function LLMConfigTab() {
  const [info, setInfo] = React.useState<LLMConfigInfo | null>(null);
  const [baseUrl, setBaseUrl] = React.useState("");
  const [model, setModel] = React.useState("");
  const [advancedModel, setAdvancedModel] = React.useState("");
  const [advancedBaseUrl, setAdvancedBaseUrl] = React.useState("");
  const [advancedApiKey, setAdvancedApiKey] = React.useState("");
  const [advancedThinkingLevel, setAdvancedThinkingLevel] = React.useState("");
  const [apiKey, setApiKey] = React.useState("");
  const [maxTokens, setMaxTokens] = React.useState("8000");
  const [timeoutSeconds, setTimeoutSeconds] = React.useState("180");
  const [thinkingLevel, setThinkingLevel] = React.useState("");
  const [show, setShow] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [msg, setMsg] = React.useState("");
  const [err, setErr] = React.useState("");

  React.useEffect(() => {
    api<LLMConfigInfo>("/api/llm/config")
      .then((data) => {
        setInfo(data);
        setBaseUrl(data.base_url);
        setModel(data.model);
        setAdvancedModel(data.advanced_model || "");
        setAdvancedBaseUrl(data.advanced_base_url || "");
        setAdvancedThinkingLevel(data.advanced_thinking_level || "");
        setMaxTokens(String(data.max_tokens || 8000));
        setTimeoutSeconds(String(data.timeout_seconds || 180));
        setThinkingLevel(data.thinking_level || "");
      })
      .catch((e) => setErr(e instanceof Error ? e.message : String(e)));
  }, []);

  const onSave = async () => {
    setBusy(true);
    setErr("");
    setMsg("");
    try {
      const data = await api<LLMConfigInfo>("/api/llm/config", {
        method: "POST",
        body: JSON.stringify({
          base_url: baseUrl,
          model,
          api_key: apiKey,
          max_tokens: parseInt(maxTokens) || 8000,
          timeout_seconds: parseFloat(timeoutSeconds) || 180,
          thinking_level: thinkingLevel.trim(),
          advanced_model: advancedModel,
          advanced_base_url: advancedBaseUrl,
          advanced_api_key: advancedApiKey.trim() ? advancedApiKey : "__keep__",
          advanced_thinking_level: advancedThinkingLevel.trim(),
        }),
      });
      setInfo((cur) => (cur ? { ...cur, ...data } : null));
      setApiKey("");
      setAdvancedApiKey("");
      setMsg("已生效并写入 data/runtime_llm.json。");
    } catch (e) {
      const detail = e instanceof ApiRequestError ? e.detail : null;
      setErr(detail ? `code: ${detail.code || "unknown"}\nmessage: ${detail.message || (e instanceof Error ? e.message : String(e))}` : e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="menu-section">
      <h3>LLM 配置</h3>
      <p className="menu-hint">
        立即生效并写入 <code>data/runtime_llm.json</code>，重启进程后自动加载。api_key 留空保留当前。
      </p>
      <label className="menu-field">
        <span>Base URL</span>
        <input
          className="menu-input"
          value={baseUrl}
          onChange={(e) => setBaseUrl(e.target.value)}
          placeholder="https://api.openai.com/v1"
        />
      </label>
      <label className="menu-field">
        <span>Model</span>
        <input
          className="menu-input"
          value={model}
          onChange={(e) => setModel(e.target.value)}
          placeholder="gpt-4o-mini"
        />
      </label>
      <label className="menu-field">
        <span>Thinking Level <small className="menu-hint">（空=默认，请填写你的模型支持的值。）</small></span>
        <input
          className="menu-input"
          value={thinkingLevel}
          onChange={(e) => setThinkingLevel(e.target.value)}
          placeholder="默认"
        />
      </label>
      <label className="menu-field">
        <span>Advanced Model <small className="menu-hint">（推演 + 打分专用，空=与 Model 一致）</small></span>
        <input
          className="menu-input"
          value={advancedModel}
          onChange={(e) => setAdvancedModel(e.target.value)}
          placeholder="deepseek-reasoner / gpt-5（留空 fallback）"
        />
      </label>
      <label className="menu-field">
        <span>Advanced Base URL <small className="menu-hint">（advanced 专用网关，空=与 Base URL 一致）</small></span>
        <input
          className="menu-input"
          value={advancedBaseUrl}
          onChange={(e) => setAdvancedBaseUrl(e.target.value)}
          placeholder="https://other-gateway/v1（留空复用主 Base URL）"
        />
      </label>
      <label className="menu-field">
        <span>
          Advanced API Key{" "}
          {info?.has_advanced_api_key ? (
            <small className="ok">（当前已设置）</small>
          ) : (
            <small className="menu-hint">（空=复用主 API Key）</small>
          )}
        </span>
        <input
          className="menu-input"
          type={show ? "text" : "password"}
          value={advancedApiKey}
          onChange={(e) => setAdvancedApiKey(e.target.value)}
          placeholder="留空=复用主 API Key / 保留当前"
        />
      </label>
      <label className="menu-field">
        <span>Advanced Thinking Level <small className="menu-hint">（空=默认，请填写你的模型支持的值。）</small></span>
        <input
          className="menu-input"
          value={advancedThinkingLevel}
          onChange={(e) => setAdvancedThinkingLevel(e.target.value)}
          placeholder="默认"
        />
      </label>
      <label className="menu-field">
        <span>Max Tokens</span>
        <input
          className="menu-input"
          type="number"
          min={256}
          max={65536}
          value={maxTokens}
          onChange={(e) => setMaxTokens(e.target.value)}
          placeholder="8000"
        />
      </label>
      <label className="menu-field">
        <span>Timeout Seconds</span>
        <input
          className="menu-input"
          type="number"
          min={10}
          max={900}
          value={timeoutSeconds}
          onChange={(e) => setTimeoutSeconds(e.target.value)}
          placeholder="180"
        />
      </label>
      <label className="menu-field">
        <span>
          API Key{" "}
          {info?.has_api_key ? <small className="ok">（当前已设置）</small> : <small className="warn">（未设置）</small>}
        </span>
        <div className="menu-row">
          <input
            className="menu-input"
            type={show ? "text" : "password"}
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder={info?.has_api_key ? "留空保留当前" : "请输入"}
            autoComplete="off"
          />
          <button className="menu-btn" type="button" onClick={() => setShow((v) => !v)}>
            {show ? "隐" : "显"}
          </button>
        </div>
      </label>
      <div className="menu-row">
        <button className="menu-btn primary" onClick={onSave} disabled={busy}>
          {busy ? <Loader2 size={14} className="spin" /> : <Check size={14} />} 保存并应用
        </button>
      </div>
      {msg ? <div className="menu-success">{msg}</div> : null}
      {err ? <div className="menu-error">{err}</div> : null}
    </section>
  );
}

function HistoryDetailView({
  loading,
  error,
  detail,
  selectedTurn,
}: {
  loading: boolean;
  error: string;
  detail: HistoryDetail | null;
  selectedTurn: number | null;
}) {
  if (selectedTurn == null) return <div className="document-section"><p className="long-copy">请从左侧择月。</p></div>;
  if (loading) return <div className="document-section"><p className="long-copy">加载中…</p></div>;
  if (error) return <div className="document-section"><p className="long-copy">加载失败：{error}</p></div>;
  if (!detail || !detail.exists) return <div className="document-section"><p className="long-copy">该回合无存档。</p></div>;

  return (
    <>
      {detail.decree_text ? (
        <section className="document-section">
          <h3 className="extraction-section-title">本月诏书</h3>
          <pre className="memorial-text">{detail.decree_text}</pre>
        </section>
      ) : null}

      {detail.directives.length ? (
        <section className="document-section">
          <h3 className="extraction-section-title">已颁草案（{detail.directives.length} 道）</h3>
          <ul className="history-directive-list">
            {detail.directives.map((d) => (
              <li key={d.id} className="history-directive-item">
                <div className="history-directive-head">
                  <b>#{d.id}</b>
                  {d.event_title ? <span>事项：{d.event_title}</span> : null}
                  {d.actor ? <span>主官：{d.actor}</span> : null}
                  {d.skill_id ? <span>技能：{d.skill_id}</span> : null}
                  <span className="history-directive-source">{d.source}</span>
                </div>
                <pre className="memorial-text">{d.text}</pre>
                {d.notes ? <div className="history-directive-notes">备注：{d.notes}</div> : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {detail.report ? (
        <section className="document-section">
          <h3 className="extraction-section-title">月末邸报奏报</h3>
          <pre className="memorial-text">{detail.report}</pre>
        </section>
      ) : null}

      {detail.extraction && detail.extraction.exists ? (
        <section className="document-section">
          <h3 className="extraction-section-title">邸报详明（extractor 解析）</h3>
          <ExtractionView data={detail.extraction} loading={false} error="" />
        </section>
      ) : null}
    </>
  );
}

function ExtractionView({ data, loading, error }: { data: ExtractionData | null; loading: boolean; error: string }) {
  if (loading) return <div className="document-section"><p className="long-copy">加载中…</p></div>;
  if (error) return <div className="document-section"><p className="long-copy">加载失败：{error}</p></div>;
  if (!data || !data.exists) return <div className="document-section"><p className="long-copy">该回合无 extractor 数据。</p></div>;
  const rawOut = data.extractor_output;
  if (!rawOut || typeof rawOut !== "object") {
    return <div className="document-section"><pre className="memorial-text">{String(rawOut ?? "")}</pre></div>;
  }
  // modular 结构：数据在 merged（已合并扁平），顶层只有 mode/modules/merged/raw。老存档是扁平对象，直接用。
  const out = (rawOut as any).mode === "modular" && (rawOut as any).merged && typeof (rawOut as any).merged === "object"
    ? (rawOut as any).merged
    : rawOut;
  return (
    <div className="document-section extraction-view">
      <ExtractionSection title="国势变化">
        <MetricDeltaBlock data={pickField(out, "国势变化", "metric_delta")} />
      </ExtractionSection>
      <ExtractionSection title="钱粮收支">
        <EconomyBlock data={pickField(out, "钱粮收支", "economy_moves")} />
      </ExtractionSection>
      <ExtractionSection title="派系变化">
        <FactionBlock data={pickField(out, "派系变化", "faction_delta")} />
      </ExtractionSection>
      <ExtractionSection title="阶级变化">
        <ClassDeltaBlock data={pickField(out, "阶级变化", "class_delta")} />
      </ExtractionSection>
      <ExtractionSection title="官职任免">
        <OfficeChangesBlock data={pickField(out, "人事变更", "office_changes")} />
      </ExtractionSection>
      <ExtractionSection title="去职变更">
        <StatusChangesBlock data={pickField(out, "人物状态变化", "character_status_changes")} />
      </ExtractionSection>
      <ExtractionSection title="人物易主">
        <PowerChangesBlock data={pickField(out, "人物易主", "character_power_changes")} />
      </ExtractionSection>
      <ExtractionSection title="后宫纳妃">
        <AppointmentsBlock data={pickField(out, "后宫册封", "appointments")} />
      </ExtractionSection>
      <ExtractionSection title="局势推进">
        <IssueAdvancesBlock data={pickField(out, "局势推进", "issue_advances")} />
      </ExtractionSection>
      <ExtractionSection title="新立局势">
        <NewIssuesBlock data={pickField(out, "新立局势", "new_issues")} />
      </ExtractionSection>
      <ExtractionSection title="结案 / 失败">
        <CloseIssuesBlock data={pickField(out, "结案局势", "close_issues")} />
      </ExtractionSection>
      <ExtractionSection title="撤旨">
        <CancelsBlock data={pickField(out, "撤销局势", "cancels")} />
      </ExtractionSection>
      <ExtractionSection title="地区变化">
        <EntityDeltaBlock data={pickField(out, "地区变化", "region_delta")} labelFn={labelRegion} />
      </ExtractionSection>
      <ExtractionSection title="军队变化">
        <EntityDeltaBlock data={pickField(out, "军队变化", "army_delta")} labelFn={labelArmy} />
      </ExtractionSection>
      <ExtractionSection title="新建军队">
        <NewArmiesBlock data={pickField(out, "新建军队", "new_armies")} />
      </ExtractionSection>
      <ExtractionSection title="势力变化">
        <EntityDeltaBlock data={pickField(out, "势力变化", "power_updates")} labelFn={labelPower} />
      </ExtractionSection>
      <ExtractionSection title="财政系数">
        <FiscalBlock data={pickField(out, "财政制度变化", "fiscal_changes")} />
      </ExtractionSection>
      <ExtractionSection title="外交关系">
        <DiplomacyBlock data={pickField(out, "外交关系", "world_advance") ?? pickField(out, "外交", "world_advance") ?? pickField(out, "外交态度", "world_advance") ?? pickField(out, "四方动向", "world_advance")} />
      </ExtractionSection>
      <ExtractionSection title="密令副作用">
        <SecretSideBlock data={pickField(out, "密令副作用", "secret_order_updates")} />
      </ExtractionSection>
      <ExtractionSection title="密令核议">
        <SecretCloseBlock data={pickField(out, "密令结案", "secret_order_closes")} />
      </ExtractionSection>
    </div>
  );
}

function pickField(obj: any, cn: string, en: string): any {
  if (!obj || typeof obj !== "object") return undefined;
  return obj[cn] ?? obj[en];
}

function pickItem(obj: any, cn: string, en: string): any {
  if (!obj || typeof obj !== "object") return undefined;
  return obj[cn] ?? obj[en];
}

function ExtractionSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="extraction-section">
      <h3 className="extraction-section-title">{title}</h3>
      <div className="extraction-section-body">{children}</div>
    </section>
  );
}

function fmtDelta(n: any): string {
  // 缺失/非数（extractor 偶尔不带 delta_bar）按 0 处理，避免渲染出字面 "undefined"
  const num = Number(n);
  if (!Number.isFinite(num)) return "0";
  if (num > 0) return `+${num}`;
  return String(num);
}

function isEmptyData(d: any): boolean {
  if (d == null) return true;
  if (Array.isArray(d)) return d.length === 0;
  if (typeof d === "object") return Object.keys(d).length === 0;
  return false;
}

function MetricDeltaBlock({ data }: { data: any }) {
  if (isEmptyData(data)) return <p className="extraction-empty">无</p>;
  return (
    <ul className="extraction-kv">
      {Object.entries(data).map(([k, v]) => (
        <li key={k}><span>{k}</span><b className={Number(v) >= 0 ? "good" : "bad"}>{fmtDelta(v)}</b></li>
      ))}
    </ul>
  );
}

function EconomyBlock({ data }: { data: any }) {
  if (isEmptyData(data) || !Array.isArray(data)) return <p className="extraction-empty">无</p>;
  return (
    <ul className="extraction-list">
      {data.map((item: any, i: number) => (
        <li key={i}>
          <b className={Number(pickItem(item, "增量", "delta")) >= 0 ? "good" : "bad"}>
            {pickItem(item, "账户", "account") || "?"} {fmtDelta(pickItem(item, "增量", "delta"))} 万
          </b>
          <span>{pickItem(item, "分类", "category") || ""}{pickItem(item, "原因", "reason") ? ` — ${pickItem(item, "原因", "reason")}` : ""}</span>
        </li>
      ))}
    </ul>
  );
}

function FactionBlock({ data }: { data: any }) {
  if (isEmptyData(data)) return <p className="extraction-empty">无</p>;
  return (
    <ul className="extraction-kv">
      {Object.entries(data).map(([k, v]: [string, any]) => {
        if (v && typeof v === "object") {
          return (
            <li key={k}>
              <span>{k}</span>
              <b>{Object.entries(v).map(([kk, vv]) => `${SAT_LEV_CN[kk] || cnField(kk)}${fmtDelta(vv)}`).join("  ")}</b>
            </li>
          );
        }
        return <li key={k}><span>{k}</span><b className={Number(v) >= 0 ? "good" : "bad"}>{fmtDelta(v)}</b></li>;
      })}
    </ul>
  );
}

function IssueAdvancesBlock({ data }: { data: any }) {
  if (isEmptyData(data) || !Array.isArray(data)) return <p className="extraction-empty">无</p>;
  return (
    <ul className="extraction-list">
      {data.map((it: any, i: number) => (
        <li key={i}>
          <b className={Number(pickItem(it, "进度增量", "delta_bar")) >= 0 ? "good" : "bad"}>
            {labelIssue(pickItem(it, "局势编号", "issue_id"))} 进度 {fmtDelta(pickItem(it, "进度增量", "delta_bar"))}
            {pickItem(it, "惯性增量", "inertia_delta") ? `，惯性 ${fmtDelta(pickItem(it, "惯性增量", "inertia_delta"))}` : ""}
          </b>
          {pickItem(it, "阶段", "stage_text") ? <span>{pickItem(it, "阶段", "stage_text")}</span> : null}
          {pickItem(it, "叙述", "narrative") ? <span className="extraction-narr">{pickItem(it, "叙述", "narrative")}</span> : null}
        </li>
      ))}
    </ul>
  );
}

function NewIssuesBlock({ data }: { data: any }) {
  if (isEmptyData(data) || !Array.isArray(data)) return <p className="extraction-empty">无</p>;
  return (
    <ul className="extraction-list">
      {data.map((it: any, i: number) => (
        <li key={i}>
          <b>{pickItem(it, "标题", "title") || pickItem(it, "编号", "id") || "新事项"}（{cnValue(pickItem(it, "类型", "kind") || pickItem(it, "来源类型", "origin_kind") || "")}）</b>
          {pickItem(it, "阶段", "stage_text") ? <span>{pickItem(it, "阶段", "stage_text")}</span> : null}
        </li>
      ))}
    </ul>
  );
}

function CloseIssuesBlock({ data }: { data: any }) {
  if (isEmptyData(data) || !Array.isArray(data)) return <p className="extraction-empty">无</p>;
  return (
    <ul className="extraction-list">
      {data.map((it: any, i: number) => (
        <li key={i}>
          <b className={pickItem(it, "原因", "reason") === "resolved" ? "good" : "bad"}>
            {labelIssue(pickItem(it, "局势编号", "issue_id"))} {pickItem(it, "原因", "reason") === "resolved" ? "结案" : "失败"}
          </b>
          {pickItem(it, "叙述", "narrative") ? <span>{pickItem(it, "叙述", "narrative")}</span> : null}
        </li>
      ))}
    </ul>
  );
}

function CancelsBlock({ data }: { data: any }) {
  if (isEmptyData(data) || !Array.isArray(data)) return <p className="extraction-empty">无</p>;
  return (
    <ul className="extraction-list">
      {data.map((it: any, i: number) => (
        <li key={i}>
          <b>{labelIssue(pickItem(it, "局势编号", "issue_id"))} 撤旨</b>
          {pickItem(it, "叙述", "narrative") ? <span>{pickItem(it, "叙述", "narrative")}</span> : null}
        </li>
      ))}
    </ul>
  );
}

function OfficeChangesBlock({ data }: { data: any }) {
  if (isEmptyData(data) || !Array.isArray(data)) return <p className="extraction-empty">无</p>;
  return (
    <ul className="extraction-list">
      {data.map((it: any, i: number) => (
        <li key={i}>
          <b className={pickItem(it, "rejected", "rejected") ? "bad" : "good"}>
            {pickItem(it, "姓名", "name")} → {pickItem(it, "新官职", "new_office")}
            {pickItem(it, "新官署类别", "new_office_type") ? `（${pickItem(it, "新官署类别", "new_office_type")}）` : ""}
            {pickItem(it, "rejected", "rejected") ? "（未落地）" : pickItem(it, "kind", "kind") === "appoint" ? "（新进朝堂）" : ""}
          </b>
          {pickItem(it, "displaced", "displaced") ? <span>顶替 {pickItem(it, "displaced", "displaced")} 去职</span> : null}
          {pickItem(it, "原因", "reason") ? <span>{pickItem(it, "原因", "reason")}</span> : null}
        </li>
      ))}
    </ul>
  );
}

function StatusChangesBlock({ data }: { data: any }) {
  if (isEmptyData(data) || !Array.isArray(data)) return <p className="extraction-empty">无</p>;
  const label: Record<string, string> = {
    dismissed: "罢黜", imprisoned: "下狱", exiled: "流放",
    retired: "致仕", dead: "身故", offstage: "去位",
  };
  return (
    <ul className="extraction-list">
      {data.map((it: any, i: number) => (
        <li key={i}>
          <b className={pickItem(it, "rejected", "rejected") ? "bad" : ""}>
            {pickItem(it, "姓名", "name")} {label[pickItem(it, "状态", "status")] || cnValue(pickItem(it, "状态", "status"))}
            {pickItem(it, "rejected", "rejected") ? "（未落地）" : ""}
          </b>
          {pickItem(it, "原因", "reason") ? <span>{pickItem(it, "原因", "reason")}</span> : null}
        </li>
      ))}
    </ul>
  );
}

function AppointmentsBlock({ data }: { data: any }) {
  if (isEmptyData(data) || !Array.isArray(data)) return <p className="extraction-empty">无</p>;
  return (
    <ul className="extraction-list">
      {data.map((it: any, i: number) => (
        <li key={i}>
          <b className={pickItem(it, "rejected", "rejected") ? "bad" : "good"}>
            {pickItem(it, "姓名", "name")} 册封 {pickItem(it, "位号", "office")}
            {pickItem(it, "rejected", "rejected") ? "（未落地）" : ""}
          </b>
          {pickItem(it, "原因", "reason") ? <span>{pickItem(it, "原因", "reason")}</span> : null}
        </li>
      ))}
    </ul>
  );
}

function FiscalBlock({ data }: { data: any }) {
  if (isEmptyData(data) || !Array.isArray(data)) return <p className="extraction-empty">无</p>;
  return (
    <ul className="extraction-list">
      {data.map((it: any, i: number) => (
        <li key={i}>
          <b className={Number(pickItem(it, "增量", "delta")) >= 0 ? "good" : "bad"}>
            {fiscalKeyLabel(pickItem(it, "键", "key"))} {fmtDelta(pickItem(it, "增量", "delta"))}
          </b>
          {pickItem(it, "原因", "reason") ? <span>{pickItem(it, "原因", "reason")}</span> : null}
        </li>
      ))}
    </ul>
  );
}

// 一个字段值渲染成可读串：数字带正负号，文字直接显示（英文枚举翻中文）。
function fmtFieldVal(v: any): { text: string; tone: string } {
  if (typeof v === "number") return { text: fmtDelta(v), tone: v >= 0 ? "good" : "bad" };
  const n = Number(v);
  if (v !== "" && v != null && Number.isFinite(n) && String(v).trim() !== "" && !isNaN(n) && /^-?\d+$/.test(String(v).trim())) {
    return { text: fmtDelta(n), tone: n >= 0 ? "good" : "bad" };
  }
  return { text: cnValue(v), tone: "" };
}

// 地区/军队/势力变化：外层 key=实体 id（翻中文名），内层=字段→增量/新值。
function EntityDeltaBlock({ data, labelFn }: { data: any; labelFn: (id: any) => string }) {
  if (isEmptyData(data) || typeof data !== "object" || Array.isArray(data)) return <p className="extraction-empty">无</p>;
  return (
    <ul className="extraction-list">
      {Object.entries(data).map(([id, fields]: [string, any]) => (
        <li key={id}>
          <b>{labelFn(id)}</b>
          {fields && typeof fields === "object" && !Array.isArray(fields) ? (
            <span className="extraction-fieldline">
              {Object.entries(fields).map(([fk, fv]) => {
                const { text, tone } = fmtFieldVal(fv);
                return <em key={fk} className={tone}>{cnField(fk)} {text}</em>;
              })}
            </span>
          ) : (
            <span>{cnValue(fields)}</span>
          )}
        </li>
      ))}
    </ul>
  );
}

// 外交关系：key=势力 id（翻中文名），value=态度字符串。
function DiplomacyBlock({ data }: { data: any }) {
  if (isEmptyData(data) || typeof data !== "object" || Array.isArray(data)) return <p className="extraction-empty">无</p>;
  return (
    <ul className="extraction-kv">
      {Object.entries(data).map(([id, stance]: [string, any]) => (
        <li key={id}><span>{labelPower(id)}</span><b>{cnValue(stance)}</b></li>
      ))}
    </ul>
  );
}

// 阶级变化：key=阶级名 或 阶级@region_id；region 后缀翻中文名。value={满意,影响力} 增量。
const SAT_LEV_CN: Record<string, string> = { satisfaction: "满意", leverage: "影响力", 满意: "满意", 影响力: "影响力" };
function labelClass(key: string): string {
  const at = key.indexOf("@");
  if (at < 0) return key;
  return `${key.slice(0, at)}（${labelRegion(key.slice(at + 1))}）`;
}
function ClassDeltaBlock({ data }: { data: any }) {
  if (isEmptyData(data) || typeof data !== "object" || Array.isArray(data)) return <p className="extraction-empty">无</p>;
  return (
    <ul className="extraction-kv">
      {Object.entries(data).map(([k, v]: [string, any]) => {
        if (v && typeof v === "object") {
          return (
            <li key={k}>
              <span>{labelClass(k)}</span>
              <b>{Object.entries(v).map(([kk, vv]) => `${SAT_LEV_CN[kk] || cnField(kk)}${fmtDelta(vv)}`).join("  ")}</b>
            </li>
          );
        }
        return <li key={k}><span>{labelClass(k)}</span><b className={Number(v) >= 0 ? "good" : "bad"}>{fmtDelta(v)}</b></li>;
      })}
    </ul>
  );
}

// 人物易主：姓名 → 新势力（翻中文名）。
function PowerChangesBlock({ data }: { data: any }) {
  if (isEmptyData(data) || !Array.isArray(data)) return <p className="extraction-empty">无</p>;
  return (
    <ul className="extraction-list">
      {data.map((it: any, i: number) => (
        <li key={i}>
          <b>{pickItem(it, "姓名", "name")} → {labelPower(pickItem(it, "new_power", "new_power"))}</b>
          {pickItem(it, "reason", "reason") || pickItem(it, "原因", "reason") ? <span>{pickItem(it, "reason", "reason") || pickItem(it, "原因", "reason")}</span> : null}
        </li>
      ))}
    </ul>
  );
}

// 密令副作用：active 密令的推演副作用。
function SecretSideBlock({ data }: { data: any }) {
  if (isEmptyData(data) || !Array.isArray(data)) return <p className="extraction-empty">无</p>;
  return (
    <ul className="extraction-list">
      {data.map((it: any, i: number) => (
        <li key={i}>
          <b>密令 #{pickItem(it, "密令编号", "order_id")}</b>
          <span>{pickItem(it, "推演备注", "sim_note") || ""}</span>
        </li>
      ))}
    </ul>
  );
}

// 密令核议：pending_review 密令结案判定。
function SecretCloseBlock({ data }: { data: any }) {
  if (isEmptyData(data) || !Array.isArray(data)) return <p className="extraction-empty">无</p>;
  return (
    <ul className="extraction-list">
      {data.map((it: any, i: number) => {
        const st = pickItem(it, "状态", "status");
        return (
          <li key={i}>
            <b className={st === "done" ? "good" : "bad"}>
              密令 #{pickItem(it, "密令编号", "order_id")} {st === "done" ? "办结" : "失败"}
            </b>
            <span>{pickItem(it, "结果", "result") || ""}</span>
          </li>
        );
      })}
    </ul>
  );
}

function NewArmiesBlock({ data }: { data: any }) {
  if (isEmptyData(data) || !Array.isArray(data)) return <p className="extraction-empty">无</p>;
  return (
    <ul className="extraction-list">
      {data.map((item: any, i: number) => {
        const name = pickItem(item, "名称", "name") || pickItem(item, "编号", "id") || "?";
        const owner = labelPower(pickItem(item, "归属", "owner_power")) || "?";
        const manpower = pickItem(item, "人数", "manpower");
        const station = pickItem(item, "驻扎地", "station") || "";
        const commander = pickItem(item, "统将", "commander") || "";
        return (
          <li key={i}>
            <b>{name}</b>（归属：{owner}）{manpower ? ` · ${manpower}人` : ""}
            <span>{station}{commander ? ` · ${commander}` : ""}</span>
          </li>
        );
      })}
    </ul>
  );
}

function PreviousSummary({ summary }: { summary: string }) {
  if (!summary) {
    return <p className="long-copy">登基伊始，尚无上月回奏。</p>;
  }
  const lines = summary.split("\n").map((line) => line.trim()).filter(Boolean);
  const rows = lines
    .map((line) => {
      const idx = line.indexOf("：");
      if (idx <= 0) return null;
      return { label: line.slice(0, idx), value: line.slice(idx + 1) };
    })
    .filter((row): row is { label: string; value: string } => !!row && !!row.value);

  if (!rows.length) {
    return <p className="long-copy">{summary}</p>;
  }

  return (
    <table className="summary-table">
      <tbody>
        {rows.map((row) => (
          <tr key={row.label}>
            <th>{row.label}</th>
            <td>{row.value}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function StateModal({ state }: { state: GameState }) {
  const report = state.last_report || state.previous_summary;
  return (
    <article className="state-document modal-scroll">
      <section className="document-section">
        {report
          ? <pre className="memorial-text">{report}</pre>
          : <div className="empty-note">尚无上月奏报。</div>}
      </section>
    </article>
  );
}

function BriefReport({ title, items }: { title: string; items: string[] }) {
  return (
    <article>
      <h2>{title}</h2>
      <ul className="brief-list">
        {items.map((item) => <li key={`${title}-${item}`}>{item}</li>)}
      </ul>
    </article>
  );
}

function SituationPanel({
  issues,
  closedIssues,
  hasLegacies,
}: {
  issues: Issue[];
  closedIssues: ClosedIssue[];
  hasLegacies: boolean;
}) {
  const active = issues.filter((issue) => issue.kind === "situation" || issue.kind === "initiative");
  const [collapsed, setCollapsed] = React.useState(false);
  if (!active.length && !closedIssues.length) return null;
  const bySeq = (a: Issue, b: Issue) => {
    if (a.kind !== b.kind) return a.kind === "initiative" ? -1 : 1;
    return a.id - b.id;
  };
  // 长期局势＝贯穿一朝的大计（甲申国亡前不结案），靠 fail_condition 文案判定，纯前端分组。
  const isLongTerm = (issue: Issue) => /甲申|贯穿一朝|倾国之大计/.test(issue.fail_condition || "");
  const longTerm = active.filter(isLongTerm).sort(bySeq);
  const nearTerm = active.filter((i) => !isLongTerm(i)).sort(bySeq);
  return (
    <aside className={`situation-panel ${collapsed ? "collapsed" : ""} ${hasLegacies ? "with-legacies" : ""}`} aria-label="局势进度">
      <div className="situation-panel-title">
        <span>局势进度</span>
        <button
          type="button"
          className="situation-toggle"
          aria-label={collapsed ? "展开局势" : "收起局势"}
          onClick={() => setCollapsed((c) => !c)}
        >{collapsed ? "+" : "−"}</button>
      </div>
      {!collapsed && closedIssues.length ? (
        <div className="situation-closed-list">
          {closedIssues.map((ci) => (
            <div className={`situation-closed-row ${ci.status}`} key={`closed-${ci.id}`} tabIndex={0}>
              <div className="situation-closed-head">
                <span className="situation-closed-badge">{ci.status === "resolved" ? "已结案" : ci.status === "failed" ? "已崩坏" : "已撤"}</span>
                <span className="situation-closed-name">{ci.title}</span>
              </div>
              <div className="situation-closed-effect">{formatClosedEffect(ci.effect)}</div>
            </div>
          ))}
        </div>
      ) : null}
      {!collapsed && (longTerm.length ? (
        <div className="situation-group">
          <div className="situation-group-title">长期局势</div>
          <div className="situation-list">
            {longTerm.map((issue) => <SituationRow key={issue.id} issue={issue} />)}
          </div>
        </div>
      ) : null)}
      {!collapsed && (nearTerm.length ? (
        <div className="situation-group">
          <div className="situation-group-title">近期局势</div>
          <div className="situation-list">
            {nearTerm.map((issue) => <SituationRow key={issue.id} issue={issue} />)}
          </div>
        </div>
      ) : null)}
    </aside>
  );
}

function SituationRow({ issue }: { issue: Issue }) {
  return (
    <div className={`situation-row ${issueTone(issue.bar_value)}`} tabIndex={0}>
      <div className="situation-row-head">
        <span className="situation-name">{issue.title}</span>
        <b>{issue.bar_value}</b>
      </div>
      <div className="situation-bar">
        <i style={{ width: `${Math.max(0, Math.min(100, issue.bar_value))}%` }} />
      </div>
      <div className="situation-tip" role="tooltip">
        <div className="situation-tip-head">#{issue.id} {issue.title}</div>
        <div className="situation-tip-row"><span>阶段</span><b>{issue.phase}</b></div>
        <div className="situation-tip-row"><span>进度</span><b>{issue.bar_value} / 100</b></div>
        <div className="situation-tip-row">
          <span>月度推进</span>
          <b>{issue.inertia > 0 ? `+${issue.inertia}` : issue.inertia}/月</b>
        </div>
        <div className="situation-tip-row">
          <span>当前影响</span>
          <b>{issue.ongoing_text || "无"}</b>
        </div>
        <p className="situation-tip-stage">{issue.stage_text}</p>
        <div className="situation-tip-outcome good">
          <div className="situation-tip-outcome-head">达成（{issue.bar_good_meaning}）</div>
          {issue.resolve_condition && <p>{issue.resolve_condition}</p>}
          <div className="situation-tip-effect">{formatIssueEffect(issue.effect_on_resolve)}</div>
        </div>
        <div className="situation-tip-outcome bad">
          <div className="situation-tip-outcome-head">失败（{issue.bar_bad_meaning}）</div>
          {issue.fail_condition && <p>{issue.fail_condition}</p>}
          <div className="situation-tip-effect">{formatIssueEffect(issue.effect_on_fail)}</div>
        </div>
        {issue.tags.length ? (
          <div className="situation-tip-tags">
            {issue.tags.map((tag) => <small key={tag}>{tag}</small>)}
          </div>
        ) : null}
      </div>
    </div>
  );
}

function IssueGroup({ title, issues }: { title: string; issues: Issue[] }) {
  if (!issues.length) return null;
  return (
    <div className="issue-group">
      <h3>{title}</h3>
      <div className="issue-list">
        {issues.map((issue) => (
          <article className={`issue-line ${issueTone(issue.bar_value)}`} key={issue.id}>
            <div className="issue-head">
              <b>#{issue.id} {issue.title}</b>
              <span>{issue.phase} · {issue.bar_value}</span>
            </div>
            <div className="issue-progress" aria-label={`${issue.title}进度 ${issue.bar_value}`}>
              <span>{issue.bar_bad_meaning}</span>
              <div>
                <i style={{ width: `${Math.max(0, Math.min(100, issue.bar_value))}%` }} />
              </div>
              <span>{issue.bar_good_meaning}</span>
            </div>
            <p>{issue.stage_text}</p>
            {issue.tags.length ? (
              <div className="issue-tags">
                {issue.tags.map((tag) => <small key={tag}>{tag}</small>)}
              </div>
            ) : null}
          </article>
        ))}
      </div>
    </div>
  );
}

function ChatModal({
  minister,
  portraitPrefix,
  chat,
  suggestions,
  pendingUserMessage,
  streamingMinisterMessage,
  chatNotice,
  canUndoLastChat,
  composerHint,
  input,
  busy,
  error,
  secretOrders,
  onInput,
  onSend,
  onUndo,
  onHint,
  onFavorite,
  onOpenEdict,
  onClose,
}: {
  minister: Minister;
  portraitPrefix: string;
  chat: ChatMessage[];
  suggestions: Suggestion[];
  pendingUserMessage: string;
  streamingMinisterMessage: string;
  chatNotice: string;
  canUndoLastChat: boolean;
  composerHint: string;
  input: string;
  busy: string;
  error: string;
  secretOrders: SecretOrder[];
  onInput: (value: string) => void;
  onSend: (text?: string) => void;
  onUndo: () => void;
  onHint: (value: string) => void;
  onFavorite: () => void;
  onOpenEdict: () => void;
  onClose: () => void;
}) {
  const isCustom = minister.portrait_id?.startsWith("custom:");
  const portraitPrimary = isCustom
    ? `/portraits/custom/${encodeURIComponent(minister.name)}?t=${cacheBust(minister.portrait_id!)}`
    : `/portraits/${portraitPrefix}${minister.id ?? minister.name}.png`;
  const portraitFallback = !isCustom && minister.portrait_id
    ? `/portraits/${minister.portrait_id}.png`
    : undefined;
  const chatLogRef = React.useRef<HTMLDivElement | null>(null);
  const inputRef = React.useRef<HTMLTextAreaElement | null>(null);
  const displayMessages: ChatDisplayMessage[] = [...chat];

  if (pendingUserMessage) {
    displayMessages.push({ role: "user", content: pendingUserMessage, pending: true });
  }
  if (streamingMinisterMessage) {
    displayMessages.push({ role: "minister", content: streamingMinisterMessage, pending: true });
  }

  React.useEffect(() => {
    inputRef.current?.focus();
  }, [minister.name]);

  React.useEffect(() => {
    const node = chatLogRef.current;
    if (node) {
      node.scrollTop = node.scrollHeight;
    }
  }, [minister.name, chat, pendingUserMessage, streamingMinisterMessage, chatNotice, busy, error]);

  const handleSend = () => {
    onSend(input);
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== "Enter" || event.shiftKey) return;
    event.preventDefault();
    onSend(input);
  };

  const sendSuggestion = (suggestion: Suggestion) => {
    if (suggestion.prefix) {
      // 填前缀到输入框，不直接发送，光标跟到末尾
      onInput(suggestion.text);
      setTimeout(() => inputRef.current?.focus(), 0);
    } else {
      onSend(suggestion.text);
    }
  };

  return (
    <div className="chat-full-grid">
      <aside className="modal-pane minister-side">
        <div className="minister-profile">
          <div>
            <h2>{minister.name}</h2>
            <p>
              {minister.status !== "active" && (
                <span className={`minister-status status-${minister.status}`}>{minister.status_label}</span>
              )}
              {minister.office && <span className="profile-office">{minister.office}</span>}
            </p>
          </div>
          <button className="icon-button" aria-label="收藏大臣" onClick={onFavorite}>
            <Star size={16} fill={minister.favorite ? "currentColor" : "none"} />
          </button>
        </div>
        <p className="profile-copy">{minister.summary}</p>
        <button className="secondary-action" onClick={onOpenEdict}>
          <ScrollText size={15} />
          转入诏书草案
        </button>
        <div className="chat-portrait-wrap">
          <MinisterPortrait primary={portraitPrimary} fallback={portraitFallback} name={minister.name} />
        </div>
        {secretOrders.length > 0 && (
          <div className="chat-secret-orders">
            <div className="secret-orders-label"><Lock size={12} />密令</div>
            {secretOrders.map((o) => (
              <div key={o.id} className="secret-order-item">
                <div className="secret-order-title">{o.title}</div>
                <div className="secret-order-meta">第 {o.year_issued} 年 {o.period_issued} 月下令</div>
                {o.content && <div className="secret-order-content">{o.content}</div>}
                {o.sim_note && <div className="secret-order-content"><b>月度动向：</b>{o.sim_note}</div>}
                {o.result && <div className="secret-order-content"><b>承办回报：</b>{o.result}</div>}
              </div>
            ))}
          </div>
        )}
      </aside>

      <section className="modal-pane chat-main">
        <div className="chat-log" ref={chatLogRef}>
          {displayMessages.map((message, index) => (
            <div className={`chat-message ${message.role} ${message.pending ? "pending" : ""}`} key={`${message.role}-${index}-${message.content}`}>
              <span>{message.role === "user" ? "朕" : minister.name}</span>
              <p>{message.content}</p>
            </div>
          ))}
          {busy && !streamingMinisterMessage && (
            <div className="chat-message minister thinking">
              <span>{minister.name}</span>
              <p><Loader2 size={14} />大臣思索中...</p>
            </div>
          )}
          {chatNotice && <div className="chat-system-note">{chatNotice}</div>}
          {error && <div className="chat-system-note danger" role="alert">{error}</div>}
        </div>
        <div className="chat-composer">
          <div className="hitl-bar">
            {suggestions.map((suggestion) => (
              <button
                key={`${suggestion.label}-${suggestion.text}`}
                onClick={() => sendSuggestion(suggestion)}
                disabled={!!busy}
                title={suggestion.prefix ? `填入前缀：${suggestion.text}` : suggestion.text}
                className={suggestion.prefix ? "hitl-prefix" : ""}
              >
                {suggestion.label}
              </button>
            ))}
          </div>
          <label className="chat-input">
            <span>问话</span>
            <textarea
              ref={inputRef}
              value={input}
              onChange={(event) => {
                onInput(event.target.value);
                if (composerHint) onHint("");
              }}
              onKeyDown={handleKeyDown}
              placeholder="问大臣军情、钱粮、地方，或要求他拟旨... Enter 发送，Shift+Enter 换行"
            />
          </label>
          <div className="composer-actions">
            <button className={`primary-action ${!input.trim() ? "is-empty" : ""}`} onClick={handleSend} disabled={!!busy}>
              <Send size={15} />
              发送
            </button>
            <button className="secondary-action composer-undo" onClick={onUndo} disabled={!!busy || !canUndoLastChat}>
              <RotateCcw size={15} />
              撤回本轮
            </button>
            <button className="secondary-action composer-exit" onClick={onClose}>
              <X size={15} />
              退出召对
            </button>
            {composerHint && <div className="composer-hint">{composerHint}</div>}
          </div>
        </div>
      </section>
    </div>
  );
}

function EdictModal({
  state,
  directiveText,
  editingDirectiveId,
  editingDirectiveText,
  decree,
  report,
  busy,
  error,
  onDirectiveTextChange,
  onEditingTextChange,
  onCreateDirective,
  onStartEdit,
  onCancelEdit,
  onSaveDirective,
  onDeleteDirective,
  onWriteDecree,
  onSaveDecree,
  onResetDecree,
  onIssueDecree,
  onConfirmDirective,
  onRejectDirective,
}: {
  state: GameState;
  directiveText: string;
  editingDirectiveId: number | null;
  editingDirectiveText: string;
  decree: string;
  report: string;
  busy: string;
  error: string;
  onDirectiveTextChange: (value: string) => void;
  onEditingTextChange: (value: string) => void;
  onCreateDirective: () => void;
  onStartEdit: (directive: Directive) => void;
  onCancelEdit: () => void;
  onSaveDirective: (directive: Directive) => void;
  onDeleteDirective: (directiveId: number) => void;
  onWriteDecree: () => void;
  onSaveDecree: (text: string) => void;
  onResetDecree: () => void;
  onIssueDecree: () => void;
  onConfirmDirective: (directiveId: number) => void;
  onRejectDirective: (directiveId: number) => void;
}) {
  const pendingDirectives = state.directives.filter((d) => d.status === "pending");
  const draftDirectives = state.directives.filter((d) => d.status !== "pending");
  const hasPending = pendingDirectives.length > 0;
  const [decreeDraft, setDecreeDraft] = React.useState(decree);
  React.useEffect(() => {
    setDecreeDraft(decree);
  }, [decree]);

  // 分幕：随 decree/report 态切。无诏文=御案理政；有诏文未结算=诏书御览；已结算=颁诏奏章。
  const phase: "desk" | "review" | "issued" = report ? "issued" : decree ? "review" : "desk";

  if (phase === "issued") {
    return (
      <div className="edict-stage edict-stage-issued">
        {error && <div className="error-line" role="alert">{error}</div>}
        <DecreeScroll text={decree} sealed />
        {report ? (
          <section className="edict-gazette">
            <h2>月末奏章</h2>
            <pre>{report}</pre>
          </section>
        ) : null}
      </div>
    );
  }

  if (phase === "review") {
    return (
      <div className="edict-stage edict-stage-review">
        {busy && <div className="busy-line"><Loader2 size={15} />{busy}...</div>}
        {error && <div className="error-line" role="alert">{error}</div>}
        <DecreeScroll text={decreeDraft} editable onChange={setDecreeDraft} />
        <div className="edict-review-bar">
          <button
            className="seal-btn-ghost"
            onClick={onResetDecree}
            disabled={!!busy}
          >
            <Edit3 size={15} />返工改稿
          </button>
          {decreeDraft !== decree && (
            <button
              className="seal-btn-save"
              onClick={() => onSaveDecree(decreeDraft)}
              disabled={!!busy || !decreeDraft.trim()}
            >
              <Check size={15} />存改
            </button>
          )}
          <button
            className="seal-btn-issue"
            onClick={onIssueDecree}
            disabled={!!busy || decreeDraft !== decree}
            title={decreeDraft !== decree ? "请先存改诏文" : "盖玉玺，诏告天下"}
          >
            盖玺颁布
          </button>
        </div>
      </div>
    );
  }

  // phase === "desk"：御案理政
  return (
    <div className="edict-stage edict-stage-desk">
      <div className="desk-columns">
        <section className="desk-pane desk-memorials">
          {hasPending && (
            <div className="pending-directives" role="region" aria-label="待核定大臣拟旨">
              <h3>朱批待定 · 大臣拟旨（{pendingDirectives.length}）</h3>
              {pendingDirectives.map((directive) => (
                <div className="directive-item pending" key={directive.id}>
                  <div className="directive-head">
                    <b>#{directive.id}</b>
                    <span>{directive.source}</span>
                  </div>
                  <p>{directive.text}</p>
                  {directive.notes ? <small>{directive.notes}</small> : null}
                  <div className="directive-tools">
                    <button className="vermilion-yes" onClick={() => onConfirmDirective(directive.id)} disabled={!!busy}><Check size={14} />准</button>
                    <button className="vermilion-no" onClick={() => onRejectDirective(directive.id)} disabled={!!busy}><X size={14} />驳</button>
                  </div>
                </div>
              ))}
            </div>
          )}
          <h2>本月指令{draftDirectives.length ? ` · ${draftDirectives.length} 道` : ""}</h2>
          <div className="directive-list">
            {draftDirectives.map((directive) => (
              <div className="directive-item" key={directive.id}>
                <div className="directive-head">
                  <b>#{directive.id}</b>
                  <span>{directive.source}</span>
                </div>
                {editingDirectiveId === directive.id ? (
                  <div className="directive-edit">
                    <textarea value={editingDirectiveText} onChange={(event) => onEditingTextChange(event.target.value)} />
                    <div>
                      <button className="icon-button" onClick={() => onSaveDirective(directive)} aria-label="保存草案"><Check size={15} /></button>
                      <button className="icon-button" onClick={onCancelEdit} aria-label="取消修改"><X size={15} /></button>
                    </div>
                  </div>
                ) : (
                  <>
                    <p>{directive.text}</p>
                    {directive.notes ? <small>{directive.notes}</small> : null}
                    <div className="directive-tools">
                      <button onClick={() => onStartEdit(directive)}><Edit3 size={14} />改</button>
                      <button onClick={() => onDeleteDirective(directive.id)}><Trash2 size={14} />删</button>
                    </div>
                  </>
                )}
              </div>
            ))}
            {!draftDirectives.length && !hasPending && <div className="empty-note">本月不可空过。请先召见大臣，或在右侧御笔自拟一道指令。</div>}
          </div>
        </section>

        <section className="desk-pane desk-compose">
          <h2>御笔自拟</h2>
          <textarea
            value={directiveText}
            onChange={(event) => onDirectiveTextChange(event.target.value)}
            placeholder="例如：命毕自严核拨关宁、山海关、蓟镇辽饷一百五十二万两..."
          />
          <button className="desk-add-btn" onClick={onCreateDirective} disabled={!!busy || !directiveText.trim()}>
            <Edit3 size={14} />新增草案
          </button>
          {busy && <div className="busy-line"><Loader2 size={15} />{busy}...</div>}
          {error && <div className="error-line" role="alert">{error}</div>}
        </section>
      </div>

      <div className="desk-footer">
        {hasPending && <small className="pending-hint">尚有 {pendingDirectives.length} 道大臣拟旨待朱批（准/驳），核定后方可拟诏。</small>}
        <button
          className="seal-btn-compose"
          onClick={onWriteDecree}
          disabled={!!busy || !draftDirectives.length || hasPending}
        >
          拟诏 →
        </button>
      </div>
    </div>
  );
}

// 明黄诏书卷轴：竖排右起，古制体例。editable 时点开变 textarea 改稿。
function DecreeScroll({
  text,
  editable,
  sealed,
  onChange,
}: {
  text: string;
  editable?: boolean;
  sealed?: boolean;
  onChange?: (value: string) => void;
}) {
  const [editing, setEditing] = React.useState(false);
  return (
    <div className={`decree-scroll${sealed ? " sealed" : ""}`}>
      <div className="decree-scroll-knob top" aria-hidden="true" />
      <div className="decree-scroll-paper">
        {editable && editing ? (
          <textarea
            className="decree-scroll-edit"
            value={text}
            autoFocus
            onChange={(event) => onChange?.(event.target.value)}
            onBlur={() => setEditing(false)}
          />
        ) : (
          <div
            className="decree-scroll-body"
            onClick={editable ? () => setEditing(true) : undefined}
            title={editable ? "点此朱笔改稿" : undefined}
          >
            {text || "（诏文待拟）"}
          </div>
        )}
        {sealed ? <div className="decree-seal-mark" aria-hidden="true">勅</div> : null}
      </div>
      <div className="decree-scroll-knob bottom" aria-hidden="true" />
    </div>
  );
}

// 官职品级权重，数字越小品级越高（排越前）
function officeRank(office: string): number {
  if (/首辅/.test(office)) return 1;
  if (/次辅/.test(office)) return 2;
  if (/大学士/.test(office)) return 3;
  if (/尚书/.test(office)) return 4;
  if (/侍郎/.test(office)) return 5;
  if (/都御史|巡抚|总督/.test(office)) return 6;
  if (/郎中/.test(office)) return 8;
  return 9;
}

function filterMinisters(ministers: Minister[], group: string) {
  const courtMinisters = ministers.filter((m) => (m.power_id || "ming") === "ming");
  if (group === "内阁+六部" || group === "内阁" || group === "六部") {
    return courtMinisters
      .filter((m) =>
        (m.office_type === "内阁" || ["吏部", "户部", "礼部", "兵部", "刑部", "工部"].includes(m.office_type))
        && m.status === "active"
        && !!(m.office || "").trim()
        && !/前|罢|致仕/.test(m.office || "")  // 无实职不排朝班
      )
      .sort((a, b) => officeRank(a.office || "") - officeRank(b.office || ""));
  }
  if (group === "在职") return courtMinisters.filter((m) => m.status === "active");
  if (group === "收藏") return courtMinisters.filter((minister) => minister.favorite);
  return courtMinisters;
}

function filterConsorts(consorts: Minister[], group: string) {
  const mingConsorts = consorts.filter((c) => (c.power_id || "ming") === "ming");
  if (group === "收藏") return mingConsorts.filter((c) => c.favorite);
  return mingConsorts;
}

const MING_MAP_COLOR = "#4f8a57";
const UNREST_MAP_COLOR = "#b83a31";
const EXTERNAL_MAP_COLOR = "#5f6366";
const DEFAULT_MAP_COLOR = EXTERNAL_MAP_COLOR;
const UNREST_DANGER_THRESHOLD = 60;
const MING_MAP_OPACITY = 0.2;
const EXTERNAL_MAP_OPACITY = 0.3;

const MAP_DISPLAY_POWER_OVERRIDES: Record<string, string> = {
  // 崇祯元年辽西只剩山海关外宁锦前线，不能按关内省份红色处理。
  liaodong: "ming_frontier",
};

const THEATER_ONLY_REGION_IDS = new Set(["liaodong"]);
const THEATER_COORD_STORAGE_KEY = "ming-map-theater-coords";
const MAP_PENCIL_STORAGE_KEY = "ming-map-pencil-line";
const MAP_TERRAIN_STORAGE_KEY = "ming-map-terrain-transform-v3";

type TerrainTransform = { x: number; y: number; width: number; height: number };

const DEFAULT_TERRAIN_TRANSFORM: TerrainTransform = {
  x: 840.22,
  y: 83.48,
  width: 276,
  height: 206,
};

function getRegionMapColor(region: RegionPathRenderItem) {
  if (region.controlledBy !== "ming") return EXTERNAL_MAP_COLOR;
  if (region.unrest > UNREST_DANGER_THRESHOLD) return UNREST_MAP_COLOR;
  return MING_MAP_COLOR;
}

function getRegionMapOpacity(region: RegionPathRenderItem) {
  return region.controlledBy === "ming" ? MING_MAP_OPACITY : EXTERNAL_MAP_OPACITY;
}

function GrandMap({ nodes, selectedId, onSelect }: { nodes: MapNode[]; selectedId: string; onSelect: (id: string) => void }) {
  const viewportRef = React.useRef<HTMLDivElement | null>(null);
  const mapTileRef = React.useRef<HTMLDivElement | null>(null);
  const svgRef = React.useRef<SVGSVGElement | null>(null);
  const didCenterRef = React.useRef(false);
  const viewBoxParts = React.useMemo(() => MAP_VIEW_BOX.split(/\s+/).map(Number), []);
  const defaultTerrainTransform = DEFAULT_TERRAIN_TRANSFORM;

  // 坐标取点工具：URL 加 ?coords=1 开启。点地图打印 x/y% 与 SVG viewBox 坐标。
  const coordPick = typeof window !== "undefined" && new URLSearchParams(window.location.search).has("coords");
  const [pick, setPick] = React.useState<{ x: number; y: number; svgX: number; svgY: number; label?: string } | null>(null);
  const [draggedTheaters, setDraggedTheaters] = React.useState<Record<string, { x: number; y: number }>>(() => {
    if (typeof window === "undefined") return {};
    try {
      const raw = window.localStorage.getItem(THEATER_COORD_STORAGE_KEY);
      if (!raw) return {};
      const parsed = JSON.parse(raw) as Record<string, { x: number; y: number }>;
      return parsed && typeof parsed === "object" ? parsed : {};
    } catch {
      return {};
    }
  });
  const [pencilMode, setPencilMode] = React.useState(false);
  const [terrainMode, setTerrainMode] = React.useState(coordPick);
  const [terrainTransform, setTerrainTransform] = React.useState<TerrainTransform>(() => {
    if (typeof window === "undefined") return defaultTerrainTransform;
    try {
      const raw = window.localStorage.getItem(MAP_TERRAIN_STORAGE_KEY);
      if (!raw) return defaultTerrainTransform;
      const parsed = JSON.parse(raw) as TerrainTransform;
      if (
        parsed &&
        Number.isFinite(parsed.x) &&
        Number.isFinite(parsed.y) &&
        Number.isFinite(parsed.width) &&
        Number.isFinite(parsed.height) &&
        parsed.width > 0 &&
        parsed.height > 0
      ) {
        return parsed;
      }
    } catch {}
    return defaultTerrainTransform;
  });
  const [pencilLine, setPencilLine] = React.useState<Array<{ x: number; y: number; svgX: number; svgY: number }>>(() => {
    if (typeof window === "undefined") return [];
    try {
      const raw = window.localStorage.getItem(MAP_PENCIL_STORAGE_KEY);
      if (!raw) return [];
      const parsed = JSON.parse(raw) as Array<{ x: number; y: number; svgX: number; svgY: number }>;
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [];
    }
  });
  const [mapZoom, setMapZoom] = React.useState(1);
  const [svgLabelPositions, setSvgLabelPositions] = React.useState<Record<string, SvgLabelPosition>>({});
  const dragRef = React.useRef<{ id: string; pointerId: number; moved: boolean } | null>(null);
  // 地图 pan：translate 平移代替 overflow:auto 滚动（兼容 matrix3d 透视外框）
  const [pan, setPan] = React.useState({ x: 0, y: 0 });
  const panDragRef = React.useRef<{ pointerId: number; startX: number; startY: number; startPanX: number; startPanY: number; moved: boolean } | null>(null);
  const onMapPanDown = React.useCallback((e: React.PointerEvent) => {
    if (coordPick) return;  // 调试模式不抢拖动
    // 不立即 capture：等 move 超阈值才算拖动，否则点击（省份/节点）能正常穿透
    panDragRef.current = { pointerId: e.pointerId, startX: e.clientX, startY: e.clientY, startPanX: pan.x, startPanY: pan.y, moved: false };
  }, [coordPick, pan.x, pan.y]);
  const onMapPanMove = React.useCallback((e: React.PointerEvent) => {
    const d = panDragRef.current;
    if (!d || d.pointerId !== e.pointerId) return;
    const dx = e.clientX - d.startX, dy = e.clientY - d.startY;
    if (!d.moved && Math.abs(dx) + Math.abs(dy) > 4) {
      d.moved = true;
      // 真拖动了才 capture，独占后续 pointer
      try { (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId); } catch {}
    }
    if (!d.moved) return;  // 未达拖动阈值，不动地图，让 click 穿透
    // 钳制：地图始终盖满地图框，不露底图（按当前 zoom 算超出量）
    setPan(clampPanRef.current(d.startPanX + dx, d.startPanY + dy));
  }, []);
  const onMapPanUp = React.useCallback((e: React.PointerEvent) => {
    const d = panDragRef.current;
    if (!d || d.pointerId !== e.pointerId) return;
    try { (e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId); } catch {}
    panDragRef.current = null;
  }, []);
  // 玩家缩放（滚轮，以光标为中心）。map-tile transform = translate(pan) scale(userZoom)
  const [userZoom, setUserZoom] = React.useState(1);
  const ZOOM_MIN = 1, ZOOM_MAX = 3;
  const clampPan = React.useCallback((nx: number, ny: number, zoom: number) => {
    const board = mapTileRef.current, vp = viewportRef.current;
    if (!board || !vp) return { x: nx, y: ny };
    const mw = board.offsetWidth * zoom, mh = board.offsetHeight * zoom;
    // 地图比框大：钳制在 [-(超出量), 0]；地图比框小：锁定居中
    const clampAxis = (v: number, mapSize: number, frameSize: number) => {
      if (mapSize >= frameSize) return Math.min(0, Math.max(-(mapSize - frameSize), v));
      return (frameSize - mapSize) / 2;  // 居中
    };
    return {
      x: clampAxis(nx, mw, vp.clientWidth),
      y: clampAxis(ny, mh, vp.clientHeight),
    };
  }, []);
  // ref 持最新 clampPan(带当前zoom)，给 deps=[] 的 pan move 用
  const clampPanRef = React.useRef((nx: number, ny: number) => ({ x: nx, y: ny }));
  React.useEffect(() => {
    clampPanRef.current = (nx: number, ny: number) => clampPan(nx, ny, userZoom);
  }, [clampPan, userZoom]);
  const onMapWheel = React.useCallback((e: React.WheelEvent) => {
    if (coordPick) return;
    e.preventDefault();
    const vp = viewportRef.current;
    if (!vp) return;
    const rect = vp.getBoundingClientRect();
    const cx = e.clientX - rect.left, cy = e.clientY - rect.top;  // 光标在 viewport 内坐标
    setUserZoom((z) => {
      const nz = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, z * (e.deltaY < 0 ? 1.12 : 1 / 1.12)));
      if (nz === z) return z;
      // 保持光标下的地图点不动：pan' = cursor - (cursor - pan) * nz/z
      setPan((p) => {
        const k = nz / z;
        const nx = cx - (cx - p.x) * k;
        const ny = cy - (cy - p.y) * k;
        return clampPan(nx, ny, nz);
      });
      return nz;
    });
  }, [coordPick, clampPan]);
  const pencilDragRef = React.useRef<{ pointerId: number } | null>(null);
  const terrainDragRef = React.useRef<{ pointerId: number; startSvgX: number; startSvgY: number; start: TerrainTransform } | null>(null);
  const svgCoordFromPct = React.useCallback((x: number, y: number) => ({
    svgX: +(viewBoxParts[0] + (x / 100) * viewBoxParts[2]).toFixed(2),
    svgY: +(viewBoxParts[1] + (y / 100) * viewBoxParts[3]).toFixed(2),
  }), [viewBoxParts]);
  const pickFromClient = React.useCallback((clientX: number, clientY: number, label?: string) => {
    const rect = mapTileRef.current?.getBoundingClientRect();
    if (!rect) return null;
    const x = +(((clientX - rect.left) / rect.width) * 100).toFixed(2);
    const y = +(((clientY - rect.top) / rect.height) * 100).toFixed(2);
    const clampedX = Math.min(100, Math.max(0, x));
    const clampedY = Math.min(100, Math.max(0, y));
    const svg = svgCoordFromPct(clampedX, clampedY);
    return { x: clampedX, y: clampedY, ...svg, label };
  }, [svgCoordFromPct]);
  const saveDraggedTheater = React.useCallback((id: string, pos: { x: number; y: number }) => {
    setDraggedTheaters((current) => {
      const next = { ...current, [id]: pos };
      try {
        window.localStorage.setItem(THEATER_COORD_STORAGE_KEY, JSON.stringify(next));
      } catch {}
      return next;
    });
  }, []);
  const saveTerrainTransform = React.useCallback((transform: TerrainTransform) => {
    setTerrainTransform(transform);
    try {
      window.localStorage.setItem(MAP_TERRAIN_STORAGE_KEY, JSON.stringify(transform));
    } catch {}
  }, []);
  const resizeTerrain = React.useCallback((factor: number) => {
    setTerrainTransform((current) => {
      const nextWidth = +(current.width * factor).toFixed(2);
      const nextHeight = +(current.height * factor).toFixed(2);
      const centerX = current.x + current.width / 2;
      const centerY = current.y + current.height / 2;
      const next = {
        x: +(centerX - nextWidth / 2).toFixed(2),
        y: +(centerY - nextHeight / 2).toFixed(2),
        width: nextWidth,
        height: nextHeight,
      };
      try {
        window.localStorage.setItem(MAP_TERRAIN_STORAGE_KEY, JSON.stringify(next));
      } catch {}
      return next;
    });
  }, []);
  const savePencilLine = React.useCallback((line: Array<{ x: number; y: number; svgX: number; svgY: number }>) => {
    setPencilLine(line);
    try {
      window.localStorage.setItem(MAP_PENCIL_STORAGE_KEY, JSON.stringify(line));
    } catch {}
  }, []);
  const addPencilPoint = React.useCallback((point: { x: number; y: number; svgX: number; svgY: number }) => {
    setPencilLine((current) => {
      const last = current[current.length - 1];
      if (last) {
        const dx = point.svgX - last.svgX;
        const dy = point.svgY - last.svgY;
        if (Math.hypot(dx, dy) < 1.2) return current;
      }
      const next = [...current, point];
      try {
        window.localStorage.setItem(MAP_PENCIL_STORAGE_KEY, JSON.stringify(next));
      } catch {}
      return next;
    });
  }, []);
  const onPickClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!coordPick || pencilMode) return;
    const next = pickFromClient(e.clientX, e.clientY);
    if (!next) return;
    setPick(next);
    console.log(`map pct: (${next.x}, ${next.y}) svg: (${next.svgX}, ${next.svgY})`);
  };
  const onPencilPointerDown = (ev: React.PointerEvent<HTMLDivElement>) => {
    if (!coordPick || !pencilMode) return;
    ev.preventDefault();
    ev.stopPropagation();
    const next = pickFromClient(ev.clientX, ev.clientY, "铅笔");
    if (!next) return;
    pencilDragRef.current = { pointerId: ev.pointerId };
    ev.currentTarget.setPointerCapture(ev.pointerId);
    const point = { x: next.x, y: next.y, svgX: next.svgX, svgY: next.svgY };
    savePencilLine([point]);
    setPick(next);
  };
  const onPencilPointerMove = (ev: React.PointerEvent<HTMLDivElement>) => {
    const drag = pencilDragRef.current;
    if (!coordPick || !pencilMode || !drag || drag.pointerId !== ev.pointerId) return;
    ev.preventDefault();
    ev.stopPropagation();
    const next = pickFromClient(ev.clientX, ev.clientY, "铅笔");
    if (!next) return;
    addPencilPoint({ x: next.x, y: next.y, svgX: next.svgX, svgY: next.svgY });
    setPick(next);
  };
  const onPencilPointerUp = (ev: React.PointerEvent<HTMLDivElement>) => {
    const drag = pencilDragRef.current;
    if (!coordPick || !pencilMode || !drag || drag.pointerId !== ev.pointerId) return;
    ev.preventDefault();
    ev.stopPropagation();
    try { ev.currentTarget.releasePointerCapture(ev.pointerId); } catch {}
    pencilDragRef.current = null;
    console.log(`pencil svg line: ${JSON.stringify(pencilLine.map((point) => [point.svgX, point.svgY]))}`);
  };
  const onTerrainPointerDown = (ev: React.PointerEvent<SVGImageElement>) => {
    if (!coordPick || !terrainMode) return;
    ev.preventDefault();
    ev.stopPropagation();
    const next = pickFromClient(ev.clientX, ev.clientY, "底图");
    if (!next) return;
    terrainDragRef.current = {
      pointerId: ev.pointerId,
      startSvgX: next.svgX,
      startSvgY: next.svgY,
      start: terrainTransform,
    };
    ev.currentTarget.setPointerCapture(ev.pointerId);
    setPick(next);
  };
  const onTerrainPointerMove = (ev: React.PointerEvent<SVGImageElement>) => {
    const drag = terrainDragRef.current;
    if (!coordPick || !terrainMode || !drag || drag.pointerId !== ev.pointerId) return;
    ev.preventDefault();
    ev.stopPropagation();
    const next = pickFromClient(ev.clientX, ev.clientY, "底图");
    if (!next) return;
    saveTerrainTransform({
      ...drag.start,
      x: +(drag.start.x + next.svgX - drag.startSvgX).toFixed(2),
      y: +(drag.start.y + next.svgY - drag.startSvgY).toFixed(2),
    });
    setPick(next);
  };
  const onTerrainPointerUp = (ev: React.PointerEvent<SVGImageElement>) => {
    const drag = terrainDragRef.current;
    if (!coordPick || !terrainMode || !drag || drag.pointerId !== ev.pointerId) return;
    ev.preventDefault();
    ev.stopPropagation();
    try { ev.currentTarget.releasePointerCapture(ev.pointerId); } catch {}
    terrainDragRef.current = null;
  };
  const onTheaterPointerDown = (node: MapNode) => (ev: React.PointerEvent<HTMLButtonElement>) => {
    if (!coordPick || node.kind !== "theater") return;
    ev.preventDefault();
    ev.stopPropagation();
    dragRef.current = { id: node.id, pointerId: ev.pointerId, moved: false };
    ev.currentTarget.setPointerCapture(ev.pointerId);
    const next = pickFromClient(ev.clientX, ev.clientY, node.label || node.id);
    if (next) {
      saveDraggedTheater(node.id, { x: next.x, y: next.y });
      setPick(next);
    }
  };
  const onTheaterPointerMove = (node: MapNode) => (ev: React.PointerEvent<HTMLButtonElement>) => {
    const drag = dragRef.current;
    if (!coordPick || !drag || drag.id !== node.id || drag.pointerId !== ev.pointerId) return;
    ev.preventDefault();
    ev.stopPropagation();
    drag.moved = true;
    const next = pickFromClient(ev.clientX, ev.clientY, node.label || node.id);
    if (!next) return;
    saveDraggedTheater(node.id, { x: next.x, y: next.y });
    setPick(next);
  };
  const onTheaterPointerUp = (node: MapNode) => (ev: React.PointerEvent<HTMLButtonElement>) => {
    const drag = dragRef.current;
    if (!coordPick || !drag || drag.id !== node.id || drag.pointerId !== ev.pointerId) return;
    ev.preventDefault();
    ev.stopPropagation();
    try { ev.currentTarget.releasePointerCapture(ev.pointerId); } catch {}
    const next = pickFromClient(ev.clientX, ev.clientY, node.label || node.id);
    if (next) {
      saveDraggedTheater(node.id, { x: next.x, y: next.y });
      setPick(next);
      console.log(`${node.id}: pct=(${next.x}, ${next.y}) svg=(${next.svgX}, ${next.svgY})`);
    }
    dragRef.current = null;
  };
  const changeMapZoom = React.useCallback((delta: number) => {
    setMapZoom((current) => Math.min(2.6, Math.max(0.8, +(current + delta).toFixed(2))));
  }, []);
  const nodeById = React.useMemo(() => new Map(nodes.map((node) => [node.id, node])), [nodes]);
  const regionPathItems = React.useMemo<RegionPathRenderItem[]>(
    () => REGION_PATH_GROUPS.filter((group) => !THEATER_ONLY_REGION_IDS.has(group.regionId)).map((group) => {
      const node = nodeById.get(group.regionId);
      return {
        id: group.regionId,
        name: node?.region?.name || group.regionId,
        controlledBy: MAP_DISPLAY_POWER_OVERRIDES[group.regionId] || String(node?.region?.controlled_by || "ming"),
        unrest: node?.region?.unrest || 0,
        risk: node?.risk || 0,
        labelX: node?.x ?? 50,
        labelY: node?.y ?? 50,
        paths: group.paths,
      };
    }),
    [nodeById],
  );
  const externalPathItems = React.useMemo<ExternalPathRenderItem[]>(
    () => {
      return EXTERNAL_PATH_GROUPS.filter((group) => group.paths.length > 0).map((group) => {
        const node = nodeById.get(group.id);
        return {
          ...group,
          labelX: node?.x ?? 50,
          labelY: node?.y ?? 50,
        };
      });
    },
    [nodeById],
  );

  React.useLayoutEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const next: Record<string, SvgLabelPosition> = {};
    const pathsByRegion = new Map<string, SVGGraphicsElement[]>();
    svg.querySelectorAll<SVGGraphicsElement>("path[data-region-id]").forEach((path) => {
      const id = path.getAttribute("data-region-id");
      if (!id) return;
      const current = pathsByRegion.get(id) || [];
      current.push(path);
      pathsByRegion.set(id, current);
    });
    for (const [id, paths] of pathsByRegion.entries()) {
      let minX = Number.POSITIVE_INFINITY;
      let minY = Number.POSITIVE_INFINITY;
      let maxX = Number.NEGATIVE_INFINITY;
      let maxY = Number.NEGATIVE_INFINITY;
      for (const path of paths) {
        const box = path.getBBox();
        if (!Number.isFinite(box.x) || !Number.isFinite(box.y) || box.width <= 0 || box.height <= 0) continue;
        minX = Math.min(minX, box.x);
        minY = Math.min(minY, box.y);
        maxX = Math.max(maxX, box.x + box.width);
        maxY = Math.max(maxY, box.y + box.height);
      }
      if (Number.isFinite(minX) && Number.isFinite(minY) && Number.isFinite(maxX) && Number.isFinite(maxY)) {
        next[id] = {
          svgX: +((minX + maxX) / 2).toFixed(2),
          svgY: +((minY + maxY) / 2).toFixed(2),
        };
      }
    }
    setSvgLabelPositions(next);
  }, [regionPathItems, externalPathItems]);

  React.useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport || didCenterRef.current) return;
    const board = viewport.querySelector<HTMLElement>(".map-tile");
    if (!board) return;
    didCenterRef.current = true;
    // 初始定位：河南居中（手动拖出的最佳位置，按地图尺寸比例，窗口无关）
    const INIT_FX = -0.1308, INIT_FY = -0.2895;
    setPan(clampPan(board.offsetWidth * INIT_FX, board.offsetHeight * INIT_FY, 1));
  }, [clampPan]);

  return (
    <section
      ref={viewportRef}
      className="grand-map"
      aria-label="大明地图"
      onPointerDown={onMapPanDown}
      onPointerMove={onMapPanMove}
      onPointerUp={onMapPanUp}
      onPointerCancel={onMapPanUp}
      onWheel={onMapWheel}
    >
      {coordPick ? (
        <div className="coord-toolbox">
          <button
            className={`coord-tool-button ${pencilMode ? "active" : ""}`}
            onClick={(ev) => {
              ev.stopPropagation();
              setPencilMode((current) => {
                const next = !current;
                if (next) setTerrainMode(false);
                return next;
              });
            }}
            aria-label="铅笔工具"
            title="铅笔工具"
          >
            <Pencil size={16} />
            <span>{pencilMode ? "铅笔开启" : "铅笔"}</span>
          </button>
          <button
            className="coord-tool-button"
            onClick={(ev) => {
              ev.stopPropagation();
              savePencilLine([]);
              console.log("pencil line cleared");
            }}
            aria-label="清除铅笔线"
            title="清除铅笔线"
          >
            <Eraser size={16} />
          </button>
          <button
            className={`coord-tool-button ${terrainMode ? "active" : ""}`}
            onClick={(ev) => {
              ev.stopPropagation();
              setTerrainMode((current) => {
                const next = !current;
                if (next) setPencilMode(false);
                return next;
              });
            }}
            aria-label="拖动底图"
            title="拖动底图"
          >
            <Move size={16} />
            <span>{terrainMode ? "底图开启" : "底图"}</span>
          </button>
          <button
            className="coord-tool-button icon-only"
            onClick={(ev) => {
              ev.stopPropagation();
              resizeTerrain(0.96);
            }}
            aria-label="缩小底图"
            title="缩小底图"
          >
            <ZoomOut size={16} />
          </button>
          <button
            className="coord-tool-button icon-only"
            onClick={(ev) => {
              ev.stopPropagation();
              resizeTerrain(1.04);
            }}
            aria-label="放大底图"
            title="放大底图"
          >
            <ZoomIn size={16} />
          </button>
          <button
            className="coord-tool-button icon-only"
            onClick={(ev) => {
              ev.stopPropagation();
              saveTerrainTransform(defaultTerrainTransform);
            }}
            aria-label="重置底图"
            title="重置底图"
          >
            <RotateCcw size={15} />
          </button>
          <button
            className="coord-tool-button icon-only"
            onClick={(ev) => {
              ev.stopPropagation();
              changeMapZoom(-0.15);
            }}
            aria-label="缩小地图"
            title="缩小地图"
          >
            <ZoomOut size={16} />
          </button>
          <span className="coord-zoom-readout">{Math.round(mapZoom * 100)}%</span>
          <button
            className="coord-tool-button icon-only"
            onClick={(ev) => {
              ev.stopPropagation();
              changeMapZoom(0.15);
            }}
            aria-label="放大地图"
            title="放大地图"
          >
            <ZoomIn size={16} />
          </button>
          <button
            className="coord-tool-button icon-only"
            onClick={(ev) => {
              ev.stopPropagation();
              setMapZoom(1);
            }}
            aria-label="重置缩放"
            title="重置缩放"
          >
            <RotateCcw size={15} />
          </button>
        </div>
      ) : null}
      <div
        className={`map-strip ${pencilMode ? "pencil-mode" : ""} ${terrainMode ? "terrain-mode" : ""}`}
        style={coordPick ? {
          width: `${1900 * mapZoom + 320}px`,
          height: `${(1900 * mapZoom * 206) / 276 + 240}px`,
        } : undefined}
        onClick={onPickClick}
        onPointerDown={onPencilPointerDown}
        onPointerMove={onPencilPointerMove}
        onPointerUp={onPencilPointerUp}
        onPointerCancel={onPencilPointerUp}
      >
        <div
          className="map-tile"
          ref={mapTileRef}
          style={coordPick
            ? { width: `${1900 * mapZoom}px` }
            : { transform: `translate(${pan.x}px, ${pan.y}px) scale(${userZoom})`, transformOrigin: "0 0" }}
        >
            <svg
              ref={svgRef}
              className="province-map-layer"
              viewBox={MAP_VIEW_BOX}
              preserveAspectRatio="xMinYMin meet"
            >
              <image
                className={`map-terrain-image ${coordPick && terrainMode ? "draggable" : ""}`}
                href="/ming-1627-terrain-map.png"
                x={terrainTransform.x}
                y={terrainTransform.y}
                width={terrainTransform.width}
                height={terrainTransform.height}
                preserveAspectRatio="xMidYMid slice"
                onPointerDown={onTerrainPointerDown}
                onPointerMove={onTerrainPointerMove}
                onPointerUp={onTerrainPointerUp}
                onPointerCancel={onTerrainPointerUp}
              />
              {externalPathItems.map((group) => {
                const selected = selectedId === group.id;
                const fill = EXTERNAL_MAP_COLOR;
                return (
                  <g
                    key={`${group.id}:external-paths`}
                    className={`province-external power-${group.powerId} ${selected ? "selected" : ""}`}
                    data-external-id={group.id}
                    style={{ "--province-fill": fill } as React.CSSProperties}
                  >
                    {group.paths.map((path) => (
                      <path
                        key={`${group.id}:${path.id}`}
                        data-map-path-id={path.id}
                        data-region-id={group.id}
                        fill={fill}
                        fillOpacity={EXTERNAL_MAP_OPACITY}
                        d={path.d}
                        onClick={(ev) => {
                          ev.stopPropagation();
                          ev.currentTarget.blur();
                          onSelect(group.id);
                        }}
                        role="button"
                        aria-label={`查看${group.name}`}
                        onKeyDown={(ev) => {
                          if (ev.key === "Enter" || ev.key === " ") {
                            ev.preventDefault();
                            onSelect(group.id);
                          }
                        }}
                      >
                        <title>{group.name}</title>
                      </path>
                    ))}
                  </g>
                );
              })}
              {regionPathItems.map((region) => {
                const selected = selectedId === region.id;
                const fill = getRegionMapColor(region);
                return (
                  <g
                    key={`${region.id}:paths`}
                    data-region-id={region.id}
                    className={`province-region power-${region.controlledBy} ${selected ? "selected" : ""} ${region.controlledBy === "ming" && region.unrest > UNREST_DANGER_THRESHOLD ? "danger" : ""}`}
                    style={{ "--province-fill": fill } as React.CSSProperties}
                  >
                    {region.paths.map((path) => (
                      <path
                        key={path.id}
                        data-map-path-id={path.id}
                        data-region-id={region.id}
                        fill={fill}
                        fillOpacity={getRegionMapOpacity(region)}
                        d={path.d}
                        onClick={(ev) => {
                          ev.stopPropagation();
                          ev.currentTarget.blur();
                          onSelect(region.id);
                        }}
                        role="button"
                        aria-label={`查看${region.name}`}
                        onKeyDown={(ev) => {
                          if (ev.key === "Enter" || ev.key === " ") {
                            ev.preventDefault();
                            onSelect(region.id);
                          }
                        }}
                      >
                        <title>{region.name}</title>
                      </path>
                    ))}
                  </g>
                );
              })}
              {pencilLine.length > 1 ? (
                <polyline
                  className="coord-pencil-line"
                  points={pencilLine.map((point) => `${point.svgX},${point.svgY}`).join(" ")}
                />
              ) : null}
              <g className="map-label-layer" aria-hidden="true">
                {externalPathItems.map((group) => {
                  const pos = svgLabelPositions[group.id] || svgCoordFromPct(group.labelX, group.labelY);
                  return (
                    <text
                      key={`${group.id}:label`}
                      className="map-region-label external"
                      x={pos.svgX}
                      y={pos.svgY}
                    >
                      {group.name.split(" / ")[0]}
                    </text>
                  );
                })}
                {regionPathItems.map((region) => {
                  const pos = svgLabelPositions[region.id] || svgCoordFromPct(region.labelX, region.labelY);
                  return (
                    <text
                      key={`${region.id}:label`}
                      className="map-region-label"
                      x={pos.svgX}
                      y={pos.svgY}
                    >
                      {region.name.split(" / ")[0]}
                    </text>
                  );
                })}
              </g>
            </svg>
            {nodes.filter((node) => node.kind === "theater").map((node) => {
              const selected = selectedId === node.id;
              const danger = node.risk > 175;
              const override = draggedTheaters[node.id];
              const nodeX = override?.x ?? node.x;
              const nodeY = override?.y ?? node.y;
              return (
                <button
                  key={node.id}
                  className={`map-node ${node.kind} ${coordPick ? "draggable" : ""} ${selected ? "selected" : ""} ${danger ? "danger" : ""}`}
                  style={{ left: `${nodeX}%`, top: `${nodeY}%` }}
                  data-node-id={node.id}
                  onPointerDown={(ev) => {
                    if (!coordPick) ev.stopPropagation();  // 防止触发地图 pan
                    onTheaterPointerDown(node)(ev);
                  }}
                  onPointerMove={onTheaterPointerMove(node)}
                  onPointerUp={onTheaterPointerUp(node)}
                  onPointerCancel={onTheaterPointerUp(node)}
                  onClick={(ev) => {
                    ev.stopPropagation();
                    if (coordPick) return;
                    onSelect(node.id);
                  }}
                  aria-label={`查看${node.region?.name || node.label}`}
                  tabIndex={0}
                >
                  {node.kind === "theater" ? <Shield size={16} /> : <MapPinned size={15} />}
                  <span>{node.region?.name.split(" / ")[0] || node.label}</span>
                </button>
              );
            })}
        </div>
      </div>
      {coordPick && pick ? (
        <div className="coord-pick-readout">
          {pick.label ? `${pick.label} ` : ""}pct: ({pick.x}, {pick.y}) &nbsp; svg: ({pick.svgX}, {pick.svgY})
        </div>
      ) : null}
    </section>
  );
}

function NodeIntel({ node }: { node: MapNode }) {
  const region = node.region;
  const power = node.power;
  if (node.kind === "external") {
    return (
      <>
        <div className="panel-title">
          <MapPinned size={14} />
          <span>{region?.name || node.label}</span>
        </div>
        <table className="intel-table">
          <tbody>
            <tr><th>归属</th><td colSpan={3}>{labelPower(region?.controlled_by || power?.id || "")}</td></tr>
          </tbody>
        </table>
        <div className="empty-note">非大明辖治，详情不可见。</div>
      </>
    );
  }
  return (
    <>
      <div className="panel-title">
        {node.kind === "theater" ? <Shield size={14} /> : <MapPinned size={14} />}
        <span>{region?.name || node.label}</span>
      </div>
      {region ? (
        <table className="intel-table">
          <tbody>
            <tr><th>人口</th><td>{region.population}万</td><th>田亩</th><td>{region.registered_land}万亩</td></tr>
            <tr><th>民心</th><td>{region.public_support}</td><th>动乱</th><td>{region.unrest}</td></tr>
            <tr><th>粮食</th><td>{region.grain_security}</td><th>月税</th><td>{monthlyAmount(region.tax_per_turn)}万/月</td></tr>
            <tr><th>归属</th><td>{labelPower(region.controlled_by || "ming")}</td><th>类型</th><td>{region.kind}</td></tr>
            <tr><th>天灾</th><td colSpan={3}>{region.natural_disaster}</td></tr>
            <tr><th>人祸</th><td colSpan={3}>{region.human_disaster}</td></tr>
            <tr><th>状况</th><td colSpan={3}>{region.status}</td></tr>
          </tbody>
        </table>
      ) : null}
      {power && power.id !== "ming" ? (
        <>
          <div className="garrison-title">势力归属</div>
          <table className="intel-table">
            <tbody>
              <tr><th>势力</th><td>{power.name}</td><th>首领</th><td>{power.leader}</td></tr>
              <tr><th>立场</th><td>{power.stance}</td><th>类型</th><td>{power.kind}</td></tr>
              <tr><th>军力</th><td>{power.military_strength}</td><th>凝聚</th><td>{power.cohesion}</td></tr>
              <tr><th>影响</th><td>{power.leverage}</td><th>补给</th><td>{power.supply}</td></tr>
              <tr><th>诉求</th><td colSpan={3}>{power.agenda}</td></tr>
              <tr><th>近况</th><td colSpan={3}>{power.last_action}</td></tr>
            </tbody>
          </table>
        </>
      ) : null}
      <div className="garrison-title">驻军</div>
      {node.armies.length ? (
        <table className="intel-table">
          <thead>
            <tr><th>番号</th><th>兵种</th><th>兵</th><th>饷</th><th>士气</th><th>欠饷</th></tr>
          </thead>
          <tbody>
            {node.armies.map((army) => {
              const maint = army.maintenance_per_turn || 0;
              const arr = army.arrears || 0;
              const months = maint > 0 && arr > 0 ? (arr / maint) : 0;
              const arrText = arr > 0
                ? (months > 0 ? `${arr}万两（≈${months.toFixed(1)}月）` : `${arr}万两`)
                : '—';
              return (
                <tr key={army.id}>
                  <td>{army.name}</td>
                  <td>{army.troop_type}</td>
                  <td>{army.manpower}</td>
                  <td>{monthlyAmount(maint)}</td>
                  <td>{army.morale}</td>
                  <td>{arrText}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      ) : <div className="empty-note">本地未记录常驻军。</div>}
      {region ? (
        <>
          <div className="garrison-title">建筑</div>
          {node.buildings && node.buildings.length ? (
            <table className="intel-table">
              <thead>
                <tr><th>名称</th><th>类别</th><th>等级</th><th>完好</th><th>维护</th><th>产出</th></tr>
              </thead>
              <tbody>
                {node.buildings.map((b) => (
                  <tr key={b.id}>
                    <td>{b.name}</td>
                    <td>{b.category}</td>
                    <td>{b.level}</td>
                    <td>{b.condition}</td>
                    <td>{b.maintenance}万/月</td>
                    <td>{b.output_metric ? `${b.output_metric}+${b.output_amount}` : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : <div className="empty-note">本地未记录建筑。</div>}
        </>
      ) : null}
    </>
  );
}

function Info({ label, value, tone }: { label: string; value: React.ReactNode; tone?: string }) {
  return (
    <div className={`info-cell ${tone || ""}`}>
      <span>{label}</span>
      <b>{value}</b>
    </div>
  );
}

function MenuPage({
  status,
  onRefresh,
  onEnterGame,
  error,
  setError,
}: {
  status: MenuStatus | null;
  onRefresh: () => Promise<MenuStatus>;
  onEnterGame: () => Promise<void>;
  error: string;
  setError: (msg: string) => void;
}) {
  const [busy, setBusy] = React.useState<string>("");
  const [showApiForm, setShowApiForm] = React.useState(false);
  const [showSaveList, setShowSaveList] = React.useState(false);

  const guard = async (label: string, fn: () => Promise<void>) => {
    setBusy(label);
    setError("");
    try {
      await fn();
    } catch (err: any) {
      setError(err?.message || String(err));
    } finally {
      setBusy("");
    }
  };

  const onNewGame = () =>
    guard("新游戏中...", async () => {
      if (status?.has_main_db && !window.confirm("将覆盖当前主进度，是否继续？建议先在游戏中保存为存档。")) return;
      await api("/api/menu/new_game", { method: "POST" });
      await onEnterGame();
    });

  const onContinue = () =>
    guard("载入上次进度...", async () => {
      await api("/api/menu/continue", { method: "POST" });
      await onEnterGame();
    });

  const onLoadSave = (name: string) =>
    guard(`载入「${name}」...`, async () => {
      await api(`/api/menu/load_save/${encodeURIComponent(name)}`, { method: "POST" });
      await onEnterGame();
    });

  const hasKey = !!status?.has_api_key;
  const hasMainDb = !!status?.has_main_db;
  const saves = status?.saves || [];
  const campaigns = status?.campaigns || [];

  return (
    <div className="menu-screen">
      <div className="menu-poster">
        <img src="/steam_assets/主宣传图.jpg" alt="明末：力挽狂澜" />
      </div>

      <h1 className="menu-title">明末：力挽狂澜</h1>

      <div className="menu-panel">
        <p className="menu-subtitle">崇祯元年正月 · 召大臣议天下事</p>

        {!hasKey && (
          <div className="menu-notice">尚未配置 API 接口。请先「设置 API」。</div>
        )}
        {error && <div className="menu-error">{error}</div>}

        <div className="menu-buttons">
          <button className="menu-btn primary" disabled={!hasKey || !!busy} onClick={onNewGame}>
            开始新游戏
          </button>
          <button className="menu-btn" disabled={!hasKey || !hasMainDb || !!busy} onClick={onContinue} title={hasMainDb ? "" : "无上次进度"}>
            继续
          </button>
          <button className="menu-btn" disabled={!hasKey || !!busy || !saves.length} onClick={() => setShowSaveList(true)} title={saves.length ? "" : "暂无存档"}>
            加载存档 {saves.length ? `(${saves.length})` : ""}
          </button>
          <button className="menu-btn" disabled={!!busy} onClick={() => setShowApiForm(true)}>
            设置 API {hasKey ? "" : "（必需）"}
          </button>
        </div>

        {busy && <div className="menu-busy">{busy}</div>}
        {hasKey && status?.llm && (
          <div className="menu-llm-info">
            当前接口：{status.llm.base_url} · {status.llm.model}
          </div>
        )}
      </div>

      {showApiForm && (
        <ApiSettingsModal
          initial={status?.llm}
          onClose={() => setShowApiForm(false)}
          onSaved={async () => {
            setShowApiForm(false);
            await onRefresh();
          }}
        />
      )}

      {showSaveList && (
        <SaveListModal
          campaigns={campaigns}
          onClose={() => setShowSaveList(false)}
          onLoad={async (name) => {
            setShowSaveList(false);
            await onLoadSave(name);
          }}
          onDelete={async (name) => {
            await api(`/api/menu/saves/${encodeURIComponent(name)}`, { method: "DELETE" });
            await onRefresh();
          }}
        />
      )}
    </div>
  );
}

function ApiSettingsModal({
  initial,
  onClose,
  onSaved,
}: {
  initial?: {
    base_url: string;
    model: string;
    has_api_key: boolean;
    max_tokens?: number;
    timeout_seconds?: number;
    thinking_level?: string;
    advanced_model?: string;
    advanced_base_url?: string;
    has_advanced_api_key?: boolean;
    advanced_thinking_level?: string;
  };
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const [baseUrl, setBaseUrl] = React.useState(initial?.base_url || "https://api.deepseek.com");
  const [model, setModel] = React.useState(initial?.model || "deepseek-chat");
  const [advancedModel, setAdvancedModel] = React.useState(initial?.advanced_model || "");
  const [advancedBaseUrl, setAdvancedBaseUrl] = React.useState(initial?.advanced_base_url || "");
  const [advancedApiKey, setAdvancedApiKey] = React.useState("");
  const [advancedThinkingLevel, setAdvancedThinkingLevel] = React.useState(initial?.advanced_thinking_level || "");
  const [apiKey, setApiKey] = React.useState("");
  const [maxTokens, setMaxTokens] = React.useState(String(initial?.max_tokens || 8000));
  const [timeoutSeconds, setTimeoutSeconds] = React.useState(String(initial?.timeout_seconds || 180));
  const [thinkingLevel, setThinkingLevel] = React.useState(initial?.thinking_level || "");
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState("");

  const onSave = async () => {
    setBusy(true);
    setErr("");
    try {
      const response = await fetch("/api/menu/llm", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          base_url: baseUrl.trim(),
          model: model.trim(),
          api_key: apiKey.trim(),
          max_tokens: parseInt(maxTokens) || 8000,
          timeout_seconds: parseFloat(timeoutSeconds) || 180,
          thinking_level: thinkingLevel.trim(),
          advanced_model: advancedModel.trim(),
          advanced_base_url: advancedBaseUrl.trim(),
          advanced_api_key: advancedApiKey.trim(),
          advanced_thinking_level: advancedThinkingLevel.trim(),
        }),
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({ detail: response.statusText }));
        const detail = normalizeApiError(payload, response.statusText);
        setErr(`code: ${detail.code || "unknown"}\nmessage: ${detail.message || response.statusText}`);
        return;
      }
      await onSaved();
    } catch (e: any) {
      setErr(`code: request_failed\nmessage: ${e?.message || String(e)}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="menu-modal-bg" onClick={onClose}>
      <div className="menu-modal" onClick={(e) => e.stopPropagation()}>
        <h2>设置 API</h2>
        <p className="menu-hint">推荐 DeepSeek（中文好、价格便宜）。配置写入本地，不上传。</p>
        <label>
          Base URL
          <input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://api.deepseek.com" />
        </label>
        <label>
          Model
          <input value={model} onChange={(e) => setModel(e.target.value)} placeholder="deepseek-chat" />
        </label>
        <label>
          Thinking Level <small className="menu-hint">（空=默认，请填写你的模型支持的值。）</small>
          <input value={thinkingLevel} onChange={(e) => setThinkingLevel(e.target.value)} placeholder="默认" />
        </label>
        <label>
          Advanced Model <small className="menu-hint">（推演 + 打分专用；留空 fallback）</small>
          <input value={advancedModel} onChange={(e) => setAdvancedModel(e.target.value)} placeholder="deepseek-reasoner / gpt-5" />
        </label>
        <label>
          Advanced Base URL <small className="menu-hint">（advanced 专用网关；留空复用主 Base URL）</small>
          <input value={advancedBaseUrl} onChange={(e) => setAdvancedBaseUrl(e.target.value)} placeholder="https://other-gateway/v1" />
        </label>
        <label>
          Advanced API Key{" "}
          <small className="menu-hint">{initial?.has_advanced_api_key ? "(已配置；留空保留)" : "(留空=复用主 API Key)"}</small>
          <input type="password" value={advancedApiKey} onChange={(e) => setAdvancedApiKey(e.target.value)} placeholder={initial?.has_advanced_api_key ? "(已配置；如需更换请重新填写)" : "留空=复用主 Key"} />
        </label>
        <label>
          Advanced Thinking Level <small className="menu-hint">（空=默认，请填写你的模型支持的值。）</small>
          <input value={advancedThinkingLevel} onChange={(e) => setAdvancedThinkingLevel(e.target.value)} placeholder="默认" />
        </label>
        <label>
          Max Tokens
          <input type="number" min={256} max={65536} value={maxTokens} onChange={(e) => setMaxTokens(e.target.value)} placeholder="8000" />
        </label>
        <label>
          Timeout Seconds
          <input type="number" min={10} max={900} value={timeoutSeconds} onChange={(e) => setTimeoutSeconds(e.target.value)} placeholder="180" />
        </label>
        <label>
          API Key
          <input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder={initial?.has_api_key ? "(已配置；如需更换请重新填写)" : "sk-..."} />
        </label>
        {err && <div className="menu-error">{err}</div>}
        <div className="menu-modal-actions">
          <button onClick={onClose} disabled={busy}>取消</button>
          <button className="primary" onClick={onSave} disabled={busy || !baseUrl.trim() || !model.trim() || (!apiKey.trim() && !initial?.has_api_key)}>
            {busy ? "保存中..." : "保存"}
          </button>
        </div>
      </div>
    </div>
  );
}

function SaveListModal({
  campaigns,
  onClose,
  onLoad,
  onDelete,
}: {
  campaigns: MenuCampaign[];
  onClose: () => void;
  onLoad: (name: string) => Promise<void>;
  onDelete: (name: string) => Promise<void>;
}) {
  const hasAny = campaigns.some((c) => c.saves.length);
  const [delBusy, setDelBusy] = React.useState("");
  const [delErr, setDelErr] = React.useState("");
  const handleDelete = async (name: string, label?: string) => {
    if (!window.confirm(`删除存档「${label || name}」？此操作不可撤销。`)) return;
    setDelBusy(name);
    setDelErr("");
    try {
      await onDelete(name);
    } catch (e) {
      setDelErr(e instanceof Error ? e.message : String(e));
    } finally {
      setDelBusy("");
    }
  };
  return (
    <div className="menu-modal-bg" onClick={onClose}>
      <div className="menu-modal" onClick={(e) => e.stopPropagation()}>
        <h2>加载存档</h2>
        {delErr ? <div className="menu-error">{delErr}</div> : null}
        {hasAny ? (
          <div className="menu-campaign-list">
            {campaigns.map((c) => (
              <div key={c.campaign_id || "__manual__"} className="menu-campaign">
                <div className="menu-campaign-head">
                  <span>{c.kind === "manual" ? "手动存档" : `战局 ${c.campaign_id.slice(0, 6)}`}</span>
                  {c.current ? <span className="menu-campaign-badge">本局</span> : null}
                </div>
                <ul className="menu-save-list">
                  {c.saves.map((s) => (
                    <li key={s.name} className="menu-save-row">
                      <button className="menu-save-load" onClick={() => onLoad(s.name)}>
                        <span className="save-name">{s.label || s.name}</span>
                        <span className="save-meta">{new Date(s.mtime * 1000).toLocaleString("zh-CN")}</span>
                      </button>
                      <button
                        className="menu-save-del"
                        title="删除存档"
                        disabled={delBusy === s.name}
                        onClick={() => handleDelete(s.name, s.label)}
                      >
                        {delBusy === s.name ? <Loader2 size={14} className="spin" /> : <Trash2 size={14} />}
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        ) : (
          <p className="menu-empty">暂无存档。</p>
        )}
        <div className="menu-modal-actions">
          <button onClick={onClose}>关闭</button>
        </div>
      </div>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
