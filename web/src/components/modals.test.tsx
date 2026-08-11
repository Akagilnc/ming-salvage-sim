import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AudienceArchiveModal, ChatModal, EdictModal, HistoryDetailView, HistoryModal, ReportModal, parseLeadingStageDirection } from "./modals";
import type { BudgetAccount, ChatMessage, GameState, Minister, PendingActionFailure, Suggestion } from "../types";
import { chatReducer, type ChatAction } from "../mindreading";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// Centralised teardown registry: every rendered root is unmounted in afterEach so a
// FAILED assertion (which aborts the test body before any inline cleanup) can never
// leak a mounted React root into the next test (gemini cmr r1).
const mountedRoots: Array<{ root: Root; host: HTMLElement }> = [];

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

function renderModal(props: {
  minister: Minister;
  ministers?: Minister[];
  portraitPrefix: string;
  scrollMode?: "audience" | "legacy";
  currentNightId?: number;
  undoneChatTurnId?: number | null;
  chat?: ChatMessage[];
  busy?: string;
  onCancel?: () => void;
  chatFailures?: PendingActionFailure[];
  onRetryFailure?: (failure: PendingActionFailure) => void;
  replyRetry?: { chat_turn_id: number; question: string } | null;
  onRetryReply?: (ministerName: string) => void;
  extractionPendingCount?: number;
  onRetryExtraction?: () => void;
  suggestions?: Suggestion[];
  secretOrders?: React.ComponentProps<typeof ChatModal>["secretOrders"];
  onSend?: (ministerName: string, text?: string) => void;
  onUndo?: (ministerName: string) => void;
  canUndoLastChat?: boolean;
  onFavorite?: (minister: Minister) => void;
  registerChatUpdate?: (update: (chat: ChatMessage[]) => void) => void;
  registerNightUpdate?: (update: (nightId: number) => void) => void;
  registerUndoUpdate?: (update: (chatTurnId: number | null) => void) => void;
  registerChatDispatch?: (dispatch: React.Dispatch<ChatAction>) => void;
}) {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);

  // Controlled input lives in the harness so prefix-chip clicks update textarea.value
  // (ChatModal is a controlled component; frozen input="" would hide real fill).
  function Harness() {
    const [input, setInput] = React.useState("");
    const [currentNightId, setCurrentNightId] = React.useState(props.currentNightId ?? 0);
    const [undoneChatTurnId, setUndoneChatTurnId] = React.useState<number | null>(props.undoneChatTurnId ?? null);
    const [chat, dispatchChat] = React.useReducer(chatReducer, props.chat ?? []);
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
    React.useEffect(() => props.registerNightUpdate?.(setCurrentNightId), []);
    React.useEffect(() => props.registerUndoUpdate?.(setUndoneChatTurnId), []);
    React.useEffect(() => props.registerChatDispatch?.(dispatchChat), []);
    return (
      <ChatModal
        minister={props.minister}
        ministers={props.ministers ?? []}
        portraitPrefix={props.portraitPrefix}
        scrollMode={props.scrollMode}
        currentCampaignId="test-campaign"
        currentNightId={currentNightId}
        undoneChatIdentity={undoneChatTurnId == null ? null : { campaign_id: "test-campaign", night_id: currentNightId, chat_turn_id: undoneChatTurnId }}
        busy={props.busy ?? ""}
        chat={chat}
        suggestions={props.suggestions ?? []}
        pendingUserMessage=""
        pendingIdentity={null}
        failedIdentity={null}
        streamingMinisterMessage=""
        chatNotice=""
        chatFailures={props.chatFailures ?? []}
        canUndoLastChat={props.canUndoLastChat ?? false}
        composerHint=""
        input={input}
        error=""
        secretOrders={props.secretOrders ?? []}
        replyRetry={props.replyRetry}
        extractionPendingCount={props.extractionPendingCount}
        onInput={(value) => setInput(value)}
        onSend={props.onSend ?? (() => {})}
        onRetryFailure={props.onRetryFailure ?? (() => {})}
        onRetryReply={props.onRetryReply}
        onRetryExtraction={props.onRetryExtraction}
        onUndo={props.onUndo ?? (() => {})}
        onHint={() => {}}
        onFavorite={props.onFavorite ?? (() => {})}
        onOpenEdict={() => {}}
        onClose={() => {}}
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

function renderReportModal(props: { report: string }) {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  act(() =>
    root.render(
      <ReportModal
        report={props.report}
        onClose={() => {}}
      />
    )
  );
  mountedRoots.push({ root, host });
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
    treasury: "",
    issues: [],
    legacies: [],
    closed_this_turn: [],
    budget: { 国库: EMPTY_BUDGET_ACCOUNT, 内库: EMPTY_BUDGET_ACCOUNT },
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
  onAdvanceWithoutEdict?: () => void;
  onOpenFailureRecovery?: () => void;
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
        error=""
        onDirectiveTextChange={() => {}}
        onEditingTextChange={() => {}}
        onCreateDirective={() => {}}
        onStartEdit={() => {}}
        onCancelEdit={() => {}}
        onSaveDirective={() => {}}
        onDeleteDirective={() => {}}
        onWriteDecree={() => {}}
        onAdvanceWithoutEdict={props.onAdvanceWithoutEdict ?? (() => {})}
        onResetDecree={() => {}}
        onIssueDecree={() => {}}
        onConfirmDirective={() => {}}
        onRejectDirective={() => {}}
        onOpenFailureRecovery={props.onOpenFailureRecovery ?? (() => {})}
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
  vi.unstubAllGlobals();
});

describe("EdictModal — hidden secret-order default approval", () => {
  it("shows generic no-edict advance without exposing hidden secret-order pending state", () => {
    const onAdvance = vi.fn();
    const { host } = renderEdictModal({
      state: baseGameState({ pending_secret_order_count: 0, pending_non_directive_action_count: 0 }),
      onAdvanceWithoutEdict: onAdvance,
    });
    const button = Array.from(host.querySelectorAll("button")).find((item) =>
      item.textContent?.includes("退朝")
    ) as HTMLButtonElement | undefined;

    expect(button).toBeTruthy();
    expect(host.textContent).not.toContain("密令已候旨");
    expect(host.textContent).not.toContain("尚有召对事项候旨");
    expect(host.textContent).toContain("本月尚无明发诏令");
    act(() => {
      button?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(onAdvance).toHaveBeenCalledTimes(1);
  });

  it("shows no-edict advance for non-directive pending actions beyond new secret orders", () => {
    const onAdvance = vi.fn();
    const { host } = renderEdictModal({
      state: baseGameState({ pending_non_directive_action_count: 1 }),
      onAdvanceWithoutEdict: onAdvance,
    });
    const button = Array.from(host.querySelectorAll("button")).find((item) =>
      item.textContent?.includes("退朝")
    ) as HTMLButtonElement | undefined;

    expect(button).toBeTruthy();
  });

  it("offers durable recovery entry for failed secret orders", () => {
    const onOpenFailureRecovery = vi.fn();
    const { host } = renderEdictModal({
      state: baseGameState({ failed_secret_order_count: 1 }),
      onOpenFailureRecovery,
    });
    const button = Array.from(host.querySelectorAll("button")).find((item) =>
      item.textContent?.includes("处理")
    ) as HTMLButtonElement | undefined;

    expect(host.textContent).toContain("密令落库失败");
    expect(button).toBeTruthy();
    act(() => {
      button?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(onOpenFailureRecovery).toHaveBeenCalledTimes(1);
  });

  it("prioritizes failed secret-order recovery over generic pending-action hint", () => {
    const onOpenFailureRecovery = vi.fn();
    const { host } = renderEdictModal({
      state: baseGameState({
        failed_secret_order_count: 1,
        pending_non_directive_action_count: 1,
      }),
      onOpenFailureRecovery,
    });
    const button = Array.from(host.querySelectorAll("button")).find((item) =>
      item.textContent?.includes("处理")
    ) as HTMLButtonElement | undefined;

    expect(host.textContent).toContain("密令落库失败");
    expect(host.textContent).not.toContain("尚有召对事项候旨");
    expect(button).toBeTruthy();
  });
});

describe("ChatModal — #527 prefix chips only (拟旨/下密令)", () => {
  /** Production suggestions_for payload after ADR 0042 / #527 cut. */
  const PREFIX_SUGGESTIONS: Suggestion[] = [
    { label: "拟旨", text: "拟旨如下：", prefix: true },
    { label: "下密令", text: "密令如下：", prefix: true },
  ];

  it("renders both prefix buttons; click fills textarea; never auto-sends", () => {
    const onSend = vi.fn();
    const host = renderModal({
      minister: MINISTER_MOCK,
      portraitPrefix: "minister_",
      suggestions: PREFIX_SUGGESTIONS,
      onSend,
    });

    const hitlButtons = Array.from(host.querySelectorAll(".hitl-bar button"));
    const labels = hitlButtons.map((b) => b.textContent?.trim());
    expect(labels).toEqual(["拟旨", "下密令"]);

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
    expect(onSend).not.toHaveBeenCalled();
  });
});

describe("ChatModal — placeholder switches on character type", () => {
  it("shows 大臣 and 他 in placeholder for ministers", () => {
    renderModal({ minister: MINISTER_MOCK, portraitPrefix: "minister_" });
    const textarea = document.querySelector("textarea") as HTMLTextAreaElement;
    expect(textarea.placeholder).toContain("大臣");
    expect(textarea.placeholder).toContain("他");
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

  it("shows secret-order landing failure with retry action", () => {
    const failure: PendingActionFailure = {
      id: 7,
      kind: "secret_order",
      action: "新建",
      retryable: true,
      message: "密令未能正式落库，请重试；若暂不处理，也不会阻断继续召对。",
    };
    const retry = vi.fn();

    renderModal({
      minister: MINISTER_MOCK,
      portraitPrefix: "minister_",
      chatFailures: [failure],
      onRetryFailure: retry,
    });

    expect(document.querySelector(".chat-failure-note")?.textContent).toContain("密令未能正式落库");
    const button = Array.from(document.querySelectorAll("button")).find((node) => node.textContent === "重试");
    expect(button).toBeTruthy();
    act(() => button?.click());
    expect(retry).toHaveBeenCalledWith(failure);
  });

  it("does not show retry action for unsupported failure kinds", () => {
    renderModal({
      minister: MINISTER_MOCK,
      portraitPrefix: "minister_",
      chatFailures: [{
        id: 8,
        kind: "office",
        action: "任命",
        message: "任免未能正式落库，已记录为失败；若暂不处理，也不会阻断继续召对。",
      }],
    });

    expect(document.querySelector(".chat-failure-note")?.textContent).toContain("任免未能正式落库");
    const button = Array.from(document.querySelectorAll("button")).find((node) => node.textContent === "重试");
    expect(button).toBeUndefined();
  });

  it("shows #505 system-layer reply retry control when replyRetry is set", () => {
    const retry = vi.fn();
    renderModal({
      minister: MINISTER_MOCK,
      portraitPrefix: "minister_",
      chat: [{ role: "user", content: "剿抚孰先？" }],
      replyRetry: { chat_turn_id: 12, question: "剿抚孰先？" },
      onRetryReply: retry,
    });
    const note = document.querySelector('[data-testid="reply-retry"]');
    expect(note?.textContent).toContain("重新生成回话");
    expect(note?.textContent).toContain("剿抚孰先？");
    const button = Array.from(document.querySelectorAll("button")).find(
      (node) => node.textContent === "重新生成回话",
    );
    expect(button).toBeTruthy();
    act(() => button?.click());
    expect(retry).toHaveBeenCalledTimes(1);
  });

  it("shows #501 extraction-pending notice with in-place retry", () => {
    const retry = vi.fn();
    renderModal({
      minister: MINISTER_MOCK,
      portraitPrefix: "minister_",
      extractionPendingCount: 2,
      onRetryExtraction: retry,
    });
    const note = document.querySelector('[data-testid="extraction-pending"]');
    expect(note?.textContent).toContain("2 段");
    const button = Array.from(document.querySelectorAll("button")).find(
      (node) => node.textContent === "重试补写",
    );
    expect(button).toBeTruthy();
    act(() => button?.click());
    expect(retry).toHaveBeenCalledTimes(1);
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
    expect(messages[1]?.textContent).toBe("臣谨奏：\n钱粮已足。");
  });
});

describe("ChatModal — four diegetic roles (#540)", () => {
  it("renders role variants and derives the private aside only from audibility", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ night_id: 23, messages: [
      { role: "scene", speaker: "", content: "殿门徐启", beat: "scene", audibility: "殿上公开" },
      { role: "user", speaker: "朕", content: "（搁笔）卿且直言。", beat: "dialogue", audibility: "殿上公开" },
      { role: "minister", speaker: "周延儒", content: "臣谨奏。", beat: "dialogue", audibility: "殿上公开" },
      { role: "attendant", speaker: "曹化淳", content: "圣上，他有所隐瞒。", beat: "aside", audibility: "御前低语" },
      { role: "attendant", speaker: "王承恩", content: "容臣低声禀报。", beat: "aside", audibility: "御前低语" },
      { role: "attendant", speaker: "王承恩", content: "公开传话。", beat: "aside", audibility: "殿上公开" },
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
    expect(host.querySelector(".chat-message.user .action")?.textContent).toBe("（搁笔）");
    expect(host.querySelector(".chat-message.user p")?.textContent).toBe("卿且直言。");
    expect(host.querySelector(".chat-message.minister")?.textContent).toContain("臣谨奏。");
    expect(host.querySelector(".chat-message.aside")?.textContent).toContain("有所隐瞒");
    const avatars = Array.from(host.querySelectorAll<HTMLImageElement>(".aside-avatar"));
    expect(avatars[0]?.alt).toBe("曹化淳");
    expect(avatars[0]?.getAttribute("src")).toMatch(/^\/portraits\/custom\/%E6%9B%B9%E5%8C%96%E6%B7%B3\?t=/);
    expect(avatars[1]?.getAttribute("src")).toBe("/portraits/minister_attendant-former.png");
    expect(host.querySelector(".chat-message.attendant:not(.aside)")?.textContent).toContain("公开传话");
  });
});

describe("ChatModal — soft scenes and current audience (#543)", () => {
  it("keeps a side interjection distinct while the whole sidebar follows the current audience", async () => {
    const favorite = vi.fn();
    const send = vi.fn();
    const undo = vi.fn();
    const retryReply = vi.fn();
    const yang = { ...MINISTER_MOCK, id: "yang", name: "杨嗣昌", summary: "兵部旧臣", favorite: false };
    const hong = { ...MINISTER_MOCK, id: "hong", name: "洪承畴", office: "三边总督", summary: "边臣", favorite: true };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ night_id: 23, messages: [
      { role: "scene", speaker: "洪承畴", content: "", beat: "divider", soft_boundary: true, container: { audience_type: "越次召对" } },
      { role: "scene", speaker: "洪承畴", content: "洪承畴趋入殿中。", beat: "entrance", container: { audience_type: "越次召对" } },
      { role: "minister", speaker: "洪承畴", content: "臣自三边来。", beat: "dialogue", container: { audience_type: "越次召对" } },
      { role: "minister", speaker: "杨嗣昌", content: "殿侧容臣插一句。", beat: "dialogue", container: { audience_type: "越次召对" } },
      { role: "scene", speaker: "", content: "", beat: "divider", soft_boundary: true, container: { audience_type: "越次召对" } },
    ] }) }));

    const host = renderModal({
      minister: yang,
      ministers: [yang, hong],
      portraitPrefix: "minister_",
      currentNightId: 23,
      onFavorite: favorite,
      onSend: send,
      onUndo: undo,
      canUndoLastChat: true,
      replyRetry: { chat_turn_id: 12, question: "辽饷何解？" },
      onRetryReply: retryReply,
      suggestions: [{ label: "追问", text: "细奏边情" }],
      secretOrders: [{ id: 9, minister_name: "洪承畴", title: "密察边饷", content: "暗访欠饷", status: "active", turn_issued: 1, due_turn: 2, year_issued: 1, period_issued: 11, tags: [], importance: 1, result: "", sim_note: "", turn_closed: null }],
    });
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });

    expect(host.querySelector(".audience-type-label")?.textContent).toBe("越次召对");
    expect(host.querySelector(".minister-side h2")?.textContent).toBe("洪承畴");
    expect(host.querySelector(".chat-portrait-wrap img")?.getAttribute("src")).toBe("/portraits/minister_hong.png");
    expect(host.querySelector(".chat-secret-orders")?.textContent).toContain("密察边饷");
    const ministerMessages = host.querySelectorAll(".chat-message.minister");
    expect(ministerMessages[ministerMessages.length - 1]?.textContent).toContain("杨嗣昌");
    const favoriteButton = host.querySelector<HTMLButtonElement>('button[aria-label="收藏大臣"]');
    expect(favoriteButton?.querySelector("svg")?.getAttribute("fill")).toBe("currentColor");
    act(() => favoriteButton?.click());
    expect(favorite).toHaveBeenCalledWith(hong);
    const clickButton = (text: string) => act(() => Array.from(host.querySelectorAll("button")).find((button) => button.textContent?.includes(text))?.click());
    clickButton("追问");
    clickButton("撤回本轮");
    clickButton("重新生成回话");
    expect(send).toHaveBeenCalledWith("洪承畴", "细奏边情");
    expect(undo).toHaveBeenCalledWith("洪承畴");
    expect(retryReply).toHaveBeenCalledWith("洪承畴");
    const divisions = Array.from(host.querySelectorAll(".beat-divider"));
    expect(divisions).toHaveLength(2);
    expect(divisions[0]?.textContent).toContain("洪承畴");
    expect(divisions[1]?.textContent).not.toMatch(/杨嗣昌|洪承畴/);
  });
});

describe("parseLeadingStageDirection", () => {
  it.each([
    ["（搁笔）卿且直言。", { action: "（搁笔）", content: "卿且直言。" }],
    ["卿且（搁笔）直言。", { action: null, content: "卿且（搁笔）直言。" }],
    ["卿且直言。", { action: null, content: "卿且直言。" }],
  ])("recognises only an explicit leading full-width parenthetical in %s", (source, expected) => {
    expect(parseLeadingStageDirection(source)).toEqual(expected);
  });
});

describe("ChatModal — single night-scroll authority (#539)", () => {
  it("retires the whole old-night snapshot when the persisted player-entry identity changes before refresh fails", async () => {
    let rejectRefresh!: (reason?: unknown) => void;
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ night_id: 23, messages: [
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
      .mockResolvedValueOnce({ ok: true, json: async () => ({ night_id: 23, messages: [
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
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ night_id: 23, messages: [
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
      resolveScroll({ ok: true, json: async () => ({ night_id: 17, messages: [{ role: "user", content: "卷首" }] }) });
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

  it("does not merge personal history while the canonical scroll refresh is delayed", async () => {
    let resolveRefresh!: (value: unknown) => void;
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ night_id: 23, messages: [{ role: "user", content: "旧卷", chat_turn_id: 1 }] }) })
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
      resolveRefresh({ ok: true, json: async () => ({ night_id: 23, messages: [
        { role: "user", content: "旧卷", chat_turn_id: 1 },
        { role: "user", content: "刚完成的新问", chat_turn_id: 2 }, { role: "minister", content: "刚完成的答复", chat_turn_id: 2 },
      ] }) });
      await Promise.resolve(); await Promise.resolve();
    });
    expect(document.body.textContent?.match(/刚完成的新问/g)).toHaveLength(1);
    expect(document.body.textContent?.match(/刚完成的答复/g)).toHaveLength(1);
  });

  it("waits for the canonical scroll before showing a late persisted aside", async () => {
    let rejectRefresh!: (reason?: unknown) => void;
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ night_id: 23, messages: [
        { role: "user", content: "初问", chat_turn_id: 1 }, { role: "minister", content: "初答", chat_turn_id: 1 },
        { role: "user", content: "再问", chat_turn_id: 2 }, { role: "minister", content: "已完成尾答", chat_turn_id: 2 },
      ] }) })
      .mockReturnValueOnce(new Promise((_resolve, reject) => { rejectRefresh = reject; }))
      .mockResolvedValueOnce({ ok: true, json: async () => ({ night_id: 23, messages: [
        { role: "user", content: "初问", chat_turn_id: 1 }, { role: "minister", content: "初答", chat_turn_id: 1 },
        { role: "attendant", content: "旧轮迟到递话", chat_turn_id: 1, record_id: 91 },
        { role: "user", content: "再问", chat_turn_id: 2 }, { role: "minister", content: "已完成尾答", chat_turn_id: 2 },
        { role: "attendant", content: "刷新触发递话", chat_turn_id: 2, record_id: 92 },
      ] }) });
    vi.stubGlobal("fetch", fetchMock);
    let dispatchChat!: React.Dispatch<ChatAction>;
    renderModal({
      minister: MINISTER_MOCK,
      portraitPrefix: "minister_",
      currentNightId: 23,
      chat: [
        { role: "user", content: "初问", chatTurnId: 1 },
        { role: "minister", content: "初答", chatTurnId: 1 },
        { role: "user", content: "再问", chatTurnId: 2 },
        { role: "minister", content: "已完成尾答", chatTurnId: 2 },
      ],
      registerChatDispatch: (dispatch) => { dispatchChat = dispatch; },
    });
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });

    await act(async () => {
      dispatchChat({ type: "mindreading", chatTurnId: 1, records: [{ id: 91, narration: "旧轮迟到递话" }] });
      await Promise.resolve();
    });
    expect(document.body.textContent).not.toContain("旧轮迟到递话");
    expect(document.body.textContent?.match(/已完成尾答/g)).toHaveLength(1);

    await act(async () => { rejectRefresh(new Error("refresh failed")); await Promise.resolve(); await Promise.resolve(); });
    expect(document.body.textContent).not.toContain("旧轮迟到递话");
    expect(document.body.textContent?.match(/已完成尾答/g)).toHaveLength(1);
    expect(document.querySelector('[role="alert"]')?.textContent).toContain("召对记录读取失败");

    await act(async () => {
      dispatchChat({ type: "mindreading", chatTurnId: 2, records: [{ id: 92, narration: "刷新触发递话" }] });
      await Promise.resolve(); await Promise.resolve();
    });
    expect(document.body.textContent?.match(/旧轮迟到递话/g)).toHaveLength(1);
    expect(document.body.textContent?.match(/已完成尾答/g)).toHaveLength(1);
    expect(document.body.textContent?.match(/刷新触发递话/g)).toHaveLength(1);
    expect(document.querySelector('[role="alert"]')).toBeNull();
  });

  it("keeps the last-known scroll without importing personal history when refresh fails", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ night_id: 23, messages: [{ role: "user", content: "旧卷", chat_turn_id: 1 }] }) })
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
      { night_id: 23, messages: [{ role: "user", content: "旧卷" }] },
      { night_id: 23, messages: [{ role: "user", content: "旧卷" }, { role: "minister", content: "非流式新答" }] },
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

describe("AudienceArchiveModal — read-only scene archive", () => {
  it("selects closed scenes through the shared scroll endpoint without a composer", async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (url === "/api/history/turns") return Promise.resolve({ ok: true, json: async () => ({ turns: [
        { kind: "month", turn: 7, year: 1, period: 11, has_report: true, has_directive: false },
        { kind: "night", turn: 7, year: 1, period: 11, night_id: 31, title: "1年11月 · 戌时乾清宫 · 越次召对 · 第1场", involved_people: ["杨嗣昌"] },
        { kind: "night", turn: 7, year: 1, period: 11, night_id: 32, title: "1年11月 · 戌时乾清宫 · 召对 · 第2场", involved_people: ["洪承畴"] },
      ] }) });
      const id = url.endsWith("31") ? 31 : 32;
      return Promise.resolve({ ok: true, json: async () => ({ messages: id === 32 ? [
        { role: "user", content: `场次${id}` },
        { role: "attendant", speaker: "退场近臣", content: "旧臣御前低语", audibility: "御前低语" },
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
    expect(host.querySelector("textarea, input, .chat-composer")).toBeNull();
    const archivedAvatar = host.querySelector<HTMLImageElement>(".aside-avatar");
    expect(archivedAvatar?.getAttribute("src")).toBe("/portraits/minister_former-attendant.png");
    const buttons = Array.from(host.querySelectorAll(".history-turn-item")) as HTMLButtonElement[];
    await act(async () => { buttons[1].click(); await Promise.resolve(); await Promise.resolve(); });
    expect(fetchMock).toHaveBeenCalledWith("/api/audience/scroll?night_id=31");
    expect(host.textContent).toContain("场次31");
  });

  it("史册 filters out scene rows and keeps the public-document boundary", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => Promise.resolve({ ok: true, json: async () =>
      url === "/api/history/turns" ? { turns: [
        { kind: "month", turn: 7, year: 1, period: 11, has_report: true, has_directive: false },
        { kind: "night", turn: 7, year: 1, period: 11, night_id: 31, title: "不应出现的场卷" },
      ] } : { turn: 7, exists: true, report: "月档奏报", directives: [] }
    })));
    const host = document.createElement("div"); document.body.appendChild(host);
    const root = createRoot(host); mountedRoots.push({ root, host });
    await act(async () => { root.render(<HistoryModal onClose={() => {}} />); await Promise.resolve(); await Promise.resolve(); });
    expect(host.textContent).toContain("奏报与诏书");
    expect(host.textContent).not.toContain("不应出现的场卷");
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
  it("renders narrative without an account page or literal organic markdown", () => {
    renderReportModal({
      report: "**辽东军情**\n- 军前缺饷",
    });

    expect(document.body.textContent).toContain("辽东军情");
    expect(document.body.textContent).toContain("军前缺饷");
    expect(document.body.textContent).not.toContain("**");
    expect(document.body.textContent).not.toContain("- 军前缺饷");

    expect(document.body.textContent).not.toContain("实账");
    expect(document.body.textContent).not.toContain("账目明细");
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
