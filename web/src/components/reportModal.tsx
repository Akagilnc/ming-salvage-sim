import { FullscreenModal } from "./hud";
import { stripOrganicMarkdown } from "../format";

export function ReportModal({
  report,
  onClose,
  periodLabel,
}: {
  report: string;
  onClose: () => void;
  /** #1356：后端 reign_period_label 投影；禁前端第二份年号表 */
  periodLabel?: string;
}) {
  const activeText = stripOrganicMarkdown(report);
  const masthead = periodLabel || "邸报";
  return (
    <FullscreenModal title="邸报" subtitle={masthead} bgClass="modal-bg-gazette" onClose={onClose} hideTitle>
      <article className="gazette-document modal-scroll">
        <div className="gazette-masthead">
          <b>邸报</b>
          <span>{masthead} · 通政使司发抄</span>
        </div>
        <pre className="memorial-text">{activeText}</pre>
        {/* #1387：主关闭钮（系统 chrome，ADR 0046）；正文仍只滚 LLM/引擎叙事，不代笔。 */}
        <div className="gazette-dismiss">
          <button type="button" className="gazette-dismiss-btn" onClick={onClose}>
            朕知道了
          </button>
        </div>
      </article>
    </FullscreenModal>
  );
}

