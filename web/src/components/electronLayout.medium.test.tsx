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
      <FullscreenModal
        title="诏书草案"
        subtitle="盖玺颁诏即草案成案并过月"
        bgClass="modal-bg-edict"
        layerClassName="edict-safe-cmd"
        onClose={noop}
      >
        <EdictModal
          state={edictState} editingDirectiveId={null} editingDirectiveText=""
          decree="" report="" busy=""
          error={`结算中止，请重试。\n错误包：/${"long-directory/".repeat(18)}error-pack\n请将整个目录发给作者。`}
          onEditingTextChange={noop}
          onStartEdit={noop} onCancelEdit={noop} onSaveDirective={noop} onDeleteDirective={noop}
          onAdvanceWithoutEdict={noop} onIssueDecree={noop}
        />
      </FullscreenModal>,
    );
    const results = await measureElectronLayout<{
      viewportWidth: number;
      viewportHeight: number;
      alertInModal: boolean;
      footerInModal: boolean;
      buttonInModal: boolean;
      alertFitsWidth: boolean;
      startReachable: boolean;
      endReachable: boolean;
      alertFooterDisjoint: boolean;
      alertContentDisjoint: boolean;
      contentFooterDisjoint: boolean;
      contentButtonDisjoint: boolean;
      buttonEnabled: boolean;
      buttonHit: boolean;
      contentHit: boolean;
    }>(page, css("base", "court", "modals", "chat", "edict", "modal-theme", "situation"), [
      { width: 1280, height: 720 },
      { width: 1100, height: 720 },
      { width: 800, height: 800 },
    ], `(() => {
      const modal = document.querySelector('.fullscreen-modal');
      const alert = document.querySelector('[role="alert"]');
      const cols = document.querySelector('.desk-columns');
      // #1849：独立手拟栏已退役，御案内容区＝草稿/已发两区滚动列表（非拟诏文本框）。
      const content = document.querySelector('.directive-list');
      const footer = document.querySelector('.desk-footer');
      const button = document.querySelector('.desk-footer button');
      if (!modal || !alert || !cols || !content || !footer || !button) {
        return { error: 'missing edict fixture element' };
      }
      const overlaps = (a, b) => a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
      const containsRect = (outer, inner) =>
        inner.left >= outer.left && inner.right <= outer.right
        && inner.top >= outer.top && inner.bottom <= outer.bottom;
      const clipVisibleRect = (el, container) => {
        const er = el.getBoundingClientRect();
        const cr = container.getBoundingClientRect();
        return {
          left: Math.max(er.left, cr.left),
          right: Math.min(er.right, cr.right),
          top: Math.max(er.top, cr.top),
          bottom: Math.min(er.bottom, cr.bottom),
        };
      };

      const modalRect = modal.getBoundingClientRect();
      const footerRect = footer.getBoundingClientRect();
      const buttonRect = button.getBoundingClientRect();

      // Resting geometry first — before any scrollIntoView / scrollTop mutation.
      const alertRect0 = alert.getBoundingClientRect();
      const contentRect0 = content.getBoundingClientRect();
      const contentVis = clipVisibleRect(content, cols);
      const contentVisH = Math.max(0, contentVis.bottom - contentVis.top);
      const hitEl = contentVisH > 0
        ? document.elementFromPoint((contentVis.left + contentVis.right) / 2, (contentVis.top + contentVis.bottom) / 2)
        : null;
      const contentHit = !!hitEl && (hitEl === content || content.contains(hitEl));

      const buttonHit = document.elementFromPoint(
        buttonRect.left + buttonRect.width / 2,
        buttonRect.top + buttonRect.height / 2,
      ) === button;

      // Alert path reachability (alert-local scroll only; compose already measured).
      const alertContents = document.createRange();
      alertContents.selectNodeContents(alert);
      const startReachable = alertContents.getBoundingClientRect().top >= alertRect0.top + alert.clientTop;
      alert.scrollTop = alert.scrollHeight;
      const endReachable = alert.scrollHeight <= alert.clientHeight
        || Math.ceil(alert.scrollTop + alert.clientHeight) >= alert.scrollHeight;
      alert.scrollTop = 0;

      return {
        viewportWidth: innerWidth,
        viewportHeight: innerHeight,
        alertInModal: containsRect(modalRect, alertRect0),
        footerInModal: containsRect(modalRect, footerRect),
        buttonInModal: containsRect(modalRect, buttonRect),
        alertFitsWidth: alert.scrollWidth <= alert.clientWidth,
        startReachable,
        endReachable,
        alertFooterDisjoint: !overlaps(alertRect0, footerRect),
        alertContentDisjoint: !overlaps(alertRect0, contentVis),
        contentFooterDisjoint: !overlaps(contentRect0, footerRect),
        contentButtonDisjoint: !overlaps(contentRect0, buttonRect),
        buttonEnabled: !button.disabled,
        buttonHit,
        contentHit,
      };
    })()`);

    expect(results.map(({ viewportWidth, viewportHeight }) => [viewportWidth, viewportHeight])).toEqual([
      [1280, 720],
      [1100, 720],
      [800, 800],
    ]);
    for (const result of results) {
      expect(result.alertInModal, `${result.viewportWidth}x${result.viewportHeight} alertInModal`).toBe(true);
      expect(result.footerInModal, `${result.viewportWidth}x${result.viewportHeight} footerInModal`).toBe(true);
      expect(result.buttonInModal, `${result.viewportWidth}x${result.viewportHeight} buttonInModal`).toBe(true);
      expect(result.alertFitsWidth, `${result.viewportWidth}x${result.viewportHeight} alertFitsWidth`).toBe(true);
      expect(result.startReachable, `${result.viewportWidth}x${result.viewportHeight} startReachable`).toBe(true);
      expect(result.endReachable, `${result.viewportWidth}x${result.viewportHeight} endReachable`).toBe(true);
      expect(result.alertFooterDisjoint, `${result.viewportWidth}x${result.viewportHeight} alertFooterDisjoint`).toBe(true);
      expect(result.alertContentDisjoint, `${result.viewportWidth}x${result.viewportHeight} alertContentDisjoint`).toBe(true);
      expect(result.contentFooterDisjoint, `${result.viewportWidth}x${result.viewportHeight} contentFooterDisjoint`).toBe(true);
      expect(result.contentButtonDisjoint, `${result.viewportWidth}x${result.viewportHeight} contentButtonDisjoint`).toBe(true);
      expect(result.buttonEnabled, `${result.viewportWidth}x${result.viewportHeight} buttonEnabled`).toBe(true);
      expect(result.buttonHit, `${result.viewportWidth}x${result.viewportHeight} buttonHit`).toBe(true);
      expect(result.contentHit, `${result.viewportWidth}x${result.viewportHeight} contentHit`).toBe(true);
    }
  });
});
