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
