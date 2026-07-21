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
    // #1094 F7: named lens wrapper, not nested-panel engine.
    expect(judge.skill).toBe("ak-cmr-completeness");
    expect(cmrWorkerSpec("fresh", "correctness").skill).toBe("ak-cmr-correctness");
    const leg = cmrPanelLegWorkerSpec({ family: "codex", slug: "gpt-5.6-sol" });
    expect(leg.kind).not.toBe(judge.kind);
    expect(leg.soul).not.toBe(judge.soul);
  });
});

describe("#1094 F1 — concurrent panel legs get unique monitor job/log paths", () => {
  it("buildCliMonitorSpawnSpec mints distinct jobPath and logBasename per dispatch", async () => {
    const { buildCliMonitorSpawnSpec } = await import(
      "../../../src/cliMonitorHooks.js"
    );
    const telemetryDir = mkdtempSync(join(tmpdir(), "1094-monitor-"));
    try {
      const legs = [
        cmrPanelLegWorkerSpec({ family: "codex", slug: "gpt-5.6-sol" }),
        cmrPanelLegWorkerSpec({ family: "claude", slug: "opus" }),
        cmrPanelLegWorkerSpec({ family: "agy", slug: "agy" }),
      ];
      const jobPaths = new Set<string>();
      const logBasenames = new Set<string>();
      for (const spec of legs) {
        const spawn = buildCliMonitorSpawnSpec({
          backendKind: "realFamily",
          backendOpts: {},
          spec,
          ctx: {
            familyBase: "family/1094",
            telemetryDir,
          },
        });
        expect(spawn).toBeDefined();
        const jobArg = spawn!.args[1]!;
        expect(jobArg.endsWith(".job.json")).toBe(true);
        expect(jobArg).toMatch(/S3\.[0-9a-f-]{36}\.job\.json$/i);
        expect(jobArg.endsWith("/S3.job.json")).toBe(false);
        jobPaths.add(jobArg);
        logBasenames.add(spawn!.logBasename ?? "");
        expect(existsSync(jobArg)).toBe(true);
        const job = JSON.parse(readFileSync(jobArg, "utf8")) as {
          spec: { model: string };
        };
        expect(job.spec.model).toBe(spec.model);
      }
      expect(jobPaths.size).toBe(3);
      expect(logBasenames.size).toBe(3);
    } finally {
      rmSync(telemetryDir, { recursive: true, force: true });
    }
  });
});

describe("#1094 F3 — sibling leg rejections do not become unhandled", () => {
  it("Promise.allSettled awaits every leg before rethrowing the first park error", async () => {
    const { dispatchFamilyCmrPanelLegs } = await import(
      "../../../src/family/cmrPanelLegs.js"
    );
    const { AdoptionPersistFailedError } = await import(
      "../../../src/dispatchRetry.js"
    );
    let settled = 0;
    const legs: WorkerCmrReviewLeg[] = [
      { family: "codex", slug: "gpt-5.6-sol" },
      { family: "claude", slug: "opus" },
      { family: "agy", slug: "agy" },
    ];
    await expect(
      dispatchFamilyCmrPanelLegs({
        legs,
        dispatch: async () => {
          settled += 1;
          await new Promise((r) => setTimeout(r, 5));
          throw new AdoptionPersistFailedError(new Error("ledger write failed"));
        },
      }),
    ).rejects.toBeInstanceOf(AdoptionPersistFailedError);
    expect(settled).toBe(3);
  });
});

describe("#1094 F5 — cmr_panel_leg.md is the authoritative prompt source", () => {
  it("versioned panel-leg prompt is loaded and prepends reviewer soul", () => {
    const promptPath = join(here, "..", "..", "..", "prompts", "cmr_panel_leg.md");
    expect(existsSync(promptPath)).toBe(true);
    const md = readFileSync(promptPath, "utf8");
    expect(md).toMatch(/Fresh eyes only/i);
    expect(md).toMatch(/Do not call another model/i);
    expect(md).toMatch(/Do not repair, commit, or push/i);
    expect(md).toMatch(/ADR 0141/i);
    const composed = buildJudgeReviewLegPrompt(
      reviewerSoul,
      `${md.trim()}\n\nPanel leg slug: gpt-5.6-sol.\n`,
    );
    expect(composed.startsWith(reviewerSoul.trim())).toBe(true);
    expect(composed).toContain("Fresh eyes only");
    expect(composed).toContain("Panel leg slug: gpt-5.6-sol");
  });
});

describe("#1094 F9 — panelLegSandboxConfig credential seams", () => {
  it("mounts only THIS leg's provider auth (isomorphic to single-slice reviewer)", async () => {
    const { RealFamilyBackend } = await import(
      "../../../src/family/realFamilyBackend.js"
    );
    const {
      SANDBOX_CODEX_DIR,
      SANDBOX_AGY_DIR,
      SANDBOX_GROK_DIR,
      SANDBOX_SOUL_ENV,
    } = await import("../../../src/realBackend.js");

    class SeamBackend extends RealFamilyBackend {
      public legConfig(
        auth: {
          codexAuthDir?: string;
          agyDir?: string;
          grokAuthDir?: string;
          claudeToken?: string;
        },
        spec: ReturnType<typeof cmrPanelLegWorkerSpec>,
      ) {
        return this.panelLegSandboxConfig(auth as never, spec, {
          familyBase: "family/1094",
        });
      }
    }

    const promptsDir = join(here, "..", "..", "..", "prompts");
    const be = new SeamBackend({
      workingRepo: mkdtempSync(join(tmpdir(), "1094-leg-repo-")),
      familyBase: "family/1094",
      ledgerDir: mkdtempSync(join(tmpdir(), "1094-leg-ledger-")),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir,
      soulsDir,
      imageName: "img",
    });

    const auth = {
      codexAuthDir: "/tmp/leg-codex",
      agyDir: "/tmp/leg-agy",
      grokAuthDir: "/tmp/leg-grok",
      claudeToken: "tok",
    };

    const codex = be.legConfig(
      auth,
      cmrPanelLegWorkerSpec({ family: "codex", slug: "gpt-5.6-sol" }),
    );
    expect(codex.mounts.some((m) => m.sandboxPath === SANDBOX_CODEX_DIR)).toBe(true);
    expect(codex.mounts.some((m) => m.sandboxPath === SANDBOX_AGY_DIR)).toBe(false);
    expect(codex.mounts.some((m) => m.sandboxPath === SANDBOX_GROK_DIR)).toBe(false);
    expect(codex.env[SANDBOX_SOUL_ENV]).toBe("READ-ONLY");

    const agy = be.legConfig(
      auth,
      cmrPanelLegWorkerSpec({ family: "agy", slug: "agy" }),
    );
    expect(agy.mounts.some((m) => m.sandboxPath === SANDBOX_AGY_DIR)).toBe(true);
    expect(agy.mounts.some((m) => m.sandboxPath === SANDBOX_CODEX_DIR)).toBe(false);

    const grok = be.legConfig(
      auth,
      cmrPanelLegWorkerSpec({ family: "grok", slug: "grok-4.5" }),
    );
    expect(grok.mounts.some((m) => m.sandboxPath === SANDBOX_GROK_DIR)).toBe(true);
    expect(grok.mounts.some((m) => m.sandboxPath === SANDBOX_CODEX_DIR)).toBe(false);

    const claude = be.legConfig(
      auth,
      cmrPanelLegWorkerSpec({ family: "claude", slug: "opus" }),
    );
    expect(claude.env.CLAUDE_CODE_OAUTH_TOKEN).toBe("tok");
    expect(claude.mounts.some((m) => m.sandboxPath === SANDBOX_CODEX_DIR)).toBe(false);
    expect(claude.mounts.some((m) => m.sandboxPath === SANDBOX_AGY_DIR)).toBe(false);
  });

  it("preparePanelLegClone builds an independent detached clone (no shared checkout)", async () => {
    const { execFileSync } = await import("node:child_process");
    const { RealFamilyBackend } = await import(
      "../../../src/family/realFamilyBackend.js"
    );
    const root = mkdtempSync(join(tmpdir(), "1094-clone-src-"));
    const ledger = mkdtempSync(join(tmpdir(), "1094-clone-ledger-"));
    try {
      execFileSync("git", ["init"], { cwd: root });
      execFileSync("git", ["config", "user.email", "t@t"], { cwd: root });
      execFileSync("git", ["config", "user.name", "t"], { cwd: root });
      writeFileSync(join(root, "a.txt"), "a\n");
      execFileSync("git", ["add", "."], { cwd: root });
      execFileSync("git", ["commit", "-m", "init"], { cwd: root });
      const head = execFileSync("git", ["rev-parse", "HEAD"], {
        cwd: root,
        encoding: "utf8",
      }).trim();

      class CloneBackend extends RealFamilyBackend {
        public clone(slug: string, sha: string): string {
          return this.preparePanelLegClone(slug, sha);
        }
      }
      const be = new CloneBackend({
        workingRepo: root,
        familyBase: "main",
        ledgerDir: ledger,
        repo: "Akagilnc/ming-salvage-sim",
        base: "main",
        promptsDir: join(here, "..", "..", "..", "prompts"),
        soulsDir,
        imageName: "img",
      });
      const cloneA = be.clone("gpt-5.6-sol", head);
      const cloneB = be.clone("opus", head);
      expect(cloneA).not.toBe(cloneB);
      expect(cloneA).not.toBe(root);
      const headA = execFileSync("git", ["rev-parse", "HEAD"], {
        cwd: cloneA,
        encoding: "utf8",
      }).trim();
      expect(headA).toBe(head);
      // Independent: deleting one clone must not touch the other or source.
      rmSync(cloneA, { recursive: true, force: true });
      expect(existsSync(cloneB)).toBe(true);
      expect(existsSync(join(root, "a.txt"))).toBe(true);
      rmSync(cloneB, { recursive: true, force: true });
    } finally {
      rmSync(root, { recursive: true, force: true });
      rmSync(ledger, { recursive: true, force: true });
    }
  });
});
