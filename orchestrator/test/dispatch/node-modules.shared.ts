import { execFileSync } from "node:child_process";

import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";

import { tmpdir } from "node:os";

import { dirname, join } from "node:path";

import { fileURLToPath } from "node:url";

import { afterEach, describe, expect, it } from "vitest";

import type * as sc from "@ai-hero/sandcastle";

import { _resetGitMutex } from "../../src/gitMutex.js";

import {
  canClonefileNodeModules,
  listNodeProjectDirs,
  lockfileFingerprint,
  packageJsonFingerprint,
  provisionNodeModules,
  provisionRepoNodeModules,
  resolveTemplateProjectDir,
} from "../../src/provisionNodeModules.js";

import {
  RealFamilyBackend,
  type RealFamilyBackendOptions,
} from "../../src/family/realFamilyBackend.js";

import {
  clonePathFor,
  RealBackend,
  type RealBackendOptions,
  repoSlug,
} from "../../src/realBackend.js";

import { buildExplicitLandingLiveHooks } from "../../src/family/landing.js";

const here = dirname(fileURLToPath(import.meta.url));

const realPromptsDir = join(here, "..", "..", "prompts");

const realSoulsDir = join(here, "..", "..", "image", "souls");

function runCpCompat(args: string[]): void {
  const compatibleArgs =
    process.platform === "darwin"
      ? args
      : args.map((arg) => (arg === "-cR" || arg === "-Rc" ? "-R" : arg));
  execFileSync("cp", compatibleArgs, { encoding: "utf8" });
}

const cleanups: string[] = [];

function mkDir(prefix: string): string {
  const d = mkdtempSync(join(tmpdir(), prefix));
  cleanups.push(d);
  return d;
}

function writeProject(
  root: string,
  opts: { lock?: string; withModules?: boolean; modulesMarker?: string } = {},
): void {
  mkdirSync(root, { recursive: true });
  writeFileSync(
    join(root, "package.json"),
    JSON.stringify({ name: "proj", version: "0.0.0", scripts: { test: "echo ok" } }),
  );
  if (opts.lock !== undefined) {
    writeFileSync(join(root, "package-lock.json"), opts.lock);
  }
  if (opts.withModules) {
    const nm = join(root, "node_modules");
    mkdirSync(nm, { recursive: true });
    writeFileSync(join(nm, ".marker"), opts.modulesMarker ?? "from-template");
  }
}

const LOCK_A = JSON.stringify({ name: "proj", version: "0.0.0", lockfileVersion: 3 });

const LOCK_B = JSON.stringify({
  name: "proj",
  version: "0.0.1",
  lockfileVersion: 3,
  mutated: true,
});

export {
  execFileSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
  tmpdir,
  dirname,
  join,
  fileURLToPath,
  afterEach,
  describe,
  expect,
  it,
  sc,
  _resetGitMutex,
  canClonefileNodeModules,
  listNodeProjectDirs,
  lockfileFingerprint,
  packageJsonFingerprint,
  provisionNodeModules,
  provisionRepoNodeModules,
  resolveTemplateProjectDir,
  RealFamilyBackend,
  RealFamilyBackendOptions,
  clonePathFor,
  RealBackend,
  RealBackendOptions,
  repoSlug,
  buildExplicitLandingLiveHooks,
  here,
  realPromptsDir,
  realSoulsDir,
  runCpCompat,
  cleanups,
  mkDir,
  writeProject,
  LOCK_A,
  LOCK_B,
};
