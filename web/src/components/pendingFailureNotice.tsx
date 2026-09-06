import type { PendingActionFailure } from "../types";

// #1765 ②：坏 payload 重放已删——此面板只如实列出「没落下的政务」，
// 不宣称恢复/处理，也不提供任何动作（0046 薄系统层）。
export function PendingFailureNoticePanel({
  failures,
  error,
}: {
  failures: PendingActionFailure[];
  error: string;
}) {
  return (
    <div className="failure-notice-panel">
      {error ? <div className="error-line" role="alert">{error}</div> : null}
      {failures.map((failure) => (
        <div className="failure-notice-item" role="alert" key={failure.id}>
          <div>
            {failure.minister_name ? (
              <span className="failure-notice-minister">{failure.minister_name}</span>
            ) : null}
            <span>{failure.message}</span>
          </div>
        </div>
      ))}
    </div>
  );
}
