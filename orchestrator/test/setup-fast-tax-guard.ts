import { vi } from "vitest";

const PROCESS_APIS = [
  "exec",
  "execFile",
  "execFileSync",
  "execSync",
  "fork",
  "spawn",
  "spawnSync",
] as const;

vi.mock("node:child_process", async (importOriginal) => {
  const childProcess = await importOriginal<typeof import("node:child_process")>();
  const guarded = { ...childProcess };

  for (const api of PROCESS_APIS) {
    guarded[api] = (() => {
      throw new Error(`[fast-tax-guard] real process API reached: ${api}`);
    }) as never;
  }

  return guarded;
});
