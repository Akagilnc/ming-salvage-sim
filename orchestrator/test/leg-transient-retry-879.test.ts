/**
 * #879 / #861 D — CMR leg transient retry at the backend wrapper layer.
 *
 * Classification + bounded retry live in `legTransientRetry.ts` (the leg
 * backend encapsulation). Availability probes (route smoke / bare-ping) call
 * `withLegTransientRetry` in production (`RealBackend.smokeModelRoute`):
 * connection reset/5xx → retry ×2 then degrade; 429/quota → immediate degrade
 * with zero retry. Worker-process crashes stay on #598; in-container skill
 * legs are out of this module.
 *
 * Positive / negative pair is the acceptance contract.
 */

import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { ExternalCallTimeoutError } from "../src/externalCall.js";
import {
  MAX_LEG_TRANSIENT_ATTEMPTS,
  classifyLegFailure,
  withLegTransientRetry,
} from "../src/legTransientRetry.js";
import { resolveRouteModels } from "../src/modelRoutes.js";
import { RealBackend } from "../src/realBackend.js";

describe("#879 classifyLegFailure — transient vs quota vs other", () => {
  it("classifies connection reset / close / ECONNRESET / 5xx as transient", () => {
    expect(classifyLegFailure(new Error("read ECONNRESET"))).toBe("transient");
    expect(classifyLegFailure(new Error("socket hang up"))).toBe("transient");
    expect(classifyLegFailure(new Error("Connection reset by peer"))).toBe(
      "transient",
    );
    expect(classifyLegFailure(new Error("connection closed unexpectedly"))).toBe(
      "transient",
    );
    expect(classifyLegFailure(new Error("HTTP 503 service overloaded"))).toBe(
      "transient",
    );
    expect(classifyLegFailure(new Error("upstream returned 502 Bad Gateway"))).toBe(
      "transient",
    );
    expect(classifyLegFailure(new Error("fetch failed: network error"))).toBe(
      "transient",
    );
  });

  it("classifies 429 / rate-limit / quota as quota (no retry)", () => {
    expect(classifyLegFailure(new Error("HTTP 429 rate limit exceeded"))).toBe(
      "quota",
    );
    expect(classifyLegFailure(new Error("provider returned status 429"))).toBe(
      "quota",
    );
    expect(classifyLegFailure(new Error("rate limit: resets at noon"))).toBe(
      "quota",
    );
    expect(classifyLegFailure(new Error("quota exhausted for opus"))).toBe(
      "quota",
    );
    expect(classifyLegFailure(new Error("too many requests"))).toBe("quota");
    expect(classifyLegFailure(new Error("额度不足，请稍后重试"))).toBe("quota");
  });

  it("does not treat permanent/auth failures as transient", () => {
    expect(classifyLegFailure(new Error("bash tool unavailable"))).toBe("other");
    expect(
      classifyLegFailure(new Error("no Claude auth — provider cannot start")),
    ).toBe("other");
    expect(
      classifyLegFailure(
        new Error("model did not complete an observable bash smoke for opus"),
      ),
    ).toBe("other");
  });

  it("classifies ExternalCallTimeoutError / timed-out text as transient (bare-ping path)", () => {
    // Production bare-ping throws ExternalCallTimeoutError from externalCall.ts;
    // must share status-first + timeout policy with classifyExternalCallFailure.
    expect(
      classifyLegFailure(
        new ExternalCallTimeoutError({
          stage: "smoke-k:opus",
          timeoutMs: 1000,
          seam: "subprocess",
        }),
      ),
    ).toBe("transient");
    expect(classifyLegFailure(new Error("external call timed out at stage x"))).toBe(
      "transient",
    );
    const abortish = new Error("The operation was aborted");
    abortish.name = "AbortError";
    expect(classifyLegFailure(abortish)).toBe("transient");
  });

  it("status-first: explicit HTTP 5xx beats quota vocabulary (align externalCall)", () => {
    expect(classifyLegFailure(new Error("HTTP 503 service overloaded quota"))).toBe(
      "transient",
    );
    expect(classifyLegFailure(new Error("upstream returned 502 Bad Gateway"))).toBe(
      "transient",
    );
  });
});

describe("#879 withLegTransientRetry — positive / negative pair", () => {
  it("positive: transient failures retry up to 2 times then succeed (3 total attempts)", async () => {
    let calls = 0;
    const result = await withLegTransientRetry(
      async () => {
        calls += 1;
        if (calls < 3) throw new Error("read ECONNRESET");
        return "ok";
      },
      { sleepMs: async () => {} },
    );

    expect(result).toBe("ok");
    expect(calls).toBe(MAX_LEG_TRANSIENT_ATTEMPTS);
    expect(MAX_LEG_TRANSIENT_ATTEMPTS).toBe(3); // 1 initial + 2 retries
  });

  it("positive exhaust: transient failures still fail after 2 retries (3 attempts total)", async () => {
    let calls = 0;
    await expect(
      withLegTransientRetry(
        async () => {
          calls += 1;
          throw new Error("HTTP 502 Bad Gateway");
        },
        { sleepMs: async () => {} },
      ),
    ).rejects.toThrow(/HTTP 502/);
    expect(calls).toBe(3);
  });

  it("negative: 429 / quota fails immediately with zero retry", async () => {
    let calls = 0;
    await expect(
      withLegTransientRetry(
        async () => {
          calls += 1;
          throw new Error("HTTP 429 rate limit exceeded");
        },
        { sleepMs: async () => {} },
      ),
    ).rejects.toThrow(/429/);
    expect(calls).toBe(1);
  });

  it("negative: permanent other failures do not retry either", async () => {
    let calls = 0;
    await expect(
      withLegTransientRetry(
        async () => {
          calls += 1;
          throw new Error("bash tool unavailable");
        },
        { sleepMs: async () => {} },
      ),
    ).rejects.toThrow(/bash tool unavailable/);
    expect(calls).toBe(1);
  });
});


describe("#879 availability probe (bare-ping smoke) uses the same classification", () => {
  const smokeFixtureDir = dirname(fileURLToPath(import.meta.url));
  const smokePromptsDir = join(smokeFixtureDir, "..", "prompts");
  const smokeSoulsDir = join(smokeFixtureDir, "..", "image", "souls");

  /** Injectable bare-ping backend (#884 smoke seam). */
  class BarePingSmokeBackend extends RealBackend {
    readonly pingCalls: Array<{ slug: string; nonce: string }> = [];
    private readonly pingImpl: (input: {
      slug: string;
      nonce: string;
    }) => Promise<string>;

    constructor(
      home: string,
      pingImpl: (input: { slug: string; nonce: string }) => Promise<string>,
    ) {
      super({
        sourceRepo: "/tmp/route-smoke-source-879",
        remote: "https://github.com/owner/route-smoke-879.git",
        runKey: 879,
        repo: "owner/route-smoke-879",
        imageName: "route-smoke-879-image",
        promptsDir: smokePromptsDir,
        soulsDir: smokeSoulsDir,
        home,
      });
      this.pingImpl = pingImpl;
    }

    protected override cloneDirExists(): boolean {
      return true;
    }

    protected override sh(file: string, args: string[]): string {
      if (file === "git" && args[0] === "rev-parse" && args[1] === "--git-common-dir") {
        return ".git";
      }
      if (
        file === "codex" ||
        file === "claude" ||
        file === "opencode" ||
        file === "grok" ||
        file === "cursor"
      ) {
        return "cli-test-version";
      }
      return "";
    }

    protected override async execBarePing(input: {
      readonly slug: string;
      readonly cwd: string;
      readonly prompt: string;
      readonly nonce: string;
      readonly file: string;
      readonly args: readonly string[];
      readonly stdin?: string;
      readonly timeoutMs: number;
    }): Promise<string> {
      this.pingCalls.push({ slug: input.slug, nonce: input.nonce });
      return this.pingImpl({ slug: input.slug, nonce: input.nonce });
    }
  }

  function prepareHome(): string {
    const home = mkdtempSync(join(tmpdir(), "route-smoke-879-"));
    mkdirSync(join(home, ".codex"), { recursive: true });
    writeFileSync(join(home, ".codex", "auth.json"), "{}\n");
    writeFileSync(join(home, ".sc-claude-token"), "test-token\n");
    const opencodeDir = join(home, ".local", "share", "opencode");
    mkdirSync(opencodeDir, { recursive: true });
    writeFileSync(
      join(opencodeDir, "auth.json"),
      JSON.stringify({
        "opencode-go": { type: "api", key: "test-key" },
        "grok-4.5": { type: "api", key: "test-key" },
      }),
    );
    return home;
  }

  it("positive: one leg recovers after exactly two transient resets (3 bare-pings total)", async () => {
    const home = prepareHome();
    // Single-slug route so every bare-ping belongs to the same logical leg
    // (S5 r1 tight assertion, adapted to #884 bare-ping seam).
    const singleLegRoute = {
      ...resolveRouteModels("normal", {}),
      slots: {
        coder: "opus",
        reviewer: "opus",
        coderFix: "opus",
        ship: "opus",
        merger: "opus",
        cmrCompleteness: "opus",
        cmrCorrectness: "opus",
        verify: "opus",
        fixer: "opus",
        cleanup: "opus",
        docRelease: "opus",
      },
      legCollections: {
        cmrReview: [{ family: "claude" as const, slug: "opus" }],
      },
      smoke: {},
    };
    let attempts = 0;
    try {
      const backend = new BarePingSmokeBackend(home, async ({ nonce }) => {
        attempts += 1;
        if (attempts <= 2) {
          throw new Error("read ECONNRESET");
        }
        // #884 oracle: a full line equal to the nonce (optional short preface).
        return `thought\n${nonce}\n`;
      });
      const smoked = await backend.smokeModelRoute(singleLegRoute);
      // 1 initial + 2 retries on the sole unique slug.
      expect(attempts).toBe(MAX_LEG_TRANSIENT_ATTEMPTS);
      expect(backend.pingCalls.length).toBe(MAX_LEG_TRANSIENT_ATTEMPTS);
      expect(
        Object.values(smoked.smoke).every((s) => s.state === "passed"),
      ).toBe(true);
    } finally {
      rmSync(home, { recursive: true, force: true });
    }
  });

  it("negative: 429 on availability probe does not retry that leg", async () => {
    const home = prepareHome();
    try {
      const backend = new BarePingSmokeBackend(home, async () => {
        throw new Error("HTTP 429 rate limit exceeded");
      });
      const smoked = await backend.smokeModelRoute(resolveRouteModels("normal", {}));
      const uniqueSlugs = new Set(
        Object.keys(smoked.smoke).map((k) => k.split(":")[1]),
      );

      // Every unique slug fails once — no per-leg retry budget spent on 429.
      expect(backend.pingCalls.length).toBe(uniqueSlugs.size);
      expect(
        Object.values(smoked.smoke).every(
          (s) => s.state === "failed" && /429/.test(s.error),
        ),
      ).toBe(true);
    } finally {
      rmSync(home, { recursive: true, force: true });
    }
  });
});
