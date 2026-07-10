import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { afterEach, describe, expect, it } from "vitest";

import {
  CONTAINER_CODEX_CONFIG_TOML,
  writeContainerCodexConfig,
} from "../src/containerCodexConfig.js";
import { codexFastRunLog } from "../src/familyDriver.js";

const tempDirs: string[] = [];

afterEach(() => {
  for (const dir of tempDirs.splice(0)) rmSync(dir, { recursive: true, force: true });
});

function write(fast: boolean): string {
  const dir = mkdtempSync(join(tmpdir(), "codex-fast-760-"));
  tempDirs.push(dir);
  const path = join(dir, "config.toml");
  writeContainerCodexConfig(path, fast);
  return readFileSync(path, "utf8");
}

describe("#760 container Codex fast master switch", () => {
  it("keeps the current config byte-identical when fast is off", () => {
    expect(write(false)).toBe(CONTAINER_CODEX_CONFIG_TOML);
  });

  it("adds the fast service tier when enabled", () => {
    expect(write(true)).toBe(
      `${CONTAINER_CODEX_CONFIG_TOML}service_tier = "fast"\n`,
    );
  });

  it("makes the resolved setting visible in the run-level log line", () => {
    expect(codexFastRunLog(true)).toBe("[orchestrator] run fast=on");
    expect(codexFastRunLog(false)).toBe("[orchestrator] run fast=off");
  });
});
