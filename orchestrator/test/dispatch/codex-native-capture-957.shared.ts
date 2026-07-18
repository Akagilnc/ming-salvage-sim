import { execFile } from "node:child_process";

import {
  copyFileSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";

import { tmpdir } from "node:os";

import { dirname, join } from "node:path";

import { fileURLToPath } from "node:url";

import type { BindMountSandboxHandle } from "@ai-hero/sandcastle";

import * as sc from "@ai-hero/sandcastle";

import { afterEach, describe, expect, it } from "vitest";

import {
  agentForSlug,
} from "../../src/modelRegistry.js";

const tempDirs: string[] = [];

function tmp(prefix: string): string {
  const d = mkdtempSync(join(tmpdir(), prefix));
  tempDirs.push(d);
  return d;
}

function localHandle(worktreePath: string): BindMountSandboxHandle {
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
    copyFileIn: async (hostPath: string, sandboxPath: string) => {
      mkdirSync(dirname(sandboxPath), { recursive: true });
      copyFileSync(hostPath, sandboxPath);
    },
    copyFileOut: async (sandboxPath: string, hostPath: string) => {
      mkdirSync(dirname(hostPath), { recursive: true });
      copyFileSync(sandboxPath, hostPath);
    },
    close: async () => {},
  };
}

const CODEX_SLUGS = [
  "gpt-5.6-sol",
  "gpt-5.6-sol-high",
  "gpt-5.6-sol-low",
  "gpt-5.6-luna",
  "gpt-5.6-terra",
] as const;

const STORAGE_METHODS = [
  "captureToHost",
  "resumeIntoSandbox",
  "readHostSession",
  "existsOnHost",
  "hostSessionFilePath",
  "findByIdOnHost",
] as const;

export {
  execFile,
  copyFileSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
  tmpdir,
  dirname,
  join,
  fileURLToPath,
  BindMountSandboxHandle,
  sc,
  afterEach,
  describe,
  expect,
  it,
  agentForSlug,
  tempDirs,
  tmp,
  localHandle,
  CODEX_SLUGS,
  STORAGE_METHODS,
};
