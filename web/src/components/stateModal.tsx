import type { GameState, Memorial } from "../types";

/**
 * #1726：奏疏面 = memorials 收件箱真源（进度奏报 + 派系检举）。
 * 与局势 issues 脱钩；正文原样，不得渲染 id / progress_band / origin / payload。
 * #1285 面键仍为 memorials；核账期只读可达，内容不借 situation 闸。
 */
export function StateModal({ state }: { state: GameState }) {
  const memorials = state.memorials || [];
  if (!memorials.length) {
    return (
      <article className="state-document modal-scroll">
        <div className="empty-note">本月无疏。</div>
      </article>
    );
  }
  return (
    <article className="state-document modal-scroll" aria-label="奏疏列表">
      <div className="memorial-inbox">
        {memorials.map((m) => (
          <MemorialCard key={m.key} memorial={m} />
        ))}
      </div>
    </article>
  );
}

function MemorialCard({ memorial }: { memorial: Memorial }) {
  return (
    <section
      className={`memorial-card${memorial.unread ? " memorial-card-unread" : ""}`}
    >
      <header className="memorial-card-head">
        <span className="memorial-author">{memorial.author_name}</span>
        {memorial.unread ? <span className="memorial-unread-mark" aria-label="未读">未读</span> : null}
      </header>
      <pre className="memorial-text">{memorial.memorial_text}</pre>
    </section>
  );
}
