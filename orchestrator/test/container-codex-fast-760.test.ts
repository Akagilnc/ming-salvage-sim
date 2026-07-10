import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  CONTAINER_CODEX_CONFIG_TOML,
  writeContainerCodexConfig,
} from "../src/containerCodexConfig.js";
import { codexFastRunLog, resolveCodexFast } from "../src/familyDriver.js";

const tempDirs: string[] = [];

afterEach(() => {
  delete process.env.ORCHESTRATOR_CODEX_FAST;
  for (const dir of tempDirs.splice(0)) rmSync(dir, { recursive: true, force: true });
});

function resolveAndWrite(): {
  fast: boolean;
  config: string;
  log: string;
  writer: ReturnType<typeof vi.fn<typeof writeContainerCodexConfig>>;
} {
  const fast = resolveCodexFast({});
  const dir = mkdtempSync(join(tmpdir(), "codex-fast-760-assembly-"));
  tempDirs.push(dir);
  const path = join(dir, "config.toml");
  const writer = vi.fn(writeContainerCodexConfig);
  writer(path, fast);
  return { fast, config: readFileSync(path, "utf8"), log: codexFastRunLog(fast), writer };
}

function write(fast: boolean): string {
  const dir = mkdtempSync(join(tmpdir(), "codex-fast-760-"));
  tempDirs.push(dir);
  const path = join(dir, "config.toml");
  writeContainerCodexConfig(path, fast);
  return readFileSync(path, "utf8");
}

describe("#760 container Codex fast master switch", () => {
  it("assembles env resolution into the writer and run log for both states", () => {
    process.env.ORCHESTRATOR_CODEX_FAST = "1";
    const on = resolveAndWrite();
    expect(on.fast).toBe(true);
    expect(on.writer).toHaveBeenCalledWith(expect.any(String), true);
    expect(on.config).toBe(`${CONTAINER_CODEX_CONFIG_TOML}service_tier = "fast"\n`);
    expect(on.log).toBe("[orchestrator] run fast=on");

    delete process.env.ORCHESTRATOR_CODEX_FAST;
    const off = resolveAndWrite();
    expect(off.fast).toBe(false);
    expect(off.writer).toHaveBeenCalledWith(expect.any(String), false);
    expect(off.config).toBe(CONTAINER_CODEX_CONFIG_TOML);
    expect(off.log).toBe("[orchestrator] run fast=off");
  });

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
