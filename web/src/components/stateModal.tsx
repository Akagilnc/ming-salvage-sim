import { SituationPanel } from "./situation";
import type { GameState } from "../types";

/**
 * #1285：奏疏面 = memorials 面键真源。
 * 模态内容复用 SituationPanel 既有列表（禁新数据源）；badge 仍接 issues 计数。
 */
export function StateModal({ state }: { state: GameState }) {
  const issues = state.issues || [];
  if (!issues.length) {
    return (
      <article className="state-document modal-scroll">
        <div className="empty-note">暂无待览奏疏。</div>
      </article>
    );
  }
  return (
    <article className="state-document modal-scroll" aria-label="奏疏列表">
      <SituationPanel issues={issues} closedIssues={[]} hasLegacies={false} />
    </article>
  );
}
