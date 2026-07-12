/**
 * #884 — external-call clocks + timeout→retry→degrade chain (S8).
 *
 * Seam under test: `externalCall` public helpers. A never-responding provider
 * must hit the clock, retry as transient (×2), then surface a stage-named
 * exhaustion error — never hang silently.
 */
import { describe, expect, it, vi } from "vitest";
import {
  classifyExternalCallFailure,
  ExternalCallExhaustedError,
  ExternalCallTimeoutError,
  execFileAsyncWithTimeout,
  execFileWithTimeout,
  withExternalCallRetry,
  withProviderTimeout,
  DEFAULT_PROVIDER_TIMEOUT_MS,
  EXTERNAL_CALL_MAX_ATTEMPTS,
  type ExternalCallAttemptRecord,
} from "../src/externalCall.js";

describe("#884 external-call clocks", () => {
  it("classifies timeout / connection-reset / 5xx as transient, 429 as quota", () => {
    expect(
      classifyExternalCallFailure(
        new ExternalCallTimeoutError({
          stage: "smoke-k:opus",
          timeoutMs: 1000,
          seam: "provider",
        }),
      ),
    ).toBe("transient");
    expect(classifyExternalCallFailure(new Error("read ECONNRESET"))).toBe(
      "transient",
    );
    expect(classifyExternalCallFailure(new Error("socket hang up"))).toBe(
      "transient",
    );
    expect(classifyExternalCallFailure(new Error("HTTP 503 unavailable"))).toBe(
      "transient",
    );
    expect(classifyExternalCallFailure(new Error("HTTP 429 rate limit"))).toBe(
      "quota",
    );
    expect(classifyExternalCallFailure(new Error("quota exceeded"))).toBe(
      "quota",
    );
    expect(classifyExternalCallFailure(new Error("auth token expired"))).toBe(
      "durable",
    );
  });

  it("provider hang: AbortSignal.timeout fires a stage-named timeout error", async () => {
    await expect(
      withProviderTimeout(
        "probe:zai",
        async (signal) =>
          await new Promise<void>((_resolve, reject) => {
            signal.addEventListener("abort", () => {
              reject(
                signal.reason instanceof Error
                  ? signal.reason
                  : new Error(String(signal.reason)),
              );
            });
            // never resolve — pure hang
          }),
        { timeoutMs: 30 },
      ),
    ).rejects.toMatchObject({
      name: "ExternalCallTimeoutError",
      stage: "probe:zai",
      seam: "provider",
    });
  });

  it("subprocess hang: execFileAsyncWithTimeout kills the child and throws typed error", async () => {
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

  it("sync subprocess seam also carries timeout + stage", () => {
    expect(() =>
      execFileWithTimeout(
        process.execPath,
        ["-e", "setInterval(() => {}, 1000)"],
        { stage: "admission:gh", timeoutMs: 40 },
      ),
    ).toThrow(ExternalCallTimeoutError);
    try {
      execFileWithTimeout(
        process.execPath,
        ["-e", "setInterval(() => {}, 1000)"],
        { stage: "admission:gh", timeoutMs: 40 },
      );
    } catch (err) {
      expect(err).toMatchObject({
        name: "ExternalCallTimeoutError",
        stage: "admission:gh",
        seam: "subprocess",
      });
    }
  });

  it("positive: transient hang then success after retries (1 initial + 2)", async () => {
    let attempts = 0;
    const records: ExternalCallAttemptRecord[] = [];
    const value = await withExternalCallRetry(
      "smoke-k:sonnet",
      async () => {
        attempts += 1;
        if (attempts < 3) {
          throw new ExternalCallTimeoutError({
            stage: "smoke-k:sonnet",
            timeoutMs: 10,
            seam: "provider",
          });
        }
        return "PONG-nonce";
      },
      {
        sleepMs: async () => {},
        record: (r) => records.push(r),
      },
    );
    expect(value).toBe("PONG-nonce");
    expect(attempts).toBe(EXTERNAL_CALL_MAX_ATTEMPTS);
    expect(records.map((r) => r.outcome)).toEqual(["retry", "retry", "ok"]);
    expect(records.every((r) => r.stage === "smoke-k:sonnet")).toBe(true);
  });

  it("negative: never-responding provider exhausts retries → stage-named degrade", async () => {
    const records: ExternalCallAttemptRecord[] = [];
    await expect(
      withExternalCallRetry(
        "smoke-k:opus",
        async () => {
          throw new ExternalCallTimeoutError({
            stage: "smoke-k:opus",
            timeoutMs: 10,
            seam: "provider",
          });
        },
        {
          sleepMs: async () => {},
          record: (r) => records.push(r),
        },
      ),
    ).rejects.toBeInstanceOf(ExternalCallExhaustedError);

    try {
      await withExternalCallRetry(
        "smoke-k:opus",
        async () => {
          throw new ExternalCallTimeoutError({
            stage: "smoke-k:opus",
            timeoutMs: 10,
            seam: "provider",
          });
        },
        { sleepMs: async () => {}, record: (r) => records.push(r) },
      );
    } catch (err) {
      expect(err).toMatchObject({
        name: "ExternalCallExhaustedError",
        stage: "smoke-k:opus",
        attempts: EXTERNAL_CALL_MAX_ATTEMPTS,
      });
      expect((err as Error).message).toMatch(/smoke-k:opus/);
    }

    const exhausted = records.filter((r) => r.outcome === "exhausted");
    expect(exhausted.length).toBeGreaterThanOrEqual(1);
    expect(exhausted[0]?.stage).toBe("smoke-k:opus");
  });

  it("negative: quota/429 is NOT retried — surfaces immediately for park/degrade", async () => {
    let attempts = 0;
    const records: ExternalCallAttemptRecord[] = [];
    await expect(
      withExternalCallRetry(
        "probe:zai",
        async () => {
          attempts += 1;
          throw new Error("HTTP 429 rate limit — wait for reset");
        },
        {
          sleepMs: async () => {},
          record: (r) => records.push(r),
        },
      ),
    ).rejects.toThrow(/429/);
    expect(attempts).toBe(1);
    expect(records.map((r) => r.outcome)).toEqual(["quota"]);
  });

  it("default provider timeout is in the 60–120s probe band", () => {
    expect(DEFAULT_PROVIDER_TIMEOUT_MS).toBeGreaterThanOrEqual(60_000);
    expect(DEFAULT_PROVIDER_TIMEOUT_MS).toBeLessThanOrEqual(120_000);
  });

  it("records every attempt with stage name (no silent wait bookkeeping)", async () => {
    const onAttempt = vi.fn();
    const records: ExternalCallAttemptRecord[] = [];
    await withExternalCallRetry(
      "dispatch:S2",
      async () => "ok",
      {
        sleepMs: async () => {},
        onAttempt,
        record: (r) => records.push(r),
      },
    );
    expect(onAttempt).toHaveBeenCalledWith(1, "dispatch:S2");
    expect(records).toEqual([
      expect.objectContaining({
        stage: "dispatch:S2",
        attempt: 1,
        outcome: "ok",
      }),
    ]);
  });
});
