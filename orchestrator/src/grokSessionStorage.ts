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
  rm,
  stat,
  writeFile,
} from "node:fs/promises";
import { homedir, tmpdir } from "node:os";
import { dirname, join, posix } from "node:path";
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
      const result = await handle.exec(
        `tar -C ${shellEscape(src)} -cf - . | base64`,
      );
      if (result.exitCode !== 0) {
        throw new Error(
          `grok-cap: sandbox session export failed (${result.exitCode}): ${result.stderr}`,
        );
      }
      const target = hostSessionDir(hostCwd, sessionId);
      await mkdir(target, { recursive: true });
      const tarPath = join(
        await mkdtemp(join(tmpdir(), "grok-cap-")),
        "session.tar",
      );
      await writeFile(tarPath, Buffer.from(result.stdout.replace(/\s+/g, ""), "base64"));
      try {
        await hostTar(["-C", target, "-xf", tarPath], "grok-session:tar-extract");
      } finally {
        await rm(dirname(tarPath), { recursive: true, force: true });
      }
      await rewriteSessionTexts(target, sandboxCwd, hostCwd);
    },

    resumeIntoSandbox: async ({ hostCwd, sandboxCwd, sessionId, handle }) => {
      let src = hostSessionDir(hostCwd, sessionId);
      if (!(await dirExists(src))) {
        const found = await findByIdOnHost(sessionId);
        if (found.path === undefined) {
          throw new Error(
            `grok-res: session "${sessionId}" not found under ${found.searchedRoot}`,
          );
        }
        src = found.path;
      }
      // Rewrite on a scratch copy — the host store stays untouched.
      const scratch = await mkdtemp(join(tmpdir(), "grok-res-"));
      try {
        const copy = join(scratch, "session");
        await cp(src, copy, { recursive: true });
        await rewriteSessionTexts(copy, hostCwd, sandboxCwd);
        // Write tar to a file (not stdout buffer) so the #884 utf8 chokepoint
        // can own the host subprocess without encoding:buffer escape hatches.
        const tarPath = join(scratch, "session.tar");
        await hostTar(
          ["-C", copy, "-cf", tarPath, "."],
          "grok-session:tar-create",
        );
        const tarBytes = await readFile(tarPath);
        const dst = posix.join(sandboxRoot, bucketFor(sandboxCwd), sessionId);
        const push = await handle.exec(
          `mkdir -p ${shellEscape(dst)} && base64 -d | tar -C ${shellEscape(dst)} -xf -`,
          { stdin: tarBytes.toString("base64") },
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
