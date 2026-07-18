/**
 * #884 — external-call clocks only (S8).
 * Retry policy lives in #879 legTransientRetry — not re-tested as a platform here.
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  classifyExternalCallFailure,
  ExternalCallTimeoutError,
  execFileAsyncWithTimeout,
  execFileWithTimeout,
  withProviderTimeout,
  DEFAULT_PROVIDER_TIMEOUT_MS,
  shWithClock,
} from "../../src/externalCall.js";
import {
  MAX_LEG_TRANSIENT_ATTEMPTS,
  withLegTransientRetry,
} from "../../src/legTransientRetry.js";

describe("#884 external-call clocks", () => {

  it("subprocess hang: execFileAsyncWithTimeout kills child + typed error", async () => {
    await expect(
      execFileAsyncWithTimeout(
        process.execPath,
        ["-e", "setInterval(() => {}, 1000)"],
        { stage: "smoke-k:codex", timeoutMs: 40 },
      ),
    ).rejects.toMatchObject({
      name: "ExternalCallTimeoutError",
      stage: "smoke-k:codex",
      seam: "subprocess",
    });
  });

  it("subprocess stdin EPIPE rejects the call instead of escaping the promise", async () => {
    const input = "x".repeat(16 * 1024 * 1024);
    await expect(
      execFileAsyncWithTimeout(
        process.execPath,
        ["-e", "process.stdin.destroy(); setTimeout(() => process.exit(0), 20)"],
        { stage: "bare-ping:stdin", timeoutMs: 2_000, input },
      ),
    ).rejects.toMatchObject({ code: "EPIPE" });
  });

  it("sync subprocess seam carries timeout + stage", () => {
    expect(() =>
      execFileWithTimeout(
        process.execPath,
        ["-e", "setInterval(() => {}, 1000)"],
        { stage: "admission:gh", timeoutMs: 40 },
      ),
    ).toThrow(ExternalCallTimeoutError);
  });

  it("shWithClock is one-shot (no retry platform) — timeout surfaces once", () => {
    expect(() =>
      shWithClock(
        process.execPath,
        ["-e", "setInterval(() => {}, 1000)"],
        { stage: "subprocess:git", timeoutMs: 40 },
      ),
    ).toThrow(/timed out|ExternalCallTimeout/i);
  });

});
