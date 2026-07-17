/**
 * #955 — sandcastle AgentSessionStorage for the grok CLI.
 *
 * Sandcastle's resume capability predicate is `provider.sessionStorage`
 * (interface-based; the "claudeCode, codex, or pi" in its error text is
 * prose). The grok CLI stores each session as a DIRECTORY —
 * `<sessionsRoot>/<encodeURIComponent(cwd)>/<sessionId>/` holding
 * chat_history.jsonl / events.jsonl / state files — so host↔sandbox transfer
 * moves a whole directory (tar over the sandbox exec channel, base64-armored
 * because exec streams text lines). Absolute cwd path rewrite walks JSON /
 * JSONL string values and replaces only exact path matches or path-prefix
 * matches (`from` or `from + "/"`), not raw text substrings — so a sibling
 * cwd like `/work/tree-2` and dialogue that merely mentions a path stay intact.
 *
 * #959 — captureToHost lands via same-volume temp dir + integrity check +
 * atomic rename swap. Failures never leave a half-written live host session.
 *
 * Host tar goes through the #884 chokepoint (`execFileAsyncWithTimeout`) via
 * dynamic import: this module sits on the vitest setup import chain
 * (modelRoutes → modelRegistry → grokAgent → here), and a static import of
 * externalCall would bind real `spawn` before per-file `vi.mock("node:child_process")`
 * can intercept (spawn-timeout / telemetry git mocks).
 */

import {
  cp,
  mkdir,
  mkdtemp,
  readdir,
  readFile,
  rename,
  rm,
  stat,
  writeFile,
} from "node:fs/promises";
import { randomBytes } from "node:crypto";
import { homedir, tmpdir } from "node:os";
import { basename, dirname, join, posix } from "node:path";
import type * as sc from "@ai-hero/sandcastle";
import { shellEscape } from "./shellEscape.js";

type Storage = NonNullable<sc.AgentProvider["sessionStorage"]>;
type HostSessionLookup = Awaited<ReturnType<Storage["findByIdOnHost"]>>;

export interface GrokSessionStorageOptions {
  /** Override the host session root (default `~/.grok/sessions`). */
  readonly hostSessionsDir?: string;
  /** Override the in-sandbox session root (default `/home/agent/.grok/sessions`). */
  readonly sandboxSessionsDir?: string;
}

const bucketFor = (cwd: string): string => encodeURIComponent(cwd);

/** Host tar of a session tree can be large; keep the chokepoint buffer generous. */
const TAR_MAX_BUFFER = 256 * 1024 * 1024;

async function dirExists(path: string): Promise<boolean> {
  try {
    return (await stat(path)).isDirectory();
  } catch {
    return false;
  }
}

/**
 * #959 — staged session tree must be parseable before it can replace the live
 * host dir. Requires chat_history.jsonl (resume critical path) and validates
 * every .json / .jsonl file under the tree.
 */
async function assertStagedSessionIntact(dir: string): Promise<void> {
  if (!(await dirExists(dir))) {
    throw new Error("grok-cap: integrity failed — staged session dir missing");
  }
  const historyPath = join(dir, "chat_history.jsonl");
  let history: string;
  try {
    history = await readFile(historyPath, "utf8");
  } catch {
    throw new Error(
      "grok-cap: integrity failed — staged session missing chat_history.jsonl",
    );
  }
  await assertJsonlParseable(history, "chat_history.jsonl");

  await walkSessionTexts(dir, async (filePath, body) => {
    const name = basename(filePath);
    if (name === "chat_history.jsonl") return; // already checked
    if (name.endsWith(".jsonl")) {
      await assertJsonlParseable(body, name);
      return;
    }
    if (name.endsWith(".json")) {
      try {
        JSON.parse(body);
      } catch (err) {
        throw new Error(
          `grok-cap: integrity failed — ${name} is not valid JSON: ${
            err instanceof Error ? err.message : String(err)
          }`,
        );
      }
    }
  });
}

async function assertJsonlParseable(body: string, label: string): Promise<void> {
  const lines = body.split("\n");
  let sawRecord = false;
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]!;
    if (line.length === 0) continue;
    sawRecord = true;
    try {
      JSON.parse(line);
    } catch (err) {
      throw new Error(
        `grok-cap: integrity failed — ${label} line ${i + 1} is not valid JSONL: ${
          err instanceof Error ? err.message : String(err)
        }`,
      );
    }
  }
  if (!sawRecord) {
    throw new Error(
      `grok-cap: integrity failed — ${label} has no parseable JSONL records`,
    );
  }
}

async function walkSessionTexts(
  dir: string,
  visit: (filePath: string, body: string) => Promise<void>,
): Promise<void> {
  const entries = await readdir(dir, { withFileTypes: true });
  for (const entry of entries) {
    const p = join(dir, entry.name);
    if (entry.isDirectory()) {
      await walkSessionTexts(p, visit);
      continue;
    }
    if (!/\.(json|jsonl)$/.test(entry.name)) continue;
    const body = await readFile(p, "utf8");
    await visit(p, body);
  }
}

/**
 * #959 — atomic directory replace on the same volume. Stage is fully written
 * + validated first; live target is only displaced once the new tree is ready.
 * Concurrent racers: last successful place wins; losers must not restore a
 * stale backup over a newer complete winner.
 */
async function atomicReplaceDir(
  sourceDir: string,
  targetDir: string,
): Promise<void> {
  const parent = dirname(targetDir);
  await mkdir(parent, { recursive: true });
  const token = randomBytes(6).toString("hex");
  const backup = join(
    parent,
    `.${basename(targetDir)}.old-${process.pid}-${token}`,
  );

  // Fast path: no live target yet.
  try {
    await rename(sourceDir, targetDir);
    return;
  } catch (err) {
    const code = (err as NodeJS.ErrnoException).code;
    // Empty dir may be replaceable on some platforms; non-empty → ENOTEMPTY /
    // EEXIST / EISDIR. Anything else is a real failure.
    if (
      code !== "ENOTEMPTY" &&
      code !== "EEXIST" &&
      code !== "EISDIR" &&
      code !== "EPERM"
    ) {
      throw err;
    }
  }

  let displaced = false;
  try {
    await rename(targetDir, backup);
    displaced = true;
  } catch (err) {
    // Another racer may have already moved the live target. Try placing into
    // the vacancy; if the winner already re-created target, leave it alone.
    try {
      await rename(sourceDir, targetDir);
      return;
    } catch {
      throw err;
    }
  }

  try {
    await rename(sourceDir, targetDir);
  } catch (err) {
    // Only restore our backup when nobody else landed a complete tree.
    if (!(await dirExists(targetDir))) {
      try {
        await rename(backup, targetDir);
      } catch {
        // Best-effort restore; surface the original place error.
      }
    }
    throw err;
  }

  await rm(backup, { recursive: true, force: true }).catch(() => {});
}

/** Exact path or path-prefix (`from` / `from/…`); never bare substring. */
function rewritePathString(value: string, from: string, to: string): string {
  if (value === from) return to;
  const prefix = from.endsWith("/") ? from : `${from}/`;
  if (value.startsWith(prefix)) {
    return `${to}${value.slice(from.length)}`;
  }
  return value;
}

function rewriteJsonValues(value: unknown, from: string, to: string): unknown {
  if (typeof value === "string") return rewritePathString(value, from, to);
  if (Array.isArray(value)) {
    return value.map((item) => rewriteJsonValues(item, from, to));
  }
  if (value !== null && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [key, child] of Object.entries(value as Record<string, unknown>)) {
      out[key] = rewriteJsonValues(child, from, to);
    }
    return out;
  }
  return value;
}

/**
 * Rewrite absolute cwd strings inside session text files (json/jsonl).
 * Whole-file JSON when parseable; otherwise line-oriented JSONL. Non-JSON
 * lines are left untouched (no split/join substring rewrite).
 */
async function rewriteSessionTexts(
  dir: string,
  from: string,
  to: string,
): Promise<void> {
  if (from === to || from.length === 0) return;
  const entries = await readdir(dir, { withFileTypes: true });
  for (const entry of entries) {
    const p = join(dir, entry.name);
    if (entry.isDirectory()) {
      await rewriteSessionTexts(p, from, to);
      continue;
    }
    if (!/\.(json|jsonl)$/.test(entry.name)) continue;
    const body = await readFile(p, "utf8");
    if (!body.includes(from)) continue;

    let next: string | undefined;
    try {
      next = JSON.stringify(rewriteJsonValues(JSON.parse(body), from, to));
      // Preserve a trailing newline when the source had one (jsonl convention).
      if (body.endsWith("\n")) next += "\n";
    } catch {
      const lines = body.split("\n");
      const rewritten = lines.map((line) => {
        if (line.length === 0 || !line.includes(from)) return line;
        try {
          return JSON.stringify(rewriteJsonValues(JSON.parse(line), from, to));
        } catch {
          return line;
        }
      });
      next = rewritten.join("\n");
    }
    if (next !== undefined && next !== body) {
      await writeFile(p, next);
    }
  }
}

/** #884 chokepoint: host tar via execFileAsyncWithTimeout (never bare child_process). */
async function hostTar(
  args: readonly string[],
  stage: "grok-session:tar-create" | "grok-session:tar-extract",
): Promise<void> {
  const {
    DEFAULT_SUBPROCESS_TIMEOUT_MS,
    execFileAsyncWithTimeout,
  } = await import("./externalCall.js");
  await execFileAsyncWithTimeout("tar", args, {
    stage,
    timeoutMs: DEFAULT_SUBPROCESS_TIMEOUT_MS,
    maxBuffer: TAR_MAX_BUFFER,
  });
}

/**
 * #884 chokepoint: sandbox `handle.exec` is an external wait outside sandcastle's
 * agent idle clock (capture/resume run after "Agent stopped"). Race the promise
 * on the public surface (`withProviderTimeout`) — do not invent a second timer.
 * Stage carries sessionId so timeouts stay attributable; budget matches host tar.
 */
async function sandboxExecWithClock<T>(
  stage: "grok-session:sandbox-export" | "grok-session:sandbox-import",
  sessionId: string,
  run: () => Promise<T>,
): Promise<T> {
  const {
    DEFAULT_SUBPROCESS_TIMEOUT_MS,
    effectiveSubprocessTimeoutMs,
    withProviderTimeout,
  } = await import("./externalCall.js");
  return withProviderTimeout(
    `${stage} sessionId=${sessionId}`,
    async () => run(),
    {
      timeoutMs: effectiveSubprocessTimeoutMs(DEFAULT_SUBPROCESS_TIMEOUT_MS),
    },
  );
}

export function makeGrokSessionStorage(
  options?: GrokSessionStorageOptions,
): Storage {
  const hostRoot =
    options?.hostSessionsDir ?? join(homedir(), ".grok", "sessions");
  const sandboxRoot =
    options?.sandboxSessionsDir ?? posix.join("/home/agent", ".grok", "sessions");

  const hostSessionDir = (cwd: string, sessionId: string): string =>
    join(hostRoot, bucketFor(cwd), sessionId);

  const findByIdOnHost = async (
    sessionId: string,
  ): Promise<HostSessionLookup> => {
    if (await dirExists(hostRoot)) {
      for (const bucket of await readdir(hostRoot)) {
        const candidate = join(hostRoot, bucket, sessionId);
        if (await dirExists(candidate)) {
          return { path: candidate, searchedRoot: hostRoot };
        }
      }
    }
    return { path: undefined, searchedRoot: hostRoot };
  };

  return {
    hostSessionFilePath: (cwd, sessionId) => hostSessionDir(cwd, sessionId),

    existsOnHost: async (cwd, sessionId) =>
      (await dirExists(hostSessionDir(cwd, sessionId))) ||
      (await findByIdOnHost(sessionId)).path !== undefined,

    readHostSession: async (cwd, sessionId) => {
      let dir = hostSessionDir(cwd, sessionId);
      if (!(await dirExists(dir))) {
        const found = await findByIdOnHost(sessionId);
        if (found.path === undefined) return undefined;
        dir = found.path;
      }
      try {
        return await readFile(join(dir, "chat_history.jsonl"), "utf8");
      } catch {
        return undefined;
      }
    },

    findByIdOnHost,

    captureToHost: async ({ hostCwd, sandboxCwd, sessionId, handle }) => {
      const src = posix.join(sandboxRoot, bucketFor(sandboxCwd), sessionId);
      const result = await sandboxExecWithClock(
        "grok-session:sandbox-export",
        sessionId,
        () => handle.exec(`tar -C ${shellEscape(src)} -cf - . | base64`),
      );
      if (result.exitCode !== 0) {
        throw new Error(
          `grok-cap: sandbox session export failed (${result.exitCode}): ${result.stderr}`,
        );
      }
      const target = hostSessionDir(hostCwd, sessionId);
      // #959: stage on the same volume as the live target so rename is atomic.
      // Unpack + rewrite + integrity run only under staging; the live dir is
      // swapped in last. Any failure leaves the previous target untouched.
      const parent = dirname(target);
      await mkdir(parent, { recursive: true });
      const work = await mkdtemp(join(parent, ".grok-cap-"));
      const staging = join(work, "session");
      const tarPath = join(work, "session.tar");
      try {
        await mkdir(staging);
        await writeFile(
          tarPath,
          Buffer.from(result.stdout.replace(/\s+/g, ""), "base64"),
        );
        await hostTar(
          ["-C", staging, "-xf", tarPath],
          "grok-session:tar-extract",
        );
        await rewriteSessionTexts(staging, sandboxCwd, hostCwd);
        await assertStagedSessionIntact(staging);
        await atomicReplaceDir(staging, target);
      } finally {
        await rm(work, { recursive: true, force: true });
      }
    },

    resumeIntoSandbox: async ({ hostCwd, sandboxCwd, sessionId, handle }) => {
      let src = hostSessionDir(hostCwd, sessionId);
      // r2-F3: rewrite `from` must be a path actually present in the session
      // files. Direct hostCwd hit → hostCwd; fallback across buckets → decode
      // the hit bucket name (encodeURIComponent(source cwd)).
      let rewriteFrom = hostCwd;
      if (!(await dirExists(src))) {
        const found = await findByIdOnHost(sessionId);
        if (found.path === undefined) {
          throw new Error(
            `grok-res: session "${sessionId}" not found under ${found.searchedRoot}`,
          );
        }
        src = found.path;
        rewriteFrom = decodeURIComponent(basename(dirname(src)));
      }
      // Rewrite on a scratch copy — the host store stays untouched.
      const scratch = await mkdtemp(join(tmpdir(), "grok-res-"));
      try {
        const copy = join(scratch, "session");
        await cp(src, copy, { recursive: true });
        await rewriteSessionTexts(copy, rewriteFrom, sandboxCwd);
        // Write tar to a file (not stdout buffer) so the #884 utf8 chokepoint
        // can own the host subprocess without encoding:buffer escape hatches.
        const tarPath = join(scratch, "session.tar");
        await hostTar(
          ["-C", copy, "-cf", tarPath, "."],
          "grok-session:tar-create",
        );
        const tarBytes = await readFile(tarPath);
        const dst = posix.join(sandboxRoot, bucketFor(sandboxCwd), sessionId);
        const push = await sandboxExecWithClock(
          "grok-session:sandbox-import",
          sessionId,
          () =>
            handle.exec(
              `mkdir -p ${shellEscape(dst)} && base64 -d | tar -C ${shellEscape(dst)} -xf -`,
              { stdin: tarBytes.toString("base64") },
            ),
        );
        if (push.exitCode !== 0) {
          throw new Error(
            `grok-res: sandbox session import failed (${push.exitCode}): ${push.stderr}`,
          );
        }
      } finally {
        await rm(scratch, { recursive: true, force: true });
      }
    },
  };
}
