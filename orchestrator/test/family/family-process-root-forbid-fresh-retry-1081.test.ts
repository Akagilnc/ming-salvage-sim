/**
 * #1081 / #1085 / ADR 0147 — family/wave resident-judge resume must not
 * silent-fresh (same continuity rule as per-slice runner isJudgeSeat gate).
 *
 * Seam: {@link dispatchFamilyWorkerOrAbort} → {@link withMechanicalRetry}.
 */

import { beforeAll, describe, expect, it } from "vitest";

import { dispatchFamilyWorkerOrAbort } from "../../src/family/familyProcessRootDispatch.js";
import {
  cmrWorkerSpec,
  familyCoderFixWorkerSpec,
} from "../../src/family/dispatchFamilyWorker.js";
import { reviewPanelLegWorkerSpec } from "../../src/family/reviewPanelLegs.js";
import type {
  FamilyBackend,
  FamilyLedgerEntry,
  MergeRequest,
} from "../../src/family/types.js";
import {
  resolveActiveModelRoute,
  smokeRouteModels,
  type ResolvedModelRoute,
} from "../../src/modelRoutes.js";
import type {
  DispatchContext,
  WorkerResult,
  WorkerSpec,
} from "../../src/types.js";

function minimalFamilyBackend(script: {
  dispatch: (spec: WorkerSpec, ctx: DispatchContext) => Promise<WorkerResult>;
}): FamilyBackend {
  const ledger: FamilyLedgerEntry[] = [];
  return {
    async mergeChildIntoFamilyBase(_child: MergeRequest) {
      return { familyHead: "head" };
    },
    async resolveMergeConflict() {
      throw new Error("not used");
    },
    async appendFamilyLedger(entry) {
      ledger.push(entry);
    },
    async readFamilyLedger() {
      return ledger;
    },
    async runFamilyVerify() {
      return { ok: true };
    },
    async dispatchWorker(spec, ctx) {
      return script.dispatch(spec, ctx);
    },
  };
}

describe("#1081 familyProcessRootDispatch forbidFreshRetry for resident judge", () => {
  let modelRoute: ResolvedModelRoute;
  const noSleep = async () => {};

  beforeAll(async () => {
    modelRoute = await smokeRouteModels(
      resolveActiveModelRoute(),
      async () => ({ cliVersion: "test-1081-family-forbid-fresh" }),
    );
  });

  it("positive: resumed family cmr judge process failure stops after one attempt", async () => {
    let calls = 0;
    const seen: DispatchContext[] = [];
    const backend = minimalFamilyBackend({
      dispatch: async (_spec, ctx) => {
        calls += 1;
        seen.push(ctx);
        return { kind: "failed", reason: "family judge resume crashed" };
      },
    });

    const result = await dispatchFamilyWorkerOrAbort(
      backend,
      cmrWorkerSpec("resume", "correctness", modelRoute),
      {
        familyBase: "family/1081-judge",
        resumeSessionId: "sess-family-judge-1081",
        cmrPass: "correctness",
        modelRoute,
      },
      undefined,
      { sleepMs: noSleep },
    );

    expect(result.kind).toBe("failed");
    if (result.kind === "failed") {
      expect(result.reason).toMatch(/family judge resume crashed/);
    }
    expect(calls).toBe(1);
    expect(seen[0]?.resumeSessionId).toBe("sess-family-judge-1081");
  });

  it("positive: resumed wave/family judge thrown process error stops after one attempt", async () => {
    let calls = 0;
    const backend = minimalFamilyBackend({
      dispatch: async () => {
        calls += 1;
        throw new Error("family judge resume threw");
      },
    });

    // Outer court collapses rethrown process failure into failed (loud package);
    // load-bearing contract = one attempt only (no silent fresh redispatch).
    const result = await dispatchFamilyWorkerOrAbort(
      backend,
      cmrWorkerSpec("resume", "completeness", modelRoute),
      {
        familyBase: "family/1081-judge-throw",
        resumeSessionId: "sess-family-judge-throw",
        cmrPass: "completeness",
        modelRoute,
      },
      undefined,
      { sleepMs: noSleep },
    );
    expect(result.kind).toBe("failed");
    if (result.kind === "failed") {
      expect(result.reason).toMatch(/family judge resume threw/);
    }
    expect(calls).toBe(1);
  });

  it("negative: family coder-fix process failure still falls through to fresh retry", async () => {
    let calls = 0;
    const seen: DispatchContext[] = [];
    const backend = minimalFamilyBackend({
      dispatch: async (_spec, ctx) => {
        calls += 1;
        seen.push(ctx);
        if (calls === 1) {
          return { kind: "failed", reason: "fixer blip" };
        }
        return {
          kind: "completed",
          output: { kind: "coder", committed: true, commitsAdded: 1 },
        };
      },
    });

    const result = await dispatchFamilyWorkerOrAbort(
      backend,
      familyCoderFixWorkerSpec(modelRoute, "resume"),
      {
        familyBase: "family/1081-fixer",
        resumeSessionId: "sess-family-fixer",
        modelRoute,
      },
      undefined,
      { sleepMs: noSleep },
    );

    expect(result.kind).toBe("completed");
    expect(calls).toBe(2);
    expect(seen[0]?.resumeSessionId).toBe("sess-family-fixer");
    expect(seen[1]?.resumeSessionId).toBeUndefined();
  });

  it("negative: fresh family judge (no resume) still process-root retries", async () => {
    let calls = 0;
    const backend = minimalFamilyBackend({
      dispatch: async () => {
        calls += 1;
        if (calls === 1) {
          return { kind: "failed", reason: "fresh judge blip" };
        }
        return {
          kind: "completed",
          output: { kind: "judge", status: "converged" },
        };
      },
    });

    const result = await dispatchFamilyWorkerOrAbort(
      backend,
      cmrWorkerSpec("fresh", "correctness", modelRoute),
      {
        familyBase: "family/1081-fresh-judge",
        cmrPass: "correctness",
        modelRoute,
      },
      undefined,
      { sleepMs: noSleep },
    );

    expect(result.kind).toBe("completed");
    expect(calls).toBe(2);
  });

  it("#1080 R3 positive: panel leg with leaked judge resume still process-root retries", async () => {
    // Panel legs share id S3 with the pure court but are kind "reviewer" /
    // session "fresh". Even if a caller leaks resumeSessionId into ctx (the
    // pre-fix contamination), they must keep the full mechanical-retry budget
    // — forbidFreshRetry is for pure-court kind:"cmr" only.
    let calls = 0;
    const seen: DispatchContext[] = [];
    const backend = minimalFamilyBackend({
      dispatch: async (_spec, ctx) => {
        calls += 1;
        seen.push(ctx);
        if (calls === 1) {
          return { kind: "failed", reason: "panel leg transient blip" };
        }
        return {
          kind: "completed",
          output: {
            kind: "reviewer",
            findingsCount: 0,
            findings: [],
            rawStdout: "panel leg ok after retry\n",
          },
        };
      },
    });

    const legSpec = reviewPanelLegWorkerSpec(
      { family: "codex", slug: "gpt-5.6-sol" },
      { kind: "family", pass: "correctness" },
    );
    expect(legSpec.id).toBe("S3");
    expect(legSpec.kind).toBe("reviewer");
    expect(legSpec.session).toBe("fresh");

    const result = await dispatchFamilyWorkerOrAbort(
      backend,
      legSpec,
      {
        familyBase: "family/1080-panel-leg",
        cmrPass: "correctness",
        modelRoute,
        // Contaminated ctx: judge resume leaked into panel fan-out.
        resumeSessionId: "sess-leaked-judge-resume",
      },
      undefined,
      { sleepMs: noSleep },
    );

    expect(result.kind).toBe("completed");
    expect(calls).toBe(2);
    // First attempt saw the leak; second is force-fresh (resume stripped by retry).
    expect(seen[0]?.resumeSessionId).toBe("sess-leaked-judge-resume");
    expect(seen[1]?.resumeSessionId).toBeUndefined();
  });

  it("#1080 R3 negative: pure-court kind:cmr with resume still stops after one attempt", async () => {
    // Contrasts the panel-leg case: kind "cmr" + resume keeps forbidFreshRetry.
    let calls = 0;
    const backend = minimalFamilyBackend({
      dispatch: async () => {
        calls += 1;
        return { kind: "failed", reason: "pure court resume still fails" };
      },
    });

    const result = await dispatchFamilyWorkerOrAbort(
      backend,
      cmrWorkerSpec("resume", "correctness", modelRoute),
      {
        familyBase: "family/1080-cmr-not-panel",
        resumeSessionId: "sess-pure-court",
        cmrPass: "correctness",
        modelRoute,
      },
      undefined,
      { sleepMs: noSleep },
    );

    expect(result.kind).toBe("failed");
    expect(calls).toBe(1);
  });
});
