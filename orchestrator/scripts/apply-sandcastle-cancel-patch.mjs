#!/usr/bin/env node
/**
 * #1010 — local patch: Sandcastle cancellation must kill the in-flight exec
 * process tree (docker/podman/no-sandbox), not merely abandon the host Promise.
 *
 * Upstream pin: @ai-hero/sandcastle@0.12.0 (exact; package.json has no ^).
 * No upstream bump available — strategy is a local dist patch so AbortSignal /
 * idle-timeout abort the shared exec seam. Idempotent — safe on every
 * postinstall / import-time ensure.
 *
 * Marker token: #1010-sandcastle-cancel
 *
 * Kill model:
 * - no-sandbox: spawn detached + process.kill(-pid) so shell + grandchildren die
 * - docker/podman: same host kill PLUS in-container pkill by SC_CANCEL_TOKEN
 *   (killing the host `docker exec` client alone leaves the remote shell alive
 *   in a reused container — the production bug #1010 names)
 * - in-container pgrep loop MUST exclude $$ so the kill helper does not match
 *   and signal itself (its own cmdline contains the SC_CANCEL_TOKEN needle)
 *
 * Needle-miss contract: every patch* helper throws Error when the expected
 * upstream dist shape is absent (version drift / unexpected minify). Main
 * exits 1 with `sandcastle-cancel-patch FAILED: …` — never silent no-op.
 * ensureSandcastleCancelPatch propagates that as a thrown Error.
 */
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const MARKER_TOKEN = "#1010-sandcastle-cancel";
const MARKER = `/* ${MARKER_TOKEN} */`;

const require = createRequire(import.meta.url);
const here = dirname(fileURLToPath(import.meta.url));

function resolveSandcastleRoot() {
  try {
    const entry = require.resolve("@ai-hero/sandcastle/sandboxes/no-sandbox");
    // .../dist/sandboxes/no-sandbox.js → package root
    return dirname(dirname(dirname(entry)));
  } catch {
    const fallback = join(here, "..", "node_modules", "@ai-hero", "sandcastle");
    if (existsSync(join(fallback, "package.json"))) return fallback;
    throw new Error(
      "apply-sandcastle-cancel-patch: @ai-hero/sandcastle not installed",
    );
  }
}

const HOST_KILL_HELPER = `${MARKER}
function __scCancelWireAbortKill(proc, signal, onAbortExtra) {
  if (!signal) return () => {};
  const killTree = (sig) => {
    const pid = proc.pid;
    if (pid !== undefined && pid > 0) {
      try {
        process.kill(-pid, sig);
        return;
      } catch {
      }
    }
    try {
      proc.kill(sig);
    } catch {
    }
  };
  const kill = () => {
    try {
      if (typeof onAbortExtra === "function") onAbortExtra();
    } catch {
    }
    killTree("SIGTERM");
    const t = setTimeout(() => {
      try {
        if (proc.exitCode === null && proc.signalCode === null) {
          killTree("SIGKILL");
        }
      } catch {
      }
    }, 200);
    if (typeof t.unref === "function") t.unref();
  };
  if (signal.aborted) {
    kill();
    return () => {};
  }
  signal.addEventListener("abort", kill, { once: true });
  return () => signal.removeEventListener("abort", kill);
}
`;

function ensureHelper(source) {
  if (source.includes("__scCancelWireAbortKill") && source.includes("onAbortExtra")) {
    return source;
  }
  // Strip any prior partial helper.
  let next = source.replace(
    /\/\* #1010-sandcastle-cancel \*\/\nfunction __scCancelWireAbortKill[\s\S]*?\n\}\n/,
    "",
  );
  const insertAt = next.indexOf("\n");
  return next.slice(0, insertAt + 1) + HOST_KILL_HELPER + next.slice(insertAt + 1);
}

/**
 * no-sandbox: detached spawn + host process-group kill.
 */
function patchNoSandbox(source) {
  if (
    source.includes(MARKER_TOKEN) &&
    source.includes("detached: true") &&
    source.includes("__scCancelWireAbortKill(proc, opts?.signal)")
  ) {
    return source;
  }
  let next = ensureHelper(source);
  // Strip prior wire lines if re-applying from a broken state.
  next = next.replace(
    /\n\s*const __scCancelUnwire = __scCancelWireAbortKill\([^)]*\);\n\s*proc\.on\("close", \(\) => \{ try \{ __scCancelUnwire\(\); \} catch \{\} \}\);/g,
    "",
  );
  next = next.replace(/,\n\s*detached: true/g, "");

  const spawnBlock =
    `const proc = spawn(shellCmd, shellArgs, {
            cwd,
            env: processEnv,
            stdio: [
              opts?.stdin !== void 0 ? "pipe" : "ignore",
              "pipe",
              "pipe"
            ],
            windowsVerbatimArguments: isWindows
          });`;

  if (!next.includes(spawnBlock)) {
    throw new Error(
      "apply-sandcastle-cancel-patch: no-sandbox spawn block not found " +
        "(needle-miss — refuse silent no-op; pin/check @ai-hero/sandcastle@0.12.0)",
    );
  }

  const replacement =
    `const proc = spawn(shellCmd, shellArgs, {
            cwd,
            env: processEnv,
            stdio: [
              opts?.stdin !== void 0 ? "pipe" : "ignore",
              "pipe",
              "pipe"
            ],
            windowsVerbatimArguments: isWindows,
            detached: true
          });
            const __scCancelUnwire = __scCancelWireAbortKill(proc, opts?.signal);
            proc.on("close", () => { try { __scCancelUnwire(); } catch {} });`;

  return next.replace(spawnBlock, replacement);
}

/** True when the in-container kill loop already excludes self ($$). */
function hasSelfExcludeKillLoop(source) {
  // Patched dist stores the kill script as a double-quoted JS string, so the
  // file bytes contain escaped quotes: [ \"$p\" = \"$$\" ].
  return (
    source.includes('[ \\"$p\\" = \\"$$\\" ]') ||
    source.includes('[ "$p" = "$$" ]')
  );
}

/**
 * Upgrade a previously patched kill loop that lacked $$ self-exclusion.
 * Returns null when the old loop shape is not present (caller does full patch).
 */
function upgradeKillLoopSelfExclude(source) {
  if (hasSelfExcludeKillLoop(source)) return source;
  // Prior #1010 shape: `); do pkill -` without skipping $$
  const old =
    '" 2>/dev/null); do pkill -"';
  const upgraded =
    '" 2>/dev/null); do [ \\"$p\\" = \\"$$\\" ] && continue; pkill -"';
  if (!source.includes(old)) return null;
  return source.split(old).join(upgraded);
}

/**
 * docker/podman: detached host client + in-container pkill by cancel token.
 * `runtime` is "docker" or "podman".
 * docker minifies the Promise resolve param as `resolve2`; podman keeps `resolve`.
 */
function patchContainerRuntime(source, runtime) {
  if (
    source.includes(MARKER_TOKEN) &&
    source.includes("SC_CANCEL_TOKEN") &&
    source.includes("onAbortExtra") &&
    hasSelfExcludeKillLoop(source)
  ) {
    return source;
  }

  // Already patched once but missing $$ exclude — migrate in place.
  if (
    source.includes("SC_CANCEL_TOKEN") &&
    source.includes("__scCancelWireAbortKill") &&
    source.includes("onAbortExtra") &&
    !hasSelfExcludeKillLoop(source)
  ) {
    const upgraded = upgradeKillLoopSelfExclude(source);
    if (upgraded !== null) return upgraded;
  }

  let next = ensureHelper(source);
  next = next.replace(
    /\n\s*const __scCancelUnwire = __scCancelWireAbortKill\([^;]*\);\n\s*proc\.on\("close", \(\) => \{ try \{ __scCancelUnwire\(\); \} catch \{\} \}\);/g,
    "",
  );
  next = next.replace(/,\n\s*detached: true/g, "");

  const resolveName = runtime === "docker" ? "resolve2" : "resolve";

  const fileExecHead =
    "exec: (command, opts) => {\n" +
    "          const effectiveCommand = opts?.sudo ? `sudo ${command}` : command;\n" +
    '          const args = ["exec"];\n' +
    '          if (opts?.stdin !== void 0) args.push("-i");\n' +
    '          if (opts?.cwd) args.push("-w", opts.cwd);\n' +
    '          args.push(containerName, "sh", "-c", effectiveCommand);\n' +
    `          return new Promise((${resolveName}, reject) => {\n` +
    `            const proc = spawn("${runtime}", args, {\n` +
    "              stdio: [\n" +
    '                opts?.stdin !== void 0 ? "pipe" : "ignore",\n' +
    '                "pipe",\n' +
    '                "pipe"\n' +
    "              ]\n" +
    "            });";

  const fileExecReplacement =
    "exec: (command, opts) => {\n" +
    "          const effectiveCommand = opts?.sudo ? `sudo ${command}` : command;\n" +
    '          const cancelToken = "sc1010_" + Math.random().toString(36).slice(2, 10);\n' +
    '          const tokenCommand = "SC_CANCEL_TOKEN=" + cancelToken + " " + effectiveCommand;\n' +
    '          const args = ["exec"];\n' +
    '          if (opts?.stdin !== void 0) args.push("-i");\n' +
    '          if (opts?.cwd) args.push("-w", opts.cwd);\n' +
    '          args.push(containerName, "sh", "-c", tokenCommand);\n' +
    `          return new Promise((${resolveName}, reject) => {\n` +
    `            const proc = spawn("${runtime}", args, {\n` +
    "              stdio: [\n" +
    '                opts?.stdin !== void 0 ? "pipe" : "ignore",\n' +
    '                "pipe",\n' +
    '                "pipe"\n' +
    "              ],\n" +
    "              detached: true\n" +
    "            });\n" +
    "            const inContainerKill = () => {\n" +
    "              const killOnce = (sig) => {\n" +
    // Children first (sleep/agent CLI), then the token-tagged shell so EXIT
    // traps can still run on TERM before any later KILL. Exclude $$ so the
    // kill helper (whose cmdline embeds the SC_CANCEL_TOKEN needle) never
    // signals itself mid-loop.
    "                const script =\n" +
    '                  "for p in $(pgrep -f SC_CANCEL_TOKEN=" +\n' +
    '                  cancelToken +\n' +
    '                  " 2>/dev/null); do [ \\"$p\\" = \\"$$\\" ] && continue; pkill -" +\n' +
    "                  sig +\n" +
    '                  " -P $p 2>/dev/null; kill -" +\n' +
    "                  sig +\n" +
    '                  " $p 2>/dev/null; done; true";\n' +
    "                try {\n" +
    `                  spawn("${runtime}", [\n` +
    '                    "exec", containerName, "sh", "-c", script,\n' +
    '                  ], { stdio: "ignore", detached: true }).unref();\n' +
    "                } catch {\n" +
    "                }\n" +
    "              };\n" +
    '              killOnce("TERM");\n' +
    '              const t = setTimeout(() => killOnce("KILL"), 400);\n' +
    '              if (typeof t.unref === "function") t.unref();\n' +
    "            };\n" +
    "            const __scCancelUnwire = __scCancelWireAbortKill(proc, opts?.signal, inContainerKill);\n" +
    '            proc.on("close", () => { try { __scCancelUnwire(); } catch {} });';

  if (!next.includes(fileExecHead)) {
    throw new Error(
      `apply-sandcastle-cancel-patch: ${runtime} exec head not found in source ` +
        `(needle-miss — refuse silent no-op; pin/check @ai-hero/sandcastle@0.12.0)`,
    );
  }
  return next.replace(fileExecHead, fileExecReplacement);
}

function patchInvokeAgent(source) {
  if (
    source.includes(MARKER_TOKEN) &&
    source.includes("/* #1010-exec-signal */")
  ) {
    return source;
  }

  const abortSetupNeedle =
    "const abortDeferred = yield* Deferred_exports.make();\n  let abortCleanup = null;\n  if (signal) {\n    if (signal.aborted) {\n      return yield* Effect_exports.die(signal.reason);\n    }\n    const onAbort = () => {\n      Effect_exports.runFork(Deferred_exports.die(abortDeferred, signal.reason));\n    };\n    signal.addEventListener(\"abort\", onAbort, { once: true });\n    abortCleanup = () => signal.removeEventListener(\"abort\", onAbort);\n  }\n  resetTimer();";

  if (!source.includes(abortSetupNeedle)) {
    throw new Error(
      "apply-sandcastle-cancel-patch: invokeAgent abort setup needle not found",
    );
  }

  const abortSetupReplacement = `${MARKER}
  const abortDeferred = yield* Deferred_exports.make();
  let abortCleanup = null;
  /* #1010-exec-signal */
  const execAbortController = new AbortController();
  const fireExecAbort = (reason) => {
    try {
      if (!execAbortController.signal.aborted) execAbortController.abort(reason);
    } catch {
    }
  };
  if (signal) {
    if (signal.aborted) {
      fireExecAbort(signal.reason);
      return yield* Effect_exports.die(signal.reason);
    }
    const onAbort = () => {
      fireExecAbort(signal.reason);
      Effect_exports.runFork(Deferred_exports.die(abortDeferred, signal.reason));
    };
    signal.addEventListener("abort", onAbort, { once: true });
    abortCleanup = () => signal.removeEventListener("abort", onAbort);
  }
  resetTimer();`;

  let next = source.replace(abortSetupNeedle, abortSetupReplacement);

  const soft =
    /yield\* Deferred_exports\.fail\(\s*timeoutSignal,\s*new AgentIdleTimeoutError\(\{[\s\S]*?\}\)\s*\);/;
  if (!soft.test(next)) {
    throw new Error(
      "apply-sandcastle-cancel-patch: idle timeout fail needle not found",
    );
  }
  next = next.replace(soft, (m) => {
    return (
      `fireExecAbort(new AgentIdleTimeoutError({ message: "agent idle timeout", timeoutMs: idleTimeoutMs }));\n          ` +
      m
    );
  });

  const execOptsNeedle = `cwd: sandboxRepoDir,
      stdin: printCmd.stdin
    });`;
  if (!next.includes(execOptsNeedle)) {
    throw new Error(
      "apply-sandcastle-cancel-patch: sandbox.exec options needle not found",
    );
  }
  next = next.replace(
    execOptsNeedle,
    `cwd: sandboxRepoDir,
      stdin: printCmd.stdin,
      signal: execAbortController.signal
    });`,
  );

  return next;
}

function writeIfChanged(path, content) {
  const prev = existsSync(path) ? readFileSync(path, "utf8") : null;
  if (prev === content) return false;
  writeFileSync(path, content, "utf8");
  return true;
}

export function applySandcastleCancelPatch(root = resolveSandcastleRoot()) {
  const files = {
    docker: join(root, "dist", "chunk-CP3TYXZA.js"),
    noSandbox: join(root, "dist", "chunk-62WN33RK.js"),
    podman: join(root, "dist", "sandboxes", "podman.js"),
    index: join(root, "dist", "index.js"),
  };
  for (const [name, path] of Object.entries(files)) {
    if (!existsSync(path)) {
      throw new Error(
        `apply-sandcastle-cancel-patch: missing ${name} at ${path}`,
      );
    }
  }

  const dockerNext = patchContainerRuntime(
    readFileSync(files.docker, "utf8"),
    "docker",
  );
  const noSandboxNext = patchNoSandbox(readFileSync(files.noSandbox, "utf8"));
  const podmanNext = patchContainerRuntime(
    readFileSync(files.podman, "utf8"),
    "podman",
  );
  const indexNext = patchInvokeAgent(readFileSync(files.index, "utf8"));

  let changed = 0;
  if (writeIfChanged(files.docker, dockerNext)) changed++;
  if (writeIfChanged(files.noSandbox, noSandboxNext)) changed++;
  if (writeIfChanged(files.podman, podmanNext)) changed++;
  if (writeIfChanged(files.index, indexNext)) changed++;

  return { root, changed, files: Object.keys(files) };
}

const isMain =
  process.argv[1] !== undefined &&
  fileURLToPath(import.meta.url) === process.argv[1];
if (isMain) {
  try {
    const result = applySandcastleCancelPatch();
    process.stdout.write(
      `sandcastle-cancel-patch: root=${result.root} changed=${result.changed}\n`,
    );
    process.exit(0);
  } catch (err) {
    process.stderr.write(
      `sandcastle-cancel-patch FAILED: ${
        err instanceof Error ? err.message : String(err)
      }\n`,
    );
    process.exit(1);
  }
}
