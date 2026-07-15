/**
 * #928 — completion-signal retirement.
 *
 * Completion = clean exit + legal sidecar/typed envelope. Monitor liveness is
 * heartbeat/log activity only. No StepSpec/WorkerSpec/monitor handle carries a
 * completionSignal field; prompts must not require *_STEP_COMPLETE sentinels.
 */

import { existsSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import {
  isMissingMonitorSidecarResult,
  workerResultFromMonitorSidecar,
} from "../../src/cliMonitorHooks.js";
import { verifyWorkerSpec, fixerWorkerSpec, docReleaseWorkerSpec } from "../../src/dispatchWorker.js";
import {
  cmrWorkerSpec,
  familyCoderFixWorkerSpec,
  familyShipWorkerSpec,
} from "../../src/family/dispatchFamilyWorker.js";
import { stepSpecsForRoute } from "../../src/runner.js";
import { resolveActiveModelRoute } from "../../src/modelRoutes.js";
import { STATION_IDS } from "../../src/stationReceiptContracts.js";
import type { WorkerMonitorHandle, WorkerSpec } from "../../src/types.js";
import {
  validateMonitorHandle,
  isWorkerIdle,
  readLogActivity,
} from "../../src/workerMonitor.js";

const PROMPTS_DIR = join(import.meta.dirname, "../../prompts");

function baseHandle(
  overrides: Partial<WorkerMonitorHandle> = {},
): WorkerMonitorHandle {
  return {
    pid: 1,
    logPath: "/tmp/928-worker.log",
    poolId: "test/pool",
    stepId: "S2",
    dispatchedAt: "2026-07-15T00:00:00.000Z",
    instanceId: "test-instance",
    ...overrides,
  };
}

describe("#928 completion-signal retirement", () => {
  describe("specs carry no completionSignal; all seats maxIter=1", () => {
    const route = resolveActiveModelRoute({});
    const steps = stepSpecsForRoute(route);

    const seats: Array<{ label: string; spec: { maxIter: number } & object }> = [
      { label: "S2 coder", spec: steps.S2 },
      { label: "S3 judge", spec: steps.S3 },
      { label: "S5 coderFix", spec: steps.S5 },
      { label: "S6 judge resume", spec: steps.S6 },
      { label: "family cmr", spec: cmrWorkerSpec("fresh", "correctness", route) },
      { label: "family coder-fix", spec: familyCoderFixWorkerSpec(route) },
      { label: "family ship", spec: familyShipWorkerSpec(route) },
      { label: "verify", spec: verifyWorkerSpec(route) },
      { label: "fixer", spec: fixerWorkerSpec(route) },
      { label: "docRelease", spec: docReleaseWorkerSpec(route) },
    ];

    it.each(seats)("$label is single-iter and has no completionSignal field", ({ spec }) => {
      expect(spec.maxIter).toBe(1);
      expect(Object.prototype.hasOwnProperty.call(spec, "completionSignal")).toBe(
        false,
      );
      expect((spec as { completionSignal?: unknown }).completionSignal).toBeUndefined();
    });

    it("T2 station set remains the five official envelopes", () => {
      expect([...STATION_IDS]).toEqual([
        "judge",
        "coder",
        "coderFix",
        "familyCoderFix",
        "ship",
      ]);
    });
  });

  describe("completion = exit + legal sidecar (no fake completed)", () => {
    it("exit 0 without a usable sidecar cannot masquerade as completed", () => {
      const dir = mkdtempSync(join(tmpdir(), "orch-928-no-sidecar-"));
      try {
        const result = workerResultFromMonitorSidecar(
          baseHandle({
            pid: process.pid,
            logPath: join(dir, "S2.log"),
            resultPath: join(dir, "S2.result.json"),
          }),
          0,
        );

        expect(result.kind).not.toBe("completed");
        expect(result.kind).toBe("failed");
        if (result.kind === "failed") {
          expect(result.reason).toMatch(/without a WorkerResult sidecar/i);
        }
        expect(isMissingMonitorSidecarResult(result)).toBe(true);
      } finally {
        rmSync(dir, { recursive: true, force: true });
      }
    });

    it("exit 0 + legal sidecar honors the sidecar completed result", () => {
      const dir = mkdtempSync(join(tmpdir(), "orch-928-sidecar-ok-"));
      try {
        const resultPath = join(dir, "S2.result.json");
        writeFileSync(
          resultPath,
          JSON.stringify({
            kind: "completed",
            output: { kind: "coder", committed: true, commitsAdded: 1 },
          }),
          "utf8",
        );

        const result = workerResultFromMonitorSidecar(
          baseHandle({
            pid: process.pid,
            logPath: join(dir, "S2.log"),
            resultPath,
          }),
          0,
        );

        expect(result).toEqual({
          kind: "completed",
          output: { kind: "coder", committed: true, commitsAdded: 1 },
        });
        expect(isMissingMonitorSidecarResult(result)).toBe(false);
      } finally {
        rmSync(dir, { recursive: true, force: true });
      }
    });

    it("non-zero exit without sidecar is failed (negative twin)", () => {
      const dir = mkdtempSync(join(tmpdir(), "orch-928-exit1-"));
      try {
        const result = workerResultFromMonitorSidecar(
          baseHandle({
            pid: process.pid,
            logPath: join(dir, "S2.log"),
            resultPath: join(dir, "S2.result.json"),
          }),
          1,
        );
        expect(result.kind).toBe("failed");
        expect(isMissingMonitorSidecarResult(result)).toBe(true);
      } finally {
        rmSync(dir, { recursive: true, force: true });
      }
    });
  });

  describe("monitor liveness is heartbeat/log activity only", () => {
    it("validateMonitorHandle does not require completionSignal", () => {
      const handle = baseHandle();
      expect(Object.prototype.hasOwnProperty.call(handle, "completionSignal")).toBe(
        false,
      );
      expect(validateMonitorHandle(handle)).toBe(true);
    });

    it("idle judgment still uses log growth only (PR #917 mechanism)", () => {
      const dir = mkdtempSync(join(tmpdir(), "orch-928-idle-"));
      try {
        const logPath = join(dir, "worker.log");
        writeFileSync(logPath, "line1\n", "utf8");
        const handle = baseHandle({ pid: process.pid, logPath });
        const first = readLogActivity(handle);
        expect(first).toBeDefined();
        writeFileSync(logPath, "line1\nline2\n", "utf8");
        expect(isWorkerIdle(handle, 60_000, first!)).toBe(false);
        const stale = readLogActivity(handle)!;
        expect(isWorkerIdle(handle, 0, stale)).toBe(true);
      } finally {
        rmSync(dir, { recursive: true, force: true });
      }
    });
  });

  describe("prompts: no STEP_COMPLETE / multi-iter signal contract", () => {
    const promptFiles = readdirSync(PROMPTS_DIR).filter((f) => f.endsWith(".md"));

    it("prompts dir is present", () => {
      expect(existsSync(PROMPTS_DIR)).toBe(true);
      expect(promptFiles.length).toBeGreaterThan(0);
    });

    it.each(promptFiles)("%s does not require *_STEP_COMPLETE", (file) => {
      const text = readFileSync(join(PROMPTS_DIR, file), "utf8");
      expect(text).not.toMatch(/_STEP_COMPLETE/);
      expect(text).not.toMatch(/completionSignal/);
      expect(text).not.toMatch(/print .*COMPLETE on its own/i);
    });

    it("production worker specs never embed a completionSignal property", () => {
      const route = resolveActiveModelRoute({});
      const specs: WorkerSpec[] = [
        familyShipWorkerSpec(route),
        familyCoderFixWorkerSpec(route),
        cmrWorkerSpec("fresh", "completeness", route),
        verifyWorkerSpec(route),
        fixerWorkerSpec(route),
        docReleaseWorkerSpec(route),
      ];
      for (const spec of specs) {
        expect(JSON.stringify(spec)).not.toMatch(/completionSignal/);
        expect(spec.maxIter).toBe(1);
      }
    });
  });
});
