import { execFile } from "node:child_process";

import {
  mkdtempSync,
  mkdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
  existsSync,
} from "node:fs";

import { tmpdir } from "node:os";

import { join } from "node:path";

import type { BindMountSandboxHandle } from "@ai-hero/sandcastle";

import { afterEach, describe, expect, it } from "vitest";

import { grokAgent } from "../../src/grokAgent.js";

import { resumeCapableForSlug } from "../../src/modelRegistry.js";

const tempDirs: string[] = [];

function tmp(prefix: string): string {
  const d = mkdtempSync(join(tmpdir(), prefix));
  tempDirs.push(d);
  return d;
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
            const code = err
              ? ((err as { code?: number }).code ?? 1)
              : 0;
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

const RUN_GROK_RESUME_SMOKE = process.env.GROK_RESUME_SMOKE === "1";

export {
  execFile,
  mkdtempSync,
  mkdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
  existsSync,
  tmpdir,
  join,
  BindMountSandboxHandle,
  afterEach,
  describe,
  expect,
  it,
  grokAgent,
  resumeCapableForSlug,
  tempDirs,
  tmp,
  localHandleWithStdin,
  RUN_GROK_RESUME_SMOKE,
};
