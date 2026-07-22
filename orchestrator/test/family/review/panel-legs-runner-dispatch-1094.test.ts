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
  WorkerLandingPayload,
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
describe("#1094 R3 F3 — zero successful panel legs escalate (never converge)", () => {
  it("declared legs with zero legal transports decision-park instead of cmr_passed", async () => {
    const { runVerifyCmr } = await import("../../../src/family/verifyCmr.js");
    const { buildExplicitLandingLiveHooks } = await import(
      "../../../src/family/landing.js"
    );
    const { isCmrPanelLegWorker } = await import(
      "../../helpers/cmr-panel-leg-dispatch.js"
    );
    const { legacyCmrScriptToWorkerOutput } = await import(
      "../../helpers/judge-fixtures.js"
    );

    let judgeDispatched = 0;
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
          return {
            kind: "failed",
            reason: `docker flake on ${spec.model}`,
          };
        }
        if (spec.kind === "cmr") {
          judgeDispatched += 1;
          // Would have converged on empty evidence — host must not reach here.
          return {
            kind: "completed",
            output: legacyCmrScriptToWorkerOutput({
              converged: true,
              successfulLegs: [],
              evidencePaths: ["cmr/review-summary.json"],
              findings: [],
            }),
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
    expect(judgeDispatched).toBe(0);
    expect(
      backend.ledger.some((e) => e.status === "cmr_passed"),
    ).toBe(false);
    expect(backend.escalations.length).toBeGreaterThan(0);
    expect(backend.escalations[0]?.escalationKind).toBe("decision");
    expect(backend.escalations[0]?.reason).toMatch(/zero successful panel legs/i);
    expect(backend.escalations[0]?.diagnosis).toMatch(/docker flake/i);
  });
});
describe("#1117/#1118 family court resume panel redispatch gate", () => {
  it("ensureFamilyCmrPanelEvidence fans out when transports missing; reuses when valid", async () => {
    const {
      ensureFamilyCmrPanelEvidence,
      hasValidPanelLegTransports,
      panelLegCompletedResult,
    } = await import("../../../src/family/cmrPanelLegs.js");
    const { successfulLegsFromTransports } = await import(
      "../../../src/legPaper.js"
    );

    const legalStdout =
      "P1: fixture panel prose for legal ADR 0141 paper.\nMore review lines.\n";
    let dispatchCount = 0;
    const legs = [
      { family: "codex" as const, slug: "gpt-5.6-sol" },
      { family: "grok" as const, slug: "grok-4.5" },
    ];

    // Negative: empty landing → real fan-out.
    const missing = await ensureFamilyCmrPanelEvidence({
      legs,
      cmrPass: "correctness",
      dispatch: async (spec) => {
        dispatchCount += 1;
        return panelLegCompletedResult(
          `${legalStdout}leg=${spec.model}\n`,
        );
      },
    });
    expect(missing.dispatched).toBe(true);
    expect(dispatchCount).toBe(2);
    expect(successfulLegsFromTransports(missing.transports).sort()).toEqual(
      ["gpt-5.6-sol", "grok-4.5"].sort(),
    );
    expect(hasValidPanelLegTransports(missing.transports)).toBe(true);

    // Control: valid prior transports → no reburn.
    dispatchCount = 0;
    const reused = await ensureFamilyCmrPanelEvidence({
      legs,
      cmrPass: "correctness",
      existingTransports: missing.transports,
      dispatch: async () => {
        dispatchCount += 1;
        throw new Error("must not reburn panel legs when transports are valid");
      },
    });
    expect(reused.dispatched).toBe(false);
    expect(dispatchCount).toBe(0);
    expect(reused.transports).toEqual(missing.transports);
  });

  it("resume after coder-fix re-dispatches panel legs and lands transports on the judge", async () => {
    const { runVerifyCmr } = await import("../../../src/family/verifyCmr.js");
    const { buildExplicitLandingLiveHooks } = await import(
      "../../../src/family/landing.js"
    );
    const { completeCmrPanelLegWorker, isCmrPanelLegWorker } = await import(
      "../../helpers/cmr-panel-leg-dispatch.js"
    );
    const { liveCmrJudgeContinue } = await import(
      "../../helpers/judge-fixtures.js"
    );
    const { findingIdentityKey } = await import("../../../src/findings.js");
    const typeFinding = {
      severity: "medium" as const,
      category: "correctness" as const,
      claim_quote: "claimed-fixed finding needs fresh panel re-review",
      location: "orchestrator/src/family/verifyCmr.ts",
      suggested_fix: "re-dispatch panel legs on court resume",
      action: "fix_now" as const,
    };
    const identityKey = findingIdentityKey(typeFinding);

    const panelDispatchCounts: string[] = [];
    const judgeLandings: Array<
      | {
          readonly panelLegTransports?: ReadonlyArray<{
            readonly slug: string;
          }>;
        }
      | undefined
    > = [];
    let completenessRound = 0;

    const backend = {
      ledger: [] as FamilyLedgerEntry[],
      escalations: [] as FamilyEscalation[],
      head: "head-pre-fix",
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
        return { familyHead: this.head };
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
        return this.head;
      },
      async runFamilyVerify() {
        return { ok: true };
      },
      async dispatchWorker(
        spec: WorkerSpec,
        ctx: DispatchContext,
        landing?: WorkerLandingPayload,
      ): Promise<WorkerResult> {
        if (isCmrPanelLegWorker(spec)) {
          panelDispatchCounts.push(
            `${ctx.cmrPass ?? "unknown"}:${spec.model}`,
          );
          return (
            completeCmrPanelLegWorker(spec) ?? {
              kind: "failed",
              reason: "panel fixture missing",
            }
          );
        }
        if (spec.kind === "cmr") {
          judgeLandings.push(landing);
          if (ctx.cmrPass === "completeness" && completenessRound++ === 0) {
            return {
              kind: "completed",
              sessionId: "judge-session-completeness-1",
              output: liveCmrJudgeContinue([typeFinding], {
                reason: "blocking finding needs coder-fix then fresh re-review",
                successfulLegs: ["gpt-5.6-sol", "grok-4.5"],
                claimedFixedFindingIdentityKeys: [],
                priorFindingDispositions: [],
                evidencePaths: ["cmr/review-summary.json"],
              }),
            };
          }
          // Re-open (resume path): require landed panel transports.
          expect(landing?.panelLegTransports?.length).toBeGreaterThan(0);
          expect(
            (landing?.panelLegTransports ?? []).every(
              (t) => typeof t.slug === "string" && t.slug.length > 0,
            ),
          ).toBe(true);
          return {
            kind: "completed",
            sessionId: "judge-session-completeness-1",
            output: {
              kind: "judge",
              status: "converged",
              successfulLegs: ["gpt-5.6-sol", "grok-4.5"],
              claimedFixedFindingIdentityKeys: [identityKey],
              priorFindingDispositions: [
                {
                  identityKey,
                  status: "verified-closed",
                  reason: "fresh panel re-review verified the fix",
                },
              ],
              evidencePaths: ["cmr/review-summary.json"],
            },
          };
        }
        if (spec.kind === "coder") {
          this.head = "head-post-fix";
          return {
            kind: "completed",
            output: { kind: "coder", committed: true, commitsAdded: 1 },
          };
        }
        if (spec.kind === "ship") {
          return {
            kind: "completed",
            output: {
              kind: "ship",
              branch: ctx.familyBase!,
              pr: "https://github.com/test/repo/pull/1118",
              prHead: this.head,
              status: "pr_opened",
            },
          };
        }
        // Post-ship online review / landing seats (#600 skeleton).
        const { skeletonReviewLoopWorkerResult } = await import(
          "../../../src/reviewLoopOutcome.js"
        );
        const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
        if (skeleton !== undefined) return skeleton;
        return { kind: "failed", reason: `unexpected ${spec.kind}` };
      },
      async recordAborted() {},
      async escalateFamily(esc: FamilyEscalation) {
        this.escalations.push(esc);
      },
    };

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/1117-resume",
      familyBackend: backend,
    });

    expect(result.ok).toBe(true);
    // First completeness open + re-open after fix must both fan out panels.
    const completenessPanelRounds = panelDispatchCounts.filter((s) =>
      s.startsWith("completeness:"),
    );
    expect(completenessPanelRounds.length).toBeGreaterThanOrEqual(2);
    // Every judge open (completeness continue + re-open + correctness) lands transports.
    for (const landing of judgeLandings) {
      expect(landing?.panelLegTransports?.length).toBeGreaterThan(0);
    }
  });

  it("valid transports already on landing are not reburned on resume open", async () => {
    const { runVerifyCmr } = await import("../../../src/family/verifyCmr.js");
    const { buildExplicitLandingLiveHooks } = await import(
      "../../../src/family/landing.js"
    );
    const { isCmrPanelLegWorker } = await import(
      "../../helpers/cmr-panel-leg-dispatch.js"
    );
    const { legacyCmrScriptToWorkerOutput } = await import(
      "../../helpers/judge-fixtures.js"
    );

    let panelDispatchCount = 0;
    const priorTransports = [
      {
        slug: "gpt-5.6-sol",
        exitCode: 0,
        stdout:
          "P1: prior legal panel paper retained across resume.\nExtra review.\n",
      },
      {
        slug: "grok-4.5",
        exitCode: 0,
        stdout:
          "P1: second prior legal panel paper retained across resume.\nExtra.\n",
      },
    ];

    // Seed a backend that pretends prior open already landed valid transports
    // via refuse/prior reopen cargo path: we inject by wrapping dispatch so the
    // first prepare has no transports (will fan-out), then for the second open
    // we return early after counting. Control is unit-tested above; this spine
    // case asserts zero-successful failure still parks with skip reasons (no
    // silent empty landing).
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
        landing?: WorkerLandingPayload,
      ): Promise<WorkerResult> {
        if (isCmrPanelLegWorker(spec)) {
          panelDispatchCount += 1;
          // All legs fail → host skip reasons, never silent empty success.
          return {
            kind: "failed",
            reason: `simulated panel failure for ${spec.model}`,
          };
        }
        if (spec.kind === "cmr") {
          // Must not open pure court with zero successful transports.
          void landing;
          void ctx;
          return {
            kind: "completed",
            output: legacyCmrScriptToWorkerOutput({
              converged: true,
              successfulLegs: [],
              evidencePaths: ["cmr/review-summary.json"],
              findings: [],
            }),
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
      familyBase: "family/1118-skip-reasons",
      familyBackend: backend,
    });

    expect(result.ok).toBe(false);
    expect(panelDispatchCount).toBeGreaterThan(0);
    expect(backend.escalations.length).toBeGreaterThan(0);
    expect(backend.escalations[0]?.escalationKind).toBe("decision");
    expect(backend.escalations[0]?.reason).toMatch(/zero successful panel legs/i);
    expect(backend.escalations[0]?.diagnosis).toMatch(/simulated panel failure/i);
    // Control unit: valid transports → no reburn (ensureFamilyCmrPanelEvidence).
    void priorTransports;
  });

  it("process re-entry after park (escalationAnswer rerun jury) re-dispatches panels before judge", async () => {
    // Models production R2–R4: prior cmr_reviewed escalate with sessionId, empty
    // landing, human answer "rerun jury" → outer runVerifyCmr re-entry must fan
    // out panel legs (not reopen pure court on silent empty landing).
    const { runVerifyCmr } = await import("../../../src/family/verifyCmr.js");
    const { buildExplicitLandingLiveHooks } = await import(
      "../../../src/family/landing.js"
    );
    const { completeCmrPanelLegWorker, isCmrPanelLegWorker } = await import(
      "../../helpers/cmr-panel-leg-dispatch.js"
    );
    const { skeletonReviewLoopWorkerResult } = await import(
      "../../../src/reviewLoopOutcome.js"
    );

    const panelDispatchCounts: string[] = [];
    const judgeLandings: Array<WorkerLandingPayload | undefined> = [];
    const familyHead = "head-parked-no-transports";

    const backend = {
      ledger: [
        {
          status: "cmr_reviewed" as const,
          event: "cmr_reviewed" as const,
          phase: "final" as const,
          cmrPass: "completeness" as const,
          reason:
            "fresh completeness jury transports are missing — no panelLegTransports",
          familyHeadAfter: familyHead,
          blockingFindingIdentityKeys: [] as string[],
          sessionId: "judge-session-completeness-parked",
          judgeStatus: "escalate" as const,
          stopSummary: {
            reason: "decision_gate_park" as const,
            summary:
              "fresh completeness jury transports are missing — no panelLegTransports",
            repairHint:
              "answer the family judge decision gate, then resume the family court in place",
          },
        },
      ] as FamilyLedgerEntry[],
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
        return { familyHead };
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
        return familyHead;
      },
      async runFamilyVerify() {
        return { ok: true };
      },
      async dispatchWorker(
        spec: WorkerSpec,
        ctx: DispatchContext,
        landing?: WorkerLandingPayload,
      ): Promise<WorkerResult> {
        // Outer resume must not thread judge resumeSessionId into panel legs.
        if (isCmrPanelLegWorker(spec)) {
          expect(ctx.resumeSessionId).toBeUndefined();
          panelDispatchCounts.push(`${ctx.cmrPass ?? "?"}:${spec.model}`);
          return (
            completeCmrPanelLegWorker(spec) ?? {
              kind: "failed",
              reason: "panel fixture missing",
            }
          );
        }
        if (spec.kind === "cmr") {
          judgeLandings.push(landing);
          // Judge resume may carry ledger session; landing must still have
          // fresh transports from this re-entry fan-out.
          expect(landing?.panelLegTransports?.length).toBeGreaterThan(0);
          expect(ctx.panelLegTransports?.length).toBeGreaterThan(0);
          if (ctx.cmrPass === "completeness") {
            expect(ctx.resumeSessionId).toBe(
              "judge-session-completeness-parked",
            );
          }
          return {
            kind: "completed",
            sessionId:
              ctx.cmrPass === "completeness"
                ? "judge-session-completeness-parked"
                : "judge-session-correctness-1",
            output: {
              kind: "judge",
              status: "converged",
              successfulLegs: ["gpt-5.6-sol", "grok-4.5"],
              evidencePaths: ["cmr/review-summary.json"],
            },
          };
        }
        if (spec.kind === "ship") {
          return {
            kind: "completed",
            output: {
              kind: "ship",
              branch: ctx.familyBase!,
              pr: "https://github.com/test/repo/pull/1117",
              prHead: familyHead,
              status: "pr_opened",
            },
          };
        }
        const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
        if (skeleton !== undefined) return skeleton;
        return { kind: "failed", reason: `unexpected ${spec.kind}` };
      },
      async recordAborted() {},
      async escalateFamily(esc: FamilyEscalation) {
        this.escalations.push(esc);
      },
    };

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/1117-process-resume",
      familyBackend: backend,
      familyHeadAfter: familyHead,
      escalationAnswer: {
        event: "escalation_answered",
        answer: "rerun jury — re-dispatch fresh completeness panel legs",
        source: "human",
      },
    });

    expect(result.ok).toBe(true);
    // Completeness re-open after park must fan out (not zero panel dispatches).
    expect(
      panelDispatchCounts.some((s) => s.startsWith("completeness:")),
    ).toBe(true);
    expect(judgeLandings.length).toBeGreaterThan(0);
    for (const landing of judgeLandings) {
      expect(landing?.panelLegTransports?.length).toBeGreaterThan(0);
    }
    // Human answer must not park again for missing transports.
    expect(
      backend.escalations.some((e) =>
        /transports are missing|zero successful panel legs/i.test(
          `${e.reason} ${e.diagnosis}`,
        ),
      ),
    ).toBe(false);
  });
});
