import { FullscreenModal } from "./hud";

export function ReportModal({
  report,
  attendantMessage,
  onClose,
  periodLabel,
}: {
  report: string;
  /** #671：王承恩独立递话；空则整区不渲染 */
  attendantMessage?: string;
  onClose: () => void;
  /** #1356：后端 previous_reign_period_label（报文自身月）投影；禁前端第二份年号表 */
  periodLabel?: string;
}) {
  // P6 / ADR 0142：官方邸报原文直写 DOM，trim 仅用于递话判空
  const rawAttendant = String(attendantMessage || "");
  const masthead = periodLabel || "邸报";
  return (
    <FullscreenModal title="邸报" subtitle={masthead} bgClass="modal-bg-gazette" onClose={onClose} hideTitle>
      {/* #1398：dismiss 移出滚容器，视口常显，长文滚底不再把「朕知道了」埋掉。 */}
      <div className="gazette-shell">
        <article className="gazette-document modal-scroll">
          <div className="gazette-masthead">
            <b>邸报</b>
            <span>{masthead} · 通政使司发抄</span>
          </div>
          {/* #1356：空卷轴复用原 pre，不另写固定空态文案（P7） */}
          <pre className="memorial-text">{report || ""}</pre>
        </article>
        {/* #671：邸报纸面之外独立递话区；原文直写 */}
        {rawAttendant.trim() ? (
          <aside className="gazette-attendant" data-testid="gazette-attendant">
            <pre className="gazette-attendant-text">{rawAttendant}</pre>
          </aside>
        ) : null}
        {/* #1387：主关闭钮（系统 chrome，ADR 0046）；正文仍只滚 LLM/引擎叙事，不代笔。 */}
        <div className="gazette-dismiss">
          <button type="button" className="gazette-dismiss-btn" onClick={onClose}>
            朕知道了
          </button>
        </div>
      </div>
    </FullscreenModal>
  );
}
