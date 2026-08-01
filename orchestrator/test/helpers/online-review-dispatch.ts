/**
 * #1145 test helper — build OnlineReviewLoopDispatch with independent
 * Collector + Verify seats (no host poll / side-effect dual-owner seams).
 */
import type {
  OnlineReviewCollectorDispatchResult,
  OnlineReviewLoopDispatch,
  OnlineReviewVerifyDispatchResult,
} from "../../src/family/onlineReviewLoop.js";
import type {
  FixerResult,
  OnlineReviewLandingSnapshot,
  VerifyResult,
  WorkerLandingPayload,
} from "../../src/types.js";
import { stubCollectorEvidence } from "../../src/reviewLoopOutcome.js";

/**
 * Build stage dispatch for unit tests.
 * - `evidence` feeds the default Collector cargo (host does not poll).
 * - `dispatchVerify` is judgment only.
 * - optional `dispatchCollector` overrides the default evidence seat.
 */
/**
 * Fixture bodies: fully opaque blob, or any named structural snapshot that
 * happens to carry prUrl/headOid (e.g. PrReviewSnapshot). No admission gate —
 * both arms are copied verbatim into Collector evidence.
 */
type EvidenceInput =
  | OnlineReviewLandingSnapshot
  | {
      readonly prUrl: string;
      readonly headOid: string;
    };

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object";
}

/** Collector seat result vs bare evidence fixture — structural, no cast fork. */
function asCollectorDispatchResult(
  raw: unknown,
): OnlineReviewCollectorDispatchResult | undefined {
  if (!isRecord(raw)) return undefined;
  if (!("evidence" in raw) && !("cargoPointer" in raw) && !("artifacts" in raw)) {
    return undefined;
  }
  const result: {
    evidence?: OnlineReviewCollectorDispatchResult["evidence"];
    cargoPointer?: string;
    artifacts?: OnlineReviewCollectorDispatchResult["artifacts"];
  } = {};
  if (raw.evidence !== undefined) {
    if (!isRecord(raw.evidence)) return undefined;
    // Any object body — copy verbatim.
    result.evidence = { ...raw.evidence };
  }
  if (typeof raw.cargoPointer === "string") {
    result.cargoPointer = raw.cargoPointer;
  }
  if (raw.artifacts !== undefined) {
    result.artifacts =
      raw.artifacts as OnlineReviewCollectorDispatchResult["artifacts"];
  }
  return result;
}

/** Bare opaque body (not a seat wrapper) — copy all own keys verbatim. */
function asBareEvidence(raw: unknown): OnlineReviewLandingSnapshot | undefined {
  if (!isRecord(raw)) return undefined;
  if ("evidence" in raw || "cargoPointer" in raw || "artifacts" in raw) {
    return undefined;
  }
  // Spread into a fresh index-signature blob so named snapshots assign cleanly.
  return { ...raw };
}

/** Bare VerifyResult vs seat wrapper — structural, no cast fork. */
function asBareVerifyResult(raw: unknown): VerifyResult | undefined {
  if (!isRecord(raw)) return undefined;
  if ("verify" in raw) return undefined;
  if (
    raw.status !== "converged" &&
    raw.status !== "continue" &&
    raw.status !== "escalate"
  ) {
    return undefined;
  }
  if (raw.kind !== undefined && raw.kind !== "verify") return undefined;
  return {
    kind: "verify",
    status: raw.status,
    ...(Object.prototype.hasOwnProperty.call(raw, "onlineReviewFixPacket")
      ? { onlineReviewFixPacket: raw.onlineReviewFixPacket }
      : {}),
  };
}

function asVerifyDispatchResult(
  raw: unknown,
): OnlineReviewVerifyDispatchResult | undefined {
  if (!isRecord(raw)) return undefined;
  if (!("verify" in raw) && !("artifacts" in raw)) return undefined;
  const bare =
    raw.verify === undefined ? undefined : asBareVerifyResult(raw.verify);
  if (raw.verify !== undefined && bare === undefined) return undefined;
  return {
    ...(bare !== undefined ? { verify: bare } : {}),
    ...(raw.artifacts !== undefined
      ? {
          artifacts:
            raw.artifacts as OnlineReviewVerifyDispatchResult["artifacts"],
        }
      : {}),
  };
}

export function onlineReviewDispatch(input: {
  readonly evidence?:
    | EvidenceInput
    | ((
        round: number,
      ) =>
        | EvidenceInput
        | Promise<EvidenceInput>
        | OnlineReviewCollectorDispatchResult
        | Promise<OnlineReviewCollectorDispatchResult>);
  /** Fixture alias — accepts evidence or PrReviewSnapshot-shaped objects. */
  readonly snapshot?:
    | EvidenceInput
    | ((
        round: number,
      ) => EvidenceInput | Promise<EvidenceInput>);
  readonly dispatchVerify?: (
    landing: WorkerLandingPayload,
    round: number,
  ) =>
    | OnlineReviewVerifyDispatchResult
    | VerifyResult
    | undefined
    | Promise<OnlineReviewVerifyDispatchResult | VerifyResult | undefined>;
  readonly dispatchCollector?: (
    landing: WorkerLandingPayload,
    round: number,
  ) =>
    | OnlineReviewCollectorDispatchResult
    | Promise<OnlineReviewCollectorDispatchResult>;
  readonly dispatchFixer?: (
    landing: WorkerLandingPayload,
  ) => FixerResult | undefined | Promise<FixerResult | undefined>;
  readonly resolveFixCommitSha?: (
    envelopeFixSha: string,
  ) => string | Promise<string>;
}): OnlineReviewLoopDispatch {
  const defaultEvidence = (): OnlineReviewLandingSnapshot =>
    stubCollectorEvidence();

  return {
    dispatchCollector: async (landing, round) => {
      if (input.dispatchCollector !== undefined) {
        return input.dispatchCollector(landing, round);
      }
      const src = input.evidence ?? input.snapshot ?? defaultEvidence;
      const raw = typeof src === "function" ? await src(round) : src;
      const asResult = asCollectorDispatchResult(raw);
      if (asResult !== undefined) return asResult;
      const bare = asBareEvidence(raw);
      if (bare !== undefined) return { evidence: bare };
      return { evidence: defaultEvidence() };
    },
    dispatchVerify: async (landing, round) => {
      if (input.dispatchVerify === undefined) {
        return { verify: { kind: "verify", status: "converged" } };
      }
      const raw = await input.dispatchVerify(landing, round);
      if (raw === undefined) return {};
      const bare = asBareVerifyResult(raw);
      if (bare !== undefined) return { verify: bare };
      const wrapped = asVerifyDispatchResult(raw);
      if (wrapped !== undefined) return wrapped;
      return {};
    },
    dispatchFixer: async (landing) => {
      if (input.dispatchFixer === undefined) return undefined;
      return input.dispatchFixer(landing);
    },
    ...(input.resolveFixCommitSha !== undefined
      ? { resolveFixCommitSha: input.resolveFixCommitSha }
      : {}),
  };
}
