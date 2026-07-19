import { execFile } from "node:child_process";

import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";

import { tmpdir } from "node:os";

import { join } from "node:path";

import type { BindMountSandboxHandle } from "@ai-hero/sandcastle";

import { afterEach, describe, expect, it, vi } from "vitest";

const faultState = { failAfterHostExtract: false };

const {
  makeGrokSessionStorage,
  grokSessionAtomicReplaceTestInject,
} = await import("../../src/grokSessionStorage.js");

const tempDirs: string[] = [];

function tmp(prefix: string): string {
  const d = mkdtempSync(join(tmpdir(), prefix));
  tempDirs.push(d);
  return d;
}

function oldBackupNames(bucketDir: string, sessionId: string): string[] {
  if (!existsSync(bucketDir)) return [];
  return readdirSync(bucketDir).filter(
    (n) => n.startsWith(`.${sessionId}.old-`) || n.includes(`.old-`),
  );
}

function localHandleWithStdin(worktreePath: string): BindMountSandboxHandle {
  return {
    worktreePath,
    exec: (
      command: string,
      options?: {
        onLine?: (line: string) => void;
        cwd?: string;
        sudo?: boolean;
        stdin?: string;
      },
    ): Promise<{ stdout: string; stderr: string; exitCode: number }> =>
      new Promise((resolve) => {
        const child = execFile(
          "bash",
          ["-c", command],
          { cwd: options?.cwd ?? worktreePath, maxBuffer: 64 * 1024 * 1024 },
          (err, stdout, stderr) => {
            const code = err ? ((err as { code?: number }).code ?? 1) : 0;
            resolve({
              stdout: String(stdout),
              stderr: String(stderr),
              exitCode: typeof code === "number" ? code : 1,
            });
          },
        );
        if (options?.stdin !== undefined) {
          child.stdin?.write(options.stdin);
        }
        child.stdin?.end();
      }),
    copyFileIn: async () => {},
    copyFileOut: async () => {},
    close: async () => {},
  };
}

function seedSandboxSession(
  sandboxFs: string,
  sbxSessions: string,
  sandboxCwd: string,
  sessionId: string,
  files: Record<string, string>,
): void {
  const dir = join(sbxSessions, encodeURIComponent(sandboxCwd), sessionId);
  mkdirSync(dir, { recursive: true });
  for (const [name, body] of Object.entries(files)) {
    writeFileSync(join(dir, name), body);
  }
}

function seedHostSession(
  hostRoot: string,
  hostCwd: string,
  sessionId: string,
  files: Record<string, string>,
): string {
  const dir = join(hostRoot, encodeURIComponent(hostCwd), sessionId);
  mkdirSync(dir, { recursive: true });
  for (const [name, body] of Object.entries(files)) {
    writeFileSync(join(dir, name), body);
  }
  return dir;
}

export {
  execFile,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  symlinkSync,
  writeFileSync,
  tmpdir,
  join,
  BindMountSandboxHandle,
  afterEach,
  describe,
  expect,
  it,
  vi,
  faultState,
  makeGrokSessionStorage,
  grokSessionAtomicReplaceTestInject,
  tempDirs,
  tmp,
  oldBackupNames,
  localHandleWithStdin,
  seedSandboxSession,
  seedHostSession,
};
