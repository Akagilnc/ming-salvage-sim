import { Power } from "lucide-react";

export type Metrics = Record<string, number>;

export type Region = {
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

export type Army = {
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

export type Power = {
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

export type Building = {
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

export type MapNode = {
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

export type RegionPathRenderItem = {
  id: string;
  name: string;
  controlledBy: string;
  unrest: number;
  risk: number;
  labelX: number;
  labelY: number;
  paths: Array<{ id: string; d: string }>;
};

export type ExternalPathRenderItem = {
  id: string;
  name: string;
  powerId: string;
  labelX: number;
  labelY: number;
  paths: Array<{ id: string; d: string }>;
};

export type SvgLabelPosition = {
  svgX: number;
  svgY: number;
};

export type Minister = {
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

export type EventItem = {
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

export type Directive = {
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

export type Issue = {
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

export type LegacyEffect = {
  国库?: number;
  内库?: number;
  民心?: number;
  皇威?: number;
  regions?: Record<string, Record<string, number>>;
  armies?: Record<string, Record<string, number>>;
};

export type Legacy = {
  id: number;
  name: string;
  narrative_hint: string;
  modifiers: LegacyEffect;
  effect_text: string;
  remaining_months: number;  // -1 = 永久
  clear_condition: string;
};

export type ClosedIssue = {
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

export type BudgetItem = {
  name: string;
  amount: number;
  note: string;
};

export type BudgetMovement = {
  delta: number;
  balance_after: number;
  category: string;
  reason: string;
};

export type BudgetAccount = {
  balance: number;
  income: BudgetItem[];
  expense: BudgetItem[];
  income_total: number;
  expense_total: number;
  net: number;
  movements: BudgetMovement[];
  movements_total: number;
};

export type Budget = Record<"国库" | "内库", BudgetAccount>;

export type DecisionOption = {
  label: string;
  hint: string;
};

export type PendingDecision = {
  idx: number;
  title: string;
  context: string;
  options: DecisionOption[];
  choice?: { label?: string; hint?: string; note?: string } | null;
  status?: string;
};

export type GameState = {
  turn: { year: number; period: number; turn: number; phase?: string };
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
  pending_decisions?: PendingDecision[];
  last_decree: string;
  last_report: string;
};

export type EndingTimelineItem = {
  turn: number; year: number; period: number;
  decree_brief: string; effect_brief: string; chapter: string;
};

export type EndingPayload = {
  status: string; label: string; summary: string; timeline: EndingTimelineItem[];
};

export type ChatMessage = { role: "user" | "minister"; content: string };

export type ChatDisplayMessage = ChatMessage & { pending?: boolean };

export type Suggestion = { label: string; text: string; prefix?: boolean };

export type ModalName = "none" | "state" | "chat" | "edict" | "report" | "extraction" | "history" | "menu" | "secret_orders" | "ending" | "long_goals";

export type SaveEntry = { name: string; size: number; mtime: number };

export type LLMConfigInfo = {
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

export type SecretOrder = {
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

export type ProposedDirective = { id: number; text: string; status: string; notes: string };

export type ChatResponse = {
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

export type ChatUndoResponse = {
  history: ChatMessage[];
  suggestions: Suggestion[];
  directives: Directive[];
  pending_count: number;
  secret_orders: SecretOrder[];
  can_undo_last_chat: boolean;
};

export type ApiErrorDetail = {
  code?: string;
  message?: string;
  provider_message?: string;
  status_code?: number | null;
};

export type AppView = "menu" | "game";

export type MenuSave = {
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

export type MenuCampaign = {
  campaign_id: string;
  kind: "auto" | "manual";
  current: boolean;
  saves: MenuSave[];
  latest_mtime: number;
};

export type MenuStatus = {
  has_api_key: boolean;
  has_running_game: boolean;
  has_main_db: boolean;
  saves: MenuSave[];
  campaigns?: MenuCampaign[];
  current_campaign?: string;
  game_settings?: { hitl_min_decisions: number };
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

export type ExtractionData = {
  turn: number;
  year: number;
  period: number;
  exists: boolean;
  extractor_output?: any;
};

export type HistoryTurnItem = {
  turn: number;
  year: number;
  period: number;
  has_report: boolean;
  has_extraction: boolean;
  has_directive: boolean;
};

export type HistoryDirective = {
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

export type HistoryDetail = {
  turn: number;
  exists: boolean;
  year: number;
  period: number;
  report: string;
  decree_text: string;
  directives: HistoryDirective[];
  extraction: ExtractionData | null;
};

export type TerrainTransform = { x: number; y: number; width: number; height: number };
