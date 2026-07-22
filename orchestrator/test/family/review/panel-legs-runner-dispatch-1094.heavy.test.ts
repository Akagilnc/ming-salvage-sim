/**
 * #1094 heavy — real-git panel-leg integration cases (clone / focus / prep).
 * Fast pool forbids execFileSync (fast-tax-guard); these pay process tax here.
 */
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

