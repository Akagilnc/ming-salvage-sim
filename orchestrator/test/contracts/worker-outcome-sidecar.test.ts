import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import {
  readRequiredWorkerOutcomeSidecar,
  readWorkerOutcomeSidecar,
} from "../../src/workerOutcomeSidecar.js";

function withTempDir(prefix: string, fn: (dir: string) => void): void {
  const dir = mkdtempSync(join(tmpdir(), prefix));
  try {
    fn(dir);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

describe("worker outcome sidecar directory fallback", () => {
  it("treats an empty directory sidecar as absent for optional readers", () => {
    withTempDir("worker-sidecar-empty-dir-", (dir) => {
      const sidecarPath = join(dir, "outcome.json");
      mkdirSync(sidecarPath);

      expect(readWorkerOutcomeSidecar(sidecarPath)).toBeUndefined();
    });
  });

  it("reads a nested outcome.json when the mounted sidecar path is a directory", () => {
    withTempDir("worker-sidecar-nested-json-", (dir) => {
      const sidecarPath = join(dir, "outcome.json");
      mkdirSync(sidecarPath);
      writeFileSync(
        join(sidecarPath, "outcome.json"),
        '{"committed":true,"commitsAdded":1}\n',
        "utf8",
      );

      expect(readWorkerOutcomeSidecar(sidecarPath)).toEqual({
        committed: true,
        commitsAdded: 1,
      });
      expect(readRequiredWorkerOutcomeSidecar(sidecarPath)).toEqual({
        committed: true,
        commitsAdded: 1,
      });
    });
  });

  it("keeps required sidecars fail-closed when a directory has no nested JSON", () => {
    withTempDir("worker-sidecar-required-empty-dir-", (dir) => {
      const sidecarPath = join(dir, "outcome.json");
      mkdirSync(sidecarPath);

      expect(() => readRequiredWorkerOutcomeSidecar(sidecarPath)).toThrow(
        /directory.*outcome\.json/i,
      );
    });
  });
});
