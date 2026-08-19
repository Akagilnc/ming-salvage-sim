import { FullscreenModal } from "./hud";
import { stripOrganicMarkdown } from "../format";

export function ReportModal({
  report,
  onClose,
}: {
  report: string;
  onClose: () => void;
}) {
  const activeText = stripOrganicMarkdown(report);
  return (
    <FullscreenModal title="邸报" subtitle="本月故事" bgClass="modal-bg-gazette" onClose={onClose} hideTitle>
      <article className="gazette-document modal-scroll">
        <div className="gazette-masthead">
          <b>邸报</b>
          <span>本月故事 · 通政使司发抄</span>
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

