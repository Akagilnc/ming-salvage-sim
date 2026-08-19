import { SituationPanel } from "./situation";
import type { GameState } from "../types";
import { SETTLEMENT_CLOSED_REASON } from "../settlementPresentation";

/**
 * #1285：奏疏面 = memorials 面键真源。
 * 模态内容复用 SituationPanel 既有列表（禁新数据源）；badge 仍接 issues 计数。
 * showIssues 由调用方喂 isFaceReachable("situation", …)——模态自不判 settlementDisplay。
 */
export function StateModal({ state, showIssues }: { state: GameState; showIssues: boolean }) {
  const issues = showIssues ? (state.issues || []) : [];
  if (!issues.length) {
    return (
      <article className="state-document modal-scroll">
        <div className="empty-note">{showIssues ? "暂无待览奏疏。" : SETTLEMENT_CLOSED_REASON}</div>
      </article>
    );
  }
  return (
    <article className="state-document modal-scroll" aria-label="奏疏列表">
      <SituationPanel issues={issues} closedIssues={[]} hasLegacies={false} />
    </article>
  );
}
