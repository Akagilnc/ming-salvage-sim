/**
 * #1145 test helper — build OnlineReviewLoopDispatch without host poll /
 * applySideEffects dual-owner seams.
 */
import type { PrReviewSnapshot } from "../../src/botPolling.js";
import type {
  OnlineReviewLoopDispatch,
  OnlineReviewVerifyDispatchResult,
} from "../../src/family/onlineReviewLoop.js";
import type {
  FixerResult,
  VerifyResult,
  WorkerLandingPayload,
} from "../../src/types.js";

export type LegacyVerifyReturn =
  | VerifyResult
  | {
      readonly kind: "rawReviewerArtifacts";
      readonly artifacts: NonNullable<
        WorkerLandingPayload["rawReviewerArtifacts"]
      >;
      readonly verify?: VerifyResult;
    };

function normalize(
  raw: LegacyVerifyReturn | OnlineReviewVerifyDispatchResult | undefined,
  snapshot: PrReviewSnapshot,
): OnlineReviewVerifyDispatchResult {
  if (raw && typeof raw === "object" && "snapshot" in raw) {
    return raw as OnlineReviewVerifyDispatchResult;
  }
  if (
    raw &&
    typeof raw === "object" &&
    (raw as { kind?: string }).kind === "rawReviewerArtifacts"
  ) {
    const r = raw as {
      artifacts?: NonNullable<WorkerLandingPayload["rawReviewerArtifacts"]>;
      verify?: VerifyResult;
    };
    return {
      snapshot,
      ...(r.artifacts !== undefined ? { artifacts: r.artifacts } : {}),
      ...(r.verify !== undefined ? { verify: r.verify } : {}),
    };
  }
  if (raw && typeof raw === "object" && "converged" in raw) {
    return { snapshot, verify: raw as VerifyResult };
  }
  return { snapshot };
}

export function onlineReviewDispatch(input: {
  readonly snapshot:
    | PrReviewSnapshot
    | ((round: number) => PrReviewSnapshot | Promise<PrReviewSnapshot>);
  readonly dispatchVerify: (
    landing: WorkerLandingPayload,
    round: number,
  ) => Promise<LegacyVerifyReturn | OnlineReviewVerifyDispatchResult>;
  readonly dispatchFixer: (
    landing: WorkerLandingPayload,
  ) => Promise<FixerResult | undefined>;
  readonly retriggerAfterFix?: () => void | Promise<void>;
  readonly resolveFixCommitSha?: (
    envelopeFixSha: string,
  ) => string | Promise<string>;
}): OnlineReviewLoopDispatch {
  return {
    dispatchVerify: async (landing, round) => {
      const snapshot =
        typeof input.snapshot === "function"
          ? await input.snapshot(round)
          : input.snapshot;
      const raw = await input.dispatchVerify(landing, round);
      return normalize(raw, snapshot);
    },
    dispatchFixer: input.dispatchFixer,
    retriggerAfterFix: input.retriggerAfterFix ?? (() => {}),
    ...(input.resolveFixCommitSha !== undefined
      ? { resolveFixCommitSha: input.resolveFixCommitSha }
      : {}),
  };
}
