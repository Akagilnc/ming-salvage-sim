import React from "react";

/** Typed wait-progress facts from the settlement SSE chain; never derived from labels. */
export type SettlementLockProgress = {
  current: number;
  total: number;
};

/**
 * #1236：同会话非权威装饰。
 * - 真源是 turn.settlement_display（王承恩递话条 / 逐面门控），本组件不参与门控。
 * - 不得遮挡 DecisionModal / DecisionRecoveryPanel / 续跑入口（无全屏锁、无键盘总截、pointer-events 不吞必达层）。
 * - 刷新/新连接路径对其零依赖。
 *
 * #1725：结算等待期进度移到画面中心（视线停留处）；刻度由透传的 typed 进度事实驱动，
 * 显示标签只负责显示，不参与进度计算。
 */
export function SettlementLock({
  stage,
  progress,
  thinking,
  narrative,
}: {
  stage: string;
  progress: SettlementLockProgress | null;
  thinking: string;
  narrative: string;
}) {
  const thinkRef = React.useRef<HTMLDivElement>(null);
  const narrRef = React.useRef<HTMLDivElement>(null);
  // 流式内容到达时自动滚到底
  React.useEffect(() => {
    if (thinkRef.current) thinkRef.current.scrollTop = thinkRef.current.scrollHeight;
  }, [thinking]);
  React.useEffect(() => {
    if (narrRef.current) narrRef.current.scrollTop = narrRef.current.scrollHeight;
  }, [narrative]);

  const stageLine = stage ? `档房摘录：${stage}` : "档房摘录正在呈递。";
  const progressRatio = progress ? progress.current / progress.total : 0;

  return (
    <div
      className="settlement-lock settlement-lock-decor"
      role="status"
      aria-live="polite"
      aria-label="核账进程摘录"
      data-testid="settlement-lock-decor"
    >
      <div className="settlement-lock-card">
        <p className="settlement-lock-stage">{stageLine}</p>
        {progress ? (
          <div className="settlement-lock-progress">
            <div
              className="settlement-lock-progress-bar"
              role="progressbar"
              aria-valuemin={0}
              aria-valuenow={progress.current}
              aria-valuemax={progress.total}
              aria-label="月末结算进度"
              data-testid="settlement-wait-progress"
            >
              <div
                className="settlement-lock-progress-fill"
                style={{ width: `${Math.round(progressRatio * 100)}%` }}
              />
            </div>
            <p className="settlement-lock-progress-label">
              第 {progress.current} 步 · 共 {progress.total} 步
            </p>
          </div>
        ) : null}
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
