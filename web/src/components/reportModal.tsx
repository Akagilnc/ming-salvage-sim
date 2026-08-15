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
      </article>
    </FullscreenModal>
  );
}

