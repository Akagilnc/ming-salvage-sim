/**
 * #955 — sandcastle AgentSessionStorage for the grok CLI.
 *
 * Sandcastle's resume capability predicate is `provider.sessionStorage`
 * (interface-based; the "claudeCode, codex, or pi" in its error text is
 * prose). The grok CLI stores each session as a DIRECTORY —
 * `<sessionsRoot>/<encodeURIComponent(cwd)>/<sessionId>/` holding
 * chat_history.jsonl / events.jsonl / state files — so host↔sandbox transfer
 * moves a whole directory (tar over the sandbox exec channel, base64-armored
 * because exec streams text lines), rewriting absolute cwd paths inside the
 * JSON/JSONL files the same way sandcastle's codex storage does.
 */

import { execFile } from "node:child_process";
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
import { promisify } from "node:util";
import type * as sc from "@ai-hero/sandcastle";
import { shellEscape } from "./shellEscape.js";

const execFileP = promisify(execFile);

type Storage = NonNullable<sc.AgentProvider["sessionStorage"]>;
type HostSessionLookup = Awaited<ReturnType<Storage["findByIdOnHost"]>>;
type SandboxHandle = Parameters<Storage["captureToHost"]>[0]["handle"];

export interface GrokSessionStorageOptions {
  /** Override the host session root (default `~/.grok/sessions`). */
  readonly hostSessionsDir?: string;
  /** Override the in-sandbox session root (default `/home/agent/.grok/sessions`). */
  readonly sandboxSessionsDir?: string;
}

const bucketFor = (cwd: string): string => encodeURIComponent(cwd);

async function dirExists(path: string): Promise<boolean> {
  try {
    return (await stat(path)).isDirectory();
  } catch {
    return false;
  }
}

/** Rewrite absolute cwd strings inside the session's text files (json/jsonl). */
async function rewriteSessionTexts(
  dir: string,
  from: string,
  to: string,
): Promise<void> {
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
    await writeFile(p, body.split(from).join(to));
  }
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
      const result = await (handle as SandboxHandle).exec(
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
        await execFileP("tar", ["-C", target, "-xf", tarPath]);
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
        const { stdout } = await execFileP(
          "tar",
          ["-C", copy, "-cf", "-", "."],
          { encoding: "buffer", maxBuffer: 256 * 1024 * 1024 } as never,
        );
        const dst = posix.join(sandboxRoot, bucketFor(sandboxCwd), sessionId);
        const push = await (handle as SandboxHandle).exec(
          `mkdir -p ${shellEscape(dst)} && base64 -d | tar -C ${shellEscape(dst)} -xf -`,
          { stdin: (stdout as unknown as Buffer).toString("base64") },
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
