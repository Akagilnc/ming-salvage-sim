import React from "react";

/**
 * #1852：核账期本面邸报落位（ADR 0158 决定 5）。
 * 非全屏自动弹窗；「朕知道了」只关阅读态。正文直写 DOM（P6 / ADR 0142）。
 */
export function SettlementGazettePanel({
  report,
  attendantMessage,
  periodLabel,
  onDismiss,
}: {
  report: string;
  attendantMessage?: string;
  periodLabel?: string;
  onDismiss: () => void;
}) {
  const rawAttendant = String(attendantMessage || "");
  const masthead = periodLabel || "邸报";
  const bodyRef = React.useRef<HTMLDivElement | null>(null);

  React.useEffect(() => {
    if (bodyRef.current) bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
  }, [report]);

  return (
    <div
      className="settlement-gazette-panel"
      role="region"
      aria-label="本月邸报"
      data-testid="settlement-gazette-panel"
    >
      <div className="gazette-shell settlement-gazette-shell">
        <div className="gazette-document modal-scroll" ref={bodyRef}>
          <div className="gazette-masthead">
            <b>邸报</b>
            <span>{masthead} · 通政使司发抄</span>
          </div>
          <pre className="memorial-text">{report || ""}</pre>
        </div>
        {rawAttendant.trim() ? (
          <aside className="gazette-attendant" data-testid="gazette-attendant">
            <pre className="gazette-attendant-text">{rawAttendant}</pre>
          </aside>
        ) : null}
        <div className="gazette-dismiss">
          <button type="button" className="gazette-dismiss-btn" onClick={onDismiss}>
            朕知道了
          </button>
        </div>
      </div>
    </div>
  );
}
