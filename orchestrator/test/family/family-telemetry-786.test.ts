/** #786 — family worker dispatch must produce the same telemetry sidecar as slices. */

import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { afterEach, describe, expect, it } from "vitest";

import { dispatchFamilyWorkerWithMonitor } from "../../src/family/dispatchFamilyWorker.js";
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
    ["merger", "merge", "completed", null],
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
});
