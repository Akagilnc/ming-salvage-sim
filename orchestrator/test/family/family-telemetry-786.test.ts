/** #786 — family worker dispatch must produce the same telemetry sidecar as slices. */

import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { afterEach, describe, expect, it, vi } from "vitest";
import * as sc from "@ai-hero/sandcastle";

import { dispatchFamilyWorkerWithMonitor } from "../../src/family/dispatchFamilyWorker.js";
import { runFamily } from "../../src/family/runner.js";
import {
  RealFamilyBackend,
  type MergerAuth,
} from "../../src/family/realFamilyBackend.js";
import { resolveRouteModels, routeSmokeEntries } from "../../src/modelRoutes.js";
import { skeletonReviewLoopWorkerResult } from "../../src/reviewLoopOutcome.js";
import {
  clearTelemetryRunEnvironment,
  readTelemetryRecords,
  type TelemetryCollectRecord,
  type TelemetryDispatchRecord,
  type TelemetryEnvironmentRecord,
  type TelemetryReviewRoundRecord,
} from "../../src/telemetry.js";
import type {
  Backend,
  DispatchContext,
  IssueMeta,
  IssueSnapshot,
  StepOutput,
  WorkerResult,
  WorkerSpec,
  WorktreeHandle,
} from "../../src/types.js";
import type {
  FamilyBackend,
  FamilyLedgerEntry,
  FamilyVerifyResult,
  MergeRequest,
} from "../../src/family/types.js";

const tempDirs: string[] = [];
const here = dirname(fileURLToPath(import.meta.url));
const realPromptsDir = join(here, "..", "..", "prompts");
const realSoulsDir = join(here, "..", "..", "image", "souls");

afterEach(() => {
  clearTelemetryRunEnvironment();
  for (const dir of tempDirs.splice(0)) {
    rmSync(dir, { recursive: true, force: true });
  }
});

function tempDir(prefix: string): string {
  const dir = mkdtempSync(join(tmpdir(), prefix));
  tempDirs.push(dir);
  return dir;
}

function smokedRoute() {
  const base = resolveRouteModels("normal", {});
  const smoke = Object.fromEntries(
    routeSmokeEntries(base).map((entry) => [
      entry.key,
      {
        state: "passed" as const,
        at: new Date().toISOString(),
        cliVersion: `cli-${entry.slug}`,
      },
    ]),
  );
  return resolveRouteModels("normal", {}, {}, smoke);
}

function familySpec(kind: WorkerSpec["kind"]): WorkerSpec {
  return {
    id: kind === "cmr" ? "S3" : "S9",
    kind,
    role: kind === "cmr" ? "reviewer" : "verify",
    host: "codex",
    session: "fresh",
    contextRetention: "clean",
    promptFile: `${kind}.md`,
    completionSignal: `<${kind}>`,
    maxIter: 1,
    model: "gpt-5.6-terra",
    soul: kind === "cmr" ? "cmr" : "verify",
    toolchain: [],
  };
}

function resultFor(kind: WorkerSpec["kind"]): WorkerResult {
  if (kind === "cmr") {
    return { kind: "failed", reason: "provider returned HTTP Error 429" };
  }
  if (kind === "verify") {
    throw new Error("stream disconnect while collecting verify output");
  }
  return {
    kind: "completed",
    output: { kind: "coder", committed: true, commitsAdded: 1 },
    sessionId: `family-${kind}-session`,
  };
}

async function waitForEnvironment(ledgerDir: string): Promise<TelemetryEnvironmentRecord | undefined> {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    const environment = readTelemetryRecords(ledgerDir).find(
      (record): record is TelemetryEnvironmentRecord => record.phase === "environment",
    );
    if (environment !== undefined) return environment;
    await new Promise<void>((resolve) => setTimeout(resolve, 5));
  }
  return undefined;
}

/** Strong-leg set so production final CMR floor admits the green verdict. */
const COMPLETE_CMR_LEGS = ["opus", "gpt-5.6-sol", "agy"] as const;
const FAMILY_HEAD = "head-809-sidecar";

/**
 * Production-path family backend for the durable dual-run shape: records every
 * DispatchContext the spine hands the unified seam (including runner-minted
 * runId). Does not accept a caller-supplied runId — runFamily must mint it.
 */
class FamilyTelemetryBackend implements FamilyBackend {
  readonly ctxs: DispatchContext[] = [];
  readonly ledger: FamilyLedgerEntry[] = [];

  constructor(private readonly durableTelemetryDir: string) {}

  async mergeChildIntoFamilyBase(_child: MergeRequest): Promise<{ familyHead: string }> {
    throw new Error("family telemetry dual-run uses an empty epic (no children)");
  }

  async appendFamilyLedger(entry: FamilyLedgerEntry): Promise<void> {
    this.ledger.push(entry);
  }

  async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
    return this.ledger;
  }

  async readFamilyHead(): Promise<string> {
    return FAMILY_HEAD;
  }

  resolveTelemetryDir(): string {
    return this.durableTelemetryDir;
  }

  async installTelemetryRunEnvironment(): Promise<void> {}

  async runFamilyVerify(): Promise<FamilyVerifyResult> {
    return { ok: true };
  }


  async dispatchWorker(spec: WorkerSpec, ctx: DispatchContext): Promise<WorkerResult> {
    this.ctxs.push(ctx);
    if (spec.kind === "cmr") {
      const cmrPass = ctx.cmrPass ?? "correctness";
      return {
        kind: "completed",
        output: {
          kind: "cmr",
          cmrPass,
          converged: true,
          findingsCount: 0,
          successfulLegs: [...COMPLETE_CMR_LEGS],
          claimedFixedFindingIdentityKeys: [],
          priorFindingDispositions: [],
          evidencePaths: [`cmr/${cmrPass}.json`],
        },
      };
    }
    if (spec.kind === "ship") {
      return {
        kind: "completed",
        output: {
          kind: "ship",
          branch: ctx.familyBase ?? "family/809-sidecar",
          pr: "pr://family/809-sidecar",
          prHead: FAMILY_HEAD,
          status: "pr_opened",
        },
      };
    }
    const reviewLoop = skeletonReviewLoopWorkerResult(spec.kind);
    if (reviewLoop !== undefined) return reviewLoop;
    throw new Error(`unexpected family worker ${spec.kind}`);
  }
}

/**
 * Empty-epic family runs only call smokeModelRoute on the single-slice backend
 * (no children → no resume/runStep). Implements Backend so the test stays
 * type-safe without `as unknown as Backend`.
 */
class SmokeOnlySingleSliceBackend implements Backend {
  async smokeModelRoute(
    _route: Parameters<Backend["smokeModelRoute"]>[0],
  ): Promise<Awaited<ReturnType<Backend["smokeModelRoute"]>>> {
    return smokedRoute();
  }

  async findResumeState(): Promise<undefined> {
    return undefined;
  }

  async cleanResidue(): Promise<void> {}

  async resumeSession(): Promise<StepOutput> {
    throw new Error("smoke-only single-slice backend: resumeSession unused");
  }

  async fetchIssueMeta(issueNumber: number): Promise<IssueMeta> {
    return {
      number: issueNumber,
      isReadyForAgent: true,
      hasSubIssues: false,
      isClosed: false,
      openBlockedBy: [],
    };
  }

  async fetchIssueSnapshot(issueNumber: number): Promise<IssueSnapshot> {
    return { number: issueNumber, body: "", comments: [], agentBrief: "" };
  }

  async prepareWorktree(issueNumber: number, base: string): Promise<WorktreeHandle> {
    return {
      branch: `feat/issue-${issueNumber}`,
      base,
      path: `/wt/${issueNumber}`,
    };
  }

  async writeSnapshot(): Promise<void> {}

  async runStep(): Promise<StepOutput> {
    throw new Error("smoke-only single-slice backend: runStep unused");
  }

  async push(): Promise<void> {}

  async writeLedger(): Promise<void> {}
}

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

    expect(result.status).toBe("success");
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
    expect(result.status).toBe("success");
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

  it.each([
    ["failed", "failed", { kind: "failed", reason: "worker exited 1" }, "rejected"],
    [
      "malformed outcome after its protocol rewrite",
      "malformed",
      { kind: "malformed", reason: "missing CMR verdict" },
      "accepted",
    ],
    [
      "outcome protocol failure",
      "protocol_failure",
      {
        kind: "outcome_protocol_failure",
        reason: "outcome guard rejected the CMR envelope",
        attempts: 1,
      },
      "accepted",
    ],
  ] as const)("preserves the %s worker verdict when the runner routes it", async (_label, verdict, terminal, finalDisposition) => {
    class RejectedTerminalBackend extends FamilyTelemetryBackend {
      override async dispatchWorker(
        spec: WorkerSpec,
        ctx: DispatchContext,
      ): Promise<WorkerResult> {
        if (spec.kind === "cmr") {
          this.ctxs.push(ctx);
          return terminal;
        }
        return super.dispatchWorker(spec, ctx);
      }
    }

    const durable = join(tempDir("orch-786-protocol-rejected-"), ".ledger-809");
    const result = await runFamily({
      epic: { issue: 809, children: [] },
      familyBackend: new RejectedTerminalBackend(durable),
      singleSliceBackend: new SmokeOnlySingleSliceBackend(),
      familyBase: "family/809-sidecar",
    });

    expect(result.status).not.toBe("success");
    expect(
      readTelemetryRecords(durable).filter(
        (record): record is TelemetryReviewRoundRecord => record.phase === "review_round",
      ),
    ).toContainEqual(
      expect.objectContaining({
        verdict,
        finalDisposition,
      }),
    );
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
          return {
            kind: "completed",
            output: {
              kind: "cmr",
              converged: false,
              successfulLegs: [...COMPLETE_CMR_LEGS],
              evidencePaths: ["cmr/blocking.json"],
              findings: [
                {
                  severity: "medium",
                  category: "correctness",
                  claim_quote: "runner must preserve the blocker",
                  location: "orchestrator/src/family/verifyCmr.ts:2680",
                  suggested_fix: "route it through coder-fix",
                  action: "fix_now",
                },
              ],
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

  it.each([
    ["family CMR", "cmr", "failed", "429-quota"],
    ["family verify", "verify", "thrown", "stream-disconnect"],
  ] as const)(
    "%s writes joined dispatch/collect sidecar rows and the terminal classification",
    async (_label, kind, terminal, errorCategory) => {
      const ledgerDir = join(tempDir(`orch-786-family-${kind}-`), ".ledger");
      const backend = {
        dispatchWorker: async (spec: WorkerSpec): Promise<WorkerResult> => resultFor(spec.kind),
        installTelemetryRunEnvironment: async () => {},
      } as unknown as FamilyBackend;
      const ctx: DispatchContext = {
        familyBase: "feat/family-786",
        stateDir: ledgerDir,
        modelRoute: smokedRoute(),
      };

      if (kind === "verify") {
        await expect(
          dispatchFamilyWorkerWithMonitor(backend, familySpec(kind), ctx),
        ).rejects.toThrow(/stream disconnect/);
      } else {
        await dispatchFamilyWorkerWithMonitor(backend, familySpec(kind), ctx);
      }

      expect(await waitForEnvironment(ledgerDir)).toBeDefined();
      const records = readTelemetryRecords(ledgerDir);
      const dispatch = records.find(
        (record): record is TelemetryDispatchRecord => record.phase === "dispatch",
      );
      const collect = records.find(
        (record): record is TelemetryCollectRecord => record.phase === "collect",
      );
      expect(dispatch).toBeDefined();
      expect(collect).toMatchObject({
        legId: dispatch?.legId,
        terminal,
        errorCategory,
      });
    },
  );

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

    class TelemetryMergerBackend extends RealFamilyBackend {
      public runMergerAgentForTest() {
        return this.runMergerAgent({
          childIssue: 786,
          childBranch: "feat/child-786",
          // This is the startup-smoked family route. The production merger must
          // preserve it when its environment row is the run's first one.
          modelRoute: smokedRoute(),
        });
      }

      protected override mountMergerAuth(): MergerAuth {
        return { claudeToken: "test-token" };
      }

      protected override prepareMergerOutcomeLanding(): { path: string; sandboxPath: string } {
        const landing = super.prepareMergerOutcomeLanding();
        outcomePath = landing.path;
        return landing;
      }

      protected override async runAgentSandbox(
        _options: Parameters<typeof sc.run>[0],
      ): Promise<Awaited<ReturnType<typeof sc.run>>> {
        if (outcomePath === undefined) throw new Error("missing merger outcome landing");
        writeFileSync(outcomePath, JSON.stringify({ resolved: true }), "utf8");
        return {
          completionSignal: "MERGER_STEP_COMPLETE",
          stdout: "<merger>{}</merger>",
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
  });

  it("schedules the lazy environment stamp even when the spawn callback throws", async () => {
    const ledgerDir = join(tempDir("orch-786-family-callback-"), ".ledger");
    const backend = {
      resolveCliMonitorDispatch: (spec: WorkerSpec) => ({
        command: process.execPath,
        args: ["-e", "setTimeout(() => process.exit(0), 50)"],
        logDir: ledgerDir,
        poolId: `codex/${spec.model}`,
        completionSignal: spec.completionSignal,
        stepId: spec.id,
      }),
      awaitMonitoredCliWorker: async (): Promise<WorkerResult> => ({
        kind: "completed",
        output: { kind: "coder", committed: true, commitsAdded: 1 },
      }),
      installTelemetryRunEnvironment: async () => {},
    } as unknown as FamilyBackend;

    await expect(
      dispatchFamilyWorkerWithMonitor(
        backend,
        familySpec("cmr"),
        {
          familyBase: "feat/family-786",
          stateDir: ledgerDir,
          modelRoute: smokedRoute(),
        },
        undefined,
        {
          onMonitorHandleSpawned: async () => {
            throw new Error("ledger persistence failed");
          },
        },
      ),
    ).rejects.toThrow(/ledger persistence failed/);

    expect(await waitForEnvironment(ledgerDir)).toBeDefined();
  });

  it("records first output from a monitored family CLI worker", async () => {
    const ledgerDir = join(tempDir("orch-786-family-first-output-"), ".ledger");
    const backend = {
      resolveCliMonitorDispatch: (spec: WorkerSpec) => ({
        command: process.execPath,
        args: ["-e", "process.stdout.write('family worker output\\n')"],
        logDir: ledgerDir,
        poolId: `codex/${spec.model}`,
        completionSignal: spec.completionSignal,
        stepId: spec.id,
      }),
      awaitMonitoredCliWorker: async (): Promise<WorkerResult> => ({
        kind: "completed",
        output: { kind: "coder", committed: true, commitsAdded: 1 },
      }),
      installTelemetryRunEnvironment: async () => {},
    } as unknown as FamilyBackend;

    await dispatchFamilyWorkerWithMonitor(backend, familySpec("cmr"), {
      familyBase: "feat/family-786",
      stateDir: ledgerDir,
      modelRoute: smokedRoute(),
    });

    const collect = readTelemetryRecords(ledgerDir).find(
      (record): record is TelemetryCollectRecord => record.phase === "collect",
    );
    expect(collect?.first_output_at).not.toBeNull();
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
