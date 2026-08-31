import React from "react";
import { readFileSync } from "node:fs";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { DecisionModal } from "./decisionModal";
import { EdictModal } from "./edictModal";
import { FullscreenModal } from "./hud";
import type { GameState, PendingDecision } from "../types";
import { measureElectronLayout } from "../testSupport/electronLayout";

const css = (...names: string[]) => names
  .map((name) => readFileSync(`${process.cwd()}/src/styles/${name}.css`, "utf8"))
  .join("\n");

const decision: PendingDecision = {
  idx: 0,
  title: "关宁军饷",
  context: "辽东急报：军中已三月未饷。",
  options: [{ label: "拨帑速发", hint: "先解燃眉之急。" }],
};

const edictState = {
  directives: [{ id: 8, text: "发饷辽东", source: "chat", status: "pending" }],
  pending_directive_count: 0,
  pending_non_directive_action_count: 0,
  failed_secret_order_count: 0,
} as GameState;

const noop = () => {};

describe.sequential("medium: shared Electron geometry", () => {
  it("keeps DecisionModal confirmation within the first viewport", async () => {
    const page = renderToStaticMarkup(<DecisionModal decisions={[decision]} onResolve={vi.fn()} />);
    const [measured] = await measureElectronLayout<{ bottom: number; viewportHeight: number }>(
      page,
      css("base", "decision"),
      [{ width: 1440, height: 900 }],
      `(() => {
        const button = document.querySelector('.decision-confirm');
        if (!button) return { error: 'missing decision confirmation' };
        return { bottom: button.getBoundingClientRect().bottom, viewportHeight: innerHeight };
      })()`,
    );
    expect(measured.bottom).toBeLessThanOrEqual(measured.viewportHeight);
  });

  it("keeps the settlement alert and primary action independently reachable at two viewports", async () => {
    const page = renderToStaticMarkup(
      <FullscreenModal title="拟诏" subtitle="" bgClass="modal-bg-edict" layerClassName="edict-safe-cmd" onClose={noop}>
        <EdictModal
          state={edictState} directiveText="" editingDirectiveId={null} editingDirectiveText=""
          decree="" report="" busy=""
          error={`结算中止，请重试。\n错误包：/${"long-directory/".repeat(18)}error-pack\n请将整个目录发给作者。`}
          onDirectiveTextChange={noop} onEditingTextChange={noop} onCreateDirective={noop}
          onStartEdit={noop} onCancelEdit={noop} onSaveDirective={noop} onDeleteDirective={noop}
          onAdvanceWithoutEdict={noop} onIssueDecree={noop} onOpenFailureRecovery={noop}
        />
      </FullscreenModal>,
    );
    const results = await measureElectronLayout<{
      viewportWidth: number;
      viewportHeight: number;
      stackOk: boolean;
      alertFitsWidth: boolean;
      startReachable: boolean;
      endReachable: boolean;
      alertFooterDisjoint: boolean;
      buttonEnabled: boolean;
      buttonHit: boolean;
      twoLines: boolean;
      textareaHit: boolean;
    }>(page, css("base", "court", "modals", "chat", "edict", "modal-theme", "situation"), [
      { width: 1280, height: 720 },
      { width: 800, height: 800 },
    ], `(() => {
      const alert = document.querySelector('[role="alert"]');
      const cols = document.querySelector('.desk-columns');
      const textarea = document.querySelector('.desk-compose textarea');
      const footer = document.querySelector('.desk-footer');
      const button = document.querySelector('.desk-footer button');
      if (!alert || !cols || !textarea || !footer || !button) {
        return { error: 'missing edict fixture element' };
      }
      const overlaps = (a, b) => a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
      const hitAtCenter = (el) => {
        const r = el.getBoundingClientRect();
        return document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2) === el;
      };
      const clipVisibleHeight = (el, container) => {
        const er = el.getBoundingClientRect();
        const cr = container.getBoundingClientRect();
        return Math.max(0, Math.min(er.bottom, cr.bottom) - Math.max(er.top, cr.top));
      };

      alert.scrollTop = 0;
      const alertRect = alert.getBoundingClientRect();
      const colsRect = cols.getBoundingClientRect();
      const footerRect = footer.getBoundingClientRect();
      const alertContents = document.createRange();
      alertContents.selectNodeContents(alert);
      const startReachable = alertContents.getBoundingClientRect().top >= alertRect.top + alert.clientTop;
      alert.scrollTop = alert.scrollHeight;
      const endReachable = alert.scrollHeight <= alert.clientHeight
        || Math.ceil(alert.scrollTop + alert.clientHeight) >= alert.scrollHeight;

      const buttonRect = button.getBoundingClientRect();
      const buttonHit = document.elementFromPoint(
        buttonRect.left + buttonRect.width / 2,
        buttonRect.top + buttonRect.height / 2,
      ) === button;

      textarea.scrollIntoView({ block: 'nearest' });
      const lineHeight = Number.parseFloat(getComputedStyle(textarea).lineHeight) || 0;
      const minEditable = 2 * lineHeight;
      const taVisH = clipVisibleHeight(textarea, cols);
      const twoLines = textarea.clientHeight >= minEditable && taVisH >= minEditable;
      const textareaHit = hitAtCenter(textarea);

      return {
        viewportWidth: innerWidth,
        viewportHeight: innerHeight,
        stackOk: colsRect.bottom <= alertRect.top,
        alertFitsWidth: alert.scrollWidth <= alert.clientWidth,
        startReachable,
        endReachable,
        alertFooterDisjoint: !overlaps(alertRect, footerRect),
        buttonEnabled: !button.disabled,
        buttonHit,
        twoLines,
        textareaHit,
      };
    })()`);

    expect(results.map(({ viewportWidth, viewportHeight }) => [viewportWidth, viewportHeight])).toEqual([[1280, 720], [800, 800]]);
    for (const result of results) {
      expect(result.stackOk).toBe(true);
      expect(result.alertFitsWidth).toBe(true);
      expect(result.startReachable).toBe(true);
      expect(result.endReachable).toBe(true);
      expect(result.alertFooterDisjoint).toBe(true);
      expect(result.buttonEnabled).toBe(true);
      expect(result.buttonHit).toBe(true);
      expect(result.twoLines).toBe(true);
      expect(result.textareaHit).toBe(true);
    }
  });
});
