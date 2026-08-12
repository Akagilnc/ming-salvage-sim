import type { PendingActionFailure } from "../types";

export function PendingFailureRecoveryPanel({
  failures,
  busy,
  error,
  onRetryFailure,
}: {
  failures: PendingActionFailure[];
  busy: string;
  error: string;
  onRetryFailure: (failure: PendingActionFailure) => void;
}) {
  return (
    <div className="failure-recovery-panel">
      {error ? <div className="error-line" role="alert">{error}</div> : null}
      {failures.map((failure) => (
        <div className="failure-recovery-item" role="alert" key={failure.id}>
          <div>
            {failure.minister_name ? (
              <span className="failure-recovery-minister">{failure.minister_name}</span>
            ) : null}
            <span>{failure.message}</span>
          </div>
          {failure.retryable ? (
            <button type="button" onClick={() => onRetryFailure(failure)} disabled={!!busy}>
              重试
            </button>
          ) : null}
        </div>
      ))}
    </div>
  );
}
