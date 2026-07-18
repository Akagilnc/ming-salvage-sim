/** #786 — family worker dispatch must produce the same telemetry sidecar as slices. */

import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { afterEach, describe, expect, it, vi } from "vitest";
import * as sc from "@ai-hero/sandcastle";

import { dispatchFamilyWorkerWithMonitor } from "../../../src/family/dispatchFamilyWorker.js";
import { runFamily } from "../../../src/family/runner.js";
import {
  RealFamilyBackend,
  type MergerAuth,
} from "../../../src/family/realFamilyBackend.js";
import { resolveRouteModels, routeSmokeEntries } from "../../../src/modelRoutes.js";
import { skeletonReviewLoopWorkerResult } from "../../../src/reviewLoopOutcome.js";
import {
  clearTelemetryRunEnvironment,
  readTelemetryRecords,
  type TelemetryCollectRecord,
  type TelemetryDispatchRecord,
  type TelemetryEnvironmentRecord,
  type TelemetryReviewRoundRecord,
} from "../../../src/telemetry.js";
import type {
  Backend,
  DispatchContext,
  IssueMeta,
  StepOutput,
  WorkerResult,
  WorkerSpec,
  WorktreeHandle,
} from "../../../src/types.js";
import type {

  FamilyBackend,
  FamilyLedgerEntry,
  FamilyVerifyResult,
  MergeRequest,
} from "../../../src/family/types.js";
import { buildExplicitLandingLiveHooks } from "../../../src/family/landing.js";

const tempDirs: string[] = [];
const here = dirname(fileURLToPath(import.meta.url));
const realPromptsDir = join(here, "..", "..", "..", "prompts");
const realSoulsDir = join(here, "..", "..", "..", "image", "souls");

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
    role: "verify",
    host: "codex",
    session: "fresh",
    contextRetention: "clean",
    promptFile: `${kind}.md`,
    maxIter: 1,
    model: "gpt-5.6-terra",
    soul: "verify",
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

  readonly ctxs: DispatchContext[] = [];
  readonly ledger: FamilyLedgerEntry[] = [];

  constructor(private readonly durableTelemetryDir: string) {}

  async mergeChildIntoFamilyBase(_child: MergeRequest): Promise<{ familyHead: string }> {
    throw new Error("family telemetry dual-run uses an empty epic (no children)");
  }
  async resolveMergeConflict(_req?: unknown): Promise<{ familyHead: string }> {
    throw new Error("resolveMergeConflict not used in this test");
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
      // #919 M1/M2: live ship green is typed kind:judge status:converged.
      // Residual findingsCount:0 is unusable (never silent clean / never ship).
      return {
        kind: "completed",
        output: {
          kind: "judge",
          status: "converged",
          cmrPass,
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

  async prepareWorktree(issueNumber: number, base: string): Promise<WorktreeHandle> {
    return {
      branch: `feat/issue-${issueNumber}`,
      base,
      path: `/wt/${issueNumber}`,
    };
  }

  async runStep(): Promise<StepOutput> {
    throw new Error("smoke-only single-slice backend: runStep unused");
  }

  async writeLedger(): Promise<void> {}
}

describe("#786 family dispatch telemetry", () => {

  it.each([
    ["failed", "failed", { kind: "failed", reason: "worker exited 1" }, "rejected"],
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

    expect(result.status).not.toBe("completed");
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

  it("schedules the lazy environment stamp even when the spawn callback throws", async () => {
    const ledgerDir = join(tempDir("orch-786-family-callback-"), ".ledger");
    const backend = {
      resolveCliMonitorDispatch: (spec: WorkerSpec) => ({
        command: process.execPath,
        args: ["-e", "setTimeout(() => process.exit(0), 50)"],
        logDir: ledgerDir,
        poolId: `codex/${spec.model}`,
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

});
