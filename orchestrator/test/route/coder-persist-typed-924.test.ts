import {
  afterEach,
  describe,
  expect,
  it,
  readFileSync,
  rmSync,
  dirname,
  join,
  fileURLToPath,
  RECEIPT_MAX_RETRIES,
  CODER_RECEIPT_TAG,
  coderStationReceiptSchema,
  decodeCoderEnvelope,
  classifyResumeError,
  runOrchestrator,
  skeletonReviewLoopWorkerResult,
  Backend,
  DispatchContext,
  Finding,
  IssueMeta,
  StepOutput,
  StepSpec,
  WorkerResult,
  WorkerSpec,
  WorktreeHandle,
  runScriptedStructuredOutput,
  ScriptedAgent,
  PROMPTS_DIR,
  WORKTREE,
  S2_SESSION,
  PersistCoderBackend,
} from "./coder-persist-typed-924.shared.js";

describe("#924 S2/S5 single-iter + S5 resumes coder session", () => {
  it("S2 is single-iter fresh; S5 is single-iter resume of the S2 session", async () => {
    const backend = new PersistCoderBackend();
    const result = await runOrchestrator({ issueNumber: 924, backend });
    expect(result.status).toBe("completed");

    const s2Idx = backend.specs.findIndex((s) => s.id === "S2");
    const s5Idx = backend.specs.findIndex((s) => s.id === "S5");
    expect(s2Idx).toBeGreaterThanOrEqual(0);
    expect(s5Idx).toBeGreaterThanOrEqual(0);

    const s2 = backend.specs[s2Idx]!;
    const s5 = backend.specs[s5Idx]!;
    const s2Ctx = backend.ctxs[s2Idx]!;
    const s5Ctx = backend.ctxs[s5Idx]!;

    // Single-iteration seats (Ralph outer multi-iter retired).
    expect(s2.maxIter).toBe(1);
    expect(s5.maxIter).toBe(1);

    // S2 establishes the session.
    expect(s2.session).toBe("fresh");
    expect(s2Ctx.resumeSessionId).toBeUndefined();

    // S5 resumes the same session S2 surfaced.
    expect(s5.session).toBe("resume");
    expect(s5Ctx.resumeSessionId).toBe(S2_SESSION);
    expect(backend.resumeSessionCalls).toContainEqual(["S5", S2_SESSION]);
  });

  it("multi-round S5 keeps resuming the same coder session id", async () => {
    /**
     * Force two fix rounds: S3 open-count>0 → S5 → S6 open-count>0 → S5 → S6 clean.
     */
    class TwoFixRoundsBackend extends PersistCoderBackend {
      private reviews = 0;
      override async dispatchWorker(
        spec: WorkerSpec,
        ctx: DispatchContext,
      ): Promise<WorkerResult> {
        if ((spec.kind === "reviewer" || spec.kind === "verify")) {
          this.dispatched.push(`${spec.id}:${spec.kind}:${spec.session}`);
          this.specs.push(spec);
          this.ctxs.push(ctx);
          this.reviews += 1;
          // r1 and r2 still open; r3 clean via explicit judge converged.
          if (this.reviews <= 2) {
            const findings: Finding[] = [
              {
                severity: "high",
                category: "correctness",
                claim_quote: `round-${this.reviews}`,
                location: `f.ts:${this.reviews}`,
                suggested_fix: "fix",
                action: "fix_now",
              },
            ];
            return {
              kind: "completed",
              output: {
                kind: "reviewer",
                findings,
                findingsCount: 1,
                fixPacketBody: "fixture residual authored body",
              },
              sessionId: `sess-review-${this.reviews}`,
            };
          }
          return {
            kind: "completed",
            output: { kind: "judge", status: "converged" },
            sessionId: `sess-review-${this.reviews}`,
          };
        }
        return super.dispatchWorker(spec, ctx);
      }
    }

    const backend = new TwoFixRoundsBackend();
    const result = await runOrchestrator({ issueNumber: 924, backend });
    expect(result.status).toBe("completed");

    const s5Resumes = backend.resumeSessionCalls.filter(([step]) => step === "S5");
    expect(s5Resumes.length).toBeGreaterThanOrEqual(2);
    for (const [, sessionId] of s5Resumes) {
      expect(sessionId).toBe(S2_SESSION);
    }
    const s5Specs = backend.specs.filter((s) => s.id === "S5");
    expect(s5Specs.every((s) => s.maxIter === 1)).toBe(true);
    expect(s5Specs.every((s) => s.session === "resume")).toBe(true);
  });
});

// #962: per-run GIT_CONFIG_GLOBAL isolation removes the old sequential need.
describe("#924 coder station-receipt Output.object (T2 schema)", () => {
  const cleanups: string[] = [];
  afterEach(() => {
    while (cleanups.length > 0) {
      const dir = cleanups.pop();
      if (dir !== undefined) rmSync(dir, { recursive: true, force: true });
    }
  });

  const goodCompleted = {
    station: "coder" as const,
    status: "completed" as const,
    committed: true,
    commitsAdded: 1,
  };

  it("rejects illegal traffic shapes at the SO schema boundary (negative)", () => {
    // Pure schema pin — no sc.run. Bad shapes are what Sandcastle re-asks;
    // the bad→good case above proves native re-ask.
    const schema = coderStationReceiptSchema();
    expect(schema.safeParse({ committed: true, commitsAdded: 1 }).success).toBe(
      false,
    );
    expect(schema.safeParse({ status: "maybe" }).success).toBe(false);
    expect(schema.safeParse({ station: "coder" }).success).toBe(false);
    expect(
      schema.safeParse({ station: "coder", status: "refused" }).success,
    ).toBe(false);
    expect(
      schema.safeParse({
        station: "coder",
        status: "completed",
        refusedFindingIdentityKeys: ["x"],
      }).success,
    ).toBe(false);
    expect(schema.safeParse(goodCompleted).success).toBe(true);
    expect(
      schema.safeParse({
        station: "coderFix",
        status: "refused",
        refusedFindingIdentityKeys: ["correctness|a.ts:1|claim"],
        cargoPointer: "artifacts/refuse.json",
      }).success,
    ).toBe(true);
  });
});

describe("#924 session lost degrades to fresh (run survives)", () => {
  it("classifyResumeError distinguishes dead sessions from other failures", () => {
    expect(
      classifyResumeError(
        new Error('resumeSession "sess-coder-s2-924" not found under /tmp/sc'),
      ),
    ).toEqual({ kind: "fresh-run" });
    expect(
      classifyResumeError(new Error("session expired while resuming")),
    ).toEqual({ kind: "fresh-run" });
    // Non-dead errors still propagate (must not mask SOE / auth as fresh).
    expect(
      classifyResumeError(new Error("401 unauthorized on resume")),
    ).toEqual({ kind: "propagate" });
  });
});
