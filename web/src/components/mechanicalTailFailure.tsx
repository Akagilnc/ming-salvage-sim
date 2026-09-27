type Failure = { error?: string; error_pack_path?: string } | null | undefined;

export function MechanicalTailFailure({ failure, onRetry }: { failure: Failure; onRetry: () => void }) {
  if (!failure) return null;
  return <div role="alert">
    机械尾执行失败{failure.error ? `：${failure.error}` : ""}。
    {failure.error_pack_path ? <>错误包：{failure.error_pack_path}，请把它发给作者。</> : null}
    <button type="button" onClick={onRetry}>重试</button>
  </div>;
}
