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
 *
 * Sandcastle parity (best-effort this slice): same `imageName`, bind-mount the
 * family worksite at the host path (worker cwd pattern), `HOME=/home/agent`,
 * `OPENCLAW_SESSION=1` (SPAWNED_WORKER_ENV), and `--user agent`. Full agent
 * `sc.run` lifecycle is not required for a pure full-suite probe — no LLM.
 */

import { shWithClock } from "./externalCall.js";
import { shellEscape } from "./shellEscape.js";

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
 * When present but `attempted: false` ⇒ same fail-closed, no recheck burn.
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

/**
 * Production default when no real baseline LLM fixer is wired.
 * Owner shape allows 报错 on red; auto fixer is out of this slice's scope —
 * the one-shot hook is always present so a real {@link BaselineFixAttempt}
 * can be injected later without rewiring the admission court. Never invents green.
 */
export const NOOP_BASELINE_FIX_ATTEMPT: BaselineFixAttempt = async () => ({
  attempted: false,
  summary:
    "baseline auto-fixer not wired this slice — fail-closed after one red (owner-accepted 报错 path)",
});

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
 * Green → ready. Red → optional one fix + recheck; still red / not attempted → stop.
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

  const fix = await input.tryFix(first);
  // attempted:false (noop / declined) → fail-closed on the first red; do not
  // burn a second full suite wall-clock when nothing was changed.
  if (!fix.attempted) {
    return stopFromFailure(first, 0);
  }

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
 *
 * Best-effort sandcastle parity (not full `sc.run`): imageName + worksite
 * bind-mount + `HOME=/home/agent` + `OPENCLAW_SESSION=1` + `--user agent`.
 * Agent auth/soul mounts are irrelevant for a pure `npm test` probe.
 */
export function buildBaselineContainerFullTestArgv(
  req: BaselineContainerFullTestRequest,
): string[] {
  // Checkout family base then run the project's canonical full entry.
  // `npm test` is the orchestrator full gate (typecheck + vitest run).
  const remoteCmd = [
    `git -C ${shellEscape(req.workingRepo)} checkout --quiet ${shellEscape(req.familyBase)}`,
    "npm test",
  ].join(" && ");
  return [
    "docker",
    "run",
    "--rm",
    // Worker-class env parity (SPAWNED_WORKER_ENV + sandcastle HOME default).
    "-e",
    "OPENCLAW_SESSION=1",
    "-e",
    "HOME=/home/agent",
    // Image USER is `agent` (Containerfile); match worker perms/path layout.
    "--user",
    "agent",
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

/**
 * Capture execFileSync-style failure detail: message + stdout + stderr.
 *
 * Node's `Command failed: …` message alone drops the locatable reason —
 * vitest puts FAIL bodies on **stdout**, noise often on stderr. Same shape as
 * family verify's summarizeError (codex R3): keep BOTH streams labeled.
 */
export function formatBaselineExecFailureOutput(err: unknown): string {
  const parts: string[] = [];
  if (err instanceof Error) {
    parts.push(err.message);
  } else if (err != null) {
    parts.push(String(err));
  }
  if (err !== null && typeof err === "object") {
    const e = err as { stdout?: unknown; stderr?: unknown };
    const stderr = streamText(e.stderr).trim();
    const stdout = streamText(e.stdout).trim();
    if (stderr.length > 0) parts.push(`stderr:\n${stderr}`);
    if (stdout.length > 0) parts.push(`stdout:\n${stdout}`);
  }
  return parts.join("\n");
}

function streamText(v: unknown): string {
  if (typeof v === "string") return v;
  if (v instanceof Buffer) return v.toString("utf8");
  return "";
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
 * Failure output = message+stdout+stderr so extractFailedTestPaths sees vitest FAIL.
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
    const output = formatBaselineExecFailureOutput(err);
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
