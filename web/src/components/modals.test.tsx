import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AudienceArchiveModal } from "./audienceArchiveModal";
import { ChatModal } from "./chatModal";
import { EdictModal } from "./edictModal";
import { HistoryModal } from "./historyModal";
import { FullscreenModal } from "./hud";
import { ReportModal } from "./reportModal";
import { ScrollMessages } from "./scrollMessages";
import type { BudgetAccount, ChatMessage, GameState, Minister, Suggestion } from "../types";
import { chatReducer, type ChatAction } from "../mindreading";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// Centralised teardown registry: every rendered root is unmounted in afterEach so a
// FAILED assertion (which aborts the test body before any inline cleanup) can never
// leak a mounted React root into the next test (gemini cmr r1).
const mountedRoots: Array<{ root: Root; host: HTMLElement }> = [];
const caretDescriptor = Object.getOwnPropertyDescriptor(document, "caretPositionFromPoint");
const rangeRectsDescriptor = Object.getOwnPropertyDescriptor(Range.prototype, "getClientRects");

const MINISTER_MOCK: Minister = {
  name: "周延儒",
  office: "内阁首辅",
  office_type: "cabinet",
  faction: "东林",
  style: "字玉绳",
  status: "active",
  status_label: "在朝",
  summary: "东林领袖",
  favorite: false,
  skills: [],
};

const CONSORT_MOCK: Minister = {
  name: "周贵人",
  office: "贵人",
  office_type: "后宫",
  faction: "",
  style: "",
  status: "active",
  status_label: "在宫",
  summary: "后宫嫔妃",
  favorite: false,
  skills: [],
};

describe("ScrollMessages — frozen ledger order", () => {
  it("groups only adjacent rows of a turn without moving an interleaved scene row", () => {
    const host = document.createElement("div"); document.body.appendChild(host);
    const root = createRoot(host); mountedRoots.push({ root, host });
    act(() => { root.render(<ScrollMessages ministerName="" ministers={[]} messages={[
      { role: "user", speaker: "朕", content: "先问", beat: "dialogue", chat_turn_id: 7, audibility: "", time: null, soft_boundary: false, highlights: [], container: { time_of_day: "", location: "", audience_type: "" } },
      { role: "scene", speaker: "", content: "烛花一爆", beat: "scene", audibility: "", time: null, soft_boundary: false, highlights: [], container: { time_of_day: "", location: "", audience_type: "" } },
      { role: "minister", speaker: "洪承畴", content: "后答", beat: "dialogue", chat_turn_id: 7, audibility: "", time: null, soft_boundary: false, highlights: [], container: { time_of_day: "", location: "", audience_type: "" } },
    ]} />); });
    expect(host.textContent).toBe("朕先问烛花一爆洪承畴后答");
    expect(host.querySelectorAll('[data-audience-turn-id="7"]')).toHaveLength(2);
  });
});

function renderModal(props: {
  minister: Minister;
  ministers?: Minister[];
  portraitPrefix: string;
  scrollMode?: "audience" | "legacy";
  currentNightId?: number;
  undoneChatTurnId?: number | null;
  chat?: ChatMessage[];
  busy?: string;
  streamingMinisterMessage?: string;
  onCancel?: () => void;
  replyRetries?: React.ComponentProps<typeof ChatModal>["replyRetries"];
  onRetryReply?: (ministerName: string) => void;
  translationRetries?: React.ComponentProps<typeof ChatModal>["translationRetries"];
  onRetryTranslation?: React.ComponentProps<typeof ChatModal>["onRetryTranslation"];
  pendingUserMessage?: string;
  pendingIdentity?: { campaign_id: string; night_id: number; chat_turn_id: number } | null;
  failedIdentity?: { campaign_id: string; night_id: number; chat_turn_id: number } | null;
  suggestions?: Suggestion[];
  secretOrders?: React.ComponentProps<typeof ChatModal>["secretOrders"];
  onSend?: (ministerName: string, text?: string) => void;
  onIntent?: (intent: "secret_order" | undefined) => void;
  onUndo?: (ministerName: string) => void;
  canUndoLastChat?: boolean;
  onFavorite?: (minister: Minister) => void;
  onClose?: () => void;
  scrollPosition?: number;
  onScrollPositionChange?: (position: number) => void;
  registerChatUpdate?: (update: (chat: ChatMessage[]) => void) => void;
  registerStreamingUpdate?: (update: (message: string) => void) => void;
  registerPendingIdentityUpdate?: (update: (identity: { campaign_id: string; night_id: number; chat_turn_id: number } | null) => void) => void;
  registerFailedIdentityUpdate?: (update: (identity: { campaign_id: string; night_id: number; chat_turn_id: number } | null) => void) => void;
  registerNightUpdate?: (update: (nightId: number) => void) => void;
  registerUndoUpdate?: (update: (chatTurnId: number | null) => void) => void;
  registerChatDispatch?: (dispatch: React.Dispatch<ChatAction>) => void;
  registerMinisterUpdate?: (update: (minister: Minister) => void) => void;
}) {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);

  // Controlled input lives in the harness so prefix-chip clicks update textarea.value
  // (ChatModal is a controlled component; frozen input="" would hide real fill).
  function Harness() {
    const [input, setInput] = React.useState("");
    const [currentNightId, setCurrentNightId] = React.useState(props.currentNightId ?? 0);
    const [activeMinister, setActiveMinister] = React.useState(props.minister);
    const [undoneChatTurnId, setUndoneChatTurnId] = React.useState<number | null>(props.undoneChatTurnId ?? null);
    const [chat, dispatchChat] = React.useReducer(chatReducer, props.chat ?? []);
    const [streamingMinisterMessage, setStreamingMinisterMessage] = React.useState(props.streamingMinisterMessage ?? "");
    const [pendingIdentity, setPendingIdentity] = React.useState(props.pendingIdentity ?? null);
    const [failedIdentity, setFailedIdentity] = React.useState(props.failedIdentity ?? null);
    const setChat = React.useCallback((next: ChatMessage[]) => dispatchChat({
      type: "history",
      history: next.map((message) => ({
        role: message.role,
        content: message.content,
        chat_turn_id: message.chatTurnId,
        record_id: message.recordId,
      })),
    }), []);
    React.useEffect(() => props.registerChatUpdate?.(setChat), [setChat]);
    React.useEffect(() => props.registerStreamingUpdate?.(setStreamingMinisterMessage), []);
    React.useEffect(() => props.registerPendingIdentityUpdate?.(setPendingIdentity), []);
    React.useEffect(() => props.registerFailedIdentityUpdate?.(setFailedIdentity), []);
    React.useEffect(() => props.registerNightUpdate?.(setCurrentNightId), []);
    React.useEffect(() => props.registerUndoUpdate?.(setUndoneChatTurnId), []);
    React.useEffect(() => props.registerChatDispatch?.(dispatchChat), []);
    React.useEffect(() => props.registerMinisterUpdate?.(setActiveMinister), []);
    return (
      <ChatModal
        minister={activeMinister}
        ministers={props.ministers ?? []}
        portraitPrefix={props.portraitPrefix}
        scrollMode={props.scrollMode}
        currentCampaignId="test-campaign"
        currentNightId={currentNightId}
        undoneChatIdentity={undoneChatTurnId == null ? null : { campaign_id: "test-campaign", night_id: currentNightId, chat_turn_id: undoneChatTurnId }}
        busy={props.busy ?? ""}
        chat={chat}
        suggestions={props.suggestions ?? []}
        pendingUserMessage={props.pendingUserMessage ?? ""}
        pendingIdentity={pendingIdentity}
        failedIdentity={failedIdentity}
        streamingMinisterMessage={streamingMinisterMessage}
        chatNotice=""
        canUndoLastChat={props.canUndoLastChat ?? false}
        composerHint=""
        input={input}
        error=""
        secretOrders={props.secretOrders ?? []}
        replyRetries={props.replyRetries}
        onInput={(value) => setInput(value)}
        onIntent={props.onIntent}
        onSend={props.onSend ?? (() => {})}
        onRetryReply={props.onRetryReply}
        translationRetries={props.translationRetries}
        onRetryTranslation={props.onRetryTranslation}
        onUndo={props.onUndo ?? (() => {})}
        onHint={() => {}}
        onFavorite={props.onFavorite ?? (() => {})}
        scrollPosition={props.scrollPosition}
        onScrollPositionChange={props.onScrollPositionChange}
        onClose={props.onClose ?? (() => {})}
        onCancel={props.onCancel}
      />
    );
  }

  act(() => {
    root.render(<Harness />);
  });
  // Register for centralised teardown (afterEach) — no inline cleanup, so a failing
  // assertion can never skip unmount and leak a root into the next test.
  mountedRoots.push({ root, host });
  return host;
}

function renderReportModal(props: {
  report: string;
  attendantMessage?: string;
  onClose?: () => void;
  periodLabel?: string;
}) {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  act(() =>
    root.render(
      <ReportModal
        report={props.report}
        attendantMessage={props.attendantMessage}
        periodLabel={props.periodLabel}
        onClose={props.onClose ?? (() => {})}
      />
    )
  );
  mountedRoots.push({ root, host });
  return host;
}

const EMPTY_BUDGET_ACCOUNT: BudgetAccount = {
  balance: 0,
  income: [],
  expense: [],
  income_total: 0,
  expense_total: 0,
  net: 0,
  movements: [],
  movements_total: 0,
};

function baseGameState(overrides: Partial<GameState> = {}): GameState {
  return {
    turn: { year: 1627, period: 10, turn: 1, phase: "summoning" },
    metrics: {},
    previous_summary: "",
    issues: [],
    legacies: [],
    closed_this_turn: [],
    budget: { 国库: EMPTY_BUDGET_ACCOUNT, 内库: EMPTY_BUDGET_ACCOUNT, army_pay_due_total: 0, settled_army_pay: null },
    region_warning: "",
    army_warning: "",
    power_warning: "",
    powers: [],
    victory_status: { status: "ongoing", summary: "" },
    ending: null,
    events: [],
    regions: [],
    armies: [],
    map_nodes: [],
    ministers: [],
    consorts: [],
    directives: [],
    pending_count: 0,
    pending_directive_count: 0,
    pending_secret_order_count: 0,
    pending_non_directive_action_count: 0,
    last_decree: "",
    last_report: "",
    ...overrides,
  };
}

function renderEdictModal(props: {
  state: GameState;
  onIssueDecree?: () => void;
  onAdvanceWithoutEdict?: () => void;
  error?: string;
}) {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  act(() =>
    root.render(
      <EdictModal
        state={props.state}
        directiveText=""
        editingDirectiveId={null}
        editingDirectiveText=""
        decree=""
        report=""
        busy=""
        error={props.error ?? ""}
        onDirectiveTextChange={() => {}}
        onEditingTextChange={() => {}}
        onCreateDirective={() => {}}
        onStartEdit={() => {}}
        onCancelEdit={() => {}}
        onSaveDirective={() => {}}
        onDeleteDirective={() => {}}
        onIssueDecree={props.onIssueDecree ?? (() => {})}
        onAdvanceWithoutEdict={props.onAdvanceWithoutEdict ?? (() => {})}
      />
    )
  );
  mountedRoots.push({ root, host });
  return { host, root };
}

afterEach(() => {
  // Unmount every root rendered this test (whether the body passed or threw).
  for (const { root, host } of mountedRoots) {
    act(() => root.unmount());
    host.remove();
  }
  mountedRoots.length = 0;
  document.body.innerHTML = "";
  if (caretDescriptor) Object.defineProperty(document, "caretPositionFromPoint", caretDescriptor);
  else Reflect.deleteProperty(document, "caretPositionFromPoint");
  if (rangeRectsDescriptor) Object.defineProperty(Range.prototype, "getClientRects", rangeRectsDescriptor);
  else Reflect.deleteProperty(Range.prototype, "getClientRects");
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("EdictModal — #1431 placeholder 去失实具名", () => {
  it("御笔 placeholder 不含毕自严等现任错位具名", () => {
    const { host } = renderEdictModal({ state: baseGameState() });
    const textarea = host.querySelector<HTMLTextAreaElement>(".desk-compose textarea");
    expect(textarea).toBeTruthy();
    const ph = textarea!.placeholder;
    expect(ph.length).toBeGreaterThan(5);
    // 数据真源：毕自严=南京户部尚书，非核拨辽饷的户部尚书；placeholder 不得硬编码其名
    expect(ph).not.toContain("毕自严");
  });
});

describe("EdictModal — decree desk behavior", () => {
  it("issues an approved conversational draft without a second review gate", () => {
    const onIssue = vi.fn();
    const { host } = renderEdictModal({
      state: baseGameState({ directives: [{ id: 8, event_id: "", event_title: "", actor: "", skill_id: "", skill_name: "", text: "发饷辽东", source: "chat", status: "pending", notes: "", authority: "" }] }),
      onIssueDecree: onIssue,
    });
    const item = host.querySelector(".directive-item");
    const tools = item?.querySelectorAll(".directive-tools button");
    const button = host.querySelector<HTMLButtonElement>(".desk-footer button");

    expect(item).not.toBeNull();
    expect(tools).toHaveLength(2);
    expect(button?.disabled).toBe(false);
    act(() => button?.click());
    expect(onIssue).toHaveBeenCalledTimes(1);
  });

  it("#1732 failed-only：页脚就地确认；取消零调用；确认后退朝", () => {
    const onAdvance = vi.fn();
    const confirm = vi.spyOn(window, "confirm");
    const { host } = renderEdictModal({
      state: baseGameState({
        directives: [],
        pending_directive_count: 0,
        pending_secret_order_count: 0,
        pending_non_directive_action_count: 0,
        failed_secret_order_count: 1,
      }),
      onAdvanceWithoutEdict: onAdvance,
    });
    const footer = host.querySelector<HTMLButtonElement>(".desk-footer button");
    expect(footer?.disabled).toBe(false);
    act(() => footer?.click());
    expect(confirm).not.toHaveBeenCalled();
    expect(onAdvance).not.toHaveBeenCalled();
    const panel = host.querySelector('[aria-label="退朝确认"]');
    expect(panel).not.toBeNull();
    expect(panel?.textContent).toContain("失败密令未处理");
    const cancel = Array.from(panel!.querySelectorAll("button")).find((b) =>
      (b.textContent || "").includes("取消")
    );
    act(() => cancel?.click());
    expect(onAdvance).not.toHaveBeenCalled();
    expect(host.querySelector('[aria-label="退朝确认"]')).toBeNull();

    const footer2 = host.querySelector<HTMLButtonElement>(".desk-footer button");
    act(() => footer2?.click());
    const yes = Array.from(host.querySelector('[aria-label="退朝确认"]')!.querySelectorAll("button")).find((b) =>
      (b.textContent || "").includes("退朝结束本月")
    );
    act(() => yes?.click());
    expect(onAdvance).toHaveBeenCalledTimes(1);
  });
});

describe("#1732 ChatModal · 撤回就地确认", () => {
  it("取消零调用；确认后 onUndo", () => {
    const onUndo = vi.fn();
    const confirm = vi.spyOn(window, "confirm");
    const host = renderModal({
      minister: MINISTER_MOCK,
      portraitPrefix: "minister_",
      canUndoLastChat: true,
      onUndo,
    });
    const undo = Array.from(host.querySelectorAll("button")).find((b) =>
      (b.textContent || "").includes("撤回本轮")
    ) as HTMLButtonElement;
    act(() => undo.click());
    expect(confirm).not.toHaveBeenCalled();
    expect(onUndo).not.toHaveBeenCalled();
    const panel = host.querySelector('[aria-label="撤回召对确认"]');
    expect(panel).not.toBeNull();
    const cancel = Array.from(panel!.querySelectorAll("button")).find((b) =>
      (b.textContent || "").includes("取消")
    );
    act(() => cancel?.click());
    expect(onUndo).not.toHaveBeenCalled();

    act(() => undo.click());
    const yes = Array.from(host.querySelector('[aria-label="撤回召对确认"]')!.querySelectorAll("button")).find((b) =>
      (b.textContent || "").includes("继续撤回")
    );
    act(() => yes?.click());
    expect(onUndo).toHaveBeenCalledWith("周延儒");
  });

  it("#1732 T3 开着确认条发送后确认条关闭", () => {
    const onSend = vi.fn();
    const host = renderModal({
      minister: MINISTER_MOCK,
      portraitPrefix: "minister_",
      canUndoLastChat: true,
      onSend,
    });
    const undo = Array.from(host.querySelectorAll("button")).find((b) =>
      (b.textContent || "").includes("撤回本轮")
    ) as HTMLButtonElement;
    act(() => undo.click());
    expect(host.querySelector('[aria-label="撤回召对确认"]')).not.toBeNull();

    const textarea = host.querySelector("textarea") as HTMLTextAreaElement;
    act(() => {
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")?.set;
      setter?.call(textarea, "问边饷");
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
    });
    const send = Array.from(host.querySelectorAll("button")).find((b) =>
      (b.textContent || "").includes("发送")
    ) as HTMLButtonElement;
    act(() => send.click());

    expect(onSend).toHaveBeenCalledWith("周延儒", "问边饷");
    expect(host.querySelector('[aria-label="撤回召对确认"]')).toBeNull();
  });

  it("#1732 T3 开着确认条点散夜后确认条关闭", () => {
    const onSend = vi.fn();
    const host = renderModal({
      minister: MINISTER_MOCK,
      portraitPrefix: "minister_",
      canUndoLastChat: true,
      onSend,
    });
    const undo = Array.from(host.querySelectorAll("button")).find((b) =>
      (b.textContent || "").includes("撤回本轮")
    ) as HTMLButtonElement;
    act(() => undo.click());
    expect(host.querySelector('[aria-label="撤回召对确认"]')).not.toBeNull();

    const retreat = Array.from(host.querySelectorAll("button")).find((b) =>
      (b.textContent || "").includes("散夜")
    ) as HTMLButtonElement;
    act(() => retreat.click());

    expect(onSend).toHaveBeenCalledWith("周延儒", "退朝");
    expect(host.querySelector('[aria-label="撤回召对确认"]')).toBeNull();
  });
});

describe("ChatModal — #1370 empty audience chrome", () => {
  it("空对话区呈等候/引导 chrome，带稳定 chat-stage 标记，不代笔开场白", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ night_id: 0, messages: [] }),
    }));
    const host = renderModal({
      minister: MINISTER_MOCK,
      portraitPrefix: "minister_",
      scrollMode: "audience",
      currentNightId: 0,
    });
    await act(async () => { await Promise.resolve(); });
    const stage = host.querySelector("[data-testid=chat-stage]") || host.querySelector(".chat-stage");
    expect(stage).not.toBeNull();
    expect(stage!.textContent || "").toMatch(/请陛下问话|等候开口/);
    // P7：不得落叙事开场白模板
    expect(stage!.textContent || "").not.toMatch(/臣.*叩见|恭请圣安/);
  });
});

describe("ChatModal — #545 final composer contract", () => {
  it("#1278 召对收夜钮称散夜，仍走 chat 口令「退朝」seam，不与拟诏台退朝撞名", () => {
    const onSend = vi.fn();
    const onClose = vi.fn();
    const host = renderModal({ minister: MINISTER_MOCK, portraitPrefix: "minister_", onSend, onClose });

    expect(host.textContent).not.toContain("转入诏书草案");
    expect(host.textContent).not.toContain("任免");
    const buttons = Array.from(host.querySelectorAll("button"));
    const leave = buttons.find((button) => button.textContent?.includes("退出召对")) as HTMLButtonElement;
    const retreat = buttons.find((button) => button.textContent?.includes("散夜")) as HTMLButtonElement;
    expect(leave).toBeTruthy();
    expect(retreat).toBeTruthy();
    // 召对 chrome 不再显示与拟诏台同名的「退朝」
    expect(buttons.some((button) => (button.textContent || "").trim() === "退朝")).toBe(false);

    act(() => leave.click());
    expect(onClose).toHaveBeenCalledOnce();
    expect(onSend).not.toHaveBeenCalled();
    act(() => retreat.click());
    // 机制零改动：仍发后端 COURT_BREAK_COMMANDS 既认词
    expect(onSend).toHaveBeenCalledWith("周延儒", "退朝");
  });
});

describe("ChatModal — #527 prefix chips only (拟旨/下密令)", () => {
  /** Production suggestions_for payload after ADR 0042 / #527 cut. */
  const PREFIX_SUGGESTIONS: Suggestion[] = [
    { label: "拟旨", text: "拟旨如下：", prefix: true },
    { label: "下密令", text: "密令如下：", prefix: true, intent: "secret_order" },
  ];

  it("switching from draft to typed secret-order replaces composer content and does not auto-send", () => {
    const onSend = vi.fn();
    const onIntent = vi.fn();
    const host = renderModal({
      minister: MINISTER_MOCK,
      portraitPrefix: "minister_",
      suggestions: PREFIX_SUGGESTIONS,
      onSend,
      onIntent,
    });

    const hitlButtons = Array.from(host.querySelectorAll(".hitl-bar button"));
    expect(hitlButtons).toHaveLength(2);

    const textarea = host.querySelector("textarea") as HTMLTextAreaElement;
    expect(textarea).toBeTruthy();

    const draftBtn = hitlButtons.find((b) => b.textContent?.trim() === "拟旨") as HTMLButtonElement;
    act(() => {
      draftBtn.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(textarea.value).toBe("拟旨如下：");
    expect(onSend).not.toHaveBeenCalled();

    const secretBtn = hitlButtons.find((b) => b.textContent?.trim() === "下密令") as HTMLButtonElement;
    act(() => {
      secretBtn.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(textarea.value).toBe("密令如下：");
    expect(onIntent).toHaveBeenLastCalledWith("secret_order");
    expect(onSend).not.toHaveBeenCalled();
  });
});

describe("ChatModal — four diegetic roles and system boundary (#541)", () => {
  it("renders entrance and exit facts as scene beats, not system notes", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        night_id: 9,
        protagonist: "", roster: [], translation_pending: false, messages: [
          { role: "scene", speaker: "周延儒", content: "宣周延儒入殿。", beat: "entrance", audibility: "殿上公开", time: null, soft_boundary: false, highlights: [], container: { time_of_day: "", location: "", audience_type: "" } },
          { role: "scene", speaker: "周延儒", content: "周延儒告退。", beat: "exit", audibility: "殿上公开", time: null, soft_boundary: false, highlights: [], container: { time_of_day: "", location: "", audience_type: "" } },
        ],
      }),
    }));

    renderModal({ minister: MINISTER_MOCK, portraitPrefix: "minister_", currentNightId: 9 });
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
    await vi.waitFor(() => expect(document.querySelectorAll(".chat-message.scene")).toHaveLength(2));

    expect(document.querySelector(".scene.beat-entrance")?.textContent).toContain("入殿");
    expect(document.querySelector(".scene.beat-exit")?.textContent).toContain("告退");
    expect(document.querySelector(".chat-system-note")).toBeNull();
  });
});

describe("ChatModal — placeholder switches on character type", () => {
  it("shows audience commands in placeholder for ministers", () => {
    renderModal({ minister: MINISTER_MOCK, portraitPrefix: "minister_" });
    const textarea = document.querySelector("textarea") as HTMLTextAreaElement;
    expect(textarea.placeholder).toContain("宣 X");
    expect(textarea.placeholder).toContain("退朝");
  });

  it("does NOT show 大臣 or 他 in placeholder for consorts", () => {
    renderModal({ minister: CONSORT_MOCK, portraitPrefix: "consort_" });
    const textarea = document.querySelector("textarea") as HTMLTextAreaElement;
    expect(textarea.placeholder).not.toContain("大臣");
    expect(textarea.placeholder).not.toContain("他");
  });

  it("consort placeholder has meaningful length", () => {
    renderModal({ minister: CONSORT_MOCK, portraitPrefix: "consort_" });
    const textarea = document.querySelector("textarea") as HTMLTextAreaElement;
    expect(textarea.placeholder.length).toBeGreaterThan(5);
  });

  it("shows #505 system-layer reply retry control when replyRetry is set", () => {
    const retry = vi.fn();
    renderModal({
      minister: MINISTER_MOCK,
      portraitPrefix: "minister_",
      chat: [{ role: "user", content: "剿抚孰先？" }],
      replyRetries: [
        { chat_turn_id: 12, question: "剿抚孰先？" },
        { chat_turn_id: 13, question: "退朝", recovery_phase: "court_break", error_pack_path: "/tmp/post-reply-pack" },
      ],
      onRetryReply: retry,
    });
    const note = document.querySelector('[data-testid="reply-retry-12"]');
    expect(note?.textContent).toContain("重试");
    expect(note?.textContent).toContain("剿抚孰先？");
    expect(document.querySelector('[data-testid="reply-retry-13"]')?.textContent).toContain("回话已保存，后续处理失败");
    expect(document.querySelector('[data-testid="reply-retry-13"]')?.textContent).toContain("/tmp/post-reply-pack");
    const button = Array.from(document.querySelectorAll("button")).find(
      (node) => node.textContent === "重试",
    );
    expect(button).toBeTruthy();
    act(() => button?.click());
    expect(retry).toHaveBeenCalledTimes(1);
    expect(retry).toHaveBeenCalledWith("殿上", 12);
  });

});

describe("ChatModal — organic markdown display cleanup", () => {
  it("strips markdown from minister replies while preserving the emperor's text", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ night_id: 0, status: "", messages: [] }),
    }));
    renderModal({
      minister: MINISTER_MOCK,
      portraitPrefix: "minister_",
      chat: [
        { role: "user", content: "朕要看 **原文**。" },
        { role: "minister", content: "**臣谨奏**：\n- 钱粮已足。" },
      ],
    });

    await act(async () => { await Promise.resolve(); });
    const messages = Array.from(document.querySelectorAll(".chat-message p"));
    expect(messages[0]?.textContent).toBe("朕要看 **原文**。");
    expect(messages[1]?.textContent).toBe("**臣谨奏**：\n- 钱粮已足。");
  });

  it("#1280 scene/attendant 角色气泡同走 stripOrganicMarkdown", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        night_id: 23,
        protagonist: "", roster: [], translation_pending: false, messages: [
          { role: "scene", speaker: "周延儒", content: "殿内 **烛影** 摇曳\n- 夜风入户", beat: "entrance" },
          { role: "attendant", speaker: "王承恩", content: "**低声**：边报已至。", beat: "aside", audibility: "御前低语" },
          { role: "minister", speaker: "周延儒", content: "臣已知。", beat: "dialogue", chat_turn_id: 1 },
        ],
      }),
    }));
    const host = renderModal({
      minister: MINISTER_MOCK,
      ministers: [{ ...MINISTER_MOCK, name: "王承恩" }],
      portraitPrefix: "minister_",
      currentNightId: 23,
    });
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(host.querySelector(".chat-message.scene p")?.textContent).toBe("殿内 **烛影** 摇曳\n- 夜风入户");
    expect(host.querySelector(".chat-message.attendant p")?.textContent).toBe("**低声**：边报已至。");
  });
});

describe("ChatModal — four diegetic roles (#540)", () => {
  it("renders role variants and derives the private aside only from audibility", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ night_id: 23, protagonist: "", roster: [], translation_pending: false, messages: [
      { role: "scene", speaker: "周延儒", content: "殿门徐启", beat: "entrance", audibility: "殿上公开" },
      { role: "user", speaker: "朕", content: "（搁笔）卿且直言。", beat: "dialogue", audibility: "殿上公开", chat_turn_id: 1 },
      { role: "minister", speaker: "周延儒", content: "臣谨奏。", beat: "dialogue", audibility: "殿上公开", chat_turn_id: 1 },
      { role: "attendant", speaker: "曹化淳", content: "圣上，他有所隐瞒。", beat: "aside", audibility: "御前低语", chat_turn_id: 1 },
      { role: "attendant", speaker: "王承恩", content: "容臣低声禀报。", beat: "aside", audibility: "御前低语", chat_turn_id: 1 },
      { role: "attendant", speaker: "王承恩", content: "公开传话。", beat: "aside", audibility: "殿上公开", chat_turn_id: 1 },
    ] }) }));

    const host = renderModal({
      minister: MINISTER_MOCK,
      ministers: [
        { ...MINISTER_MOCK, id: "attendant-current", name: "曹化淳", portrait_id: "custom:8" },
        { ...MINISTER_MOCK, id: "attendant-former", name: "王承恩", portrait_id: "portrait_court_03" },
      ],
      portraitPrefix: "minister_",
      currentNightId: 23,
    });
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });

    expect(host.querySelector(".chat-message.scene")?.textContent).toBe("殿门徐启");
    expect(host.querySelector(".turn-segment.user p")?.textContent).toBe("（搁笔）卿且直言。");
    expect(host.querySelector(".turn-segment.minister")?.textContent).toContain("臣谨奏。");
    expect(host.querySelector(".turn-segment.aside")?.textContent).toContain("有所隐瞒");
    const avatars = Array.from(host.querySelectorAll<HTMLImageElement>(".aside-avatar"));
    expect(avatars[0]?.alt).toBe("曹化淳");
    expect(avatars[0]?.getAttribute("src")).toMatch(/^\/portraits\/custom\/%E6%9B%B9%E5%8C%96%E6%B7%B3\?t=/);
    expect(avatars[1]?.getAttribute("src")).toBe("/portraits/minister_attendant-former.png");
    expect(host.querySelector(".turn-segment.attendant:not(.aside)")?.textContent).toContain("公开传话");
  });
});

describe("ChatModal — soft scenes and selected-minister lens (#543 / #1511)", () => {
  it("keeps a side interjection in the selected minister segment without window bleed", async () => {
    const favorite = vi.fn();
    const send = vi.fn();
    const undo = vi.fn();
    const retryReply = vi.fn();
    const yang = { ...MINISTER_MOCK, id: "yang", name: "杨嗣昌", summary: "兵部旧臣", favorite: false };
    const hong = { ...MINISTER_MOCK, id: "hong", name: "洪承畴", office: "三边总督", summary: "边臣", favorite: true };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ night_id: 23, protagonist: "洪承畴", roster: [{ name: "洪承畴", present: true }], translation_retries: [{ chat_turn_id: 1, night_id: 23, minister_name: "洪承畴", kind: "translation_pending", retryable: true, error_pack_path: "/tmp/audience-turn-1" }], messages: [
      { role: "scene", speaker: "洪承畴", content: "", beat: "divider", soft_boundary: true, container: { audience_type: "越次召对" } },
      { role: "scene", speaker: "洪承畴", content: "洪承畴趋入殿中。", beat: "entrance", container: { audience_type: "越次召对" } },
      { role: "minister", speaker: "洪承畴", content: "臣自三边来。", beat: "dialogue", container: { audience_type: "越次召对" }, chat_turn_id: 1 },
      { role: "minister", speaker: "杨嗣昌", content: "殿侧容臣插一句。", beat: "dialogue", container: { audience_type: "越次召对" } },
      { role: "user", speaker: "朕", content: "辽饷何解？", beat: "dialogue", container: { audience_type: "越次召对" }, chat_turn_id: 12 },
      { role: "scene", speaker: "", content: "", beat: "divider", soft_boundary: true, container: { audience_type: "越次召对" } },
    ] }) }));

    // #1511 lens key = selected minister (洪), not a mismatched modal entry.
    const host = renderModal({
      minister: hong,
      ministers: [yang, hong],
      portraitPrefix: "minister_",
      currentNightId: 23,
      onFavorite: favorite,
      onSend: send,
      onUndo: undo,
      canUndoLastChat: true,
      replyRetries: [{ chat_turn_id: 12, question: "辽饷何解？" }],
      onRetryReply: retryReply,
      onRetryTranslation: vi.fn(),
      suggestions: [{ label: "追问", text: "细奏边情" }],
      secretOrders: [{ id: 9, minister_name: "洪承畴", title: "密察边饷", content: "暗访欠饷", status: "active", turn_issued: 1, due_turn: 2, year_issued: 1, period_issued: 11, tags: [], importance: 1, result: "", sim_note: "", turn_closed: null }],
    });
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });

    expect(host.querySelector(".audience-type-label")?.textContent).toBe("越次召对");
    expect(host.querySelector(".minister-profile")).toBeNull();
    expect(host.querySelector(".chat-portrait-wrap img")?.getAttribute("src")).toBe("/portraits/minister_hong.png");
    expect(host.querySelector(".chat-secret-orders")).toBeNull();
    const ministerMessages = host.querySelectorAll(".chat-message.minister");
    expect(ministerMessages[ministerMessages.length - 1]?.textContent).toContain("杨嗣昌");
    const clickButton = (text: string) => act(() => Array.from(host.querySelectorAll("button")).find((button) => button.textContent?.includes(text))?.click());
    clickButton("追问");
    // #1732 B：撤回就地确认
    clickButton("撤回本轮");
    clickButton("继续撤回");
    act(() => host.querySelector<HTMLButtonElement>('[data-testid="reply-retry-12"] button')?.click());
    expect(send).toHaveBeenCalledWith("洪承畴", "细奏边情");
    expect(undo).toHaveBeenCalledWith("洪承畴");
    expect(retryReply).toHaveBeenCalledWith("殿上", 12);
    const replyFailure = host.querySelector('[data-testid="reply-retry-12"]');
    expect(replyFailure?.closest('[data-audience-turn-id="12"]')).not.toBeNull();
    const translationFailure = host.querySelector('[data-testid="translation-retry-1"]');
    expect(translationFailure?.closest('[data-audience-turn-id="1"]')).not.toBeNull();
    expect(translationFailure?.textContent).toContain("/tmp/audience-turn-1");
    expect(translationFailure?.textContent).toContain("请交给作者");
    const divisions = Array.from(host.querySelectorAll(".beat-divider"));
    expect(divisions).toHaveLength(2);
    expect(divisions[0]?.textContent).toContain("洪承畴");
    expect(divisions[1]?.textContent).not.toMatch(/杨嗣昌|洪承畴/);
  });
});

describe("ChatModal — single night-scroll authority (#539)", () => {
  it("retires the whole old-night snapshot when the persisted player-entry identity changes before refresh fails", async () => {
    let rejectRefresh!: (reason?: unknown) => void;
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ night_id: 23, protagonist: "", roster: [], translation_pending: false, messages: [
        { role: "user", speaker: "朕", content: "旧夜问话", chat_turn_id: 1 },
        { role: "minister", speaker: MINISTER_MOCK.name, content: "旧夜答复", chat_turn_id: 1 },
        { role: "minister", speaker: "洪承畴", content: "同夜他臣", chat_turn_id: 2 },
        { role: "attendant", speaker: "王承恩", content: "旧轮迟到递话", chat_turn_id: 1, record_id: 91 },
      ] }) })
      .mockReturnValueOnce(new Promise((_resolve, reject) => { rejectRefresh = reject; }));
    vi.stubGlobal("fetch", fetchMock);
    let updateNight!: (nightId: number) => void;
    renderModal({ minister: MINISTER_MOCK, portraitPrefix: "minister_", currentNightId: 23,
      chat: [{ role: "user", content: "旧夜问话", chatTurnId: 1 }],
      registerNightUpdate: (update) => { updateNight = update; } });
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    // #1511: other minister's turn is lens-filtered out of this window immediately.
    expect(document.body.textContent).toContain("同夜他臣");
    expect(document.body.textContent).toContain("旧轮迟到递话");

    await act(async () => { updateNight(24); await Promise.resolve(); });
    expect(document.body.textContent).not.toContain("旧夜问话");
    expect(document.body.textContent).not.toContain("旧夜答复");
    expect(document.body.textContent).not.toContain("同夜他臣");
    expect(document.body.textContent).not.toContain("旧轮迟到递话");

    await act(async () => { rejectRefresh(new Error("refresh failed")); await Promise.resolve(); });
    expect(document.body.textContent).not.toContain("旧夜问话");
  });

  it("retires the pre-withdrawal snapshot when a successful undo identifies its turn", async () => {
    let rejectRefresh!: (reason?: unknown) => void;
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ night_id: 23, protagonist: "", roster: [], translation_pending: false, messages: [
        { role: "user", speaker: "朕", content: "撤回前问话", chat_turn_id: 1 },
        { role: "minister", speaker: MINISTER_MOCK.name, content: "撤回前答复", chat_turn_id: 1 },
        { role: "minister", speaker: "洪承畴", content: "仍在旧 snapshot", chat_turn_id: 2 },
      ] }) })
      .mockReturnValueOnce(new Promise((_resolve, reject) => { rejectRefresh = reject; }));
    vi.stubGlobal("fetch", fetchMock);
    let updateUndo!: (chatTurnId: number | null) => void;
    renderModal({
      minister: MINISTER_MOCK, portraitPrefix: "minister_", currentNightId: 23,
      chat: [{ role: "user", content: "撤回前问话", chatTurnId: 1 }],
      registerUndoUpdate: (update) => { updateUndo = update; },
    });
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(document.body.textContent).toContain("撤回前答复");

    await act(async () => { updateUndo(1); await Promise.resolve(); });
    expect(document.body.textContent).not.toContain("撤回前问话");
    expect(document.body.textContent).not.toContain("撤回前答复");
    expect(document.body.textContent).not.toContain("仍在旧 snapshot");

    await act(async () => { rejectRefresh(new Error("refresh failed")); await Promise.resolve(); });
    expect(document.body.textContent).not.toContain("撤回前答复");
  });

  it("does not treat an ordinary history reduction as a withdrawal", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ night_id: 23, protagonist: "", roster: [], translation_pending: false, messages: [
      { role: "user", speaker: "朕", content: "公共卷仍保留", chat_turn_id: 1 },
      { role: "minister", speaker: MINISTER_MOCK.name, content: "公共答复仍保留", chat_turn_id: 1 },
    ] }) }));
    let updateChat!: (chat: ChatMessage[]) => void;
    renderModal({
      minister: MINISTER_MOCK, portraitPrefix: "minister_", currentNightId: 23,
      chat: [{ role: "user", content: "个人 history", chatTurnId: 1 }],
      registerChatUpdate: (update) => { updateChat = update; },
    });
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    await act(async () => { updateChat([]); await Promise.resolve(); });

    expect(document.body.textContent).toContain("公共卷仍保留");
    expect(document.body.textContent).toContain("公共答复仍保留");
  });
  it("does not flash old minister chat while the night scroll is loading or failed", async () => {
    let reject!: (reason?: unknown) => void;
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise((_resolve, rejectPromise) => { reject = rejectPromise; })));
    renderModal({
      minister: MINISTER_MOCK,
      portraitPrefix: "minister_",
      chat: [{ role: "minister", content: "旧分线程不应闪回" }],
    });

    expect(document.body.textContent).not.toContain("旧分线程不应闪回");
    await act(async () => { reject(new Error("卷轴读取失败")); await Promise.resolve(); });
    expect(document.body.textContent).not.toContain("旧分线程不应闪回");
    expect(document.querySelector('[role="alert"]')?.textContent).toContain("召对记录读取失败");
  });

  it("restores at the tail, follows new content only while the player remains at the tail", async () => {
    let resolveScroll!: (value: unknown) => void;
    const fetchMock = vi.fn().mockReturnValue(new Promise((resolve) => { resolveScroll = resolve; }));
    vi.stubGlobal("fetch", fetchMock);
    let updateChat!: (chat: ChatMessage[]) => void;
    const host = renderModal({
      minister: MINISTER_MOCK,
      portraitPrefix: "minister_",
      chat: [{ role: "user", content: "初问" }],
      registerChatUpdate: (update) => { updateChat = update; },
    });
    const log = host.querySelector(".chat-log") as HTMLDivElement;
    let scrollHeight = 600;
    Object.defineProperties(log, {
      scrollHeight: { get: () => scrollHeight },
      clientHeight: { get: () => 200 },
    });

    await act(async () => {
      resolveScroll({ ok: true, json: async () => ({ night_id: 17, protagonist: "", roster: [], translation_pending: false, messages: [{ role: "user", content: "卷首" }] }) });
      await Promise.resolve(); await Promise.resolve();
    });
    expect(log.scrollTop).toBe(600);

    scrollHeight = 700;
    await act(async () => { updateChat([{ role: "user", content: "完成一轮" }]); await Promise.resolve(); });
    expect(log.scrollTop).toBe(700);

    log.scrollTop = 100;
    act(() => log.dispatchEvent(new Event("scroll", { bubbles: true })));
    scrollHeight = 800;
    await act(async () => { updateChat([{ role: "user", content: "完成二轮" }]); await Promise.resolve(); });
    expect(log.scrollTop).toBe(100);
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("restores a saved position and reports player scrolling for the open night", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ night_id: 23, protagonist: "", roster: [], translation_pending: false, messages: [{ role: "user", content: "卷首" }] }) }));
    const save = vi.fn();
    const host = renderModal({ minister: MINISTER_MOCK, portraitPrefix: "minister_", currentNightId: 23, scrollPosition: 137, onScrollPositionChange: save });
    const log = host.querySelector(".chat-log") as HTMLDivElement;
    Object.defineProperties(log, { scrollHeight: { value: 600 }, clientHeight: { value: 200 } });
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(log.scrollTop).toBe(137);
    log.scrollTop = 91;
    act(() => log.dispatchEvent(new Event("scroll", { bubbles: true })));
    expect(save).toHaveBeenLastCalledWith(91);
  });

  it("does not merge personal history while the canonical scroll refresh is delayed", async () => {
    let resolveRefresh!: (value: unknown) => void;
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ night_id: 23, protagonist: "", roster: [], translation_pending: false, messages: [
        { role: "user", speaker: "朕", content: "旧卷", chat_turn_id: 1 },
        { role: "minister", speaker: MINISTER_MOCK.name, content: "旧答", chat_turn_id: 1 },
      ] }) })
      .mockReturnValueOnce(new Promise((resolve) => { resolveRefresh = resolve; }));
    vi.stubGlobal("fetch", fetchMock);
    let updateChat!: (chat: ChatMessage[]) => void;
    renderModal({
      minister: MINISTER_MOCK,
      portraitPrefix: "minister_",
      currentNightId: 23,
      chat: [{ role: "user", content: "旧卷", chatTurnId: 1 }],
      registerChatUpdate: (update) => { updateChat = update; },
    });
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });

    await act(async () => {
      updateChat([
        { role: "user", content: "旧卷", chatTurnId: 1 },
        { role: "user", content: "刚完成的新问", chatTurnId: 2 },
        { role: "minister", content: "刚完成的答复", chatTurnId: 2 },
      ]);
      await Promise.resolve();
    });
    expect(document.body.textContent).toContain("旧卷");
    expect(document.body.textContent).not.toContain("刚完成的新问");
    expect(document.body.textContent).not.toContain("刚完成的答复");

    await act(async () => {
      resolveRefresh({ ok: true, json: async () => ({ night_id: 23, protagonist: "", roster: [], translation_pending: false, messages: [
        { role: "user", speaker: "朕", content: "旧卷", chat_turn_id: 1 },
        { role: "minister", speaker: MINISTER_MOCK.name, content: "旧答", chat_turn_id: 1 },
        { role: "user", speaker: "朕", content: "刚完成的新问", chat_turn_id: 2 },
        { role: "minister", speaker: MINISTER_MOCK.name, content: "刚完成的答复", chat_turn_id: 2 },
      ] }) });
      await Promise.resolve(); await Promise.resolve();
    });
    expect(document.body.textContent?.match(/刚完成的新问/g)).toHaveLength(1);
    expect(document.body.textContent?.match(/刚完成的答复/g)).toHaveLength(1);
  });



  it("keeps the last-known scroll without importing personal history when refresh fails", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ night_id: 23, protagonist: "", roster: [], translation_pending: false, messages: [
        { role: "user", speaker: "朕", content: "旧卷", chat_turn_id: 1 },
        { role: "minister", speaker: MINISTER_MOCK.name, content: "旧答", chat_turn_id: 1 },
      ] }) })
      .mockRejectedValueOnce(new Error("refresh failed"));
    vi.stubGlobal("fetch", fetchMock);
    let updateChat!: (chat: ChatMessage[]) => void;
    renderModal({
      minister: MINISTER_MOCK,
      portraitPrefix: "minister_",
      currentNightId: 23,
      chat: [{ role: "user", content: "旧卷", chatTurnId: 1 }],
      registerChatUpdate: (update) => { updateChat = update; },
    });
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    await act(async () => {
      updateChat([
        { role: "user", content: "旧卷", chatTurnId: 1 },
        { role: "user", content: "失败前新问", chatTurnId: 2 },
        { role: "minister", content: "失败前已完成", chatTurnId: 2 },
      ]);
      await Promise.resolve(); await Promise.resolve();
    });

    expect(document.body.textContent).toContain("旧卷");
    expect(document.body.textContent).not.toContain("失败前新问");
    expect(document.body.textContent).not.toContain("失败前已完成");
    expect(document.querySelector('[role="alert"]')?.textContent).toContain("召对记录读取失败");
  });

  it("refreshes the canonical scroll after a non-streaming completed chat update", async () => {
    const replies = [
      { night_id: 23, protagonist: "", roster: [], translation_pending: false, messages: [
        { role: "user", speaker: "朕", content: "旧卷", chat_turn_id: 1 },
        { role: "minister", speaker: MINISTER_MOCK.name, content: "旧答", chat_turn_id: 1 },
      ] },
      { night_id: 23, protagonist: "", roster: [], translation_pending: false, messages: [
        { role: "user", speaker: "朕", content: "旧卷", chat_turn_id: 1 },
        { role: "minister", speaker: MINISTER_MOCK.name, content: "旧答", chat_turn_id: 1 },
        { role: "minister", speaker: MINISTER_MOCK.name, content: "非流式新答", chat_turn_id: 2 },
      ] },
    ];
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async () => ({ ok: true, json: async () => replies.shift() })));
    let updateChat!: (chat: ChatMessage[]) => void;
    renderModal({ minister: MINISTER_MOCK, portraitPrefix: "minister_",
      currentNightId: 23, registerChatUpdate: (update) => { updateChat = update; } });
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(document.body.textContent).toContain("旧卷");
    await act(async () => { updateChat([{ role: "minister", content: "旧分线程答" }]); await Promise.resolve(); await Promise.resolve(); });
    expect(document.body.textContent).toContain("非流式新答");
    expect(document.body.textContent).not.toContain("旧分线程答");
  });

  it("renders a streaming reply as a neutral scene block", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ night_id: 23, protagonist: "", roster: [], translation_pending: false, messages: [
        { role: "scene", speaker: "洪承畴", content: "入殿", beat: "entrance" },
        { role: "minister", speaker: "洪承畴", content: "臣在。", beat: "dialogue", chat_turn_id: 1 },
        { role: "attendant", speaker: "杨嗣昌", content: "御前低语", audibility: "御前低语", beat: "dialogue" },
      ] }),
    }));
    const hong = { ...MINISTER_MOCK, name: "洪承畴" };
    renderModal({
      minister: hong,
      ministers: [{ ...MINISTER_MOCK, name: "杨嗣昌" }, hong],
      portraitPrefix: "minister_",
      currentNightId: 23,
      busy: "大臣思索中",
      streamingMinisterMessage: "臣请奏边务",
    });

    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    const streamed = Array.from(document.querySelectorAll(".chat-message.scene"))
      .find((node) => node.textContent?.includes("臣请奏边务"));
    expect(streamed?.classList.contains("scene")).toBe(true);
    expect(streamed?.querySelector("span")).toBeNull();
    expect(document.body.textContent).toContain("杨嗣昌御前低语");
  });

  it("attributes the thinking row to the selected minister", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ night_id: 23, protagonist: "洪承畴", roster: [{ name: "洪承畴", present: true }], messages: [
        { role: "scene", speaker: "洪承畴", content: "入殿", beat: "entrance" },
      ] }),
    }));
    renderModal({
      minister: { ...MINISTER_MOCK, name: "洪承畴" },
      ministers: [{ ...MINISTER_MOCK, name: "杨嗣昌" }, { ...MINISTER_MOCK, name: "洪承畴" }],
      portraitPrefix: "minister_",
      currentNightId: 23,
      busy: "大臣思索中",
    });
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(document.querySelector(".chat-message.thinking span")?.textContent).toBe("洪承畴");
  });

  it("keeps ordinary no-night chat on the legacy projection", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ night_id: 0, status: "", messages: [] }),
    }));
    renderModal({
      minister: CONSORT_MOCK,
      portraitPrefix: "consort_",
      chat: [{ role: "minister", content: "宫中旧话照常" }],
    });

    await act(async () => { await Promise.resolve(); });
    expect(document.body.textContent).toContain("宫中旧话照常");
  });
});

describe("ChatModal — one-night audience scroll (#1849)", () => {
  const hong = { ...MINISTER_MOCK, id: "hong", name: "洪承畴", office: "三边总督" };
  const xu = { ...MINISTER_MOCK, id: "xu", name: "许誉卿", office: "给事中" };
  const nightScroll = [
    { role: "user", speaker: "朕", content: "密令：整饬边备。", beat: "dialogue", chat_turn_id: 11, audibility: "殿上公开", time: null, soft_boundary: false, highlights: [], container: { time_of_day: "戌时", location: "乾清宫", audience_type: "召对" } },
    { role: "minister", speaker: "洪承畴", content: "臣领旨。", beat: "dialogue", chat_turn_id: 11, audibility: "殿上公开", time: null, soft_boundary: false, highlights: [], container: { time_of_day: "戌时", location: "乾清宫", audience_type: "召对" } },
    { role: "attendant", speaker: "王承恩", content: "他神色凝重。", beat: "aside", chat_turn_id: 11, audibility: "御前低语", time: null, soft_boundary: false, highlights: [], container: { time_of_day: "戌时", location: "乾清宫", audience_type: "召对" } },
  ];

  it("shows portraits for declared people outside the court and talent lists", async () => {
    const visitor = { ...MINISTER_MOCK, name: "夜访者", portrait_id: "portrait_guest" };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({
      night_id: 23, protagonist: visitor.name,
      roster: [{ name: visitor.name, present: true }], characters: [visitor],
      translation_pending: false, messages: [{ ...nightScroll[2], speaker: visitor.name }],
    }) }));
    const host = renderModal({ minister: xu, ministers: [hong, xu], portraitPrefix: "minister_", currentNightId: 23 });
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(host.querySelector(".chat-portrait-wrap img")?.getAttribute("src")).toBe("/portraits/minister_夜访者.png");
    expect(host.querySelector(".audience-roster img")?.getAttribute("src")).toBe("/portraits/minister_夜访者.png");
    expect(host.querySelector("img.aside-avatar")?.getAttribute("src")).toBe("/portraits/minister_夜访者.png");
  });

  it("prefers current-night portrait data over a stale court-list copy", async () => {
    const updated = { ...hong, portrait_id: "custom:latest" };
    let reads = 0;
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async () => ({ ok: true, json: async () => ({
      night_id: 23, protagonist: hong.name,
      roster: [{ name: hong.name, present: true }], characters: [reads++ ? updated : hong],
      translation_pending: false, messages: [{ ...nightScroll[2], speaker: hong.name }],
    }) })));
    let updateMinister!: (minister: Minister) => void;
    const host = renderModal({ minister: xu, ministers: [hong, xu], portraitPrefix: "minister_", currentNightId: 23,
      registerMinisterUpdate: (update) => { updateMinister = update; } });
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    await act(async () => { host.querySelector<HTMLImageElement>(".audience-roster img")?.dispatchEvent(new Event("error")); });
    expect(host.querySelector(".audience-roster .minister-card-portrait-placeholder")).not.toBeNull();
    await act(async () => { updateMinister({ ...xu, name: "另位臣" }); await Promise.resolve(); await Promise.resolve(); });
    expect(host.querySelector(".chat-portrait-wrap img")?.getAttribute("src")).toMatch(/^\/portraits\/custom\/%E6%B4%AA%E6%89%BF%E7%95%B4\?t=/);
    expect(host.querySelector(".audience-roster img")?.getAttribute("src")).toMatch(/^\/portraits\/custom\/%E6%B4%AA%E6%89%BF%E7%95%B4\?t=/);
    expect(host.querySelector("img.aside-avatar")?.getAttribute("src")).toMatch(/^\/portraits\/custom\/%E6%B4%AA%E6%89%BF%E7%95%B4\?t=/);
  });

  it("shows the whole chronological night instead of a selected-minister window", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ night_id: 23, protagonist: "", roster: [], translation_pending: false, messages: nightScroll }) }));
    renderModal({ minister: xu, ministers: [hong, xu], portraitPrefix: "minister_", currentNightId: 23 });
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(document.body.textContent).toContain("密令：整饬边备");
    expect(document.body.textContent).toContain("臣领旨");
    expect(document.body.textContent).toContain("神色凝重");
  });

  it("uses roster clicks as summon commands without changing panels", async () => {
    const onSend = vi.fn();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ night_id: 23, protagonist: "许誉卿", roster: [{ name: "洪承畴", present: true }, { name: "许誉卿", present: true }], messages: nightScroll }) }));
    renderModal({ minister: xu, ministers: [hong, xu], portraitPrefix: "minister_", currentNightId: 23, onSend });
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    const summon = Array.from(document.querySelectorAll<HTMLButtonElement>(".audience-roster button"))
      .find((button) => button.textContent?.includes("洪承畴"));
    act(() => summon?.click());
    expect(onSend).toHaveBeenCalledWith("许誉卿", "宣洪承畴");
  });

  it("renders the declared protagonist while keeping every entrant in the avatar roster", async () => {
    let updateNight!: (nightId: number) => void;
    let protagonist = "";
    let nightId = 23;
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async () => ({ ok: true, json: async () => ({
      night_id: nightId,
      protagonist,
      roster: protagonist ? [
        { name: "洪承畴", present: true },
        { name: "许誉卿", present: false },
      ] : [],
      messages: nightScroll,
    }) })));
    const host = renderModal({ minister: xu, ministers: [hong, xu], portraitPrefix: "minister_", currentNightId: 23,
      registerNightUpdate: (update) => { updateNight = update; } });
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(host.querySelector(".chat-portrait-wrap img")).toBeNull();
    expect(Array.from(host.querySelectorAll(".audience-roster button")).map((node) => node.getAttribute("data-presence")))
      .toEqual(["waiting", "waiting"]);

    protagonist = "洪承畴";
    nightId = 24;
    await act(async () => { updateNight(24); await Promise.resolve(); await Promise.resolve(); });

    expect(host.querySelector(".chat-portrait-wrap img")?.getAttribute("src")).toBe("/portraits/minister_hong.png");
    expect(Array.from(host.querySelectorAll(".audience-roster img")).map((node) => node.getAttribute("src")))
      .toEqual(["/portraits/minister_hong.png", "/portraits/minister_xu.png"]);
    expect(host.querySelector('[data-roster-name="许誉卿"]')?.getAttribute("data-presence")).toBe("departed");
    expect(host.querySelectorAll(".minister-side > .chat-portrait-wrap")).toHaveLength(1);
    act(() => { host.querySelector<HTMLImageElement>(".chat-portrait-wrap img")?.dispatchEvent(new Event("error")); });
    expect(host.querySelector(".chat-portrait-wrap img")).toBeNull();
    protagonist = "许誉卿";
    nightId = 25;
    await act(async () => { updateNight(25); await Promise.resolve(); await Promise.resolve(); });
    expect(host.querySelector(".chat-portrait-wrap img")?.getAttribute("src")).toBe("/portraits/minister_xu.png");
    protagonist = "名册之外";
    nightId = 26;
    await act(async () => { updateNight(26); await Promise.resolve(); await Promise.resolve(); });
    expect(host.querySelector(".chat-portrait-wrap img")).toBeNull();
  });

  it("refreshes the open scroll when a late translation finishes after the reply", async () => {
    vi.useFakeTimers();
    let pending = true;
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async () => ({ ok: true, json: async () => ({
      night_id: 23,
      messages: [],
      protagonist: pending ? "洪承畴" : "许誉卿",
      roster: [{ name: "洪承畴", present: pending }],
      translation_pending: pending,
    }) })));
    try {
      const host = renderModal({ minister: xu, ministers: [hong, xu], portraitPrefix: "minister_", currentNightId: 23 });
      await act(async () => { await Promise.resolve(); await Promise.resolve(); });
      expect(host.querySelector(".chat-portrait-wrap img")?.getAttribute("src")).toBe("/portraits/minister_hong.png");
      pending = false;
      await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
      expect(host.querySelector(".chat-portrait-wrap img")?.getAttribute("src")).toBe("/portraits/minister_hong.png");
      await act(async () => { await vi.advanceTimersByTimeAsync(500); });
      expect(host.querySelector(".chat-portrait-wrap img")?.getAttribute("src")).toBe("/portraits/minister_xu.png");
      expect(host.querySelector('[data-roster-name="洪承畴"]')?.getAttribute("data-presence")).toBe("departed");
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps one turn container while a streamed reply becomes durable", async () => {
    let updateChat!: (chat: ChatMessage[]) => void;
    let updateStreaming!: (message: string) => void;
    let updatePendingIdentity!: (identity: { campaign_id: string; night_id: number; chat_turn_id: number } | null) => void;
    let reads = 0;
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async () => ({
      ok: true,
      json: async () => reads++ === 0
        ? ({ night_id: 23, protagonist: "", roster: [], translation_pending: false, messages: [] })
        : ({ night_id: 23, protagonist: "", roster: [], translation_pending: false, messages: nightScroll.filter((message) => message.chat_turn_id === 11) }),
    })));
    renderModal({
      minister: hong,
      ministers: [hong, xu],
      portraitPrefix: "minister_",
      currentNightId: 23,
      pendingIdentity: { campaign_id: "test-campaign", night_id: 23, chat_turn_id: 11 },
      streamingMinisterMessage: "流式回话",
      registerChatUpdate: (update) => { updateChat = update; },
      registerStreamingUpdate: (update) => { updateStreaming = update; },
      registerPendingIdentityUpdate: (update) => { updatePendingIdentity = update; },
    });
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    const streamingTurn = document.querySelector<HTMLElement>('[data-audience-turn-id="11"]');
    expect(streamingTurn).not.toBeNull();

    await act(async () => {
      updateStreaming("");
      updatePendingIdentity(null);
      await Promise.resolve();
    });
    expect(document.querySelector('[data-audience-turn-id="11"]')).toBe(streamingTurn);

    await act(async () => {
      updateChat([{ role: "user", content: "已落卷", chatTurnId: 11 }]);
      await Promise.resolve();
      await Promise.resolve();
    });
    await act(async () => { await vi.waitFor(() => expect(document.querySelectorAll('[data-audience-turn-id="11"] .turn-segment')).toHaveLength(3)); });
    expect(document.querySelector('[data-audience-turn-id="11"]')).toBe(streamingTurn);
  });

  it("adds translated roles and minister emphasis inside the same unchanged turn block", async () => {
    vi.useFakeTimers();
    let reads = 0;
    const parts = ["密令：整饬边备。", "臣领旨。", "臣附议。", "王承恩低语。", "殿内烛影摇曳。"];
    const turnId = 11;
    const trailing = { role: "user", speaker: "朕", content: "后续诏问", beat: "dialogue", chat_turn_id: turnId + 1 };
    const neutral = [{ role: "scene", speaker: "", content: parts.join(""), beat: "dialogue", chat_turn_id: turnId }, trailing];
    const translated = [
      { role: "user", speaker: "朕", content: parts[0], beat: "dialogue", chat_turn_id: turnId },
      { role: "minister", speaker: "洪承畴", content: parts[1], beat: "dialogue", highlights: ["领旨"], chat_turn_id: turnId },
      { role: "minister", speaker: "许誉卿", content: parts[2], beat: "dialogue", highlights: ["附议"], chat_turn_id: turnId },
      { role: "attendant", speaker: "王承恩", content: parts[3], beat: "aside", audibility: "御前低语", highlights: ["低语"], chat_turn_id: turnId },
      { role: "scene", speaker: "", content: parts[4], beat: "dialogue", chat_turn_id: turnId },
      trailing,
    ];
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async () => {
      if (reads++ === 1) throw new Error("temporary read failure");
      return {
        ok: true,
        json: async () => reads === 1
          ? ({ night_id: 23, messages: neutral, translation_pending: true })
          : ({ night_id: 23, messages: translated, translation_pending: false }),
      };
    }));
    renderModal({
      minister: hong,
      ministers: [hong, xu],
      portraitPrefix: "minister_",
      currentNightId: 23,
    });
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    const turn = document.querySelector<HTMLElement>(`[data-audience-turn-id="${turnId}"]`);
    const originalStory = Array.from(turn?.querySelectorAll("p") ?? [], (node) => node.textContent).join("");
    const stage = document.querySelector<HTMLElement>(".chat-stage")!;
    Object.defineProperties(stage, { scrollHeight: { value: 600 }, clientHeight: { value: 200 } });
    vi.spyOn(stage, "getBoundingClientRect").mockReturnValue({ top: 0, left: 0 } as DOMRect);
    const storyParagraph = turn?.querySelector("p")!;
    vi.spyOn(storyParagraph, "getBoundingClientRect").mockReturnValue({ top: -20, bottom: 100, left: 14 } as DOMRect);
    const storyNode = storyParagraph.firstChild;
    Object.defineProperty(document, "caretPositionFromPoint", {
      configurable: true, value: () => ({ offsetNode: storyNode, offset: parts[0].length }),
    });
    Object.defineProperty(Range.prototype, "getClientRects", { configurable: true, value: function (this: Range) {
      const segment = this.startContainer.parentElement?.closest(".turn-segment");
      const top = !segment || turn?.querySelectorAll(".turn-segment").length === 1 ? 50
        : segment === turn?.querySelectorAll(".turn-segment")[1] ? 150 : 110;
      return [{ top } as DOMRect] as unknown as DOMRectList;
    } });
    stage.scrollTop = 100;
    act(() => stage.dispatchEvent(new Event("scroll", { bubbles: true })));

    await act(async () => { await vi.advanceTimersByTimeAsync(1500); });
    expect(Array.from(turn?.querySelectorAll(".turn-segment p") ?? [], (node) => node.textContent).join("")).toBe(originalStory);
    expect(stage.scrollTop).toBe(100);
    await act(async () => { await vi.advanceTimersByTimeAsync(1500); });
    expect(turn?.querySelectorAll('.turn-segment')).toHaveLength(translated.length - 1);
    expect(stage.scrollTop).toBe(200);
    expect(document.querySelectorAll(`[data-audience-turn-id="${turnId}"]`)).toHaveLength(1);
    expect(document.querySelector(`[data-audience-turn-id="${turnId}"]`)).toBe(turn);
    expect(turn?.querySelectorAll(".chat-message")).toHaveLength(0);
    expect(turn?.querySelectorAll(".turn-segment")).toHaveLength(translated.length - 1);
    expect(turn?.querySelectorAll(".turn-segment.minister strong.hl")).toHaveLength(2);
    expect(turn?.querySelectorAll(".turn-segment.aside p")).toHaveLength(1);
    expect(turn?.querySelectorAll(".turn-segment.user strong.hl, .turn-segment.aside strong.hl, .turn-segment.scene strong.hl")).toHaveLength(0);
    expect(Array.from(turn?.querySelectorAll(".turn-segment p") ?? [], (node) => node.textContent).join("")).toBe(originalStory);
  });

  it("shows a background translation failure beneath its turn without reopening the scroll", async () => {
    vi.useFakeTimers();
    const story = { role: "scene", content: "臣请据实核账。", chat_turn_id: 11 };
    let reads = 0;
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async () => ({
      ok: true,
      json: async () => (++reads === 1
        ? { night_id: 23, messages: [story], translation_pending: true, translation_retries: [] }
        : { night_id: 23, messages: [story], translation_pending: true, translation_retries: [
            { chat_turn_id: 11, night_id: 23, minister_name: "洪承畴", kind: "translation_pending", retryable: true, error_pack_path: "/tmp/turn-11" },
          ] }),
    })));
    const retry = vi.fn();
    renderModal({ minister: hong, ministers: [hong], portraitPrefix: "minister_", currentNightId: 23, onRetryTranslation: retry });
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(document.querySelector('[data-testid="translation-retry-11"]')).toBeNull();
    await act(async () => { await vi.advanceTimersByTimeAsync(1500); });
    const turn = document.querySelector('[data-audience-turn-id="11"]');
    const button = turn?.querySelector<HTMLButtonElement>('[data-testid="translation-retry-11"] button');
    expect(button).not.toBeNull();
    act(() => button?.click());
    expect(retry).toHaveBeenCalledWith(11);
  });

  it("removes an unpersisted streamed turn when its request fails", async () => {
    let updateStreaming!: (message: string) => void;
    let updatePendingIdentity!: (identity: { campaign_id: string; night_id: number; chat_turn_id: number } | null) => void;
    let updateFailedIdentity!: (identity: { campaign_id: string; night_id: number; chat_turn_id: number } | null) => void;
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ night_id: 23, protagonist: "", roster: [], translation_pending: false, messages: [] }) }));
    renderModal({
      minister: hong,
      ministers: [hong, xu],
      portraitPrefix: "minister_",
      currentNightId: 23,
      pendingIdentity: { campaign_id: "test-campaign", night_id: 23, chat_turn_id: 11 },
      streamingMinisterMessage: "未落卷回话",
      registerStreamingUpdate: (update) => { updateStreaming = update; },
      registerPendingIdentityUpdate: (update) => { updatePendingIdentity = update; },
      registerFailedIdentityUpdate: (update) => { updateFailedIdentity = update; },
    });
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(document.querySelector('[data-audience-turn-id="11"]')).not.toBeNull();

    await act(async () => {
      updateStreaming("");
      updatePendingIdentity(null);
      updateFailedIdentity({ campaign_id: "test-campaign", night_id: 23, chat_turn_id: 11 });
      await Promise.resolve();
    });
    expect(document.querySelector('[data-audience-turn-id="11"]')).toBeNull();
  });

  it("半轮 replyRetry：保留同 turn user 气泡且不重复 pending 气泡", async () => {
    const halfTurnScroll = [
      { role: "user", speaker: "朕", content: "辽饷何解？", beat: "dialogue", chat_turn_id: 12, audibility: "殿上公开", time: null, soft_boundary: false, highlights: [], container: { time_of_day: "戌时", location: "乾清宫", audience_type: "召对" } },
      // The same night keeps every participant in chronological order.
      ...nightScroll,
    ];
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ night_id: 23, protagonist: "", roster: [], translation_pending: false, messages: halfTurnScroll }) }));
    renderModal({
      minister: xu,
      ministers: [hong, xu],
      portraitPrefix: "minister_",
      currentNightId: 23,
      replyRetries: [{ chat_turn_id: 12, question: "辽饷何解？" }],
      pendingUserMessage: "辽饷何解？",
      pendingIdentity: { campaign_id: "test-campaign", night_id: 23, chat_turn_id: 12 },
    });
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(document.body.textContent).toContain("辽饷何解？");
    expect(document.body.textContent).toContain("密令：整饬边备");
    expect(document.body.textContent).toContain("臣领旨");
    // Single user bubble — claimed persisted turn suppresses the synthetic pending duplicate.
    const userBubbles = Array.from(document.querySelectorAll(".turn-segment.user"))
      .filter((node) => node.textContent?.includes("辽饷何解？"));
    expect(userBubbles).toHaveLength(1);
  });

  it("切回有记录大臣：语义轮完整含朕问/回话/递话", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ night_id: 23, protagonist: "", roster: [], translation_pending: false, messages: nightScroll }) }));
    renderModal({ minister: hong, ministers: [hong, xu], portraitPrefix: "minister_", currentNightId: 23 });
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(document.body.textContent).toContain("密令：整饬边备");
    expect(document.body.textContent).toContain("臣领旨");
    expect(document.body.textContent).toContain("神色凝重");
    expect(document.querySelector(".minister-profile")).toBeNull();
  });

});

describe("#1480 / #1499 FullscreenModal modal-layout-bare 只随 hideTitle", () => {
  it("hideTitle 挂 modal-layout-bare；起居注有可见标题栏不挂", async () => {
    const bareHost = document.createElement("div");
    document.body.appendChild(bareHost);
    const bareRoot = createRoot(bareHost);
    mountedRoots.push({ root: bareRoot, host: bareHost });
    act(() => {
      bareRoot.render(
        <FullscreenModal title="召对：周延儒" subtitle="内阁首辅" bgClass="modal-bg-chat" hideTitle onClose={() => {}}>
          <div className="chat-full-grid">长转录正文</div>
        </FullscreenModal>,
      );
    });
    const bareModal = bareHost.querySelector(".fullscreen-modal.modal-bg-chat");
    expect(bareModal).not.toBeNull();
    expect(bareModal!.classList.contains("modal-layout-bare")).toBe(true);
    expect(bareHost.querySelector(".modal-header-bare")).not.toBeNull();
    expect(bareHost.querySelector(".modal-title")).toBeNull();

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ turns: [] }),
    }));
    const archiveHost = document.createElement("div");
    document.body.appendChild(archiveHost);
    const archiveRoot = createRoot(archiveHost);
    mountedRoots.push({ root: archiveRoot, host: archiveHost });
    await act(async () => {
      archiveRoot.render(<AudienceArchiveModal ministers={[]} onClose={() => {}} />);
      await Promise.resolve();
    });
    const archiveModal = archiveHost.querySelector(".fullscreen-modal.modal-bg-chat");
    expect(archiveModal).not.toBeNull();
    expect(archiveModal!.classList.contains("modal-layout-bare")).toBe(false);
    expect(archiveHost.querySelector(".modal-header-bare")).toBeNull();
    expect(archiveHost.querySelector(".modal-title h1")?.textContent).toContain("起居注");
  });
});

describe("AudienceArchiveModal — read-only scene archive", () => {
  it("selects closed scenes through the shared scroll endpoint without a composer", async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (url === "/api/history/turns") return Promise.resolve({ ok: true, json: async () => ({ turns: [
        { kind: "month", turn: 7, year: 1, period: 11, has_report: true, has_attendant: false, has_directive: false },
        { kind: "night", turn: 7, year: 1, period: 11, night_id: 31, title: "1年11月 · 戌时乾清宫 · 越次召对 · 第1场", involved_people: ["杨嗣昌"] },
        { kind: "night", turn: 7, year: 1, period: 11, night_id: 32, title: "1年11月 · 戌时乾清宫 · 召对 · 第2场", involved_people: ["洪承畴"] },
      ] }) });
      const id = url.endsWith("31") ? 31 : 32;
      return Promise.resolve({ ok: true, json: async () => ({ messages: id === 32 ? [
        { role: "user", speaker: "朕", content: `场次${id}`, beat: "dialogue", chat_turn_id: 8 },
        { role: "minister", speaker: "殿上", content: "群臣奏对", beat: "dialogue", chat_turn_id: 8 },
        { role: "attendant", speaker: "退场近臣", content: "旧臣御前低语", beat: "aside", chat_turn_id: 8, audibility: "御前低语" },
      ] : [{ role: "user", content: `场次${id}` }] }) });
    });
    vi.stubGlobal("fetch", fetchMock);
    const host = document.createElement("div"); document.body.appendChild(host);
    const root = createRoot(host); mountedRoots.push({ root, host });
    await act(async () => { root.render(<AudienceArchiveModal ministers={[
      { ...MINISTER_MOCK, id: "former-attendant", name: "退场近臣", portrait_id: "portrait_court_03" },
    ]} onClose={() => {}} />); await Promise.resolve(); await Promise.resolve(); });
    expect(host.textContent).toContain("召对记录");
    expect(host.textContent).toContain("涉及人物：洪承畴");
    expect(host.textContent).toContain("场次32");
    const filter = host.querySelector<HTMLSelectElement>('select[aria-label="按臣过滤"]')!;
    await act(async () => {
      filter.value = "洪承畴";
      filter.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(host.textContent).toContain("群臣奏对");
    expect(host.querySelector("textarea, input, .chat-composer")).toBeNull();
    const archivedAvatar = host.querySelector<HTMLImageElement>(".aside-avatar");
    expect(archivedAvatar?.getAttribute("src")).toBe("/portraits/minister_former-attendant.png");
    const buttons = Array.from(host.querySelectorAll(".history-turn-item")) as HTMLButtonElement[];
    await act(async () => { buttons[1].click(); await Promise.resolve(); await Promise.resolve(); });
    expect(fetchMock).toHaveBeenCalledWith("/api/audience/scroll?night_id=31");
    expect(host.textContent).toContain("场次31");
    expect(host.querySelector<HTMLSelectElement>('select[aria-label="按臣过滤"]')?.value).toBe("");
  });

  it("史册 filters out scene rows and keeps the public-document boundary", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => Promise.resolve({ ok: true, json: async () =>
      url === "/api/history/turns" ? { turns: [
        { kind: "month", turn: 7, year: 1, period: 11, has_report: true, has_attendant: false, has_directive: false },
        { kind: "night", turn: 7, year: 1, period: 11, night_id: 31, title: "不应出现的场卷" },
      ] } : { turn: 7, exists: true, report: "月档奏报", directives: [] }
    })));
    const host = document.createElement("div"); document.body.appendChild(host);
    const root = createRoot(host); mountedRoots.push({ root, host });
    await act(async () => { root.render(<HistoryModal onClose={() => {}} />); await Promise.resolve(); await Promise.resolve(); });
    expect(host.textContent).toMatch(/奏报.*诏书.*递话|奏报、诏书与递话/);
    expect(host.textContent).not.toContain("不应出现的场卷");
  });

  it("#671 史册月档经 HistoryModal fetch 呈现独立递话原文", async () => {
    const raw = "\n  **皇爷**，洪承畴本月抵京候旨。  \n";
    const blank = "   \n\t  ";
    const monthTurn = { kind: "month" as const, turn: 7, year: 1, period: 11, has_report: true, has_attendant: true, has_directive: false };
    const fetchMock = vi.fn().mockImplementation((url: string) => Promise.resolve({
      ok: true,
      json: async () => url === "/api/history/turns"
        ? { turns: [monthTurn] }
        : {
            turn: 7,
            exists: true,
            year: 1,
            period: 11,
            report: "一、人事除目",
            attendant_message: raw,
            decree_text: "",
            directives: [],
          },
    }));
    vi.stubGlobal("fetch", fetchMock);
    const host = document.createElement("div"); document.body.appendChild(host);
    const root = createRoot(host); mountedRoots.push({ root, host });
    await act(async () => {
      root.render(<HistoryModal onClose={() => {}} />);
    });
    // 等详情链落地后再断言递话原文（完成信号，非固定微任务次数）
    await act(async () => {
      await vi.waitFor(async () => {
        await Promise.resolve();
        expect(host.querySelector("[data-testid=history-attendant]")).not.toBeNull();
      });
    });
    expect(fetchMock).toHaveBeenCalledWith("/api/history/turns");
    expect(fetchMock).toHaveBeenCalledWith("/api/history/turn/7");
    const section = host.querySelector("[data-testid=history-attendant]");
    // trim 仅判空；DOM 写原文（含空白与 markdown 标记）
    expect(section!.querySelector("pre")?.textContent).toBe(raw);

    // 纯空白递话：先等详情 report 正文落地，再断言 section 缺席
    fetchMock.mockImplementation((url: string) => Promise.resolve({
      ok: true,
      json: async () => url === "/api/history/turns"
        ? { turns: [monthTurn] }
        : {
            turn: 7,
            exists: true,
            year: 1,
            period: 11,
            report: "一、人事除目",
            attendant_message: blank,
            decree_text: "",
            directives: [],
          },
    }));
    const hostBlank = document.createElement("div"); document.body.appendChild(hostBlank);
    const rootBlank = createRoot(hostBlank); mountedRoots.push({ root: rootBlank, host: hostBlank });
    await act(async () => {
      rootBlank.render(<HistoryModal onClose={() => {}} />);
    });
    await act(async () => {
      await vi.waitFor(async () => {
        await Promise.resolve();
        const reportPre = Array.from(hostBlank.querySelectorAll("pre.memorial-text"))
          .find((el) => el.textContent === "一、人事除目");
        expect(reportPre).toBeTruthy();
      });
    });
    expect(hostBlank.querySelector("[data-testid=history-attendant]")).toBeNull();

    // 第三场景：纯空白 report + 非空递话 → 递话原文呈现，不画空奏报 section
    const attendantOnlyTurn = {
      kind: "month" as const,
      turn: 7,
      year: 1,
      period: 11,
      has_report: false,
      has_attendant: true,
      has_directive: false,
    };
    fetchMock.mockImplementation((url: string) => Promise.resolve({
      ok: true,
      json: async () => url === "/api/history/turns"
        ? { turns: [attendantOnlyTurn] }
        : {
            turn: 7,
            exists: true,
            year: 1,
            period: 11,
            report: blank,
            attendant_message: raw,
            decree_text: "",
            directives: [],
          },
    }));
    const hostBlankReport = document.createElement("div"); document.body.appendChild(hostBlankReport);
    const rootBlankReport = createRoot(hostBlankReport); mountedRoots.push({ root: rootBlankReport, host: hostBlankReport });
    await act(async () => {
      rootBlankReport.render(<HistoryModal onClose={() => {}} />);
    });
    await act(async () => {
      await vi.waitFor(async () => {
        await Promise.resolve();
        expect(hostBlankReport.querySelector("[data-testid=history-attendant]")).not.toBeNull();
      });
    });
    const attendantSection = hostBlankReport.querySelector("[data-testid=history-attendant]");
    expect(attendantSection!.querySelector("pre")?.textContent).toBe(raw);
    const memorialPres = Array.from(hostBlankReport.querySelectorAll("pre.memorial-text"));
    expect(memorialPres).toHaveLength(1);
    expect(memorialPres[0].textContent).toBe(raw);
  });

  it("#671 attendant-only 月档列表标签为递话、不冒充奏报", async () => {
    const monthTurn = {
      kind: "month" as const,
      turn: 7,
      year: 1627,
      period: 10,
      has_report: false,
      has_attendant: true,
      has_directive: false,
    };
    vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => Promise.resolve({
      ok: true,
      json: async () => url === "/api/history/turns"
        ? { turns: [monthTurn] }
        : {
            turn: 7,
            exists: true,
            year: 1627,
            period: 10,
            report: "",
            attendant_message: "递话正文",
            decree_text: "",
            directives: [],
          },
    })));
    const host = document.createElement("div"); document.body.appendChild(host);
    const root = createRoot(host); mountedRoots.push({ root, host });
    await act(async () => {
      root.render(<HistoryModal onClose={() => {}} />);
      await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
    });

    const item = host.querySelector(".history-turn-item");
    expect(item).not.toBeNull();
    const label = item!.textContent || "";
    expect(label).toContain("递话");
    expect(label).not.toContain("奏报");

    // 标题/摘要承认第三种内容（契约：含「递话」；不锁死全句）
    const dialog = host.querySelector('[role="dialog"]');
    expect(dialog?.getAttribute("aria-label") || "").toContain("递话");
    expect(host.textContent).toContain("递话");
    expect(host.textContent).not.toMatch(/仅收奏报与诏书/);
  });
});

describe("ChatModal — thinking/loading text switches on character type (gemini cmr r1)", () => {
  const thinkingText = (): string =>
    (document.querySelector(".chat-message.thinking p")?.textContent ?? "");

  it("shows 大臣思索中 while a minister is thinking", () => {
    renderModal({ minister: MINISTER_MOCK, portraitPrefix: "minister_", busy: "思考中" });
    expect(thinkingText()).toContain("大臣思索中");
  });

  it("does NOT show 大臣 while a consort is thinking (neutral text)", () => {
    renderModal({ minister: CONSORT_MOCK, portraitPrefix: "consort_", busy: "思考中" });
    const text = thinkingText();
    expect(text).not.toContain("大臣");
    expect(text.length).toBeGreaterThan(0);
  });
});

describe("ChatModal — cancel button during busy (issue #353)", () => {
  it("shows an observer-exit button when busy and onCancel is provided", () => {
    renderModal({
      minister: MINISTER_MOCK,
      portraitPrefix: "minister_",
      busy: "大臣思索中",
      onCancel: vi.fn(),
    });
    const cancelBtn = document.querySelector(".composer-cancel");
    expect(cancelBtn).not.toBeNull();
    expect(cancelBtn?.textContent).toContain("离开等待");
  });

  it("does NOT show a cancel button when idle", () => {
    renderModal({
      minister: MINISTER_MOCK,
      portraitPrefix: "minister_",
      busy: "",
      onCancel: vi.fn(),
    });
    const cancelBtn = document.querySelector(".composer-cancel");
    expect(cancelBtn).toBeNull();
  });

  it("calls onCancel when cancel button is clicked", () => {
    const onCancel = vi.fn();
    renderModal({
      minister: MINISTER_MOCK,
      portraitPrefix: "minister_",
      busy: "大臣思索中",
      onCancel,
    });
    const cancelBtn = document.querySelector(".composer-cancel") as HTMLButtonElement;
    act(() => cancelBtn.click());
    expect(onCancel).toHaveBeenCalledOnce();
  });

  it("does NOT show cancel button when busy but onCancel is not provided", () => {
    renderModal({
      minister: MINISTER_MOCK,
      portraitPrefix: "minister_",
      busy: "大臣思索中",
    });
    const cancelBtn = document.querySelector(".composer-cancel");
    expect(cancelBtn).toBeNull();
  });
});

describe("ChatModal — elapsed timer during thinking (issue #353)", () => {
  it("shows elapsed time in the thinking indicator while busy", () => {
    vi.useFakeTimers();
    renderModal({
      minister: MINISTER_MOCK,
      portraitPrefix: "minister_",
      busy: "大臣思索中",
    });
    // Timer starts at 0; advance 3 seconds
    act(() => { vi.advanceTimersByTime(3000); });
    const thinkingP = document.querySelector(".chat-message.thinking p");
    expect(thinkingP?.textContent).toMatch(/\d+\s*秒/);
    vi.useRealTimers();
  });
});

describe("ReportModal — narrative settlement bulletin", () => {
  it("renders narrative without an account page", () => {
    renderReportModal({
      report: "**辽东军情**\n- 军前缺饷",
    });

    expect(document.body.textContent).toContain("辽东军情");
    expect(document.body.textContent).toContain("军前缺饷");
    expect(document.body.textContent).not.toContain("实账");
    expect(document.body.textContent).not.toContain("账目明细");
  });

  it("#1387 底部有朕知道了主按钮可达关闭，不靠右上小 X", () => {
    const onClose = vi.fn();
    const host = renderReportModal({
      report: "一、边报\n\n二、钱粮\n\n三、探子回报\n下文应可滚完",
      onClose,
    });
    const dismiss = Array.from(host.querySelectorAll("button")).find((b) =>
      (b.textContent || "").includes("朕知道了") || (b.textContent || "").includes("收卷"),
    ) as HTMLButtonElement | undefined;
    expect(dismiss).toBeTruthy();
    expect(host.querySelector(".gazette-document")).not.toBeNull();
    expect(host.querySelector(".gazette-dismiss")).not.toBeNull();
    act(() => dismiss!.click());
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("#1356 报头吃报文自身月 periodLabel，不吃当前 turn 月", () => {
    // 上月报文 + 状态口当前月：报头必须=报文月（真结算九月 / 跨年十二月）
    const hostSept = renderReportModal({
      report: "天启七年九月邸报\n\n一、真结算九月",
      periodLabel: "天启七年九月",
    });
    const mastSept = hostSept.querySelector(".gazette-masthead")?.textContent || "";
    expect(mastSept).toContain("天启七年九月");
    expect(mastSept).not.toContain("天启七年十月");

    const hostDec = renderReportModal({
      report: "天启七年十二月邸报·跨年",
      periodLabel: "天启七年十二月",
    });
    const mastDec = hostDec.querySelector(".gazette-masthead")?.textContent || "";
    expect(mastDec).toContain("天启七年十二月");
    // 正月状态不得混充报头
    expect(mastDec).not.toContain("崇祯元年正月");
    expect(mastDec).not.toContain("天启七年正月");
  });

  it("#1356 空邸报态不崩：卷轴壳复用 pre + 朕知道了可关闭（无固定空注）", () => {
    const onClose = vi.fn();
    const host = renderReportModal({ report: "", onClose });
    expect(host.querySelector(".gazette-document")).not.toBeNull();
    expect(host.querySelector(".gazette-masthead")).not.toBeNull();
    // 空壳复用原 pre，不另写固定空态文案
    expect(host.querySelector("pre.memorial-text")).not.toBeNull();
    expect(host.textContent).not.toContain("尚无上月邸报");
    expect(host.textContent).not.toContain("登基伊始");
    const dismiss = Array.from(host.querySelectorAll("button")).find((b) =>
      (b.textContent || "").includes("朕知道了"),
    ) as HTMLButtonElement | undefined;
    expect(dismiss).toBeTruthy();
    act(() => dismiss!.click());
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("#1398 朕知道了视口常显：不埋在长文滚底", () => {
    const onClose = vi.fn();
    const longReport = Array.from({ length: 48 }, (_, i) =>
      `第${i + 1}段·边报钱粮探子回报——${"详文".repeat(24)}`,
    ).join("\n\n");
    const host = renderReportModal({ report: longReport, onClose });
    const scroll = host.querySelector(".gazette-document") as HTMLElement | null;
    const dismissWrap = host.querySelector(".gazette-dismiss") as HTMLElement | null;
    const dismissBtn = Array.from(host.querySelectorAll("button")).find((b) =>
      (b.textContent || "").includes("朕知道了"),
    ) as HTMLButtonElement | undefined;
    expect(scroll).not.toBeNull();
    expect(dismissWrap).not.toBeNull();
    expect(dismissBtn).toBeTruthy();
    // 吸底/视口常显：dismiss 不得是滚容器后代（长文滚底才见）
    expect(scroll!.contains(dismissWrap)).toBe(false);
    act(() => dismissBtn!.click());
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("#671 王承恩递话在邸报纸面外独立区，不经 stripOrganicMarkdown；空则不渲染", () => {
    const hostEmpty = renderReportModal({ report: "一、边报" });
    expect(hostEmpty.querySelector("[data-testid=gazette-attendant]")).toBeNull();

    // 纯空白 / 空串：trim 判空后不渲染
    expect(
      renderReportModal({ report: "一、边报", attendantMessage: "   \n\t  " })
        .querySelector("[data-testid=gazette-attendant]"),
    ).toBeNull();
    expect(
      renderReportModal({ report: "一、边报", attendantMessage: "" })
        .querySelector("[data-testid=gazette-attendant]"),
    ).toBeNull();

    const rawWithWs = "\n  **皇爷**，洪承畴本月抵京候旨。  \n";
    const host = renderReportModal({
      report: "**辽东军情**",
      attendantMessage: rawWithWs,
    });
    const aside = host.querySelector("[data-testid=gazette-attendant]");
    expect(aside).not.toBeNull();
    // 递话原文含首尾空白与 markdown 标记；官方邸报逐字契约只在 App→DOM tracer
    expect(aside?.textContent).toBe(rawWithWs);
    // 递话区在纸面 article 之外
    expect(host.querySelector(".gazette-document")?.contains(aside)).toBe(false);
  });
});

describe("ChatModal — explicit legacy authority", () => {
  it("does not request or consume an open-night scroll for a consort", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    renderModal({
      minister: CONSORT_MOCK,
      portraitPrefix: "consort_",
      scrollMode: "legacy",
      chat: [{ role: "minister", content: "宫中旧话照常", chatTurnId: 99 }],
    });
    await act(async () => { await Promise.resolve(); });
    expect(fetchMock).not.toHaveBeenCalled();
    expect(document.body.textContent?.match(/宫中旧话照常/g)).toHaveLength(1);
  });
});

describe("#1683 ChatModal place ⊥ office DOM", () => {
  it("shows transit destination and keeps office when transit_to is set", () => {
    renderModal({
      minister: {
        ...MINISTER_MOCK,
        location: "henan",
        location_label: "河南",
        transit_to: "shandong",
        transit_to_label: "山东",
      },
      portraitPrefix: "minister_",
      scrollMode: "legacy",
    });

    const transit = document.querySelector(".minister-place.minister-transit");
    expect(transit).not.toBeNull();
    expect(transit!.textContent).toBe("山东");
    expect(document.querySelectorAll(".minister-place")).toHaveLength(1);
    expect(document.querySelector(".profile-office")?.textContent).toBe("内阁首辅");
  });

  it("shows location and keeps office when only location is set", () => {
    renderModal({
      minister: {
        ...MINISTER_MOCK,
        location: "henan",
        location_label: "河南",
      },
      portraitPrefix: "minister_",
      scrollMode: "legacy",
    });

    const place = document.querySelector(".minister-place");
    expect(place).not.toBeNull();
    expect(place!.classList.contains("minister-transit")).toBe(false);
    expect(place!.textContent).toBe("河南");
    expect(document.querySelector(".profile-office")?.textContent).toBe("内阁首辅");
  });
});
