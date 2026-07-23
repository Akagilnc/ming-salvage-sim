/**
 * #1094 — family CMR panel legs are runner-dispatched first-class workers
 * (isomorphic to single-slice fresh reviewer), not nested CLIs inside the judge.
 *
 * Seams:
 *   1. cmrPanelLegWorkerSpec — one WorkerSpec per route leg (model/soul/session)
 *   2. family CMR round — dispatches N leg workers, then judge with their prose
 *   3. leg failure/degradation — surfaces as degraded evidence, not silent success
 *   4. demolition — nested-CLI claude mount/assert plumbing is gone
 *   5. R2 — judge identity mount, leg-only slug degrade, pass-distinct lenses
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
  cmrPanelLegPromptFile,
  cmrPanelLegWorkerSpec,
  dispatchFamilyCmrPanelLegs,
  legTransportFromPanelLegResult,
  skippedLegsFromTransports,
} from "../../../src/family/cmrPanelLegs.js";
import { cmrWorkerSpec } from "../../../src/family/dispatchFamilyWorker.js";
import { provisionWorkerAuth } from "../../../src/realBackend.js";
import { successfulLegsFromTransports } from "../../../src/legPaper.js";
import { buildJudgeReviewLegPrompt } from "../../../src/judgeStation.js";
import { workerHostForModel } from "../../../src/dispatchWorker.js";
import type { CmrAuth } from "../../../src/family/realFamilyBackend.js";
import type {
  FamilyEscalation,
  FamilyLedgerEntry,
} from "../../../src/family/types.js";
import type {
  DispatchContext,
  WorkerCmrReviewLeg,
  WorkerResult,
  WorkerSpec,
} from "../../../src/types.js";

const here = dirname(fileURLToPath(import.meta.url));
const soulsDir = join(here, "..", "..", "..", "image", "souls");
const promptsDir = join(here, "..", "..", "..", "prompts");
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
      const spec = cmrPanelLegWorkerSpec(leg, "correctness");
      expect(spec.kind).toBe("reviewer");
      expect(spec.role).toBe("reviewer");
      expect(spec.soul).toBe("READ-ONLY");
      expect(spec.session).toBe("fresh");
      expect(spec.contextRetention).toBe("clean");
      expect(spec.model).toBe(leg.slug);
      expect(spec.host).toBe(workerHostForModel(leg.slug));
      expect(spec.host).toBe(expectedHost[leg.slug]);
      expect(spec.maxIter).toBe(1);
      expect(spec.skill).toBeUndefined();
      expect(spec.promptFile).toBe(cmrPanelLegPromptFile("correctness"));
    }
    const hosts = new Set(
      legs.map((leg) => cmrPanelLegWorkerSpec(leg, "correctness").host),
    );
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
    const dispatched: string[] = [];
    const legs: WorkerCmrReviewLeg[] = [
      { family: "codex", slug: "gpt-5.6-sol" },
      { family: "claude", slug: "opus" },
      { family: "agy", slug: "agy" },
    ];
    const round = await dispatchFamilyCmrPanelLegs({
      legs,
      cmrPass: "correctness",
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
    expect(
      [...successfulLegsFromTransports(round.transports)].sort(),
    ).toEqual(["agy", "gpt-5.6-sol"].sort());
    expect(round.skippedLegs).toEqual([
      {
        slug: "opus",
        reason: expect.stringMatching(/opus.*quota exhausted/i),
      },
    ]);
    expect(successfulLegsFromTransports(round.transports)).not.toContain("opus");
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

  it("judge cmrWorkerSpec pins pass via promptFile; skill is omitted (write-only dead metadata)", () => {
    const judge = cmrWorkerSpec("fresh", "completeness");
    expect(judge.kind).toBe("cmr");
    expect(judge.soul).toBe("verify");
    expect(judge.role).toBe("verify");
    expect(judge.skill).toBeUndefined();
    expect(judge.promptFile).toBe("integrated_cmr_completeness.md");
    expect(cmrWorkerSpec("fresh", "correctness").promptFile).toBe(
      "integrated_cmr_correctness.md",
    );
    const leg = cmrPanelLegWorkerSpec(
      { family: "codex", slug: "gpt-5.6-sol" },
      "completeness",
    );
    expect(leg.kind).not.toBe(judge.kind);
    expect(leg.soul).not.toBe(judge.soul);
    expect(leg.skill).toBeUndefined();
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

describe("#1094 R2 F8 — pass-distinct lens prompts", () => {
  it("completeness and correctness legs key distinct authoritative prompt sources", () => {
    const completeness = cmrPanelLegWorkerSpec(
      { family: "codex", slug: "gpt-5.6-sol" },
      "completeness",
    );
    const correctness = cmrPanelLegWorkerSpec(
      { family: "codex", slug: "gpt-5.6-sol" },
      "correctness",
    );
    expect(completeness.promptFile).toBe("cmr_panel_leg_completeness.md");
    expect(correctness.promptFile).toBe("cmr_panel_leg_correctness.md");
    expect(completeness.promptFile).not.toBe(correctness.promptFile);

    const cBody = readFileSync(
      join(promptsDir, completeness.promptFile),
      "utf8",
    );
    const kBody = readFileSync(
      join(promptsDir, correctness.promptFile),
      "utf8",
    );
    expect(cBody).toMatch(/Clause–Wire–Exercise/);
    expect(cBody).not.toMatch(/Trace–Break–Prove/);
    expect(kBody).toMatch(/Trace–Break–Prove/);
    expect(kBody).not.toMatch(/Clause–Wire–Exercise/);
  });
});

describe("#1094 R2 F7 — CMR-leg-only slug degrades loudly (never crashes the family run)", () => {
  it("historical gpt-5.5 leg degrades as skipped evidence without throwing", async () => {
    let dispatched = 0;
    const round = await dispatchFamilyCmrPanelLegs({
      legs: [
        { family: "codex", slug: "gpt-5.5" },
        { family: "claude", slug: "opus" },
      ],
      cmrPass: "correctness",
      dispatch: async (spec) => {
        dispatched += 1;
        expect(spec.model).not.toBe("gpt-5.5");
        return {
          kind: "completed",
          output: {
            kind: "reviewer",
            findingsCount: 0,
            findings: [],
            rawStdout: `ok from ${spec.model}\n`,
          },
        };
      },
    });
    expect(dispatched).toBe(1);
    expect(successfulLegsFromTransports(round.transports)).toEqual(["opus"]);
    expect(round.skippedLegs.map((s) => s.slug)).toContain("gpt-5.5");
    expect(round.skippedLegs.find((s) => s.slug === "gpt-5.5")!.reason).toMatch(
      /CMR-leg-only|not a live worker/i,
    );
  });
});

describe("#1094 F5 — pass-keyed panel-leg prompts are the authoritative sources", () => {
  it("versioned panel-leg prompts load and prepend reviewer soul", () => {
    for (const pass of ["completeness", "correctness"] as const) {
      const promptPath = join(promptsDir, cmrPanelLegPromptFile(pass));
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
    }
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
      SANDBOX_OUTCOME_PATH_ENV,
    } = await import("../../../src/realBackend.js");

    class SeamBackend extends RealFamilyBackend {
      public legConfig(
        auth: CmrAuth,
        spec: ReturnType<typeof cmrPanelLegWorkerSpec>,
      ) {
        return this.panelLegSandboxConfig(auth, spec, {
          familyBase: "family/1094",
        });
      }
    }

    const workingRepo = mkdtempSync(join(tmpdir(), "1094-leg-repo-"));
    const ledgerDir = mkdtempSync(join(tmpdir(), "1094-leg-ledger-"));
    try {
      const be = new SeamBackend({
        workingRepo,
        familyBase: "family/1094",
        ledgerDir,
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
      expect(codex.env[SANDBOX_OUTCOME_PATH_ENV]).toBeUndefined();

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
    } finally {
      rmSync(workingRepo, { recursive: true, force: true });
      rmSync(ledgerDir, { recursive: true, force: true });
    }
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
        promptsDir,
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

describe("#1094 R2 F1 — judge cmrSandboxConfig mounts OWN family credential only", () => {
  it("codex judge mounts ~/.codex; does not mount agy/grok nested armament", async () => {
    const { RealFamilyBackend } = await import(
      "../../../src/family/realFamilyBackend.js"
    );
    const {
      SANDBOX_CODEX_DIR,
      SANDBOX_AGY_DIR,
      SANDBOX_GROK_DIR,
    } = await import("../../../src/realBackend.js");

    class JudgeSeam extends RealFamilyBackend {
      public cfg(auth: CmrAuth, model: string) {
        return this.cmrSandboxConfig(auth, {
          model,
          host: workerHostForModel(model),
        });
      }
    }

    const workingRepo = mkdtempSync(join(tmpdir(), "1094-judge-repo-"));
    const ledgerDir = mkdtempSync(join(tmpdir(), "1094-judge-ledger-"));
    try {
      const be = new JudgeSeam({
        workingRepo,
        familyBase: "family/1094",
        ledgerDir,
        repo: "Akagilnc/ming-salvage-sim",
        base: "main",
        promptsDir,
        soulsDir,
        imageName: "img",
      });
      const auth = {
        codexAuthDir: "/tmp/judge-codex",
        agyDir: "/tmp/judge-agy",
        grokAuthDir: "/tmp/judge-grok",
        claudeToken: "tok",
      };

      const codexJudge = cmrWorkerSpec("fresh", "completeness");
      expect(codexJudge.model).toBe("gpt-5.6-sol");
      const cfg = be.cfg(auth, codexJudge.model);
      expect(cfg.mounts.some((m) => m.sandboxPath === SANDBOX_CODEX_DIR)).toBe(true);
      expect(cfg.mounts.some((m) => m.sandboxPath === SANDBOX_AGY_DIR)).toBe(false);
      expect(cfg.mounts.some((m) => m.sandboxPath === SANDBOX_GROK_DIR)).toBe(false);

      const opusCfg = be.cfg(auth, "opus");
      expect(opusCfg.mounts.some((m) => m.sandboxPath === SANDBOX_CODEX_DIR)).toBe(
        false,
      );
      expect(opusCfg.env.CLAUDE_CODE_OAUTH_TOKEN).toBe("tok");
    } finally {
      rmSync(workingRepo, { recursive: true, force: true });
      rmSync(ledgerDir, { recursive: true, force: true });
    }
  });
});

describe("#1094 R2 F3 — prepareFamilyCmrPanelRound returns structured escalate on missing cut-SHA", () => {
  it("does not throw a bare Error across the prepare seam", async () => {
    const { RealFamilyBackend } = await import(
      "../../../src/family/realFamilyBackend.js"
    );
    const { execFileSync } = await import("node:child_process");
    const root = mkdtempSync(join(tmpdir(), "1094-prep-"));
    const ledgerDir = mkdtempSync(join(tmpdir(), "1094-prep-ledger-"));
    try {
      execFileSync("git", ["init"], { cwd: root });
      execFileSync("git", ["config", "user.email", "t@t"], { cwd: root });
      execFileSync("git", ["config", "user.name", "t"], { cwd: root });
      writeFileSync(join(root, "a.txt"), "a\n");
      execFileSync("git", ["add", "."], { cwd: root });
      execFileSync("git", ["commit", "-m", "init"], { cwd: root });

      class PrepBackend extends RealFamilyBackend {
        public prep(ctx: { familyBase: string }) {
          return this.prepareFamilyCmrPanelRound(ctx);
        }
      }
      const be = new PrepBackend({
        workingRepo: root,
        familyBase: "main",
        ledgerDir,
        repo: "Akagilnc/ming-salvage-sim",
        base: "main",
        promptsDir,
        soulsDir,
        imageName: "img",
        // no familyBaseStartHead
      });
      const prep = be.prep({ familyBase: "main" });
      expect(prep).toMatchObject({
        kind: "escalate",
        reason: expect.stringMatching(/familyBaseStartHead|cut SHA/i),
        diagnosis: expect.stringMatching(/exact|scope|stale/i),
      });
      expect("escalation" in prep && prep.escalation).toBeTruthy();
    } finally {
      rmSync(root, { recursive: true, force: true });
      rmSync(ledgerDir, { recursive: true, force: true });
    }
  });
});

describe("#1094 R3 F1 — relayed pool mounts the executing provider credential", () => {
  it("gpt-5.6-sol judge under grok-build pool mounts ~/.grok, not ~/.codex", async () => {
    const { RealFamilyBackend } = await import(
      "../../../src/family/realFamilyBackend.js"
    );
    const {
      SANDBOX_CODEX_DIR,
      SANDBOX_AGY_DIR,
      SANDBOX_GROK_DIR,
    } = await import("../../../src/realBackend.js");
    const { resolveModelSlugForPool } = await import(
      "../../../src/modelRegistry.js"
    );

    expect(resolveModelSlugForPool("gpt-5.6-sol", "grok-build").provider).toBe(
      "grok",
    );

    class JudgeSeam extends RealFamilyBackend {
      public cfg(auth: CmrAuth, model: string, billingPool?: string) {
        return this.cmrSandboxConfig(
          auth,
          { model, host: workerHostForModel(model) },
          undefined,
          billingPool !== undefined ? { billingPool } : undefined,
        );
      }
    }

    const workingRepo = mkdtempSync(join(tmpdir(), "1094-r3-f1-repo-"));
    const ledgerDir = mkdtempSync(join(tmpdir(), "1094-r3-f1-ledger-"));
    try {
      const be = new JudgeSeam({
        workingRepo,
        familyBase: "family/1094",
        ledgerDir,
        repo: "Akagilnc/ming-salvage-sim",
        base: "main",
        promptsDir,
        soulsDir,
        imageName: "img",
      });
      const auth = {
        codexAuthDir: "/tmp/r3-f1-codex",
        agyDir: "/tmp/r3-f1-agy",
        grokAuthDir: "/tmp/r3-f1-grok",
        claudeToken: "tok",
      };

      const relayed = be.cfg(auth, "gpt-5.6-sol", "grok-build");
      expect(relayed.mounts.some((m) => m.sandboxPath === SANDBOX_GROK_DIR)).toBe(
        true,
      );
      expect(relayed.mounts.some((m) => m.sandboxPath === SANDBOX_CODEX_DIR)).toBe(
        false,
      );
      expect(relayed.mounts.some((m) => m.sandboxPath === SANDBOX_AGY_DIR)).toBe(
        false,
      );

      const opusRelayed = be.cfg(auth, "opus", "codex-5h");
      expect(
        resolveModelSlugForPool("opus", "codex-5h").provider,
      ).toBe("codex");
      expect(
        opusRelayed.mounts.some((m) => m.sandboxPath === SANDBOX_CODEX_DIR),
      ).toBe(true);
    } finally {
      rmSync(workingRepo, { recursive: true, force: true });
      rmSync(ledgerDir, { recursive: true, force: true });
    }
  });
});

describe("#1094 R3 F2 — panel legs do not inherit the judge billingPool", () => {
  it("leg dispatch ctx carries no judge pool after a cmr-slot relay", async () => {
    const { runVerifyCmr } = await import("../../../src/family/verifyCmr.js");
    const { buildExplicitLandingLiveHooks } = await import(
      "../../../src/family/landing.js"
    );
    const { completeCmrPanelLegWorker, isCmrPanelLegWorker } = await import(
      "../../helpers/cmr-panel-leg-dispatch.js"
    );
    const { legacyCmrScriptToWorkerOutput } = await import(
      "../../helpers/judge-fixtures.js"
    );

    const legPools: Array<string | undefined> = [];
    let judgePool: string | undefined;

    const backend = {
      ledger: [] as FamilyLedgerEntry[],
      escalations: [] as FamilyEscalation[],
      resolveLandingLiveHooks(input: {
        prUrl: string;
        convergedHeadOid: string;
        familyBase: string;
      }) {
        return buildExplicitLandingLiveHooks({
          prUrl: input.prUrl,
          headOid: input.convergedHeadOid,
          remoteBranchName: input.familyBase,
        });
      },
      async mergeChildIntoFamilyBase() {
        return { familyHead: "head-1" };
      },
      async resolveMergeConflict() {
        throw new Error("unused");
      },
      async appendFamilyLedger(entry: FamilyLedgerEntry) {
        this.ledger.push(entry);
      },
      async readFamilyLedger() {
        return this.ledger;
      },
      async readFamilyHead() {
        return "head-1";
      },
      async runFamilyVerify() {
        return { ok: true };
      },
      async dispatchWorker(
        spec: WorkerSpec,
        ctx: DispatchContext,
      ): Promise<WorkerResult> {
        if (isCmrPanelLegWorker(spec)) {
          legPools.push(ctx.billingPool);
          return (
            completeCmrPanelLegWorker(spec) ?? {
              kind: "failed",
              reason: "panel leg fixture missing",
            }
          );
        }
        if (spec.kind === "cmr") {
          judgePool = ctx.billingPool;
          return {
            kind: "completed",
            output: legacyCmrScriptToWorkerOutput({
              converged: true,
              successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
              evidencePaths: ["cmr/review-summary.json"],
              findings: [],
            }),
          };
        }
        if (spec.kind === "ship") {
          return {
            kind: "completed",
            output: {
              kind: "ship",
              branch: ctx.familyBase!,
              pr: "https://github.com/test/repo/pull/1094",
              prHead: "head-1",
              status: "pr_opened",
            },
          };
        }
        return { kind: "failed", reason: `unexpected ${spec.kind}` };
      },
      async recordAborted() {},
      async escalateFamily(esc: FamilyEscalation) {
        this.escalations.push(esc);
      },
    };

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/1094-r3-f2",
      familyBackend: backend,
      billingPool: "grok-build",
      billingPoolSlots: ["cmrCorrectness", "cmrCompleteness"],
    });

    // Seam under test is leg vs judge pool — not the post-ship online-review stage.
    void result;
    expect(judgePool).toBe("grok-build");
    expect(legPools.length).toBeGreaterThan(0);
    expect(legPools.every((p) => p === undefined)).toBe(true);
  });
});

describe("#1080 R3 — panel legs do not inherit the pure-court resumeSessionId", () => {
  it("outer-gate panel fan-out strips judge resume even after a prior court open", async () => {
    // After coder-fix, pure-judge receive soft-accepts and re-opens with panels
    // while the pure court itself resumes. Legs must stay session:"fresh" with
    // no resumeSessionId — else forbidFreshRetry collapses their retry budget.
    const { runVerifyCmr } = await import("../../../src/family/verifyCmr.js");
    const { buildExplicitLandingLiveHooks } = await import(
      "../../../src/family/landing.js"
    );
    const { completeCmrPanelLegWorker, isCmrPanelLegWorker } = await import(
      "../../helpers/cmr-panel-leg-dispatch.js"
    );
    const {
      completedJudge,
      judgeContinue,
      judgeConverged,
      sampleFinding,
    } = await import("../../helpers/judge-fixtures.js");

    const legResumes: Array<string | undefined> = [];
    const judgeResumes: Array<string | undefined> = [];
    let correctnessOpens = 0;
    const finding = sampleFinding("panel resume leak", "pl.ts:1");

    const backend = {
      ledger: [] as FamilyLedgerEntry[],
      escalations: [] as FamilyEscalation[],
      resolveLandingLiveHooks(input: {
        prUrl: string;
        convergedHeadOid: string;
        familyBase: string;
      }) {
        return buildExplicitLandingLiveHooks({
          prUrl: input.prUrl,
          headOid: input.convergedHeadOid,
          remoteBranchName: input.familyBase,
        });
      },
      async mergeChildIntoFamilyBase() {
        return { familyHead: "head-1" };
      },
      async resolveMergeConflict() {
        throw new Error("unused");
      },
      async appendFamilyLedger(entry: FamilyLedgerEntry) {
        this.ledger.push(entry);
      },
      async readFamilyLedger() {
        return this.ledger;
      },
      async readFamilyHead() {
        return "head-1";
      },
      async runFamilyVerify() {
        return { ok: true };
      },
      async dispatchWorker(
        spec: WorkerSpec,
        ctx: DispatchContext,
      ): Promise<WorkerResult> {
        if (isCmrPanelLegWorker(spec)) {
          legResumes.push(ctx.resumeSessionId);
          return (
            completeCmrPanelLegWorker(spec) ?? {
              kind: "failed",
              reason: "panel leg fixture missing",
            }
          );
        }
        if (spec.kind === "cmr") {
          judgeResumes.push(ctx.resumeSessionId);
          if (ctx.cmrPass === "completeness") {
            return completedJudge(judgeConverged(), "sess-comp-1080-r3");
          }
          correctnessOpens += 1;
          if (correctnessOpens === 1) {
            return completedJudge(
              judgeContinue([finding]),
              "sess-corr-1080-r3",
            );
          }
          return completedJudge(judgeConverged(), "sess-corr-1080-r3");
        }
        if (spec.kind === "coder") {
          return {
            kind: "completed",
            output: { kind: "coder", committed: true, commitsAdded: 1 },
            sessionId: "sess-fix-1080-r3",
          };
        }
        if (spec.kind === "ship") {
          return {
            kind: "completed",
            output: {
              kind: "ship",
              branch: ctx.familyBase!,
              pr: "https://github.com/test/repo/pull/1080",
              prHead: "head-1",
              status: "pr_opened",
            },
          };
        }
        return { kind: "failed", reason: `unexpected ${spec.kind}` };
      },
      async recordAborted() {},
      async escalateFamily(esc: FamilyEscalation) {
        this.escalations.push(esc);
      },
    };

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/1080-r3-panel-resume",
      familyBackend: backend,
      familyHeadAfter: "head-1",
    });

    void result;
    // Outer-gate reopen must have fanned panels after a pure-court resume existed.
    expect(judgeResumes.some((r) => r === "sess-corr-1080-r3")).toBe(true);
    expect(legResumes.length).toBeGreaterThan(0);
    // Load-bearing: no panel leg ever carries the pure-court resume id.
    expect(legResumes.every((r) => r === undefined)).toBe(true);
  });
});

describe("#1094 R3 F3 / #1118 — zero successful panel legs still open pure court", () => {
  it("lands skip reasons, opens judge, judge escalates (no runner direct-stop)", async () => {
    const { runVerifyCmr } = await import("../../../src/family/verifyCmr.js");
    const { buildExplicitLandingLiveHooks } = await import(
      "../../../src/family/landing.js"
    );
    const { isCmrPanelLegWorker } = await import(
      "../../helpers/cmr-panel-leg-dispatch.js"
    );

    let judgeDispatched = 0;
    let sawSkip = false;
    const backend = {
      ledger: [] as FamilyLedgerEntry[],
      escalations: [] as FamilyEscalation[],
      resolveLandingLiveHooks(input: {
        prUrl: string;
        convergedHeadOid: string;
        familyBase: string;
      }) {
        return buildExplicitLandingLiveHooks({
          prUrl: input.prUrl,
          headOid: input.convergedHeadOid,
          remoteBranchName: input.familyBase,
        });
      },
      async mergeChildIntoFamilyBase() {
        return { familyHead: "head-1" };
      },
      async resolveMergeConflict() {
        throw new Error("unused");
      },
      async appendFamilyLedger(entry: FamilyLedgerEntry) {
        this.ledger.push(entry);
      },
      async readFamilyLedger() {
        return this.ledger;
      },
      async readFamilyHead() {
        return "head-1";
      },
      async runFamilyVerify() {
        return { ok: true };
      },
      async dispatchWorker(
        spec: WorkerSpec,
        ctx: DispatchContext,
        landing?: import("../../../src/types.js").WorkerLandingPayload,
      ): Promise<WorkerResult> {
        if (isCmrPanelLegWorker(spec)) {
          return {
            kind: "failed",
            reason: `docker flake on ${spec.model}`,
          };
        }
        if (spec.kind === "cmr") {
          judgeDispatched += 1;
          const skips =
            landing?.panelLegSkippedLegs ?? ctx.panelLegSkippedLegs ?? [];
          if (skips.length > 0) sawSkip = true;
          // #1118: judge is the sole closer — escalate on empty paper.
          return {
            kind: "completed",
            output: {
              kind: "judge",
              status: "escalate",
              reason: `family integrated cmr ${ctx.cmrPass ?? "?"}: zero successful panel legs`,
              diagnosis: skips.map((s) => `${s.slug}: ${s.reason}`).join("; "),
            },
          };
        }
        void ctx;
        return { kind: "failed", reason: `unexpected ${spec.kind}` };
      },
      async recordAborted() {},
      async escalateFamily(esc: FamilyEscalation) {
        this.escalations.push(esc);
      },
    };

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/1094-r3-f3",
      familyBackend: backend,
    });

    expect(result.ok).toBe(false);
    expect(judgeDispatched).toBeGreaterThan(0);
    expect(sawSkip).toBe(true);
    expect(
      backend.ledger.some((e) => e.status === "cmr_passed"),
    ).toBe(false);
    expect(backend.escalations.length).toBeGreaterThan(0);
    expect(backend.escalations[0]?.escalationKind).toBe("decision");
    expect(backend.escalations[0]?.reason).toMatch(/zero successful panel legs/i);
    expect(backend.escalations[0]?.diagnosis).toMatch(/docker flake/i);
  });
});

describe("#1094 R3 F4 — focus-copy failure degrades the leg (never present)", () => {
  it("missing .cmr-focus.md yields failed transport, not a green present leg", async () => {
    const { execFileSync } = await import("node:child_process");
    const { RealFamilyBackend, CMR_FOCUS_FILENAME } = await import(
      "../../../src/family/realFamilyBackend.js"
    );
    const { legTransportFromPanelLegResult } = await import(
      "../../../src/family/cmrPanelLegs.js"
    );
    const { isLegalLegPaper } = await import("../../../src/legPaper.js");

    const root = mkdtempSync(join(tmpdir(), "1094-r3-f4-"));
    const ledger = mkdtempSync(join(tmpdir(), "1094-r3-f4-ledger-"));
    try {
      execFileSync("git", ["init"], { cwd: root });
      execFileSync("git", ["config", "user.email", "t@t"], { cwd: root });
      execFileSync("git", ["config", "user.name", "t"], { cwd: root });
      writeFileSync(join(root, "a.txt"), "a\n");
      execFileSync("git", ["add", "."], { cwd: root });
      execFileSync("git", ["commit", "-m", "init"], { cwd: root });
      execFileSync("git", ["branch", "-M", "main"], { cwd: root });
      // Intentionally NO .cmr-focus.md — copyFileSync must fail-loud.

      class FocusFailBackend extends RealFamilyBackend {
        public async runLeg(
          spec: ReturnType<typeof cmrPanelLegWorkerSpec>,
          ctx: DispatchContext,
        ) {
          return this.runCmrPanelLegWorker(spec, ctx);
        }
        protected mountCmrAuth() {
          return {
            codexAuthDir: mkdtempSync(join(tmpdir(), "f4-codex-")),
            agyDir: undefined,
            grokAuthDir: undefined,
            claudeToken: undefined,
            ghToken: undefined,
            providerAuth: { claude: false, grok: false, agy: false },
          };
        }
        protected unavailableWorkerProviderAuth() {
          return undefined;
        }
        protected async runAgentSandbox(): Promise<never> {
          throw new Error("runAgentSandbox must not run after focus-copy failure");
        }
      }

      const be = new FocusFailBackend({
        workingRepo: root,
        familyBase: "main",
        ledgerDir: ledger,
        repo: "Akagilnc/ming-salvage-sim",
        base: "main",
        promptsDir,
        soulsDir,
        imageName: "img",
      });
      const spec = cmrPanelLegWorkerSpec(
        { family: "codex", slug: "gpt-5.6-sol" },
        "correctness",
      );
      const result = await be.runLeg(spec, { familyBase: "main" });
      expect(result.kind).toBe("failed");
      if (result.kind === "failed") {
        expect(result.reason).toMatch(new RegExp(CMR_FOCUS_FILENAME));
      }
      const transport = legTransportFromPanelLegResult("gpt-5.6-sol", result);
      expect(isLegalLegPaper(transport)).toBe(false);
      expect(transport.exitCode).not.toBe(0);
    } finally {
      rmSync(root, { recursive: true, force: true });
      rmSync(ledger, { recursive: true, force: true });
    }
  });
});

describe("#1094 R3 F5 — lens follows spec.promptFile (not ctx.cmrPass)", () => {
  it("reads completeness promptFile even when ctx.cmrPass is correctness", async () => {
    const { execFileSync } = await import("node:child_process");
    const { RealFamilyBackend, CMR_FOCUS_FILENAME } = await import(
      "../../../src/family/realFamilyBackend.js"
    );

    const root = mkdtempSync(join(tmpdir(), "1094-r3-f5-"));
    const ledger = mkdtempSync(join(tmpdir(), "1094-r3-f5-ledger-"));
    let capturedPrompt = "";
    try {
      execFileSync("git", ["init"], { cwd: root });
      execFileSync("git", ["config", "user.email", "t@t"], { cwd: root });
      execFileSync("git", ["config", "user.name", "t"], { cwd: root });
      writeFileSync(join(root, "a.txt"), "a\n");
      execFileSync("git", ["add", "."], { cwd: root });
      execFileSync("git", ["commit", "-m", "init"], { cwd: root });
      execFileSync("git", ["branch", "-M", "main"], { cwd: root });
      writeFileSync(
        join(root, CMR_FOCUS_FILENAME),
        "# focus\n`git diff aaa...bbb`\n",
      );

      class LensBackend extends RealFamilyBackend {
        public async runLeg(
          spec: ReturnType<typeof cmrPanelLegWorkerSpec>,
          ctx: DispatchContext,
        ) {
          return this.runCmrPanelLegWorker(spec, ctx);
        }
        protected mountCmrAuth() {
          return {
            codexAuthDir: mkdtempSync(join(tmpdir(), "f5-codex-")),
            agyDir: undefined,
            grokAuthDir: undefined,
            claudeToken: undefined,
            ghToken: undefined,
            providerAuth: { claude: false, grok: false, agy: false },
          };
        }
        protected unavailableWorkerProviderAuth() {
          return undefined;
        }
        protected override async runAgentSandbox(
          options: { promptFile?: string },
        ): Promise<{
          stdout: string;
          iterations: never[];
          commits: never[];
          branch: string;
        }> {
          capturedPrompt = readFileSync(options.promptFile!, "utf8");
          return {
            stdout: "P1: lens authority must follow spec.promptFile.\n",
            iterations: [],
            commits: [],
            branch: "HEAD",
          };
        }
      }

      const be = new LensBackend({
        workingRepo: root,
        familyBase: "main",
        ledgerDir: ledger,
        repo: "Akagilnc/ming-salvage-sim",
        base: "main",
        promptsDir,
        soulsDir,
        imageName: "img",
      });
      // Spec pinned to completeness lens; ctx deliberately disagrees.
      const spec = cmrPanelLegWorkerSpec(
        { family: "codex", slug: "gpt-5.6-sol" },
        "completeness",
      );
      expect(spec.promptFile).toBe("cmr_panel_leg_completeness.md");
      const result = await be.runLeg(spec, {
        familyBase: "main",
        cmrPass: "correctness",
      });
      expect(result.kind).toBe("completed");
      expect(capturedPrompt).toMatch(/Clause–Wire–Exercise/);
      expect(capturedPrompt).not.toMatch(/Trace–Break–Prove/);
      expect(capturedPrompt).toMatch(/CMR pass: completeness/);
    } finally {
      rmSync(root, { recursive: true, force: true });
      rmSync(ledger, { recursive: true, force: true });
    }
  });
});

describe("#1094 R4 F-A — setup/clone failure degrades the leg (never whole-pass cmr_failed)", () => {
  it("preparePanelLegClone reclaims legRoot when clone fails", async () => {
    const { RealFamilyBackend } = await import(
      "../../../src/family/realFamilyBackend.js"
    );
    const notARepo = mkdtempSync(join(tmpdir(), "1094-r4-fa-norepo-"));
    const ledger = mkdtempSync(join(tmpdir(), "1094-r4-fa-ledger-"));
    try {
      class CloneBackend extends RealFamilyBackend {
        public clone(slug: string, sha: string): string {
          return this.preparePanelLegClone(slug, sha);
        }
      }
      const be = new CloneBackend({
        workingRepo: notARepo,
        familyBase: "main",
        ledgerDir: ledger,
        repo: "Akagilnc/ming-salvage-sim",
        base: "main",
        promptsDir,
        soulsDir,
        imageName: "img",
      });
      expect(() =>
        be.clone("gpt-5.6-sol", "0000000000000000000000000000000000000000"),
      ).toThrow();
      expect(
        readdirSync(ledger).filter((n) => n.startsWith("panel-leg-")),
      ).toEqual([]);
    } finally {
      rmSync(notARepo, { recursive: true, force: true });
      rmSync(ledger, { recursive: true, force: true });
    }
  });

  it("clone/setup throw yields failed transport; sibling legs still settle", async () => {
    const { execFileSync } = await import("node:child_process");
    const { RealFamilyBackend, CMR_FOCUS_FILENAME } = await import(
      "../../../src/family/realFamilyBackend.js"
    );
    const { panelLegCompletedResult } = await import(
      "../../../src/family/cmrPanelLegs.js"
    );
    const { isLegalLegPaper } = await import("../../../src/legPaper.js");

    const root = mkdtempSync(join(tmpdir(), "1094-r4-fa-setup-"));
    const ledger = mkdtempSync(join(tmpdir(), "1094-r4-fa-setup-ledger-"));
    try {
      execFileSync("git", ["init"], { cwd: root });
      execFileSync("git", ["config", "user.email", "t@t"], { cwd: root });
      execFileSync("git", ["config", "user.name", "t"], { cwd: root });
      writeFileSync(join(root, "a.txt"), "a\n");
      execFileSync("git", ["add", "."], { cwd: root });
      execFileSync("git", ["commit", "-m", "init"], { cwd: root });
      execFileSync("git", ["branch", "-M", "main"], { cwd: root });
      writeFileSync(
        join(root, CMR_FOCUS_FILENAME),
        "# focus\n`git diff aaa...bbb`\n",
      );

      class SetupFailBackend extends RealFamilyBackend {
        public async runLeg(
          spec: ReturnType<typeof cmrPanelLegWorkerSpec>,
          ctx: DispatchContext,
        ) {
          return this.runCmrPanelLegWorker(spec, ctx);
        }
        protected mountCmrAuth() {
          return {
            codexAuthDir: mkdtempSync(join(tmpdir(), "r4-fa-codex-")),
            agyDir: undefined,
            grokAuthDir: undefined,
            claudeToken: undefined,
            ghToken: undefined,
            providerAuth: { claude: false, grok: false, agy: false },
          };
        }
        protected unavailableWorkerProviderAuth() {
          return undefined;
        }
        protected preparePanelLegClone(): string {
          throw new Error("git clone failed: simulated");
        }
        protected async runAgentSandbox(): Promise<never> {
          throw new Error("runAgentSandbox must not run after clone failure");
        }
      }

      const be = new SetupFailBackend({
        workingRepo: root,
        familyBase: "main",
        ledgerDir: ledger,
        repo: "Akagilnc/ming-salvage-sim",
        base: "main",
        promptsDir,
        soulsDir,
        imageName: "img",
      });
      const failingSpec = cmrPanelLegWorkerSpec(
        { family: "codex", slug: "gpt-5.6-sol" },
        "correctness",
      );
      const failed = await be.runLeg(failingSpec, { familyBase: "main" });
      expect(failed.kind).toBe("failed");
      if (failed.kind === "failed") {
        expect(failed.reason).toMatch(/panel leg gpt-5\.6-sol:.*git clone failed/i);
      }
      const failedTransport = legTransportFromPanelLegResult(
        "gpt-5.6-sol",
        failed,
      );
      expect(isLegalLegPaper(failedTransport)).toBe(false);

      // Fan-out: one failed transport + one legal sibling — judge still opens
      // (siblings settle; zero-success path stays R3 F3 escalate, not touched).
      let siblingRan = false;
      const round = await dispatchFamilyCmrPanelLegs({
        legs: [
          { family: "codex", slug: "gpt-5.6-sol" },
          { family: "claude", slug: "opus" },
        ],
        dispatch: async (spec) => {
          if (spec.model === "gpt-5.6-sol") return failed;
          siblingRan = true;
          return panelLegCompletedResult(
            "P1: sibling panel leg still ran after peer clone failure.\n",
          );
        },
      });
      expect(siblingRan).toBe(true);
      expect(round.transports).toHaveLength(2);
      expect(successfulLegsFromTransports(round.transports)).toEqual(["opus"]);
      expect(round.skippedLegs.map((s) => s.slug)).toContain("gpt-5.6-sol");
    } finally {
      rmSync(root, { recursive: true, force: true });
      rmSync(ledger, { recursive: true, force: true });
    }
  });
});
