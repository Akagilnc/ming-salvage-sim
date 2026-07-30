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
 * Host-typed keys only. Named snapshots (e.g. PrReviewSnapshot) stay assignable
 * structurally; loose object literals use {@link LooseEvidenceFixture}.
 * No business-field allowlist — runtime extras ride through spread (#1145).
 */
type EvidenceFixture = {
  readonly prUrl: string;
  readonly headOid: string;
};

/** Open fixture for object-literal extras (index signature). */
type LooseEvidenceFixture = EvidenceFixture & {
  readonly [key: string]: unknown;
};

/** Public input: named snapshots OR loose literals with opaque extras. */
type EvidenceInput = EvidenceFixture | LooseEvidenceFixture;

function toEvidence(raw: EvidenceFixture): OnlineReviewLandingSnapshot {
  // Opaque envelope only — remaining own keys ride through as-is (#1145).
  return { ...raw, prUrl: raw.prUrl, headOid: raw.headOid };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object";
}

/** Collector seat result vs bare evidence fixture — structural, no cast fork. */
function asCollectorDispatchResult(
  raw: unknown,
): OnlineReviewCollectorDispatchResult | undefined {
  if (!isRecord(raw)) return undefined;
  // Bare evidence fixtures carry prUrl at the top level.
  if (typeof raw.prUrl === "string") return undefined;
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
    // Opaque pass-through — sparse body legal; no prUrl/headOid gate (#1145).
    if (
      typeof raw.evidence.prUrl === "string" &&
      typeof raw.evidence.headOid === "string"
    ) {
      // Full opaque pass-through — no field allowlist.
      result.evidence = toEvidence(raw.evidence as EvidenceFixture);
    } else {
      // Sparse opaque blob — legal cargo≠fate; no prUrl/headOid required.
      result.evidence = { ...raw.evidence };
    }
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

function asEvidenceFixture(raw: unknown): EvidenceFixture | undefined {
  if (!isRecord(raw)) return undefined;
  if (typeof raw.prUrl !== "string" || typeof raw.headOid !== "string") {
    return undefined;
  }
  // Keep the full runtime object so soft fields survive toEvidence spread.
  return raw as EvidenceFixture;
}

/** Bare VerifyResult vs seat wrapper — structural, no cast fork. */
function asBareVerifyResult(raw: unknown): VerifyResult | undefined {
  if (!isRecord(raw)) return undefined;
  if ("verify" in raw) return undefined;
  if (typeof raw.converged !== "boolean") return undefined;
  // Prefer explicit kind when present; allow sparse fixtures with only converged.
  if (raw.kind !== undefined && raw.kind !== "verify") return undefined;
  return {
    kind: "verify",
    converged: raw.converged,
    ...(raw.findingDispositions !== undefined
      ? {
          findingDispositions:
            raw.findingDispositions as VerifyResult["findingDispositions"],
        }
      : {}),
    ...(Array.isArray(raw.fixMarkedFindingIdentityKeys)
      ? {
          fixMarkedFindingIdentityKeys:
            raw.fixMarkedFindingIdentityKeys.filter(
              (k): k is string => typeof k === "string",
            ),
        }
      : {}),
    ...(Array.isArray(raw.fixMarkedFindingThreads)
      ? {
          fixMarkedFindingThreads: raw.fixMarkedFindingThreads.flatMap(
            (binding) => {
              if (!isRecord(binding)) return [];
              if (
                typeof binding.identityKey !== "string" ||
                typeof binding.threadId !== "string"
              ) {
                return [];
              }
              return [
                {
                  identityKey: binding.identityKey,
                  threadId: binding.threadId,
                },
              ];
            },
          ),
        }
      : {}),
    ...(typeof raw.terminalState === "string"
      ? {
          terminalState:
            raw.terminalState as NonNullable<VerifyResult["terminalState"]>,
        }
      : {}),
    ...(typeof raw.isRecheck === "boolean" ? { isRecheck: raw.isRecheck } : {}),
    ...(typeof raw.advanceCoder === "string"
      ? { advanceCoder: raw.advanceCoder }
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
      const fixture = asEvidenceFixture(raw);
      if (fixture !== undefined) return { evidence: toEvidence(fixture) };
      return { evidence: defaultEvidence() };
    },
    dispatchVerify: async (landing, round) => {
      if (input.dispatchVerify === undefined) {
        return { verify: { kind: "verify", converged: true } };
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
