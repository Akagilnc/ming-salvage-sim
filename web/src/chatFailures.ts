import type { PendingActionFailure } from "./types";

export function mergePendingActionFailures(
  current: PendingActionFailure[],
  incoming: PendingActionFailure[],
): PendingActionFailure[] {
  if (!incoming.length) return current;
  const byId = new Map<number, PendingActionFailure>();
  for (const failure of current) {
    byId.set(failure.id, failure);
  }
  for (const failure of incoming) {
    byId.set(failure.id, failure);
  }
  return Array.from(byId.values());
}

export function refreshRetriedPendingActionFailures(
  current: PendingActionFailure[],
  retriedFailureId: number,
  targetMinisterName: string | undefined,
  incoming: PendingActionFailure[],
): PendingActionFailure[] {
  const kept = current.filter((item) => {
    if (item.id === retriedFailureId) return false;
    return !(item.kind === "secret_order" && item.minister_name === targetMinisterName);
  });
  return mergePendingActionFailures(kept, incoming);
}
