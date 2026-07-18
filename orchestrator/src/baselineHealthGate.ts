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
 * Deps (sibling of family verify `installDeps` / worktree `provisionWorktreeNodeModules`):
 * host-side provision of `verifyCwd` node_modules (clonefile / npm ci) before
 * container `npm test`, so a clean family clone has a reachable green path.
 *
 * Sandcastle parity (best-effort this slice): same `imageName`, bind-mount the
 * family worksite at the host path (worker cwd pattern), `HOME=/home/agent`,
 * `OPENCLAW_SESSION=1` (SPAWNED_WORKER_ENV), and `--user agent`. Full agent
 * `sc.run` lifecycle is not required for a pure full-suite probe — no LLM.
 */

import { isAbsolute, relative, resolve, sep } from "node:path";

import { shWithClock } from "./externalCall.js";
import { formatExecFailureOutput } from "./execFailureOutput.js";
import { gitExitStatus, isFileNotFound } from "./fsErrors.js";
import {
  provisionNodeModules,
  resolveTemplateProjectDir,
  type Sh as ProvisionSh,
} from "./provisionNodeModules.js";
import { SPAWNED_WORKER_ENV } from "./realBackend.js";

/** Infra (tooling/deps) vs suite (product tests) — diagnosis/hint branch. */
export type BaselineFailureClass = "infra" | "suite";

/** Outcome of one canonical full suite invocation. */
export type BaselineFullTestResult =
  | { readonly ok: true }
  | {
      readonly ok: false;
      readonly exitCode: number;
      readonly output: string;
      readonly failedTests?: ReadonlyArray<string>;
      /** Explicit class when known (provision/spawn). Else classified from output. */
      readonly failureClass?: BaselineFailureClass;
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

/**
 * Shared docker/npm tooling heuristics for infra vs suite classification.
 * Used by {@link classifyBaselineFailure} and {@link isInfraExecFailure} so
 * ENOENT / daemon / image-pull / socket-perm / missing-cli patterns live in
 * one place (#1006 CR R4 S1 + base CR ST-S1/SP-S3).
 *
 * Keep narrow: only pure tooling reds. Suite FAIL bodies (vitest/npm exit 1)
 * must stay "suite" so operators still get the pre-fix ticket pointer.
 */
const INFRA_DOCKER_DAEMON_RE = /Cannot connect to the Docker daemon/i;
/** Socket perm beyond "Cannot connect…" (common on rootless / group-less hosts). */
const INFRA_DOCKER_SOCKET_PERM_RE =
  /permission denied.*(?:docker\.sock|Docker daemon)|(?:docker\.sock|Docker daemon).*permission denied|permission denied while trying to connect to the Docker daemon/i;
/** Image missing / registry pull denied — worker image not usable. */
const INFRA_DOCKER_IMAGE_RE =
  /Unable to find image|pull access denied|pull denied|repository does not exist|manifest for .+ not found|Error response from daemon:.*(?:not found|pull access denied)/i;
/**
 * Docker client usage/config (often exit 125) — clearly tooling, not suite.
 * Avoid bare "error" / "failed" so real suite reds never match.
 */
const INFRA_DOCKER_USAGE_RE =
  /docker:\s*(?:['`][^'`]+['`]\s+)?requires at least|unknown flag:|flag provided but not defined|invalid reference format|docker:\s*invalid|failed to create (?:task|shim)|OCI runtime (?:create )?failed/i;
const INFRA_DOCKER_MISSING_RE =
  /spawn\s+docker\s+ENOENT|docker:\s*(?:command\s+)?not found|ENOENT.*\bdocker\b/i;
const INFRA_NPM_MISSING_RE =
  /spawn\s+npm\s+ENOENT|npm:\s*(?:command\s+)?not found|ENOENT.*\bnpm\b/i;

function matchesInfraToolingOutput(output: string): boolean {
  return (
    INFRA_DOCKER_DAEMON_RE.test(output) ||
    INFRA_DOCKER_SOCKET_PERM_RE.test(output) ||
    INFRA_DOCKER_IMAGE_RE.test(output) ||
    INFRA_DOCKER_USAGE_RE.test(output) ||
    INFRA_DOCKER_MISSING_RE.test(output) ||
    INFRA_NPM_MISSING_RE.test(output)
  );
}

/**
 * Classify baseline red as infrastructure vs suite disease.
 * Explicit `failureClass` wins; otherwise heuristic on output (docker/npm spawn,
 * provision, daemon) so pure infra never steers operators at a pre-fix ticket.
 */
export function classifyBaselineFailure(
  failure: Extract<BaselineFullTestResult, { ok: false }>,
): BaselineFailureClass {
  if (failure.failureClass === "infra" || failure.failureClass === "suite") {
    return failure.failureClass;
  }
  const o = failure.output;
  if (
    /baseline health gate:\s*(deps provision|worksite prepare|empty container argv)/i.test(
      o,
    ) ||
    matchesInfraToolingOutput(o) ||
    /deps provision|provision(?:ing)? failed|npm ci failed/i.test(o)
  ) {
    return "infra";
  }
  // Docker client usage/config exits (125/126) when text is tooling-shaped —
  // never treat vitest FAIL bodies as infra even if exit were atypical.
  if (
    (failure.exitCode === 125 || failure.exitCode === 126) &&
    /\bdocker\b/i.test(o) &&
    !/\bFAIL\b|\.test\.\w+/i.test(o)
  ) {
    return "infra";
  }
  return "suite";
}

/** Suite disease → one pre-fix ticket; infra → repair tooling/deps, no ticket. */
export function formatBaselineHealthFailurePackage(
  failure: Extract<BaselineFullTestResult, { ok: false }>,
): string {
  const kind = classifyBaselineFailure(failure);
  const outputTail = failure.output.trim();
  const clipped =
    outputTail.length > 4000 ? `${outputTail.slice(-4000)}\n…(truncated)` : outputTail;
  if (kind === "infra") {
    return [
      "family baseline health gate: infrastructure RED (not suite disease) on family base before fan-out",
      `exit code: ${failure.exitCode}`,
      "pure infrastructure — do NOT open a pre-fix ticket / 前置修复票 for docker-missing, npm-missing, or deps provision failures",
      "repair: ensure docker is available + daemon up, host deps provisioned (installDeps / npm ci class), then re-admit",
      "--- infra output ---",
      clipped,
    ].join("\n");
  }
  const tests =
    failure.failedTests !== undefined && failure.failedTests.length > 0
      ? failure.failedTests.join(", ")
      : "(see full output — parser found no individual test paths)";
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

/** Operator repair hint for stopSummary — branches on infra vs suite. */
export function baselineHealthRepairHint(
  failure: Extract<BaselineFullTestResult, { ok: false }>,
): string {
  if (classifyBaselineFailure(failure) === "infra") {
    return (
      "repair baseline-gate infrastructure (docker available, host deps provision / npm ci) " +
      "then re-admit — do not open a suite pre-fix ticket for pure infra red"
    );
  }
  return (
    "file one pre-fix ticket for the family-base full failure, land the fix on main/family base, " +
    "then re-admit — do not fan out N children to re-fix the same baseline disease"
  );
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

/** Inputs for building the production container full-test argv + host provision. */
export interface BaselineContainerFullTestRequest {
  readonly imageName: string;
  readonly workingRepo: string;
  readonly familyBase: string;
  readonly verifyCwd: string;
  /**
   * Warm monorepo template for clonefile (#746) — same as family verify
   * `depsTemplateRoot` / driver `sourceRepo`. Optional; absent → npm ci/install.
   */
  readonly depsTemplateRoot?: string;
  /**
   * Injectable host deps provision (tests / alternate installers).
   * Default = {@link provisionNodeModules} at verifyCwd (installDeps class).
   */
  readonly provisionDeps?: (verifyCwd: string) => Promise<void>;
}

/**
 * Container-side worksite root for the baseline full probe.
 *
 * Host clones often live under `/root/.sc-orchestrator/…` when the orchestrator
 * runs as root. The worker image runs as non-root `agent`, who cannot traverse
 * `/root`. Always bind-mount the host worksite at this agent-readable path and
 * translate `verifyCwd` relative to it (Codex online P1 / #1006).
 */
export const BASELINE_CONTAINER_WORKSITE = "/home/agent/baseline-worksite";

/**
 * Map host verifyCwd under workingRepo → container path under
 * {@link BASELINE_CONTAINER_WORKSITE}.
 *
 * Normalizes both paths, then requires verifyCwd to stay inside workingRepo
 * (no lexical `..` escape, no unrelated absolute path). Escape / unmappable
 * paths throw — callers must fail closed rather than point docker `-w` outside
 * the bind mount (PR #1017 verifyCwd containment).
 */
export function containerBaselineVerifyCwd(
  workingRepo: string,
  verifyCwd: string,
): string {
  const hostRoot = resolve(workingRepo);
  const absVerify = resolve(verifyCwd);
  const rel = relative(hostRoot, absVerify);
  // Contained: "" (same path) or a relative segment that does not climb out.
  // Reject ".." / "../…" and absolute rel (Windows cross-drive).
  if (rel === ".." || rel.startsWith(`..${sep}`) || isAbsolute(rel)) {
    throw new Error(
      `baseline health gate: verifyCwd escapes workingRepo ` +
        `(verifyCwd=${verifyCwd}, workingRepo=${workingRepo})`,
    );
  }
  return rel.length > 0
    ? `${BASELINE_CONTAINER_WORKSITE}/${rel.split(sep).join("/")}`
    : BASELINE_CONTAINER_WORKSITE;
}

/**
 * Production argv for the worker-image full suite.
 * Same image class as coder workers; host worksite bind-mounted at an
 * agent-readable container path; `npm test` runs *inside* the container —
 * never as a bare host invocation (owner hard constraint: no lying host greens).
 *
 * Host must already have provisioned `verifyCwd` node_modules (see
 * {@link runBaselineFullTestsInWorkerContainer}); the bind mount carries them in.
 *
 * Best-effort sandcastle parity (not full `sc.run`): imageName + worksite
 * bind-mount + `HOME=/home/agent` + `OPENCLAW_SESSION=1` + `--user agent`.
 * Agent auth/soul mounts are irrelevant for a pure `npm test` probe.
 */
export function buildBaselineContainerFullTestArgv(
  req: BaselineContainerFullTestRequest,
): string[] {
  // Host {@link ensureBaselineWorksiteReady} already checked out familyBase on
  // the bind-mounted worksite — do not re-checkout inside the container (DRY;
  // #1006 CR N1). Container only runs the project's canonical full entry.
  // `npm test` is the orchestrator full gate (typecheck + vitest run).
  // Deps are host-provisioned before this container starts (installDeps class).
  // SPAWNED_WORKER_ENV from realBackend — single source for OPENCLAW_SESSION etc.
  const spawnedEnvFlags = Object.entries(SPAWNED_WORKER_ENV).flatMap(
    ([key, value]) => ["-e", `${key}=${value}`],
  );
  const containerCwd = containerBaselineVerifyCwd(
    req.workingRepo,
    req.verifyCwd,
  );
  return [
    "docker",
    "run",
    "--rm",
    // Worker-class env parity (SPAWNED_WORKER_ENV + sandcastle HOME default).
    ...spawnedEnvFlags,
    "-e",
    "HOME=/home/agent",
    // Image USER is `agent` (Containerfile); match worker perms/path layout.
    "--user",
    "agent",
    // Host path may be under /root; container path must be agent-traversable.
    "-v",
    `${req.workingRepo}:${BASELINE_CONTAINER_WORKSITE}`,
    "-w",
    containerCwd,
    req.imageName,
    "bash",
    "-lc",
    "npm test",
  ];
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
 * Host worksite prepare: checkout family base + provision node_modules at
 * verifyCwd — same class as family verify `installDeps` / worktree provision.
 * Must run before container `npm test` so a clean clone has a reachable green path.
 */
export async function ensureBaselineWorksiteReady(
  req: BaselineContainerFullTestRequest,
  sh: BaselineSh = defaultBaselineSh,
): Promise<void> {
  // Checkout first so package.json / lock match the suite under test.
  sh("git", [
    "-C",
    req.workingRepo,
    "checkout",
    "--quiet",
    req.familyBase,
  ]);
  if (req.provisionDeps !== undefined) {
    await req.provisionDeps(req.verifyCwd);
    return;
  }
  const templateProjectDir = resolveTemplateProjectDir(req.verifyCwd, {
    templateRoot: req.depsTemplateRoot,
    targetRoot: req.workingRepo,
  });
  const provisionSh: ProvisionSh = (file, args, cwd) =>
    sh(file, args, cwd !== undefined ? { cwd } : undefined);
  await provisionNodeModules(req.verifyCwd, {
    templateProjectDir,
    sh: provisionSh,
  });
}

/**
 * Production runner: host provision (installDeps class) → docker worker image
 * + mounted family clone + `npm test`. Throws map to ok:false (fail-closed).
 * Failure output = message+stdout+stderr so extractFailedTestPaths sees vitest FAIL.
 * Provision / docker-spawn failures are tagged `failureClass: "infra"`.
 */
export async function runBaselineFullTestsInWorkerContainer(
  req: BaselineContainerFullTestRequest,
  sh: BaselineSh = defaultBaselineSh,
): Promise<BaselineFullTestResult> {
  try {
    await ensureBaselineWorksiteReady(req, sh);
  } catch (err) {
    const output = formatExecFailureOutput(err);
    return {
      ok: false,
      exitCode: 1,
      output: `baseline health gate: deps provision / worksite prepare failed\n${output}`,
      failureClass: "infra",
    };
  }

  let argv: string[];
  try {
    argv = buildBaselineContainerFullTestArgv(req);
  } catch (err) {
    // verifyCwd containment / argv build — fail closed as infra (no docker spawn).
    const output = formatExecFailureOutput(err);
    return {
      ok: false,
      exitCode: 1,
      output: `baseline health gate: container argv rejected\n${output}`,
      failureClass: "infra",
    };
  }
  const [file, ...args] = argv;
  if (file === undefined) {
    return {
      ok: false,
      exitCode: 1,
      output: "baseline health gate: empty container argv",
      failureClass: "infra",
    };
  }
  try {
    sh(file, args, {
      // Full suite once per campaign — generous wall; not the 15s probe budget.
      timeoutMs: 30 * 60 * 1000,
    });
    return { ok: true };
  } catch (err) {
    const output = formatExecFailureOutput(err);
    const exitCode = gitExitStatus(err) ?? 1;
    const failedTests = extractFailedTestPaths(output);
    const infra = isInfraExecFailure(err, output);
    return {
      ok: false,
      exitCode: exitCode === 0 ? 1 : exitCode,
      output,
      ...(failedTests.length > 0 ? { failedTests } : {}),
      ...(infra ? { failureClass: "infra" as const } : {}),
    };
  }
}

/**
 * Docker/npm spawn, daemon, image pull, or docker client usage — not suite disease.
 * Exit 125/126 are docker-client / cannot-invoke class; only tag infra when the
 * failure text is docker-tooling-shaped so a suite exit never rides along.
 */
function isInfraExecFailure(err: unknown, output: string): boolean {
  // ENOENT spawn (docker/npm missing) — reuse shared FS absence predicate.
  if (isFileNotFound(err)) {
    return true;
  }
  if (matchesInfraToolingOutput(output)) {
    return true;
  }
  // Docker CLI: 125 = client/daemon/config; 126 = contained command cannot invoke.
  // Production argv is always `docker run …`; suite reds exit 1 via npm/vitest.
  const status = gitExitStatus(err);
  if (
    (status === 125 || status === 126) &&
    /\bdocker\b/i.test(output) &&
    !/\bFAIL\b|\.test\.\w+/i.test(output)
  ) {
    return true;
  }
  return false;
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
