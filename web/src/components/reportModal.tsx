import { FullscreenModal } from "./hud";
import { stripOrganicMarkdown } from "../format";

/** #1486：按空行切块，各节独立块级流式竖排，避免长卷单 pre 底节塌陷叠字。 */
function splitGazetteBlocks(text: string): string[] {
  const normalized = String(text || "").replace(/\r\n/g, "\n").trim();
  if (!normalized) return [];
  return normalized.split(/\n\s*\n/).map((b) => b.trim()).filter(Boolean);
}

export function ReportModal({
  report,
  onClose,
  periodLabel,
}: {
  report: string;
  onClose: () => void;
  /** #1356：后端 previous_reign_period_label（报文自身月）投影；禁前端第二份年号表 */
  periodLabel?: string;
}) {
  const activeText = stripOrganicMarkdown(report || "");
  const blocks = splitGazetteBlocks(activeText);
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
          {/* #1356：空卷轴不另写固定空态文案（P7）；#1486：有文时分节块级流式 */}
          {blocks.length === 0 ? (
            <pre className="memorial-text" />
          ) : (
            blocks.map((block, i) => (
              <section key={i} className="gazette-block memorial-text">
                {block}
              </section>
            ))
          )}
        </article>
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
