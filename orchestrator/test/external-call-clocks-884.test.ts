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
} from "../src/externalCall.js";
import {
  MAX_LEG_TRANSIENT_ATTEMPTS,
  withLegTransientRetry,
} from "../src/legTransientRetry.js";

describe("#884 external-call clocks", () => {
  it("classifies failures from typed timeout, code, and numeric status only", () => {
    expect(
      classifyExternalCallFailure(
        new ExternalCallTimeoutError({
          stage: "smoke-k:opus",
          timeoutMs: 1000,
          seam: "provider",
        }),
      ),
    ).toBe("transient");
    const eai = new Error("getaddrinfo EAI_AGAIN api.example.com");
    (eai as { code?: string }).code = "EAI_AGAIN";
    expect(classifyExternalCallFailure(eai)).toBe("transient");
    const resetWithCause = new TypeError("fetch failed", {
      cause: Object.assign(new Error("socket reset"), { code: "ECONNRESET" }),
    });
    expect(classifyExternalCallFailure(resetWithCause)).toBe("transient");
    const enet = new Error("connect ENETUNREACH");
    (enet as { code?: string }).code = "ENETUNREACH";
    expect(classifyExternalCallFailure(enet)).toBe("transient");
    expect(classifyExternalCallFailure({ status: 500 })).toBe("transient");
    expect(classifyExternalCallFailure({ status: 599 })).toBe("transient");
    expect(classifyExternalCallFailure({ status: 500.5 })).toBe("durable");
    expect(
      classifyExternalCallFailure({ status: 500.5, statusCode: 429 }),
    ).toBe("quota");
    expect(
      classifyExternalCallFailure({ status: Number.NaN, statusCode: 503 }),
    ).toBe("transient");
    expect(classifyExternalCallFailure({ statusCode: 429 })).toBe("quota");
    expect(classifyExternalCallFailure({ status: 100 })).toBe("durable");
    expect(classifyExternalCallFailure({ status: 99 })).toBe("durable");
    expect(classifyExternalCallFailure({ status: 600 })).toBe("durable");
    expect(classifyExternalCallFailure(new Error("auth token expired"))).toBe(
      "durable",
    );
    const auth401 = Object.assign(new Error("network authentication failed"), {
      status: 401,
    });
    expect(classifyExternalCallFailure(auth401)).toBe("durable");
    const forbid403 = Object.assign(new Error("quota access denied"), {
      status: 403,
    });
    expect(classifyExternalCallFailure(forbid403)).toBe("durable");
    expect(classifyExternalCallFailure({ status: 401 })).toBe("durable");
  });

  it("treats unstructured rate-limit text as durable and does not retry", async () => {
    const failure = new Error("rate limit exceeded");
    expect(classifyExternalCallFailure(failure)).toBe("durable");
    let attempts = 0;
    await expect(
      withLegTransientRetry(async () => {
        attempts += 1;
        throw failure;
      }),
    ).rejects.toBe(failure);
    expect(attempts).toBe(1);
  });

  it("treats unstructured connection text as durable and does not retry", async () => {
    const failure = new Error("socket hang up");
    expect(classifyExternalCallFailure(failure)).toBe("durable");
    let attempts = 0;
    await expect(
      withLegTransientRetry(async () => {
        attempts += 1;
        throw failure;
      }),
    ).rejects.toBe(failure);
    expect(attempts).toBe(1);
  });

  it("has no free-text failure classification court", () => {
    const here = dirname(fileURLToPath(import.meta.url));
    const source = readFileSync(join(here, "../src/externalCall.ts"), "utf8")
      .replace(/\/\*[\s\S]*?\*\//g, "")
      .replace(/(^|[^:])\/\/.*$/gm, "$1");
    expect(source).not.toMatch(
      /(?:includes|match|test)\s*\([^\n]*(?:rate.?limit|quota|额度|配额|too many requests|timed?\s?out|econnreset|socket hang up|connection (?:refused|reset|closed|aborted)|broken pipe|network)/i,
    );
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
