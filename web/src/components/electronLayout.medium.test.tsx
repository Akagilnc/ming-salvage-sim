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
      alertInModal: boolean;
      footerInModal: boolean;
      buttonInModal: boolean;
      alertFitsWidth: boolean;
      startReachable: boolean;
      endReachable: boolean;
      alertFooterDisjoint: boolean;
      taFooterDisjoint: boolean;
      taButtonDisjoint: boolean;
      alertBgOpaque: boolean;
      buttonEnabled: boolean;
      buttonHit: boolean;
      twoLines: boolean;
      textareaHit: boolean;
      toolButtonsReachable: boolean;
    }>(page, css("base", "court", "modals", "chat", "edict", "modal-theme", "situation"), [
      { width: 1280, height: 720 },
      { width: 1100, height: 720 },
      { width: 800, height: 800 },
    ], `(() => {
      const modal = document.querySelector('.fullscreen-modal');
      const alert = document.querySelector('[role="alert"]');
      const cols = document.querySelector('.desk-columns');
      const memorials = document.querySelector('.desk-memorials');
      const toolButtons = Array.from(document.querySelectorAll('.directive-tools > button'));
      const textarea = document.querySelector('.desk-compose textarea');
      const footer = document.querySelector('.desk-footer');
      const button = document.querySelector('.desk-footer button');
      if (!modal || !alert || !cols || !memorials || toolButtons.length !== 2 || !textarea || !footer || !button) {
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
      // Self-only hit: no sibling / tools-container stand-in.
      const hitSelf = (el, container) => {
        const vis = clipVisibleRect(el, container);
        const w = vis.right - vis.left;
        const h = vis.bottom - vis.top;
        if (w <= 0 || h <= 0) return false;
        const hit = document.elementFromPoint((vis.left + vis.right) / 2, (vis.top + vis.bottom) / 2);
        return !!hit && (hit === el || el.contains(hit));
      };
      // Reachable at rest via memorials, or after memorials-only scroll. No cols fallback.
      const reachableViaMemorials = (el) => {
        if (hitSelf(el, memorials)) return true;
        const prevMemScroll = memorials.scrollTop;
        const canScroll = memorials.scrollHeight > memorials.clientHeight + 1;
        memorials.scrollTop = memorials.scrollHeight;
        const ok = canScroll && hitSelf(el, memorials);
        memorials.scrollTop = prevMemScroll;
        return ok;
      };

      const modalRect = modal.getBoundingClientRect();
      const footerRect = footer.getBoundingClientRect();
      const buttonRect = button.getBoundingClientRect();

      // Resting geometry first — Class A before any scrollIntoView / scrollTop mutation.
      const alertRect0 = alert.getBoundingClientRect();
      const taRect0 = textarea.getBoundingClientRect();
      const taStyle = getComputedStyle(textarea);
      const lineHeight = Number.parseFloat(taStyle.lineHeight) || 0;
      const padY = (Number.parseFloat(taStyle.paddingTop) || 0) + (Number.parseFloat(taStyle.paddingBottom) || 0);
      const contentH = Math.max(0, textarea.clientHeight - padY);
      const twoLines = contentH >= 2 * lineHeight;
      const taVis = clipVisibleRect(textarea, cols);
      const taVisH = Math.max(0, taVis.bottom - taVis.top);
      const hitEl = taVisH > 0
        ? document.elementFromPoint((taVis.left + taVis.right) / 2, (taVis.top + taVis.bottom) / 2)
        : null;
      const textareaHit = !!hitEl && (hitEl === textarea || textarea.contains(hitEl));

      const buttonHit = document.elementFromPoint(
        buttonRect.left + buttonRect.width / 2,
        buttonRect.top + buttonRect.height / 2,
      ) === button;

      // .directive-tools direct children: sole owner is .desk-memorials (no cols / sibling fallback).
      const toolButtonsReachable = toolButtons.length > 0 && toolButtons.every(reachableViaMemorials);

      // Theme * wash must not zero the error-line background under modal-bg-edict.
      const alertBg = getComputedStyle(alert).backgroundColor;
      const alertBgOpaque = !!alertBg
        && alertBg !== 'transparent'
        && alertBg !== 'rgba(0, 0, 0, 0)'
        && alertBg !== 'rgba(0,0,0,0)';

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
        taFooterDisjoint: !overlaps(taRect0, footerRect),
        taButtonDisjoint: !overlaps(taRect0, buttonRect),
        alertBgOpaque,
        buttonEnabled: !button.disabled,
        buttonHit,
        twoLines,
        textareaHit,
        toolButtonsReachable,
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
      expect(result.taFooterDisjoint, `${result.viewportWidth}x${result.viewportHeight} taFooterDisjoint`).toBe(true);
      expect(result.taButtonDisjoint, `${result.viewportWidth}x${result.viewportHeight} taButtonDisjoint`).toBe(true);
      expect(result.alertBgOpaque, `${result.viewportWidth}x${result.viewportHeight} alertBgOpaque`).toBe(true);
      expect(result.buttonEnabled, `${result.viewportWidth}x${result.viewportHeight} buttonEnabled`).toBe(true);
      expect(result.buttonHit, `${result.viewportWidth}x${result.viewportHeight} buttonHit`).toBe(true);
      expect(result.twoLines, `${result.viewportWidth}x${result.viewportHeight} twoLines`).toBe(true);
      expect(result.textareaHit, `${result.viewportWidth}x${result.viewportHeight} textareaHit`).toBe(true);
      expect(result.toolButtonsReachable, `${result.viewportWidth}x${result.viewportHeight} toolButtonsReachable`).toBe(true);
    }
  });
});
