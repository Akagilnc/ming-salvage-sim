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
  silenceWholeMinutes,
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

    it("T2 station set remains the seven official envelopes", () => {
      // #919 T2 expansion: merger + onlineReview join the five base stations.
      expect([...STATION_IDS]).toEqual([
        "judge",
        "coder",
        "coderFix",
        "familyCoderFix",
        "ship",
        "merger",
        "onlineReview",
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

    it("non-zero exit with completed sidecar cannot masquerade as completed", () => {
      const dir = mkdtempSync(join(tmpdir(), "orch-928-exit1-completed-"));
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
          1,
        );
        expect(result.kind).toBe("failed");
        if (result.kind === "failed") {
          expect(result.reason).toMatch(/clean exit required/i);
        }
        expect(isMissingMonitorSidecarResult(result)).toBe(false);
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

    it("log activity is observational; silenceWholeMinutes never invents kill (#937)", () => {
      const dir = mkdtempSync(join(tmpdir(), "orch-928-idle-"));
      try {
        const logPath = join(dir, "worker.log");
        writeFileSync(logPath, "line1\n", "utf8");
        const handle = baseHandle({ pid: process.pid, logPath });
        const first = readLogActivity(handle);
        expect(first).toBeDefined();
        writeFileSync(logPath, "line1\nline2\n", "utf8");
        const second = readLogActivity(handle)!;
        expect(second.sizeBytes).toBeGreaterThan(first!.sizeBytes);
        expect(silenceWholeMinutes(second.mtimeMs - 30_000, second.mtimeMs)).toBe(0);
        expect(silenceWholeMinutes(second.mtimeMs - 120_000, second.mtimeMs)).toBe(2);
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

  describe("sandcastle sc.run: explicit completionSignal disable (not omit)", () => {
    /**
     * Fact (node_modules/@ai-hero/sandcastle):
     *   if (options.completionSignal === undefined)
     *     completionSignals = ["<promise>COMPLETE</promise>"];  // DEFAULT
     *   else if (Array.isArray(options.completionSignal))
     *     completionSignals = options.completionSignal;        // [] disables
     * Omitting the option is therefore NOT off — production must pass [].
     */
    it("documents sandcastle: omit defaults ON; empty array disables", () => {
      const sandcastleIndex = join(
        import.meta.dirname,
        "../../node_modules/@ai-hero/sandcastle/dist/index.js",
      );
      expect(existsSync(sandcastleIndex)).toBe(true);
      const src = readFileSync(sandcastleIndex, "utf8");
      expect(src).toMatch(
        /DEFAULT_COMPLETION_SIGNAL\s*=\s*"<promise>COMPLETE<\/promise>"/,
      );
      expect(src).toMatch(
        /options\.completionSignal\s*===\s*void 0[\s\S]*DEFAULT_COMPLETION_SIGNAL/,
      );
      // Array branch assigns through — empty array yields zero matchable signals.
      expect(src).toMatch(
        /Array\.isArray\(options\.completionSignal\)[\s\S]*completionSignals\s*=\s*options\.completionSignal/,
      );
    });

    it("both production sc.run chokepoints force completionSignal: []", () => {
      const real = readFileSync(
        join(import.meta.dirname, "../../src/realBackend.ts"),
        "utf8",
      );
      const family = readFileSync(
        join(import.meta.dirname, "../../src/family/realFamilyBackend.ts"),
        "utf8",
      );
      const shared = readFileSync(
        join(import.meta.dirname, "../../src/sandboxStreamHeartbeat.ts"),
        "utf8",
      );
      // #919 F2: both backends funnel sc.run through the shared wrap that
      // force-disables the sandcastle default password (omit is NOT off).
      expect(shared).toMatch(/completionSignal:\s*\[\s*\]/);
      expect(shared).toMatch(/function withSandcastleInvokeDefaults/);
      // Must not rely on "no field" / undefined alone at either chokepoint.
      const realInvoke = real.slice(
        real.indexOf("protected async invokeSandcastleRun"),
        real.indexOf("protected async runAgentSandbox"),
      );
      const familyInvoke = family.slice(
        family.indexOf("protected async invokeSandcastleRun"),
        family.indexOf("protected async runAgentSandbox"),
      );
      expect(realInvoke).toMatch(/withSandcastleInvokeDefaults\s*\(/);
      expect(familyInvoke).toMatch(/withSandcastleInvokeDefaults\s*\(/);
    });
  });
});
