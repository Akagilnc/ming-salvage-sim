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
  army_needed: number; // #173 引擎实扣月应发(万两)=ceil(manpower×salary_rate/10000)，月饷呈现真源(维护费列已删)
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
  commitment_progress?: Record<string, unknown>;
  commitment_progress_text?: string;
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

export type DossierDecision = "promulgated" | "rejected" | "force_promulgated";

export type DecisionChoice = {
  label?: string;
  hint?: string;
  note?: string;
  dossier_id?: number | null;
  dossier_decision?: DossierDecision;
};

export type DecisionOption = {
  label: string;
  hint: string;
  dossier_id?: number;
  dossier_decision?: DossierDecision;
};

export type PendingDecision = {
  idx: number;
  event_id?: string;
  title: string;
  context: string;
  rejection_reason?: string;
  opposition?: string;
  options: DecisionOption[];
  choice?: DecisionChoice | null;
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
  talent_pool?: Minister[];  // 在野人才池：可起复的罢居/致仕前臣（offstage，#120）
  directives: Directive[];
  pending_count: number;
  pending_directive_count?: number;  // 对话式拟旨暂存数（pending_actions kind=directive）
  pending_secret_order_count?: number;  // 兼容旧字段；隐藏的新密令候选不再向前端计数
  pending_non_directive_action_count?: number;  // 可见的非拟旨 pending_actions（不含隐藏新密令候选）
  failed_secret_order_count?: number;
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

export type ChatMessage = {
  /** user=朕 / minister=大臣 / attendant=递话（王承恩读心，ADR 0046） */
  role: "user" | "minister" | "attendant";
  content: string;
  /** attendant 递话的稳定记录身份（#499）：按 (chatTurnId, recordId) 去重/归位，不依赖 narration 文本 */
  chatTurnId?: number;
  recordId?: number;
};

export type ChatDisplayMessage = ChatMessage & { pending?: boolean };

export type AudienceScrollMessage = {
  role: "user" | "minister" | "attendant" | "scene";
  speaker: string;
  audibility: string;
  time: string | null;
  content: string;
  soft_boundary: boolean;
  beat: "opening" | "entrance" | "dialogue" | "aside" | "scene" | "exit" | "divider" | "closing" | "coda";
  highlights: string[];
  container: { time_of_day: string; location: string; audience_type: string };
  /** Internal durable identity used only to merge a refreshing live projection. */
  chat_turn_id?: number;
  record_id?: number;
};

/** 服务端 turn-identified 召对投影里的一条消息（#499）：user/minister 带 chat_turn_id，
 *  attendant 递话额外带 record_id；前端映射为 ChatMessage 后渲染。 */
export type ServerChatMessage = {
  role: "user" | "minister" | "attendant";
  content: string;
  chat_turn_id?: number;
  record_id?: number;
};

export type Suggestion = { label: string; text: string; prefix?: boolean };

export type ModalName = "none" | "state" | "chat" | "edict" | "report" | "history" | "audience_archive" | "menu" | "secret_orders" | "ending";

export type SaveEntry = { name: string; size: number; mtime: number };

// CLI Model 策展下拉的一档；value="" = runner 默认档（提交空串走后端默认）。
// 单一真源在后端 cli_backend.cli_model_choices()，经 config 端点下发，前端不硬编。
export type CliModelChoice = { value: string; label: string };
export type CliModelChoices = Record<string, CliModelChoice[]>;
export type ReasoningStrengthChoice = { value: string; label: string };

export type LLMConfigInfo = {
  channel?: "api" | "cli";
  base_url: string;
  model: string;
  max_tokens: number;
  timeout_seconds: number;
  thinking_level: string;
  advanced_model: string;
  advanced_base_url: string;
  has_advanced_api_key: boolean;
  advanced_thinking_level: string;
  reasoning_strength?: string;
  api_reasoning_strength?: string;
  cli_reasoning_strength?: string;
  reasoning_supported?: boolean;
  reasoning_strengths?: ReasoningStrengthChoice[];
  has_api_key: boolean;
  cli_runner?: string;
  cli_model?: string;
  cli_model_choices?: CliModelChoices;
  cli_timeout_seconds?: number;
  persisted: {
    channel?: "api" | "cli";
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
    reasoning_strength?: string;
    api_reasoning_strength?: string;
    cli_reasoning_strength?: string;
    cli_runner?: string;
    cli_model?: string;
    cli_timeout_seconds?: number;
  };
};

export type DossierProgressReport = {
  id: number;
  dossier_id: number;
  turn: number;
  progress_band: string;
  memorial_text: string;
  is_terminal: boolean;
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
  dossier_progress?: DossierProgressReport[];
  turn_closed: number | null;
};

export type ProposedDirective = { id: number; text: string; status: string; notes: string };

export type PendingActionFailure = {
  id: number;
  kind: string;
  action: string;
  minister_name?: string;
  retryable?: boolean;
  message: string;
};

/** #505：崩溃后待重试的中断回话（系统层恢复，非内容选项）。 */
export type ReplyRetry = {
  chat_turn_id: number;
  minister_name: string;
  turn: number;
  question: string;
};

/** #501：待补叙事抽取状态（显眼提示 + 原地重试）。 */
export type ExtractionPendingStatus = {
  night_id: number;
  count: number;
  pending: Array<{
    chat_turn_id: number;
    minister_name: string;
    night_id: number;
  }>;
};

export type ChatIdentity = { campaign_id: string; night_id: number; chat_turn_id: number };

export type ChatResponse = {
  answer: string;
  campaign_id: string;
  night_id: number;
  chat_turn_id: number;
  history: ServerChatMessage[];
  suggestions: Suggestion[];
  directives: Directive[];
  pending_count?: number;
  can_undo_last_chat?: boolean;
  court_action?: string;
  next_minister?: string;
  registered_minister?: string;
  proposed_directive?: ProposedDirective | null;
  secret_order_id?: number;
  pending_action_failures?: PendingActionFailure[];
  // #502 AC5：多道准驳含糊态（候选 id/摘要）供前端展示大臣追问哪一道；无则缺席/null。
  directive_confirmation_ambiguous?: DirectiveConfirmationAmbiguous | null;
};

export type DirectiveConfirmationAmbiguous = {
  candidates: { id: number; summary: string }[];
};

export type ChatUndoResponse = {
  campaign_id: string;
  night_id: number;
  undone_chat_turn_id: number;
  history: ServerChatMessage[];
  suggestions: Suggestion[];
  directives: Directive[];
  pending_count: number;
  secret_orders: SecretOrder[];
  can_undo_last_chat: boolean;
  pending_action_failures?: PendingActionFailure[];
};

export type ApiErrorDetail = {
  code?: string;
  message?: string;
  provider_message?: string;
  status_code?: number | null;
  pending_action_failures?: PendingActionFailure[];
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
  llm_ready?: boolean;
  has_running_game: boolean;
  has_main_db: boolean;
  saves: MenuSave[];
  campaigns?: MenuCampaign[];
  current_campaign?: string;
  game_settings?: { hitl_min_decisions: number };
  llm: {
    channel?: "api" | "cli";
    base_url: string;
    model: string;
    has_api_key: boolean;
    cli_runner?: string;
    cli_model?: string;          // resolved（兜底默认名，供「当前后端」展示）
    cli_model_saved?: string;    // raw 存盘值（空=默认档，供设置表单初始化）
    cli_model_choices?: CliModelChoices;
    cli_timeout_seconds?: number;
    max_tokens: number;
    timeout_seconds: number;
    thinking_level: string;
    advanced_model: string;
    advanced_base_url: string;
    has_advanced_api_key: boolean;
    advanced_thinking_level: string;
    reasoning_strength?: string;
    api_reasoning_strength?: string;
    cli_reasoning_strength?: string;
    reasoning_supported?: boolean;
    reasoning_strengths?: ReasoningStrengthChoice[];
  };
};

export type HistoryTurnItem = {
  kind: "month" | "night";
  turn: number;
  year: number;
  period: number;
  has_report: boolean;
  has_directive: boolean;
  /** Persisted closed audience night for a scene archive. */
  night_id?: number;
  time_of_day?: string;
  location?: string;
  /** Stable sequence among same-turn, same-place, same-time closed scenes. */
  scene_number?: number;
  scene_count?: number;
  audience_type?: string;
  title?: string;
  involved_people?: string[];
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
};

export type TerrainTransform = { x: number; y: number; width: number; height: number };
