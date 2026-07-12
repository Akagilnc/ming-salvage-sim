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
  withExternalCallRetrySync,
  withProviderTimeout,
  DEFAULT_PROVIDER_TIMEOUT_MS,
  EXTERNAL_CALL_MAX_ATTEMPTS,
  shWithClock,
  hostSubprocessRetryAttempts,
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
    // DNS/route blips — node err.code path (not free-text "network")
    const eai = new Error("getaddrinfo EAI_AGAIN api.example.com");
    (eai as { code?: string }).code = "EAI_AGAIN";
    expect(classifyExternalCallFailure(eai)).toBe("transient");
    const enet = new Error("connect ENETUNREACH");
    (enet as { code?: string }).code = "ENETUNREACH";
    expect(classifyExternalCallFailure(enet)).toBe("transient");
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
    // Status-first free text: 5xx token beats quota vocabulary (opencode path).
    expect(
      classifyExternalCallFailure(
        "HTTP 503 upstream quota / rate limit text in 503 body",
      ),
    ).toBe("transient");
    expect(
      classifyExternalCallFailure("exit 1: HTTP 429 rate limit exceeded"),
    ).toBe("quota");
  });

  it("provider hang: non-cooperative promise still times out (wrapper races abort)", async () => {
    // #884 hang class: provider never settles AND ignores AbortSignal.
    // The wrapper must still reject — cooperative signal handling alone is not enough.
    await expect(
      withProviderTimeout(
        "probe:zai",
        async (_signal) =>
          await new Promise<void>(() => {
            // never resolve, never listen to signal
          }),
        { timeoutMs: 40 },
      ),
    ).rejects.toMatchObject({
      name: "ExternalCallTimeoutError",
      stage: "probe:zai",
      seam: "provider",
    });
  });

  it("provider hang through retry: timeout → transient ×2 → stage-named exhaust", async () => {
    const records: ExternalCallAttemptRecord[] = [];
    await expect(
      withExternalCallRetry(
        "probe:never",
        () =>
          withProviderTimeout(
            "probe:never",
            async () =>
              await new Promise<void>(() => {
                /* hang */
              }),
            { timeoutMs: 25 },
          ),
        {
          sleepMs: async () => {},
          record: (r) => records.push(r),
        },
      ),
    ).rejects.toMatchObject({
      name: "ExternalCallExhaustedError",
      stage: "probe:never",
      attempts: EXTERNAL_CALL_MAX_ATTEMPTS,
    });
    expect(records.map((r) => r.outcome)).toEqual([
      "retry",
      "retry",
      "exhausted",
    ]);
    expect(records.every((r) => r.stage === "probe:never")).toBe(true);
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

  it("sync seam: transient timeout retries ×2 then exhausts with stage name", () => {
    let attempts = 0;
    const records: ExternalCallAttemptRecord[] = [];
    expect(() =>
      withExternalCallRetrySync(
        "admission:gh",
        () => {
          attempts += 1;
          throw new ExternalCallTimeoutError({
            stage: "admission:gh",
            timeoutMs: 10,
            seam: "subprocess",
          });
        },
        {
          sleepMs: () => {},
          record: (r) => records.push(r),
        },
      ),
    ).toThrow(ExternalCallExhaustedError);
    expect(attempts).toBe(EXTERNAL_CALL_MAX_ATTEMPTS);
    expect(records.map((r) => r.outcome)).toEqual([
      "retry",
      "retry",
      "exhausted",
    ]);
    expect(records.every((r) => r.stage === "admission:gh")).toBe(true);
  });

  it("sync seam: 429/quota is NOT retried", () => {
    let attempts = 0;
    const records: ExternalCallAttemptRecord[] = [];
    expect(() =>
      withExternalCallRetrySync(
        "admission:gh",
        () => {
          attempts += 1;
          throw new Error("HTTP 429 rate limit");
        },
        {
          sleepMs: () => {},
          record: (r) => records.push(r),
        },
      ),
    ).toThrow(/429/);
    expect(attempts).toBe(1);
    expect(records.map((r) => r.outcome)).toEqual(["quota"]);
  });

  it("mutation seam defaults to no-retry (retry:false → 1 attempt even outside vitest)", () => {
    const prev = process.env.VITEST;
    delete process.env.VITEST;
    try {
      expect(hostSubprocessRetryAttempts({ retry: false })).toBe(1);
      expect(hostSubprocessRetryAttempts({ retry: true })).toBe(
        EXTERNAL_CALL_MAX_ATTEMPTS,
      );
      expect(hostSubprocessRetryAttempts({})).toBe(EXTERNAL_CALL_MAX_ATTEMPTS);
    } finally {
      if (prev === undefined) delete process.env.VITEST;
      else process.env.VITEST = prev;
    }
  });

  it("production shape: shWithClock({retry:false}) never re-fires a timed-out mutation", () => {
    const prev = process.env.VITEST;
    delete process.env.VITEST;
    try {
      // Point at a hanging node so the clock fires; retry:false must not re-spawn.
      expect(() =>
        shWithClock(
          process.execPath,
          ["-e", "setInterval(() => {}, 1000)"],
          {
            stage: "subprocess:git-push-mutation",
            timeoutMs: 40,
            retry: false,
          },
        ),
      ).toThrow(/timed out|ExternalCallTimeout/i);
    } finally {
      if (prev === undefined) delete process.env.VITEST;
      else process.env.VITEST = prev;
    }
  });

  it("RealBackend/RealFamilyBackend mixed sh seam disables mutation retry", async () => {
    const { readFileSync } = await import("node:fs");
    const { join, dirname } = await import("node:path");
    const { fileURLToPath } = await import("node:url");
    const here = dirname(fileURLToPath(import.meta.url));
    const realBackend = readFileSync(
      join(here, "../src/realBackend.ts"),
      "utf8",
    );
    const familyBackend = readFileSync(
      join(here, "../src/family/realFamilyBackend.ts"),
      "utf8",
    );
    const familyDriver = readFileSync(
      join(here, "../src/familyDriver.ts"),
      "utf8",
    );
    const workerMonitor = readFileSync(
      join(here, "../src/workerMonitor.ts"),
      "utf8",
    );
    // Class-level sh is a mixed read/write seam — must default retry:false so
    // git push/merge/clone and gh writes are exactly-once on timeout.
    expect(realBackend).toMatch(
      /protected sh\([\s\S]*?shWithClock\([\s\S]*?retry:\s*false/,
    );
    expect(familyBackend).toMatch(
      /protected sh\([\s\S]*?shWithClock\([\s\S]*?retry:\s*false/,
    );
    // familyDriver defaultSh also cuts git branches — same exactly-once rule.
    expect(familyDriver).toMatch(
      /defaultSh[\s\S]*?shWithClock\([\s\S]*?retry:\s*false/,
    );
    // Spawn acknowledgement must carry a stage-named clock (no infinite wait).
    expect(workerMonitor).toMatch(/dispatch:\$\{input\.stepId\}:spawn/);
    expect(workerMonitor).toMatch(/ExternalCallTimeoutError/);
    // kill-axis: spawn-ack timer rejects with timeout only — no bare-PID kill
    // between setTimeout callback open and its close (cmr r10).
    const spawnTimer = workerMonitor.match(
      /const timer = setTimeout\(\(\) => \{([\s\S]*?)\}, spawnTimeoutMs\)/,
    );
    expect(spawnTimer?.[1] ?? "").toMatch(/ExternalCallTimeoutError/);
    expect(spawnTimer?.[1] ?? "").not.toMatch(/process\.kill\s*\(/);
  });
});
