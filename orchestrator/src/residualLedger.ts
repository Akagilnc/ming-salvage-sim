import type {
  WorkerLandingPayload,
  WorkerMonitorHandle,
} from "./types.js";

/** Opaque pointers for transporting an unusable worker's raw artifacts. */
export function reviewerRawArtifactPointers(
  handle: WorkerMonitorHandle | undefined,
  sessionId: string | undefined,
): NonNullable<WorkerLandingPayload["rawReviewerArtifacts"]> {
  return {
    ...(handle?.logPath !== undefined ? { stdoutPath: handle.logPath } : {}),
    ...(handle?.resultPath !== undefined
      ? { sidecarPath: handle.resultPath }
      : {}),
    ...(sessionId !== undefined ? { reviewerSessionId: sessionId } : {}),
    statement: "the previous reviewer raw artifacts are here",
  };
}
