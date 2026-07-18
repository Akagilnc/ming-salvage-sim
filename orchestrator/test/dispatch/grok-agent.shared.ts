import { spawn } from "node:child_process";

import {
  chmodSync,
  mkdirSync,
  mkdtempSync,
  readdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";

import { tmpdir } from "node:os";

import { join } from "node:path";

import { afterEach, describe, expect, it } from "vitest";

import {
  createGrokStreamParser,
  grokAgent,
  shellEscape,
} from "../../src/grokAgent.js";

import {
  POOL_DISPATCH_BINDINGS,
  agentForSlug,
  resolveModelSlug,
  resolveModelSlugForPool,
} from "../../src/modelRegistry.js";

import { barePingArgv, barePingNonceSatisfied } from "../../src/realBackend.js";

import { routeSmokeEntries, resolveRouteModels } from "../../src/modelRoutes.js";

const transportDirs: string[] = [];

function transportDir(prefix: string): string {
  const dir = mkdtempSync(join(tmpdir(), prefix));
  transportDirs.push(dir);
  return dir;
}

function transportEnv(
  binDir: string,
  staging: string,
  pathOut: string,
  childPidOut: string,
  extra: NodeJS.ProcessEnv = {},
): NodeJS.ProcessEnv {
  return {
    ...process.env,
    PATH: `${binDir}:${process.env.PATH ?? ""}`,
    TMPDIR: staging,
    GROK_PROMPT_PATH_OUT: pathOut,
    GROK_CHILD_PID_OUT: childPidOut,
    // Harness-only: default off so a polluted parent env cannot hang normal-exit cases.
    GROK_HOLD_OPEN: "0",
    GROK_EXIT_CODE: "0",
    ...extra,
  };
}

function fakeGrokPath(binDir: string): string {
  const path = join(binDir, "grok");
  writeFileSync(
    path,
    "#!/bin/sh\ncat \"$2\"\nprintf '%s' \"$2\" > \"$GROK_PROMPT_PATH_OUT\"\nprintf '%s' \"$$\" > \"$GROK_CHILD_PID_OUT\"\nif [ \"${GROK_HOLD_OPEN:-0}\" = 1 ]; then exec sleep 30; fi\nexit \"${GROK_EXIT_CODE:-0}\"\n",
    "utf8",
  );
  chmodSync(path, 0o755);
  return path;
}

export {
  spawn,
  chmodSync,
  mkdirSync,
  mkdtempSync,
  readdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
  tmpdir,
  join,
  afterEach,
  describe,
  expect,
  it,
  createGrokStreamParser,
  grokAgent,
  shellEscape,
  POOL_DISPATCH_BINDINGS,
  agentForSlug,
  resolveModelSlug,
  resolveModelSlugForPool,
  barePingArgv,
  barePingNonceSatisfied,
  routeSmokeEntries,
  resolveRouteModels,
  transportDirs,
  transportDir,
  transportEnv,
  fakeGrokPath,
};
