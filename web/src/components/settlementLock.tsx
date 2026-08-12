import React from "react";
import { Loader2 } from "lucide-react";

export function SettlementLock({
  stage,
  thinking,
  narrative,
}: {
  stage: string;
  thinking: string;
  narrative: string;
}) {
  const thinkRef = React.useRef<HTMLDivElement>(null);
  const narrRef = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => {
    const block = (event: KeyboardEvent) => {
      event.preventDefault();
      event.stopPropagation();
    };
    window.addEventListener("keydown", block, true);
    return () => window.removeEventListener("keydown", block, true);
  }, []);
  // 流式内容到达时自动滚到底
  React.useEffect(() => {
    if (thinkRef.current) thinkRef.current.scrollTop = thinkRef.current.scrollHeight;
  }, [thinking]);
  React.useEffect(() => {
    if (narrRef.current) narrRef.current.scrollTop = narrRef.current.scrollHeight;
  }, [narrative]);
  return (
    <div className="settlement-lock" role="alertdialog" aria-modal="true" aria-label="月末结算">
      <div className="settlement-lock-card">
        <Loader2 className="settlement-spin" size={28} />
        <h2>月末结算中</h2>
        <p>{stage === "数值推演结算" ? "档房核账中，钱粮、地方、军务落账，请稍候。" : stage ? `当前：${stage}` : "朝廷推演钱粮、地方、军务，请勿操作。"}</p>
        {thinking && (
          <div className="settlement-stream-block">
            <div className="settlement-stream-label">邸报房推敲</div>
            <div className="settlement-stream-text settlement-thinking" ref={thinkRef}>
              {thinking}
            </div>
          </div>
        )}
        {narrative && (
          <div className="settlement-stream-block">
            <div className="settlement-stream-label">月末奏章</div>
            <div className="settlement-stream-text settlement-narrative" ref={narrRef}>
              {narrative}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
