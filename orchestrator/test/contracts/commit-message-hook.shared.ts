import { describe, it, expect, beforeEach, afterEach } from "vitest";

import { execFileSync } from "node:child_process";

import { mkdtempSync, writeFileSync, readFileSync, rmSync, statSync } from "node:fs";

import { tmpdir } from "node:os";

import { join, dirname } from "node:path";

import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));

const HOOK = join(here, "..", "..", "image", "hooks", "commit-msg");

const hookState = { dir: "" };

function runHook(message: string): string {
  const f = join(hookState.dir, "COMMIT_EDITMSG");
  writeFileSync(f, message);
  execFileSync("sh", [HOOK, f]);
  return readFileSync(f, "utf8");
}

export {
  describe,
  it,
  expect,
  beforeEach,
  afterEach,
  execFileSync,
  mkdtempSync,
  writeFileSync,
  readFileSync,
  rmSync,
  statSync,
  tmpdir,
  join,
  dirname,
  fileURLToPath,
  here,
  HOOK,
  hookState,
  runHook,
};
