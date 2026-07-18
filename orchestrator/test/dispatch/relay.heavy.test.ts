import {
  execFileSync,
  existsSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
  tmpdir,
  join,
  afterEach,
  describe,
  expect,
  it,
  vi,
  CODER_ROSTER,
  lookupCoderRosterEntry,
  resolveCoderRecOrder,
  selectCoderRecEntry,
  modelIdForSlug,
  DEFAULT_PARK_THRESHOLD_MS,
  DEFAULT_POOL_MODELS,
  billingPoolFromQuotaPool,
  buildDefaultBillingPools,
  decideParkOrRelay,
  hasLiveRelayBaton,
  resolveRelayPools,
  selectCapacityRelayBaton,
  selectNextRelayBaton,
  BillingPoolEntry,
  BillingPoolId,
  PoolTable,
  MAX_RELAY_HANDOFFS,
  applyResourceFailureHandoff,
  buildRelayHandoffLedgerEntry,
  canRelayHandoff,
  CapacityRelayError,
  countRelayHandoffsInLedger,
  forkQuotaWallAt683Point,
  isCapacityRelayError,
  isRelayChainReadyForReviewGate,
  renderEphemeralRelayBrief,
  resumeRelayFromLedger,
  RelayHandoffLedgerEvent,
  QuotaWaitForResetError,
  buildCliMonitorSpawnSpec,
  dispatchWorkerWithMonitor,
  legacyDispatchWorker,
  runOrchestrator,
  skeletonReviewLoopWorkerResult,
  Backend,
  DispatchContext,
  IssueMeta,
  PersistentLedgerEntry,
  ResumeState,
  StepSpec,
  StepOutput,
  WorkerResult,
  WorkerSpec,
  WorktreeHandle,
  writeRoutePreset,
} from "./relay.shared.js";

describe("#787 capacity relay", () => {
  const now = new Date("2026-07-11T12:00:00.000Z");

  it.each(["S3", "S6"] as const)(
    "uses the reviewer pool and next reviewer baton for first-leg %s capacity",
    async (capacityStep) => {
      const worktree: WorktreeHandle = {
        branch: `feat/787-${capacityStep.toLowerCase()}-capacity-test`,
        base: "main",
        path: mkdtempSync(join(tmpdir(), "relay-787-reviewer-capacity-")),
      };
      const reviewerModels: string[] = [];
      const blockingFinding = {
        severity: "medium" as const,
        category: "correctness",
        claim_quote: "needs one repair pass",
        location: "runner.ts:1",
        suggested_fix: "repair it",
        action: "fix_now" as const,
      };
      class ReviewerCapacityBackend implements Backend {
        async smokeModelRoute(route: any): Promise<any> {
          const { smokeRouteModels } = await import("../../src/modelRoutes.js");
          return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
        }
        async findResumeState(): Promise<undefined> { return undefined; }
        async resumeSession(): Promise<StepOutput> {
          return { kind: "coder", committed: true, commitsAdded: 1 };
        }
        async fetchIssueMeta(n: number): Promise<IssueMeta> {
          return {
            number: n,
            isReadyForAgent: true,
            hasSubIssues: false,
            isClosed: false,
            openBlockedBy: [],
            body: "Coder-Rec: grok-4.5 → terra@med → luna@med",
          };
        }
        async prepareWorktree(): Promise<WorktreeHandle> { return worktree; }
        async runStep(): Promise<StepOutput> {
          return { kind: "coder", committed: true, commitsAdded: 1 };
        }
        async writeLedger(): Promise<void> {}
        async dispatchWorker(spec: WorkerSpec): Promise<WorkerResult> {
          if ((spec.kind === "reviewer" || spec.kind === "verify")) {
            reviewerModels.push(`${spec.id}:${spec.model}`);
            if (spec.id === capacityStep && spec.model === "gpt-5.6-terra") {
              return { kind: "failed", reason: "Selected model is at capacity" };
            }
            if (spec.id === "S3" && capacityStep === "S6") {
              return {
                kind: "completed",
                output: { kind: "reviewer", findings: [blockingFinding], findingsCount: 1, fixPacketBody: "fixture residual authored body" },
              };
            }
            if (spec.id === "S6" && capacityStep === "S6") {
              return {
                kind: "completed",
                output: { kind: "judge", status: "converged" },
              };
            }
            return { kind: "completed", output: { kind: "judge", status: "converged" } };
          }
          if (spec.kind === "coder") {
            return {
              kind: "completed",
              output: { kind: "coder", committed: true, commitsAdded: 1 },
            };
          }
          if (spec.kind === "ship") {
            return {
              kind: "completed",
              output: { kind: "ship", branch: worktree.branch, status: "pushed" },
            };
          }
          const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
          if (skeleton !== undefined) return skeleton;
          return {
            kind: "completed",
            output: { kind: "coder", committed: true, commitsAdded: 1 },
          };
        }
      }

      const presetPath = writeRoutePreset("relay-reviewer-cap", {
        coder: "grok-4.5",
        verify: "gpt-5.6-terra",
      });
      vi.stubEnv("ORCHESTRATOR_ROUTE_PRESETS_PATH", presetPath);
      vi.stubEnv("ORCHESTRATOR_ROUTE", "relay-reviewer-cap");
      try {
        const result = await runOrchestrator({
          issueNumber: 787,
          backend: new ReviewerCapacityBackend(),
          now: () => now,
          // Explicit pools so capacity relay has a baton after terra walls.
          relayPools: [
            {
              id: "grok-build",
              status: "live",
              parkThresholdMs: DEFAULT_PARK_THRESHOLD_MS,
              models: ["grok-4.5"],
            },
            {
              id: "codex-5h",
              status: "live",
              parkThresholdMs: DEFAULT_PARK_THRESHOLD_MS,
              models: ["terra@med", "luna@med"],
            },
          ],
          family: {
            parentIssue: 686,
            familyBase: "feat/686-family-base",
            mergedBlockers: [],
          },
        });

        expect(result.status, JSON.stringify(result, null, 2)).not.toBe("error");
        // Capacity on terra must relay to another codex seat (luna) and continue.
        expect(
          reviewerModels.filter((model) => model.startsWith(`${capacityStep}:`)),
        ).toEqual([
          `${capacityStep}:gpt-5.6-terra`,
          `${capacityStep}:gpt-5.6-terra`,
          `${capacityStep}:gpt-5.6-luna`,
        ]);
        const handoff = result.stepLedger.find(
          (entry) =>
            entry.event === "relay_baton_handoff" &&
            entry.step === capacityStep &&
            entry.toModelId === "luna@med",
        );
        expect(handoff).toMatchObject({
          trigger: "capacity",
          toPool: "codex-5h",
        });
        expect(handoff).toMatchObject({ toModelId: "luna@med" });
      } finally {
        // #936: route preset via vi.stubEnv; cleaned by afterEach
        rmSync(worktree.path, { recursive: true, force: true });
      }
    },
  );

});

/**
 * #686 R2 — production-seam fixes from fresh reviewer (P0–P3).
 */
describe("#686 R2 production seams", () => {
  const NOW = new Date("2026-07-10T12:00:00.000Z");

  it("P1: free-log decision_gate is not a host fate channel (#937 ID-007)", async () => {
    const tmp = mkdtempSync(join(tmpdir(), "relay-826-decision-gate-"));
    const rawDecisionGate = '{"decision_gate":{},"unexpected_cargo":[1,2,3]}';
    const workerLog = `<relay>${rawDecisionGate}</relay>`;
    const WORKER_SESSION_ID = "relay-826-worker-session";
    const backend = {
      resolveCliMonitorDispatch: () => ({
        command: process.execPath,
        args: ["-e", `console.log(${JSON.stringify(workerLog)})`],
        logDir: tmp,
        poolId: "grok-build",
        stepId: "S2",
        readInstanceId: () => "relay-826-test",
      }),
      async awaitMonitoredCliWorker(): Promise<WorkerResult> {
        return {
          kind: "completed",
          output: { kind: "coder", committed: true, commitsAdded: 1 },
          sessionId: WORKER_SESSION_ID,
        };
      },
    } as unknown as Backend;
    const spec: WorkerSpec = {
      id: "S2",
      kind: "coder",
      role: "coder",
      host: "codex",
      session: "fresh",
      contextRetention: "retain",
      promptFile: "coder.md",
      maxIter: 1,
      model: "grok-4.5",
      soul: "coder",
      toolchain: [],
    };
    try {
      await expect(
        dispatchWorkerWithMonitor(backend, spec, {}, undefined, {
          monitorDeps: { readInstanceId: () => "relay-826-test" },
        }),
      ).resolves.toMatchObject({
        result: {
          kind: "completed",
          sessionId: WORKER_SESSION_ID,
        },
      });
    } finally {
      rmSync(tmp, { recursive: true, force: true });
    }
  });

});
