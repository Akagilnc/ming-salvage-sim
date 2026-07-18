/**
 * #1006 — family baseline health gate (admission hot-check member).
 *
 * Placement: after route preflight + smoke-k + family base cut, before fan-out.
 * Semantics: smoke checks the *people* (route/auth can work); this gate checks
 * the *worksite* (family base is healthy under the worker container class).
 *
 * Three-question self-check (once-per-campaign full cost vs N duplicate fixes):
 *   1. Probability — real: #969 five children each hit the same base red
 *      (`/dev/stdin` os error 6) that host/CI greens hid.
 *   2. Severity — high: N independent duplicate fixes + merger conflict tax.
 *   3. Downstream fallback — wave S3 full gates catch it only after wasted
 *      fan-out; no free downstream that prevents the structural waste.
 *
 * Hard constraint (owner): production full must run inside the same worker
 * image / container class as coder workers — never host `npm test` alone.
 */

import { shWithClock } from "./externalCall.js";

/** Outcome of one canonical full suite invocation. */
export type BaselineFullTestResult =
  | { readonly ok: true }
  | {
      readonly ok: false;
      readonly exitCode: number;
      readonly output: string;
      readonly failedTests?: ReadonlyArray<string>;
    };

export type BaselineHealthAdmission =
  | { readonly kind: "ready"; readonly fixAttempts: number }
  | {
      readonly kind: "stop";
      readonly escalation: { readonly reason: string; readonly diagnosis: string };
      readonly failure: Extract<BaselineFullTestResult, { ok: false }>;
      readonly fixAttempts: number;
    };

export type BaselineFixAttemptResult = {
  readonly attempted: boolean;
  readonly summary?: string;
};

/**
 * One optional baseline fix round (owner shape: red → at most one fix → recheck).
 * Production may inject a real fixer dispatch; tests inject controlled outcomes.
 * Absence ⇒ fail-closed immediately on first red (报错 path, also owner-accepted).
 */
export type BaselineFixAttempt = (
  failure: Extract<BaselineFullTestResult, { ok: false }>,
) => Promise<BaselineFixAttemptResult>;

export type BaselineFullTestRunner = () => Promise<BaselineFullTestResult>;

export interface AdmitBaselineHealthInput {
  readonly runFullTests: BaselineFullTestRunner;
  /** At most one attempt; never looped. */
  readonly tryFix?: BaselineFixAttempt;
}

/** Suggest filing a single pre-fix ticket rather than N parallel child fixes. */
export function formatBaselineHealthFailurePackage(
  failure: Extract<BaselineFullTestResult, { ok: false }>,
): string {
  const tests =
    failure.failedTests !== undefined && failure.failedTests.length > 0
      ? failure.failedTests.join(", ")
      : "(see full output — parser found no individual test paths)";
  const outputTail = failure.output.trim();
  const clipped =
    outputTail.length > 4000 ? `${outputTail.slice(-4000)}\n…(truncated)` : outputTail;
  return [
    "family baseline health gate: canonical full suite RED on family base before fan-out",
    `failed tests: ${tests}`,
    `exit code: ${failure.exitCode}`,
    "baseline disease is pre-family — do NOT fan out N children to each re-fix it",
    "file one single pre-fix ticket (前置修复票) against the family base / main, then re-admit",
    "--- full test output ---",
    clipped,
  ].join("\n");
}

/**
 * Pure admission court for the baseline health gate.
 * Green → ready. Red → optional one fix + recheck; still red → stop package.
 */
export async function admitBaselineHealth(
  input: AdmitBaselineHealthInput,
): Promise<BaselineHealthAdmission> {
  const first = await input.runFullTests();
  if (first.ok) {
    return { kind: "ready", fixAttempts: 0 };
  }

  if (input.tryFix === undefined) {
    return stopFromFailure(first, 0);
  }

  await input.tryFix(first);
  const second = await input.runFullTests();
  if (second.ok) {
    return { kind: "ready", fixAttempts: 1 };
  }
  return stopFromFailure(second, 1);
}

function stopFromFailure(
  failure: Extract<BaselineFullTestResult, { ok: false }>,
  fixAttempts: number,
): BaselineHealthAdmission {
  return {
    kind: "stop",
    escalation: {
      reason: "baseline health gate failed",
      diagnosis: formatBaselineHealthFailurePackage(failure),
    },
    failure,
    fixAttempts,
  };
}

/** Inputs for building the production container full-test argv. */
export interface BaselineContainerFullTestRequest {
  readonly imageName: string;
  readonly workingRepo: string;
  readonly familyBase: string;
  readonly verifyCwd: string;
}

/**
 * Production argv for the worker-image full suite.
 * Same image class as coder workers; repo bind-mounted at the host path so
 * paths match the worksite; `npm test` runs *inside* the container — never as
 * a bare host invocation (owner hard constraint: no lying host greens).
 */
export function buildBaselineContainerFullTestArgv(
  req: BaselineContainerFullTestRequest,
): string[] {
  // Checkout family base then run the project's canonical full entry.
  // `npm test` is the orchestrator full gate (typecheck + vitest run).
  const remoteCmd = [
    `git -C ${shellSingleQuote(req.workingRepo)} checkout --quiet ${shellSingleQuote(req.familyBase)}`,
    "npm test",
  ].join(" && ");
  return [
    "docker",
    "run",
    "--rm",
    "-v",
    `${req.workingRepo}:${req.workingRepo}`,
    "-w",
    req.verifyCwd,
    req.imageName,
    "bash",
    "-lc",
    remoteCmd,
  ];
}

function shellSingleQuote(value: string): string {
  return `'${value.replace(/'/g, `'\\''`)}'`;
}

/**
 * Heuristic failed-test path extraction from vitest / jest-ish output.
 * Best-effort only — the full output is always retained on the failure package.
 */
export function extractFailedTestPaths(output: string): string[] {
  const found = new Set<string>();
  for (const line of output.split(/\r?\n/)) {
    const fail = /^\s*(?:FAIL|×|x)\s+(\S+\.test\.\w+)/i.exec(line);
    if (fail?.[1]) {
      found.add(fail[1]);
      continue;
    }
    const pathOnly = /(\S+\/\S+\.test\.\w+)/.exec(line);
    if (pathOnly?.[1] && /FAIL|failed|Error/i.test(line)) {
      found.add(pathOnly[1]);
    }
  }
  return [...found];
}

export type BaselineSh = (
  file: string,
  args: ReadonlyArray<string>,
  opts?: { readonly cwd?: string; readonly timeoutMs?: number },
) => string;

/**
 * Production runner: docker worker image + mounted family clone + `npm test`.
 * Throws are mapped to ok:false so admission stays fail-closed.
 */
export async function runBaselineFullTestsInWorkerContainer(
  req: BaselineContainerFullTestRequest,
  sh: BaselineSh = defaultBaselineSh,
): Promise<BaselineFullTestResult> {
  const argv = buildBaselineContainerFullTestArgv(req);
  const [file, ...args] = argv;
  if (file === undefined) {
    return {
      ok: false,
      exitCode: 1,
      output: "baseline health gate: empty container argv",
    };
  }
  try {
    sh(file, args, {
      // Full suite once per campaign — generous wall; not the 15s probe budget.
      timeoutMs: 30 * 60 * 1000,
    });
    return { ok: true };
  } catch (err) {
    const output = err instanceof Error ? err.message : String(err);
    const exitCode =
      err !== null &&
      typeof err === "object" &&
      "status" in err &&
      typeof (err as { status?: unknown }).status === "number"
        ? ((err as { status: number }).status as number)
        : 1;
    const failedTests = extractFailedTestPaths(output);
    return {
      ok: false,
      exitCode: exitCode === 0 ? 1 : exitCode,
      output,
      ...(failedTests.length > 0 ? { failedTests } : {}),
    };
  }
}

function defaultBaselineSh(
  file: string,
  args: ReadonlyArray<string>,
  opts?: { readonly cwd?: string; readonly timeoutMs?: number },
): string {
  return shWithClock(file, [...args], {
    ...(opts?.cwd !== undefined ? { cwd: opts.cwd } : {}),
    ...(opts?.timeoutMs !== undefined ? { timeoutMs: opts.timeoutMs } : {}),
  });
}
