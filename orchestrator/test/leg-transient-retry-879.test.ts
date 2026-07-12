/**
 * #879 / #861 D — CMR leg transient retry at the backend wrapper layer.
 *
 * Classification + bounded retry live in `legTransientRetry.ts` (the leg
 * backend encapsulation). Availability probes (route smoke) use the same
 * policy: connection reset/5xx → retry ×2 then degrade; 429/quota → immediate
 * degrade with zero retry.
 *
 * Positive / negative pair is the acceptance contract.
 */

import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it, vi } from "vitest";
import type * as sc from "@ai-hero/sandcastle";
import {
  MAX_LEG_TRANSIENT_ATTEMPTS,
  classifyLegFailure,
  withLegTransientRetry,
} from "../src/legTransientRetry.js";
import { resolveRouteModels } from "../src/modelRoutes.js";
import { RealBackend } from "../src/realBackend.js";

const { runSpy } = vi.hoisted(() => ({ runSpy: vi.fn() }));

vi.mock("@ai-hero/sandcastle", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@ai-hero/sandcastle")>();
  return { ...actual, run: runSpy };
});

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

describe("#879 availability probe (route smoke) uses the same classification", () => {
  const smokeFixtureDir = dirname(fileURLToPath(import.meta.url));
  const smokePromptsDir = join(smokeFixtureDir, "..", "prompts");
  const smokeSoulsDir = join(smokeFixtureDir, "..", "image", "souls");

  class ProductionSmokeBackend extends RealBackend {
    protected override cloneDirExists(): boolean {
      return true;
    }

    protected override sh(file: string, args: string[]): string {
      if (file === "git" && args[0] === "rev-parse" && args[1] === "--git-common-dir") {
        return ".git";
      }
      return "";
    }
  }

  function productionSmokeBackend(home: string): ProductionSmokeBackend {
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
    return new ProductionSmokeBackend({
      sourceRepo: "/tmp/route-smoke-source-879",
      remote: "https://github.com/owner/route-smoke-879.git",
      runKey: 879,
      repo: "owner/route-smoke-879",
      imageName: "route-smoke-879-image",
      promptsDir: smokePromptsDir,
      soulsDir: smokeSoulsDir,
      home,
    });
  }

  async function renderPromptForScriptedSmoke(
    options: Parameters<typeof sc.run>[0],
  ): Promise<string> {
    const sandcastle = await vi.importActual<typeof import("@ai-hero/sandcastle")>(
      "@ai-hero/sandcastle",
    );
    let renderedPrompt: string | undefined;
    const sandboxHome = mkdtempSync(join(tmpdir(), "route-smoke-879-render-"));
    try {
      await sandcastle.run({
        agent: {
          name: "prompt-capture",
          env: {},
          captureSessions: false,
          buildPrintCommand: ({ prompt }) => {
            renderedPrompt = prompt;
            return { command: "printf 'ROUTE_SMOKE_COMPLETE\\n'" };
          },
          parseStreamLine: (line) => [{ type: "text", text: line }],
        },
        sandbox: (
          await import("@ai-hero/sandcastle/sandboxes/no-sandbox")
        ).noSandbox({ env: { HOME: sandboxHome } }),
        cwd: process.cwd(),
        promptFile: options.promptFile,
        promptArgs: options.promptArgs,
        maxIterations: 1,
        completionSignal: "ROUTE_SMOKE_COMPLETE",
        logging: { type: "file", path: join(sandboxHome, "render.log") },
      });
    } finally {
      rmSync(sandboxHome, { recursive: true, force: true });
    }
    if (renderedPrompt === undefined) {
      throw new Error("scripted smoke did not receive a rendered prompt");
    }
    return renderedPrompt;
  }

  function evidenceFromPrompt(
    prompt: string,
  ): { readonly nonceFile: string; readonly nonce: string } | undefined {
    const match =
      /create the nonce evidence file at\s+(\S+)\s+\(relative\s+to\s+your\s+working\s+directory\)\s+containing\s+exactly\s+(\S+),\s+then\s+emit/i.exec(
        prompt,
      );
    if (match === null) return undefined;
    const [, nonceFile, nonce] = match;
    if (nonceFile.includes("{{") || nonce.includes("{{")) return undefined;
    return { nonceFile, nonce };
  }

  async function successfulSmoke(options: Parameters<typeof sc.run>[0]) {
    const rendered = await renderPromptForScriptedSmoke(options);
    const instruction = evidenceFromPrompt(rendered);
    if (instruction !== undefined && options.cwd) {
      mkdirSync(options.cwd, { recursive: true });
      writeFileSync(
        join(options.cwd, instruction.nonceFile),
        `${instruction.nonce}\n`,
      );
    }
    return {
      completionSignal: "ROUTE_SMOKE_COMPLETE",
    } as Awaited<ReturnType<typeof sc.run>>;
  }

  it("positive: availability probe recovers after two transient connection resets on a leg", async () => {
    const home = mkdtempSync(join(tmpdir(), "route-smoke-879-transient-"));
    // Per-leg attempt counters keyed by the smoke entry model in promptArgs is
    // unavailable; count by sequential global runs and force only the first
    // two calls (same first leg under serial-or-parallel start) to reset.
    // The contract under test: with the wrapper, a leg that hits ECONNRESET
    // twice still ends up "passed" after the third try, and total sc.run count
    // exceeds unique-slug one-shot count.
    const attemptsByCwd = new Map<string, number>();
    runSpy.mockImplementation(async (options: Parameters<typeof sc.run>[0]) => {
      // All smokes share the same workingRepo cwd; differentiate by log path.
      const logPath =
        typeof options.logging === "object" &&
        options.logging !== null &&
        "path" in options.logging
          ? String((options.logging as { path: string }).path)
          : "unknown";
      // Each smoke invocation uses a unique logDir; group by parent of log path
      // is unique per attempt. Count total calls per "logical leg" by reusing
      // a single shared counter for the whole smoke pass is enough when we
      // only fail the first two attempts of the ENTIRE batch for one slug —
      // simpler: fail first 2 attempts of EVERY unique attempt-key, but only
      // for keys that are still under 3. Actually: fail attempt 1 and 2 for
      // each logDir parent (each invocation is unique). Use a global map of
      // attempt ordinal across all runs for the first unique "wave":
      const n = (attemptsByCwd.get("all") ?? 0) + 1;
      attemptsByCwd.set("all", n);
      // Force every leg's first two tries via a per-invocation id: each sc.run
      // has a unique logDir, so we cannot key by leg easily. Instead inject by
      // counting how many times we've seen this exact call site sequence:
      // use a WeakMap-like approach — store attempt counts on a module map
      // keyed by nothing: fail only when total runs so far for the "current
      // wave" ... 
      // Cleaner approach used below: track attempts by a rolling "leg key"
      // derived from the NONCE in promptArgs (unique per attempt, not per leg).
      // So we instead fail the first TWO sc.run calls overall, then succeed.
      // With per-leg retry, those two failures may land on one or two legs;
      // either way the route must still have passed entries and more runs
      // than unique slugs.
      void logPath;
      if (n <= 2) {
        throw new Error("read ECONNRESET");
      }
      return successfulSmoke(options);
    });

    try {
      const backend = productionSmokeBackend(home);
      const smoked = await backend.smokeModelRoute(resolveRouteModels("normal", {}));
      const totalRuns = attemptsByCwd.get("all") ?? 0;
      const uniqueSlugs = new Set(
        Object.keys(smoked.smoke).map((k) => k.split(":")[1]),
      );

      // Retried: more physical launches than one-shot unique slugs.
      expect(totalRuns).toBeGreaterThan(uniqueSlugs.size);
      // Not all-failed solely from two resets — at least one leg passed.
      expect(Object.values(smoked.smoke).some((s) => s.state === "passed")).toBe(
        true,
      );
    } finally {
      runSpy.mockReset();
      rmSync(home, { recursive: true, force: true });
    }
  });

  it("negative: 429 on availability probe does not retry that leg", async () => {
    const home = mkdtempSync(join(tmpdir(), "route-smoke-879-quota-"));
    let globalRuns = 0;
    runSpy.mockImplementation(async () => {
      globalRuns += 1;
      throw new Error("HTTP 429 rate limit exceeded");
    });

    try {
      const backend = productionSmokeBackend(home);
      const smoked = await backend.smokeModelRoute(resolveRouteModels("normal", {}));
      const uniqueSlugs = new Set(
        Object.keys(smoked.smoke).map((k) => k.split(":")[1]),
      );

      // Every unique slug fails once — no per-leg retry budget spent on 429.
      expect(globalRuns).toBe(uniqueSlugs.size);
      expect(
        Object.values(smoked.smoke).every(
          (s) => s.state === "failed" && /429/.test(s.error),
        ),
      ).toBe(true);
    } finally {
      runSpy.mockReset();
      rmSync(home, { recursive: true, force: true });
    }
  });
});
