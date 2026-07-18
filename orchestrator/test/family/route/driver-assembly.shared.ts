import { execFileSync } from "node:child_process";

import { mkdtempSync, rmSync } from "node:fs";

import { tmpdir } from "node:os";

import { dirname, join } from "node:path";

import { fileURLToPath } from "node:url";

import { afterEach, describe, expect, it, vi } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));

const realPromptsDir = join(here, "..", "..", "..", "prompts");

const realSoulsDir = join(here, "..", "..", "..", "image", "souls");

import {
  buildFamilyEpic,
  cutFamilyBase,
  discoverSubprojects,
  filterExternalBlockedChildren,
  FamilyRootBlockerError,
  inferVerifyCwd,
  parseSubIssueAdmission,
  readFamilyEpic,
  type Sh,
} from "../../../src/familyDriver.js";

import { RealFamilyBackend } from "../../../src/family/realFamilyBackend.js";

import type { GhBlockedBy } from "../../../src/realBackend.js";

function git(cwd: string, ...args: string[]): string {
  return execFileSync("git", args, { cwd, encoding: "utf8" }).trim();
}

const cleanups: string[] = [];

export {
  execFileSync,
  mkdtempSync,
  rmSync,
  tmpdir,
  dirname,
  join,
  fileURLToPath,
  afterEach,
  describe,
  expect,
  it,
  vi,
  here,
  realPromptsDir,
  realSoulsDir,
  buildFamilyEpic,
  cutFamilyBase,
  discoverSubprojects,
  filterExternalBlockedChildren,
  FamilyRootBlockerError,
  inferVerifyCwd,
  parseSubIssueAdmission,
  readFamilyEpic,
  Sh,
  RealFamilyBackend,
  GhBlockedBy,
  git,
  cleanups,
};
