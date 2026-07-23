import {
  mkdtempSync,
  rmSync,
  writeFileSync,
  tmpdir,
  dirname,
  join,
  fileURLToPath,
  afterEach,
  describe,
  expect,
  it,
  vi,
  sc,
  dispatchFamilyWorkerWithMonitor,
  runFamily,
  RealFamilyBackend,
  MergerAuth,
  resolveRouteModels,
  routeSmokeEntries,
  skeletonReviewLoopWorkerResult,
  clearTelemetryRunEnvironment,
  readTelemetryRecords,
  TelemetryCollectRecord,
  TelemetryDispatchRecord,
  TelemetryEnvironmentRecord,
  TelemetryReviewRoundRecord,
  Backend,
  DispatchContext,
  IssueMeta,
  StepOutput,
  WorkerResult,
  WorkerSpec,
  WorktreeHandle,
  FamilyBackend,
  FamilyLedgerEntry,
  FamilyVerifyResult,
  MergeRequest,
  buildExplicitLandingLiveHooks,
  tempDirs,
  here,
  realPromptsDir,
  realSoulsDir,
  tempDir,
  smokedRoute,
  familySpec,
  resultFor,
  waitForEnvironment,
  COMPLETE_CMR_LEGS,
  FAMILY_HEAD,
  FamilyTelemetryBackend,
  SmokeOnlySingleSliceBackend,
} from "./telemetry.shared.js";
import { docker } from "@ai-hero/sandcastle/sandboxes/docker";
import { AGY_SOUL_RULES_FILE } from "../../../src/soulInstructions.js";

afterEach(() => {
  clearTelemetryRunEnvironment();
  for (const dir of tempDirs.splice(0)) {
    rmSync(dir, { recursive: true, force: true });
  }
});

describe("#786 family dispatch telemetry", () => {
  it("keeps two full family runner invocations distinct in one durable telemetry sidecar", async () => {
    const durable = join(tempDir("orch-809-family-runner-sidecar-"), ".ledger-809");
    // Separate backends share only the durable sidecar path: each invocation
    // must mint its own run id through production runFamily → runVerifyCmr →
    // dispatchFamilyWorkerWithMonitor. No manual runId is injected here.
    const first = new FamilyTelemetryBackend(durable);
    const second = new FamilyTelemetryBackend(durable);
    const singleSliceBackend = new SmokeOnlySingleSliceBackend();

    await runFamily({
      epic: { issue: 809, children: [] },
      familyBackend: first,
      singleSliceBackend,
      familyBase: "family/809-sidecar",
    });
    await runFamily({
      epic: { issue: 809, children: [] },
      familyBackend: second,
      singleSliceBackend,
      familyBase: "family/809-sidecar",
    });
    await new Promise((resolve) => setImmediate(resolve));

    const firstRunId = first.ctxs[0]?.runId;
    const secondRunId = second.ctxs[0]?.runId;
    expect(first.ctxs.length).toBeGreaterThan(0);
    expect(second.ctxs.length).toBeGreaterThan(0);
    expect(firstRunId).toEqual(expect.any(String));
    expect(secondRunId).toEqual(expect.any(String));
    expect(firstRunId).not.toBe(secondRunId);
    expect(first.ctxs.every((ctx) => ctx.runId === firstRunId)).toBe(true);
    expect(second.ctxs.every((ctx) => ctx.runId === secondRunId)).toBe(true);

    const records = readTelemetryRecords(durable);
    const environments = records.filter(
      (record): record is TelemetryEnvironmentRecord => record.phase === "environment",
    );
    expect(environments.map((record) => record.runId)).toEqual([firstRunId, secondRunId]);
    // Both runs leave more than just the environment stamp — dispatch/collect
    // half-rows must stay readable after the second invocation starts.
    expect(records.filter((r) => r.phase === "dispatch").length).toBeGreaterThanOrEqual(2);
    expect(records.filter((r) => r.phase === "collect").length).toBeGreaterThanOrEqual(2);
    expect(records.some((r) => r.phase === "dispatch" && r.runId === firstRunId)).toBe(true);
    expect(records.some((r) => r.phase === "dispatch" && r.runId === secondRunId)).toBe(true);
    const reviewRounds = records.filter(
      (record): record is TelemetryReviewRoundRecord => record.phase === "review_round",
    );
    expect(reviewRounds).toHaveLength(4);
    expect(reviewRounds.map((record) => record.verdict)).toEqual([
      "converged",
      "converged",
      "converged",
      "converged",
    ]);
    expect(reviewRounds.map((record) => record.findingsBySeverity)).toEqual([
      null,
      null,
      null,
      null,
    ]);
  });

  it("keeps the family flow green when review-round telemetry resolution throws", async () => {
    class ThrowingTelemetryBackend extends FamilyTelemetryBackend {
      override resolveTelemetryDir(): string {
        throw new Error("telemetry directory unavailable");
      }
    }

    const backend = new ThrowingTelemetryBackend(
      join(tempDir("orch-786-review-round-failopen-"), ".ledger-809"),
    );
    const result = await runFamily({
      epic: { issue: 809, children: [] },
      familyBackend: backend,
      singleSliceBackend: new SmokeOnlySingleSliceBackend(),
      familyBase: "family/809-sidecar",
    });

    expect(result.status).toBe("completed");
  });

  it("#876 preserves a green CMR verdict when the reviewer worktree HEAD drifted", async () => {
    class HeadMovingReviewerBackend extends FamilyTelemetryBackend {
      async readFamilyCurrentHead(): Promise<string> {
        return `${FAMILY_HEAD}-reviewer-moved`;
      }
    }

    const durable = join(tempDir("orch-786-review-round-head-advisory-"), ".ledger-809");
    const result = await runFamily({
      epic: { issue: 809, children: [] },
      familyBackend: new HeadMovingReviewerBackend(durable),
      singleSliceBackend: new SmokeOnlySingleSliceBackend(),
      familyBase: "family/809-sidecar",
    });

    // Head drift is advisory routing plumbing (#876), not a durable reject.
    expect(result.status).toBe("completed");
    const reviewRounds = readTelemetryRecords(durable).filter(
      (record): record is TelemetryReviewRoundRecord => record.phase === "review_round",
    );
    expect(reviewRounds.length).toBeGreaterThanOrEqual(1);
    expect(reviewRounds[0]).toMatchObject({
      cmrPass: "completeness",
      verdict: "converged",
      finalDisposition: "accepted",
    });
  });

it("keeps an unknown review-round row when durable abort persistence throws", async () => {
    class ThrowingDurableAbortBackend extends FamilyTelemetryBackend {
      override async appendFamilyLedger(): Promise<void> {
        throw new Error("durable abort ledger unavailable");
      }

      override async dispatchWorker(
        spec: WorkerSpec,
        ctx: DispatchContext,
      ): Promise<WorkerResult> {
        if (spec.kind === "cmr") {
          this.ctxs.push(ctx);
          return { kind: "failed", reason: "provider returned HTTP 429" };
        }
        return super.dispatchWorker(spec, ctx);
      }
    }

    const durable = join(tempDir("orch-786-abort-telemetry-"), ".ledger-809");
    await expect(
      runFamily({
        epic: { issue: 809, children: [] },
        familyBackend: new ThrowingDurableAbortBackend(durable),
        singleSliceBackend: new SmokeOnlySingleSliceBackend(),
        familyBase: "family/809-sidecar",
      }),
    ).rejects.toThrow("durable abort ledger unavailable");

    expect(
      readTelemetryRecords(durable).filter(
        (record): record is TelemetryReviewRoundRecord => record.phase === "review_round",
      ),
    ).toContainEqual(
      expect.objectContaining({
        verdict: "failed",
        finalDisposition: "unknown",
      }),
    );
  });

  it("keeps an unknown review-round row when CMR-reviewed persistence throws", async () => {
    class ThrowingReviewedBackend extends FamilyTelemetryBackend {
      override async appendFamilyLedger(): Promise<void> {
        throw new Error("CMR-reviewed ledger unavailable");
      }

      override async dispatchWorker(
        spec: WorkerSpec,
        ctx: DispatchContext,
      ): Promise<WorkerResult> {
        if (spec.kind === "cmr") {
          this.ctxs.push(ctx);
          // #919 CR: stamp only reads live kind:"judge". Residual kind:"cmr"
          // is not a live verdict signal (maps not_converged). Blocking
          // fixture must mint continue + live dispositions.
          const findings = [
            {
              severity: "medium" as const,
              category: "correctness" as const,
              claim_quote: "runner must preserve the blocker",
              location: "orchestrator/src/family/verifyCmr.ts:2680",
              suggested_fix: "route it through coder-fix",
              action: "fix_now" as const,
            },
          ];
          return {
            kind: "completed",
            output: {
              kind: "judge",
              status: "continue",
              successfulLegs: [...COMPLETE_CMR_LEGS],
              evidencePaths: ["cmr/blocking.json"],
              findings,
              findingDispositions: findings.map((f) => ({
                identityKey: `${f.category}|${f.location}|${f.claim_quote}`,
                action: "live" as const,
              })),
            },
          };
        }
        return super.dispatchWorker(spec, ctx);
      }
    }

    const durable = join(tempDir("orch-786-reviewed-telemetry-"), ".ledger-809");
    await expect(
      runFamily({
        epic: { issue: 809, children: [] },
        familyBackend: new ThrowingReviewedBackend(durable),
        singleSliceBackend: new SmokeOnlySingleSliceBackend(),
        familyBase: "family/809-sidecar",
      }),
    ).rejects.toThrow("CMR-reviewed ledger unavailable");

    expect(
      readTelemetryRecords(durable).filter(
        (record): record is TelemetryReviewRoundRecord => record.phase === "review_round",
      ),
    ).toContainEqual(
      expect.objectContaining({
        verdict: "blocking",
        finalDisposition: "unknown",
      }),
    );
  });

  it("joins the environment stamp before rethrowing a failed family dispatch", async () => {
    const ledgerDir = join(tempDir("orch-786-family-env-on-throw-"), ".ledger");
    let releaseFingerprint!: () => void;
    const fingerprintReleased = new Promise<void>((resolve) => {
      releaseFingerprint = resolve;
    });
    let fingerprintStarted = false;
    let dispatchSettled = false;
    const backend = {
      dispatchWorker: async (): Promise<WorkerResult> => {
        throw new Error("family worker boom");
      },
      installTelemetryRunEnvironment: async () => {
        fingerprintStarted = true;
        await fingerprintReleased;
      },
    } as unknown as FamilyBackend;

    const dispatch = dispatchFamilyWorkerWithMonitor(
      backend,
      familySpec("cmr"),
      { familyBase: "feat/family-786", stateDir: ledgerDir, modelRoute: smokedRoute() },
    );
    void dispatch.then(
      () => {
        dispatchSettled = true;
      },
      () => {
        dispatchSettled = true;
      },
    );

    await vi.waitFor(() => expect(fingerprintStarted).toBe(true));
    expect(dispatchSettled).toBe(false);

    releaseFingerprint();
    await expect(dispatch).rejects.toThrow("family worker boom");
    expect(readTelemetryRecords(ledgerDir).some((record) => record.phase === "environment")).toBe(true);
  });

  it("writes telemetry when the real merger-agent sandbox path runs", async () => {
    const ledgerDir = join(tempDir("orch-786-real-merger-"), ".ledger");
    let outcomePath: string | undefined;
    let runOptions: Parameters<typeof sc.run>[0] | undefined;
    let mergerSpec: Pick<WorkerSpec, "model" | "soul"> | undefined;
    let mergerMounts:
      | ReadonlyArray<{ hostPath: string; sandboxPath: string; readonly?: boolean }>
      | undefined;
    const route = smokedRoute();
    const agyRoute = {
      ...route,
      slots: { ...route.slots, merger: "agy" },
    };

    class TelemetryMergerBackend extends RealFamilyBackend {
  resolveLandingLiveHooks(input: {
    prUrl: string;
    convergedHeadOid: string;
    familyBase: string;
  }) {
    return buildExplicitLandingLiveHooks({
      prUrl: input.prUrl,
      headOid: input.convergedHeadOid,
      remoteBranchName: input.familyBase,
    });
  }

      public runMergerAgentForTest() {
        return this.runMergerAgent({
          childIssue: 786,
          childBranch: "feat/child-786",
          // This is the startup-smoked family route. The production merger must
          // preserve it when its environment row is the run's first one.
          modelRoute: agyRoute,
        });
      }

      protected override mountMergerAuth(): MergerAuth {
        return { agyDir: tempDir("orch-786-merger-agy-auth-") };
      }

      protected override mergerSandbox(
        auth: MergerAuth,
        outcomeLanding: { path: string; sandboxPath: string } | undefined,
        spec: Pick<WorkerSpec, "model" | "soul">,
      ): sc.SandboxProvider {
        mergerSpec = spec;
        const config = this.mergerSandboxConfig(auth, outcomeLanding, spec);
        mergerMounts = config.mounts;
        return docker(config);
      }

      protected override prepareMergerOutcomeLanding(): { path: string; sandboxPath: string } {
        const landing = super.prepareMergerOutcomeLanding();
        outcomePath = landing.path;
        return landing;
      }

      protected override async runAgentSandbox(
        options: Parameters<typeof sc.run>[0],
      ): Promise<Awaited<ReturnType<typeof sc.run>>> {
        runOptions = options;
        if (outcomePath === undefined) throw new Error("missing merger outcome landing");
        writeFileSync(outcomePath, JSON.stringify({ resolved: true }), "utf8");
        return {
          branch: "family/786",
          stdout: "<merger>{}</merger>",
          commits: [],
          iterations: [],
          // Typed T2 merger completed (SO was attached on this seat).
          output: { station: "merger", status: "completed" },
        } as Awaited<ReturnType<typeof sc.run>>;
      }
    }

    const backend = new TelemetryMergerBackend({
      workingRepo: tempDir("orch-786-real-merger-repo-"),
      familyBase: "family/786",
      ledgerDir,
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "test-image",
    });

    await expect(backend.runMergerAgentForTest()).resolves.toEqual({ resolved: true });

    const environment = await waitForEnvironment(ledgerDir);
    expect(environment).toBeDefined();
    expect(environment?.routeSlots).not.toBeNull();
    expect(environment?.routeCmrReviewLegs).not.toBeNull();
    expect(environment?.cliVersions).not.toBeNull();
    const records = readTelemetryRecords(ledgerDir);
    const dispatch = records.find(
      (record): record is TelemetryDispatchRecord => record.phase === "dispatch",
    );
    const collect = records.find(
      (record): record is TelemetryCollectRecord => record.phase === "collect",
    );
    expect(dispatch).toMatchObject({ kind: "merge", issue: 786 });
    expect(collect).toMatchObject({ legId: dispatch?.legId, terminal: "completed" });
    expect(mergerSpec).toMatchObject({ model: "agy", soul: "merger" });
    expect(
      runOptions?.agent.buildPrintCommand({ prompt: "TASK_SENTINEL" } as never)
        .command,
    ).toContain("TASK_SENTINEL");
    expect(mergerMounts).toContainEqual({
      hostPath: join(realSoulsDir, "merger.md"),
      sandboxPath: AGY_SOUL_RULES_FILE,
      readonly: true,
    });
  });

  it("keeps family dispatch alive when resolveTelemetryDir throws", async () => {
    // Symmetric to single-slice telemetry-786 "keeps dispatch alive when
    // resolveTelemetryDir throws" (CodeRabbit #815 / #809): optional chaining
    // only guards missing methods; a throwing family resolveTelemetryDir must
    // degrade telemetry (fallback stateDir), not abort dispatch.
    const ledgerDir = join(tempDir("orch-809-family-resolve-throw-"), ".ledger");
    const backend = {
      dispatchWorker: async (): Promise<WorkerResult> => ({
        kind: "completed",
        output: { kind: "coder", committed: true, commitsAdded: 1 },
        sessionId: "family-809-resolve-throw-session",
      }),
      installTelemetryRunEnvironment: async () => {},
      resolveTelemetryDir: (): string => {
        throw new Error("resolveTelemetryDir boom");
      },
    } as unknown as FamilyBackend;

    const outcome = await dispatchFamilyWorkerWithMonitor(
      backend,
      familySpec("cmr"),
      {
        familyBase: "feat/family-809",
        stateDir: ledgerDir,
        modelRoute: smokedRoute(),
      },
    );

    expect(outcome.result.kind).toBe("completed");
    // Fail-open falls back to stateDir; sidecar may still write there.
    const records = readTelemetryRecords(ledgerDir);
    expect(records.filter((r) => r.phase === "dispatch")).toHaveLength(1);
    expect(records.filter((r) => r.phase === "collect")).toHaveLength(1);
  });
});
