import React from "react";
import type {
  DecisionChoice, PendingActionFailure, PendingDecision, RescriptDeskAction,
} from "../types";

function isCheatConsoleTarget(target: EventTarget | null): boolean {
  return target instanceof Element && target.closest(".cheat-console") !== null;
}

const RESCRIPT_ACTIONS: { action: RescriptDeskAction; label: string; hint: string }[] = [
  { action: "follow_draft", label: "依拟", hint: "照票拟落差务" },
  { action: "return_revise", label: "发回改票", hint: "退回重拟一轮" },
  { action: "midzhi", label: "另旨·中旨", hint: "中旨直发" },
  { action: "deliberate", label: "下部议·廷议", hint: "立议程集议" },
  { action: "hold", label: "留中", hint: "不批，惯性结算" },
  { action: "summon", label: "召见", hint: "当回合入召对" },
];

function isRescriptDraft(d: PendingDecision | undefined): boolean {
  return String(d?.kind || "") === "rescript_draft";
}

function decisionKeyOf(d: PendingDecision, fallbackIdx: number): string | undefined {
  if (d.decision_key) return String(d.decision_key);
  // 仅 #657 案头行（带 kind）合成键；旧 decision-only 载荷不强制 decision_key
  if (!d.kind) return undefined;
  const kind = String(d.kind || "decision");
  const turn = d.source_turn ?? d.turn ?? 0;
  return `${kind}:${turn}:${d.idx ?? fallbackIdx}`;
}

export function DecisionModal({
  decisions,
  failures = [],
  onResolve,
}: {
  decisions: PendingDecision[];
  failures?: PendingActionFailure[];
  onResolve: (choices: DecisionChoice[]) => void;
}) {
  const [cursor, setCursor] = React.useState(0);
  const [picks, setPicks] = React.useState<DecisionChoice[]>(() =>
    decisions.map((d, i) => {
      const key = decisionKeyOf(d, i);
      return key ? { decision_key: key } : {};
    }),
  );
  const pageRef = React.useRef<HTMLElement>(null);

  const cur = decisions[cursor];
  const pick = picks[cursor] || {};
  const rescript = isRescriptDraft(cur);
  const requiresListedChoice = (cur?.event_id || "").startsWith("dossier:");
  const decided = rescript
    ? !!(pick.action && (pick.action !== "summon" || (pick.summon_target || "").trim())
      && (pick.action !== "follow_draft" || (pick.draft_capability || pick.label)))
    : requiresListedChoice
      ? !!pick.label
      : !!(pick.label || (pick.note || "").trim());
  const last = cursor >= decisions.length - 1;
  const setPick = (choice: DecisionChoice) =>
    setPicks((all) =>
      all.map((item, i) => {
        if (i !== cursor) return item;
        const key = item.decision_key || decisionKeyOf(cur, cursor);
        return key
          ? { ...item, ...choice, decision_key: key }
          : { ...item, ...choice };
      }),
    );

  const next = () => {
    if (!decided) return;
    if (last) onResolve(picks);
    else setCursor((value) => value + 1);
  };

  const pickRescriptAction = (action: RescriptDeskAction) => {
    if (action === "follow_draft") {
      // 需先选票拟 option；若已选 option 则带 capability
      const opt = cur.options.find((o) => o.label === pick.label) || cur.options[0];
      if (!opt) {
        setPick({ action, label: "依拟" });
        return;
      }
      setPick({
        action,
        label: String(opt.label),
        hint: String(opt.hint || ""),
        draft_capability: String(opt.draft_capability || ""),
        action_type: opt.action_type ? String(opt.action_type) : undefined,
        assignee_name: opt.assignee_name ? String(opt.assignee_name) : undefined,
        target_kind: opt.target_kind ? String(opt.target_kind) : undefined,
        target_id: opt.target_id ? String(opt.target_id) : undefined,
        locality_scope: opt.locality_scope ? String(opt.locality_scope) : undefined,
        region_id: opt.region_id ? String(opt.region_id) : undefined,
        transaction_category: opt.transaction_category
          ? String(opt.transaction_category)
          : undefined,
      });
      return;
    }
    if (action === "hold") {
      setPick({ action, label: "留中", hint: "不批，惯性结算" });
      return;
    }
    if (action === "return_revise") {
      setPick({ action, label: "发回改票", hint: "退回重拟一轮" });
      return;
    }
    if (action === "deliberate") {
      setPick({ action, label: "下部议·廷议", hint: "立议程集议" });
      return;
    }
    if (action === "midzhi") {
      // 中旨：与 follow_draft 同形——把所选 option（已选则用选中项，否则首 option）
      // 上 §C.4 闭集键投影进 choice；空/缺按协议默认，不发明值、不回读旧拟。
      const opt =
        cur.options.find((o) => o.label === pick.label) ||
        cur.options[0] ||
        { label: "中旨", hint: "" };
      const s = (v: unknown) => (v == null || v === "" ? undefined : String(v));
      const n = (v: unknown) => {
        if (v == null || v === "") return undefined;
        const num = Number(v);
        return Number.isFinite(num) ? num : undefined;
      };
      setPick({
        action,
        label: "另旨·中旨",
        hint: "中旨直发",
        action_type: s(opt.action_type) || "assignment",
        assignee_name: s(opt.assignee_name) || "",
        name: s((opt as { name?: unknown }).name) || "",
        target_kind: s(opt.target_kind) || "region",
        target_id: s(opt.target_id) || "",
        transaction_category: s(opt.transaction_category) || "",
        locality_scope: s(opt.locality_scope) || "none",
        region_id: s(opt.region_id) || "",
        title: s((opt as { title?: unknown }).title) || "",
        commitment_kind: s((opt as { commitment_kind?: unknown }).commitment_kind) || "",
        stop_condition: s((opt as { stop_condition?: unknown }).stop_condition) || "",
        end_turn: n((opt as { end_turn?: unknown }).end_turn),
        deadline_months: n((opt as { deadline_months?: unknown }).deadline_months),
        station: s((opt as { station?: unknown }).station) || "",
        due_turn: n((opt as { due_turn?: unknown }).due_turn),
        office: s((opt as { office?: unknown }).office) || "",
        grant_action: s((opt as { grant_action?: unknown }).grant_action) || "",
        account: s((opt as { account?: unknown }).account) || "",
        amount: n((opt as { amount?: unknown }).amount),
        cadence: s((opt as { cadence?: unknown }).cadence) || "",
        execution_surface: s((opt as { execution_surface?: unknown }).execution_surface) || "",
        appoint_action: s((opt as { appoint_action?: unknown }).appoint_action) || "",
        appointment_tenure: s((opt as { appointment_tenure?: unknown }).appointment_tenure) || "",
        punish_action: s((opt as { punish_action?: unknown }).punish_action) || "",
        privilege: s((opt as { privilege?: unknown }).privilege) || "",
        summon_target: s((opt as { summon_target?: unknown }).summon_target) || "",
      });
      return;
    }
    if (action === "summon") {
      setPick({
        action,
        label: "召见",
        hint: "当回合入召对",
        summon_target: pick.summon_target || cur.actor_name || "",
      });
    }
  };

  React.useEffect(() => {
    const page = pageRef.current;
    if (!page) return;

    const focusableSelector = [
      "button:not([disabled])",
      "textarea:not([disabled])",
      "input:not([disabled])",
      "select:not([disabled])",
      "a[href]",
      "[tabindex]:not([tabindex='-1'])",
    ].join(",");
    const focusables = () => Array.from(page.querySelectorAll<HTMLElement>(focusableSelector));
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;

    const keepFocusInPage = (event: KeyboardEvent) => {
      if (isCheatConsoleTarget(event.target)) return;
      if (event.ctrlKey && (event.key === "~" || event.key === "`")) {
        event.preventDefault();
        event.stopImmediatePropagation();
        (focusables()[0] || page).focus();
        return;
      }
      if (event.key !== "Tab") return;
      const elements = focusables();
      if (!elements.length) {
        event.preventDefault();
        page.focus();
        return;
      }

      const activeIndex = elements.indexOf(document.activeElement as HTMLElement);
      if (activeIndex === -1) {
        event.preventDefault();
        elements[event.shiftKey ? elements.length - 1 : 0].focus();
      } else if (event.shiftKey && activeIndex === 0) {
        event.preventDefault();
        elements[elements.length - 1].focus();
      } else if (!event.shiftKey && activeIndex === elements.length - 1) {
        event.preventDefault();
        elements[0].focus();
      }
    };

    const keepFocusInPageOnFocus = (event: FocusEvent) => {
      if (event.target instanceof Node && page.contains(event.target)) return;
      if (isCheatConsoleTarget(event.target)) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      (focusables()[0] || page).focus();
    };

    document.addEventListener("keydown", keepFocusInPage, true);
    document.addEventListener("focusin", keepFocusInPageOnFocus, true);
    return () => {
      document.removeEventListener("keydown", keepFocusInPage, true);
      document.removeEventListener("focusin", keepFocusInPageOnFocus, true);
      if (previousFocus?.isConnected) previousFocus.focus();
    };
  }, [decisions.length]);

  React.useEffect(() => {
    const page = pageRef.current;
    if (!page) return;
    const firstFocusable = page.querySelector<HTMLElement>(
      "button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), a[href], [tabindex]:not([tabindex='-1'])",
    );
    if (isCheatConsoleTarget(document.activeElement)) return;
    (firstFocusable || page).focus();
  }, [cursor, decisions.length]);

  if (decisions.length === 0) return null;

  const kickerKind = rescript ? "急务票拟" : "打回件";

  return (
    <section
      ref={pageRef}
      className="decision-page"
      role="dialog"
      aria-modal="true"
      aria-labelledby="decision-page-title"
      tabIndex={-1}
    >
      <article className="decision-document">
        <div className="decision-head">
          <span className="decision-kicker" aria-live="polite">
            月末批红 · {kickerKind} · 第 {cursor + 1} / {decisions.length} 疏
          </span>
          <h2 id="decision-page-title" className="decision-title">奏疏批红</h2>
        </div>
        {failures.length ? <div className="decision-failure-list" role="alert">
          {failures.map((failure) => <div className="decision-failure-item" key={failure.id}>{failure.message}</div>)}
        </div> : null}
        <section aria-labelledby="decision-document-title">
          <div className="decision-document-section">
            <span className="decision-section-label">疏文</span>
            <h3 id="decision-document-title">{cur.title}</h3>
            <p>{cur.context || "臣等谨陈时局，请陛下裁夺。"}</p>
            {rescript && cur.actor_name ? (
              <p className="decision-actor">票拟：{cur.actor_name}
                {cur.actor_office ? `（${cur.actor_office}）` : ""}
              </p>
            ) : null}
          </div>
          {cur.rejection_reason || cur.opposition ? <div className="decision-document-section">
            <span className="decision-section-label">封驳具由</span>
            {cur.rejection_reason ? <p>{cur.rejection_reason}</p> : null}
            {cur.opposition ? <p>持议者：{cur.opposition}</p> : null}
          </div> : null}

          {rescript ? (
            <>
              <div className="decision-document-section">
                <span className="decision-section-label">内阁票拟</span>
                <div className="decision-options">
                  {cur.options.map((option) => (
                    <button
                      key={option.label}
                      type="button"
                      className={"decision-option" + (pick.label === option.label && pick.action === "follow_draft" ? " is-picked" : "")}
                      onClick={() => {
                        setPick({
                          action: "follow_draft",
                          label: option.label,
                          hint: option.hint || "",
                          draft_capability: String(option.draft_capability || ""),
                          action_type: option.action_type ? String(option.action_type) : undefined,
                          assignee_name: option.assignee_name ? String(option.assignee_name) : undefined,
                          target_kind: option.target_kind ? String(option.target_kind) : undefined,
                          target_id: option.target_id ? String(option.target_id) : undefined,
                          locality_scope: option.locality_scope ? String(option.locality_scope) : undefined,
                          region_id: option.region_id ? String(option.region_id) : undefined,
                          transaction_category: option.transaction_category
                            ? String(option.transaction_category)
                            : undefined,
                        });
                      }}
                    >
                      <span className="decision-option-label">拟批：{option.label}</span>
                      {option.hint ? <span className="decision-option-hint">{option.hint}</span> : null}
                    </button>
                  ))}
                </div>
              </div>
              <div className="decision-document-section" data-testid="rescript-six-actions">
                <span className="decision-section-label">批红六动作</span>
                <div className="decision-options decision-rescript-actions">
                  {RESCRIPT_ACTIONS.map((item) => (
                    <button
                      key={item.action}
                      type="button"
                      className={"decision-option" + (pick.action === item.action ? " is-picked" : "")}
                      data-action={item.action}
                      onClick={() => pickRescriptAction(item.action)}
                    >
                      <span className="decision-option-label">{item.label}</span>
                      <span className="decision-option-hint">{item.hint}</span>
                    </button>
                  ))}
                </div>
                {pick.action === "summon" ? (
                  <label className="decision-summon-target">
                    召见对象
                    <input
                      type="text"
                      value={pick.summon_target || ""}
                      placeholder={cur.actor_name || "大臣名"}
                      onChange={(event) => setPick({
                        action: "summon",
                        label: "召见",
                        summon_target: event.target.value,
                      })}
                    />
                  </label>
                ) : null}
              </div>
            </>
          ) : (
            <div className="decision-document-section">
              <span className="decision-section-label">内阁票拟</span>
              <div className="decision-options">
                {cur.options.map((option) => (
                  <button
                    key={option.label}
                    type="button"
                    className={"decision-option" + (pick.label === option.label ? " is-picked" : "")}
                    onClick={() => setPick(option)}
                  >
                    <span className="decision-option-label">拟批：{option.label}</span>
                    {option.hint ? <span className="decision-option-hint">{option.hint}</span> : null}
                  </button>
                ))}
              </div>
            </div>
          )}

          <div className="decision-document-section decision-red-pen">
            <label className="decision-section-label" htmlFor="decision-note">朱笔亲批</label>
            <textarea
              id="decision-note"
              className="decision-note"
              placeholder="亲笔补批（可选）"
              value={pick.note || ""}
              onChange={(event) => setPick({ note: event.target.value })}
            />
          </div>
          <button
            type="button"
            className="decision-confirm"
            disabled={!decided}
            onClick={next}
            aria-label={last ? "批红落印，续推时局" : "批下一疏"}
          >
            {last ? "批红落印" : "批下一疏"}
          </button>
        </section>
        <div className="decision-actions">
          <span className="decision-hint-line">
            {decided
              ? "已择，落印即行。"
              : rescript
                ? (pick.action === "summon" && !(pick.summon_target || "").trim()
                  ? "召见须填写对象。"
                  : "请择六动作之一（留中为默认）。")
                : requiresListedChoice
                  ? "此疏须择一票拟。"
                  : "请择一票拟，或亲笔批示。"}
          </span>
        </div>
      </article>
    </section>
  );
}
