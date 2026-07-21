/**
 * #1094 — family CMR panel legs are runner-dispatched first-class workers
 * (isomorphic to single-slice fresh reviewer), not nested CLIs inside the judge.
 *
 * Seams:
 *   1. cmrPanelLegWorkerSpec — one WorkerSpec per route leg (model/soul/session)
 *   2. family CMR round — dispatches N leg workers, then judge with their prose
 *   3. leg failure/degradation — surfaces as degraded evidence, not silent success
 *   4. demolition — nested-CLI claude mount/assert plumbing is gone
 */
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  cmrPanelLegWorkerSpec,
  legTransportFromPanelLegResult,
  skippedLegsFromTransports,
} from "../../../src/family/cmrPanelLegs.js";
import { cmrWorkerSpec } from "../../../src/family/dispatchFamilyWorker.js";
import { provisionWorkerAuth } from "../../../src/realBackend.js";
import { successfulLegsFromTransports } from "../../../src/legPaper.js";
import { buildJudgeReviewLegPrompt } from "../../../src/judgeStation.js";
import { workerHostForModel } from "../../../src/dispatchWorker.js";
import type { WorkerCmrReviewLeg, WorkerResult } from "../../../src/types.js";

const here = dirname(fileURLToPath(import.meta.url));
const soulsDir = join(here, "..", "..", "..", "image", "souls");
const reviewerSoul = readFileSync(join(soulsDir, "reviewer.md"), "utf8");

describe("#1094 cmrPanelLegWorkerSpec — fresh reviewer worker per route leg", () => {
  it("freezes each cmrReview leg as a fresh READ-ONLY reviewer worker", () => {
    const legs: WorkerCmrReviewLeg[] = [
      { family: "codex", slug: "gpt-5.6-sol" },
      { family: "claude", slug: "opus" },
      { family: "grok", slug: "grok-4.5" },
    ];
    const expectedHost: Record<string, string> = {
      "gpt-5.6-sol": "codex",
      opus: "claude",
      "grok-4.5": "grok",
    };
    for (const leg of legs) {
      const spec = cmrPanelLegWorkerSpec(leg);
      expect(spec.kind).toBe("reviewer");
      expect(spec.role).toBe("reviewer");
      expect(spec.soul).toBe("READ-ONLY");
      expect(spec.session).toBe("fresh");
      expect(spec.contextRetention).toBe("clean");
      expect(spec.model).toBe(leg.slug);
      expect(spec.host).toBe(workerHostForModel(leg.slug));
      expect(spec.host).toBe(expectedHost[leg.slug]);
      expect(spec.maxIter).toBe(1);
    }
    // Cross-vendor legs resolve to distinct CLI hosts (not nested judge scripts).
    const hosts = new Set(legs.map((leg) => cmrPanelLegWorkerSpec(leg).host));
    expect(hosts.size).toBe(legs.length);
  });

  it("leg prompt prepends full reviewer soul (same helper as single-slice)", () => {
    const body = "Review the family base diff for completeness.";
    const prompt = buildJudgeReviewLegPrompt(reviewerSoul, body);
    expect(prompt.startsWith(reviewerSoul.trim())).toBe(true);
    expect(prompt).toContain(body);
  });
});

describe("#1094 panel leg transport → judge evidence (ADR 0141)", () => {
  it("successful legs are transport-present; failed legs are skipped not silent success", () => {
    const ok: WorkerResult = {
      kind: "completed",
      output: {
        kind: "reviewer",
        findingsCount: 0,
        findings: [],
        rawStdout: "P1: missing AC coverage on the merge seam.\n",
      },
    };
    const failed: WorkerResult = {
      kind: "failed",
      reason: "provider unavailable",
    };
    const emptySuccess: WorkerResult = {
      kind: "completed",
      output: {
        kind: "reviewer",
        findingsCount: 0,
        findings: [],
        rawStdout: "",
      },
    };
    const greetingOnly: WorkerResult = {
      kind: "completed",
      output: {
        kind: "reviewer",
        findingsCount: 0,
        findings: [],
        rawStdout: "我要开始审了",
      },
    };

    const transports = [
      legTransportFromPanelLegResult("gpt-5.6-sol", ok),
      legTransportFromPanelLegResult("opus", failed),
      legTransportFromPanelLegResult("agy", emptySuccess),
      legTransportFromPanelLegResult("grok-4.5", greetingOnly),
    ];
    const declared: WorkerCmrReviewLeg[] = [
      { family: "codex", slug: "gpt-5.6-sol" },
      { family: "claude", slug: "opus" },
      { family: "agy", slug: "agy" },
      { family: "grok", slug: "grok-4.5" },
    ];

    expect(successfulLegsFromTransports(transports)).toEqual(["gpt-5.6-sol"]);
    const skipped = skippedLegsFromTransports(declared, transports);
    expect(skipped.map((s) => s.slug).sort()).toEqual(
      ["agy", "grok-4.5", "opus"].sort(),
    );
    expect(skipped.every((s) => s.reason.length > 0)).toBe(true);
  });
});

describe("#1094 family CMR round dispatches N leg workers then the judge", () => {
  it("dispatchFamilyCmrPanelLegs fans out one worker per declared leg", async () => {
    const { dispatchFamilyCmrPanelLegs } = await import(
      "../../../src/family/cmrPanelLegs.js"
    );
    const dispatched: string[] = [];
    const legs: WorkerCmrReviewLeg[] = [
      { family: "codex", slug: "gpt-5.6-sol" },
      { family: "claude", slug: "opus" },
      { family: "agy", slug: "agy" },
    ];
    const round = await dispatchFamilyCmrPanelLegs({
      legs,
      dispatch: async (spec) => {
        dispatched.push(`${spec.kind}:${spec.model}:${spec.soul}`);
        if (spec.model === "opus") {
          return { kind: "failed", reason: "quota exhausted" };
        }
        return {
          kind: "completed",
          output: {
            kind: "reviewer",
            findingsCount: 0,
            findings: [],
            rawStdout: `Review from ${spec.model}: seam looks correct.\n`,
          },
        };
      },
    });
    expect(dispatched.sort()).toEqual(
      [
        "reviewer:agy:READ-ONLY",
        "reviewer:gpt-5.6-sol:READ-ONLY",
        "reviewer:opus:READ-ONLY",
      ].sort(),
    );
    expect([...round.successfulLegs].sort()).toEqual(["agy", "gpt-5.6-sol"].sort());
    expect(round.skippedLegs).toEqual([
      {
        slug: "opus",
        reason: expect.stringMatching(/opus.*quota exhausted/i),
      },
    ]);
    // Degraded leg is evidence for the judge — not silent success.
    expect(round.successfulLegs).not.toContain("opus");
  });
});

describe("#1094 demolition — nested-CLI claude mount plumbing is gone", () => {
  it("family provisionWorkerAuth does not copy host Claude credentials into temp dirs", () => {
    const home = mkdtempSync(join(tmpdir(), "1094-demolition-"));
    try {
      mkdirSync(join(home, ".claude"), { recursive: true });
      writeFileSync(
        join(home, ".claude", ".credentials.json"),
        '{"tokens":{"claude":"nested-should-not-copy"}}\n',
      );
      writeFileSync(join(home, ".sc-claude-token"), "worker-oauth-token\n");
      const homeEnv = join(home, "home-CLAUDE.md");
      writeFileSync(homeEnv, "# test\n", "utf8");

      const auth = provisionWorkerAuth({
        home,
        homeEnvFile: homeEnv,
        pathPolicy: { kind: "family", rolePrefix: "cmr" },
      });

      expect(auth.claudeToken).toBe("worker-oauth-token");
      const scRoot = join(home, ".sc-orchestrator");
      const claudeCredentialTemps =
        existsSync(scRoot)
          ? readdirSync(scRoot).filter((name) => name.includes("-claude-auth-"))
          : [];
      expect(claudeCredentialTemps).toEqual([]);
    } finally {
      rmSync(home, { recursive: true, force: true });
    }
  });

  it("judge cmrWorkerSpec no longer carries nested review-leg spawn duty as its sole job", () => {
    // Judge remains a cmr/verify seat; panel legs are separate reviewer specs.
    const judge = cmrWorkerSpec("fresh", "completeness");
    expect(judge.kind).toBe("cmr");
    expect(judge.soul).toBe("verify");
    expect(judge.role).toBe("verify");
    const leg = cmrPanelLegWorkerSpec({ family: "codex", slug: "gpt-5.6-sol" });
    expect(leg.kind).not.toBe(judge.kind);
    expect(leg.soul).not.toBe(judge.soul);
  });
});
