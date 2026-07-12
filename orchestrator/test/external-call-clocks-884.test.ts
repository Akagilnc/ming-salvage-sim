/**
 * #884 — external-call clocks only (S8).
 * Retry policy lives in #879 legTransientRetry — not re-tested as a platform here.
 */
import { describe, expect, it } from "vitest";
import {
  classifyExternalCallFailure,
  ExternalCallTimeoutError,
  execFileAsyncWithTimeout,
  execFileWithTimeout,
  withProviderTimeout,
  DEFAULT_PROVIDER_TIMEOUT_MS,
  shWithClock,
} from "../src/externalCall.js";
import {
  MAX_LEG_TRANSIENT_ATTEMPTS,
  withLegTransientRetry,
} from "../src/legTransientRetry.js";

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
    expect(
      classifyExternalCallFailure(
        "HTTP 503 upstream quota / rate limit text in 503 body",
      ),
    ).toBe("transient");
    expect(
      classifyExternalCallFailure("exit 1: HTTP 429 rate limit exceeded"),
    ).toBe("quota");
    const auth401 = Object.assign(new Error("network authentication failed"), {
      status: 401,
    });
    expect(classifyExternalCallFailure(auth401)).toBe("durable");
    const forbid403 = Object.assign(new Error("quota access denied"), {
      status: 403,
    });
    expect(classifyExternalCallFailure(forbid403)).toBe("durable");
    expect(classifyExternalCallFailure(new Error("HTTP 401 unauthorized"))).toBe(
      "durable",
    );
    expect(
      classifyExternalCallFailure(new Error("request timed out after 120 seconds")),
    ).toBe("transient");
    expect(
      classifyExternalCallFailure(
        new Error("connection closed after 300 seconds"),
      ),
    ).toBe("transient");
    expect(
      classifyExternalCallFailure(
        new Error("quota exceeded; remaining credits 500"),
      ),
    ).toBe("quota");
    expect(
      classifyExternalCallFailure(
        new Error("network error: rate limit exceeded"),
      ),
    ).toBe("quota");
    const stdoutOnly = Object.assign(new Error("Command failed: opencode"), {
      stdout: "network error: ECONNRESET",
      stderr: "",
    });
    expect(classifyExternalCallFailure(stdoutOnly)).toBe("transient");
  });

  it("provider hang: non-cooperative promise still times out", async () => {
    await expect(
      withProviderTimeout(
        "probe:zai",
        async (_signal) =>
          await new Promise<void>(() => {
            /* hang */
          }),
        { timeoutMs: 40 },
      ),
    ).rejects.toMatchObject({
      name: "ExternalCallTimeoutError",
      stage: "probe:zai",
      seam: "provider",
    });
  });

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

  it("sync subprocess seam carries timeout + stage", () => {
    expect(() =>
      execFileWithTimeout(
        process.execPath,
        ["-e", "setInterval(() => {}, 1000)"],
        { stage: "admission:gh", timeoutMs: 40 },
      ),
    ).toThrow(ExternalCallTimeoutError);
  });

  it("default provider timeout is in the 60–120s probe band", () => {
    expect(DEFAULT_PROVIDER_TIMEOUT_MS).toBeGreaterThanOrEqual(60_000);
    expect(DEFAULT_PROVIDER_TIMEOUT_MS).toBeLessThanOrEqual(120_000);
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

  it("leg layer (#879) owns retry around provider clock", async () => {
    let attempts = 0;
    await expect(
      withLegTransientRetry(
        async () => {
          attempts += 1;
          throw new ExternalCallTimeoutError({
            stage: "probe:never",
            timeoutMs: 10,
            seam: "provider",
          });
        },
        { sleepMs: async () => {} },
      ),
    ).rejects.toBeInstanceOf(ExternalCallTimeoutError);
    expect(attempts).toBe(MAX_LEG_TRANSIENT_ATTEMPTS);
  });

  it("production seams route host sh through shWithClock (clock only)", async () => {
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
    const externalCall = readFileSync(
      join(here, "../src/externalCall.ts"),
      "utf8",
    );
    // No retry platform in the clock module.
    expect(externalCall).not.toMatch(/withExternalCallRetry/);
    expect(externalCall).not.toMatch(/ExternalCallExhaustedError/);
    expect(externalCall).not.toMatch(/EXTERNAL_CALL_MAX_ATTEMPTS/);
    expect(realBackend).toMatch(
      /protected sh\([\s\S]*?shWithClock\(/,
    );
    expect(familyBackend).toMatch(
      /protected sh\([\s\S]*?shWithClock\(/,
    );
    expect(familyDriver).toMatch(/shWithClock\(/);
    expect(workerMonitor).toMatch(/dispatch:\$\{input\.stepId\}:spawn/);
    expect(workerMonitor).toMatch(/ExternalCallTimeoutError/);
    const spawnTimer = workerMonitor.match(
      /const timer = setTimeout\(\(\) => \{([\s\S]*?)\}, spawnTimeoutMs\)/,
    );
    expect(spawnTimer?.[1] ?? "").toMatch(/ExternalCallTimeoutError/);
    expect(spawnTimer?.[1] ?? "").not.toMatch(/process\.kill\s*\(/);
  });
});
