/** #786 — family worker dispatch must produce the same telemetry sidecar as slices. */

import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { afterEach, describe, expect, it, vi } from "vitest";
import * as sc from "@ai-hero/sandcastle";

import { dispatchFamilyWorkerWithMonitor } from "../../src/family/dispatchFamilyWorker.js";
import {
  RealFamilyBackend,
  type MergerAuth,
} from "../../src/family/realFamilyBackend.js";
import { resolveRouteModels, routeSmokeEntries } from "../../src/modelRoutes.js";
import {
  clearTelemetryRunEnvironment,
  readTelemetryRecords,
  type TelemetryCollectRecord,
  type TelemetryDispatchRecord,
  type TelemetryEnvironmentRecord,
} from "../../src/telemetry.js";
import type { DispatchContext, WorkerResult, WorkerSpec } from "../../src/types.js";
import type { FamilyBackend } from "../../src/family/types.js";

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

describe("#786 family dispatch telemetry", () => {
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
});
