import React from "react";

export function DecisionRecoveryPanel({
  message,
  busy,
  onRetry,
}: {
  message: string;
  busy: string;
  onRetry: () => void;
}) {
  return (
    <div className="recovery-banner decision-recovery-banner" role="alert" aria-live="assertive">
      <span className="recovery-banner-message">{message}</span>
      <button type="button" className="seal-btn-issue" onClick={onRetry} disabled={!!busy}>
        重新拉取待批决策
      </button>
    </div>
  );
}
