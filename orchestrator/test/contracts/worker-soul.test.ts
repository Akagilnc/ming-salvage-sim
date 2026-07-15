/**
 * #334 — the first end-to-end tracer for running slice workers through the
 * unified dispatchWorker seam (ADR 0026 / PRD #330), on the baked 2b image.
 * ADR 0030 later split per-slice review/fix convergence into separate
 * runner-visible reviewer/coder-fix worker boundaries.
 *
 * This slice makes the seam REAL in two ways the #331 prefactor only declared:
 *
 *   1. RealBackend's sandbox stops bind-mounting host skills at runtime
 *      (host skill mounts) — the baked image's skills win (cross-slice note from
 *      #332/#333: the runtime mount SHADOWS the baked skills). The behaviour
 *      change is assertable on the pure `boxConfig()` seam (no container needed),
 *      mirroring the family `mergerSandboxConfig()` testability pattern.
 *
 *   2. The versioned promptFiles are THIN entrypoints: they read the baked soul,
 *      live-fetch the issue through gh, and define the output contract. They do
 *      NOT hand-copy the TDD/review/fix METHOD into the prompt. The workflow lives
 *      in the baked soul + skills.
 *
 * Plus the load-bearing [C] (ADR 0030): the runner dispatches implementation,
 * reviewer, fix, reviewer, and ship workers through visible boundaries.
 */

import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";

// vi.mock hoisted. Literal key avoids TDZ/eval order issues with vitest transform.
// Only mock child_process (this file never calls it directly); for launcher smoke
// we create a temp stub dist/ so dynamic import succeeds without side effects.
vi.mock("node:child_process", () => ({
  execFileSync: vi.fn(() => ""),
}));

import { afterAll, afterEach, describe, expect, it, vi } from "vitest";
import { runOrchestrator } from "../../src/runner.js";
import {
  RealBackend,
  SANDBOX_CODEX_DIR,
  SANDBOX_FIX_FINDINGS_PATH_ENV,
  SANDBOX_GH_TOKEN_ENV,
  SANDBOX_ISSUE_NUMBER_ALIAS_ENV,
  SANDBOX_ISSUE_NUMBER_ENV,
  SANDBOX_REPO_ENV,
  SANDBOX_SKILLS_DIR,
  SANDBOX_SOUL_ENV,
  SPAWNED_WORKER_ENV,
  soulsMount,
} from "../../src/realBackend.js";
import type {
  Backend,
  DispatchContext,
  Finding,
  IssueMeta,
  IssueSnapshot,
  PersistentLedgerEntry,
  StepOutput,
  StepSpec,
  WorkerResult,
  WorkerSpec,
  WorktreeHandle,
} from "../../src/types.js";

const here = dirname(fileURLToPath(import.meta.url));
const promptsDir = join(here, "..", "..", "prompts");
const imageDir = join(here, "..", "..", "image");
const soulsDir = join(here, "..", "..", "image", "souls");

const tempHomes: string[] = [];

function cleanupTempHomes(): void {
  while (tempHomes.length > 0) {
    const home = tempHomes.pop();
    if (home !== undefined) rmSync(home, { recursive: true, force: true });
  }
}

afterEach(cleanupTempHomes);
afterAll(cleanupTempHomes);

// ─── (1) RealBackend.boxConfig uses baked skills (#334) ──────────────────────

describe("#334 RealBackend.boxConfig uses baked skills", () => {
  /** Stub the clone seams so construction never shells out to git. */
  class StubBackend extends RealBackend {
    protected override cloneDirExists(): boolean {
      return true;
    }
    protected override sh(file: string, args: string[]): string {
      if (file === "git" && args[0] === "rev-parse" && args[1] === "--git-common-dir") {
        return ".git";
      }
      return "";
    }
    // Expose the pure config seam + a way to feed canned auth without reading
    // host credential files (the auth-file I/O is not under test here).
    public config(
      spec: StepSpec,
      options?: Parameters<RealBackend["runStep"]>[2],
    ): {
      imageName: string;
      env: Record<string, string>;
      mounts: ReadonlyArray<{ hostPath: string; sandboxPath: string; readonly?: boolean }>;
    } {
      return this.boxConfig(
        { authDir: "/tmp/auth-256", claudeToken: "tok", ghToken: "gho_test" },
        spec,
        334,
        options,
      );
    }
  }

  const coderSpec: StepSpec = {
    id: "S2",
    role: "coder",
    promptFile: "coder_implement.md",
    model: "sonnet",
    completionSignal: "CODER_STEP_COMPLETE",
    maxIter: 5,
    soul: "coder",
    toolchain: ["python"],
  };

  function makeBackend(): StubBackend {
    const home = mkdtempSync(join(tmpdir(), "rb-home-334-"));
    tempHomes.push(home);
    return new StubBackend({
      sourceRepo: "/tmp/source",
      remote: "https://github.com/owner/name.git",
      runKey: 999,
      repo: "owner/name",
      imageName: "ming-orchestrator-coder:latest",
      promptsDir,
      soulsDir,
      // #748: construction resolves paths under home; keep off real $HOME.
      home,
    });
  }

  it("the sandbox mounts do NOT include the host skills dir (baked skills are used)", () => {
    const cfg = makeBackend().config(coderSpec);
    const skillMount = cfg.mounts.find(
      (m) => m.sandboxPath === SANDBOX_SKILLS_DIR,
    );
    expect(skillMount).toBeUndefined();
  });

  it("still mounts codex auth + injects the role soul (only the skills mount is dropped)", () => {
    const cfg = makeBackend().config(coderSpec);
    expect(
      cfg.mounts.some((m) => m.sandboxPath === SANDBOX_CODEX_DIR),
    ).toBe(true);
    expect(cfg.env[SANDBOX_SOUL_ENV]).toBe("coder");
  });

  it("#905: boxConfig does not mount opencode auth or inject GLM_KEY", () => {
    vi.stubEnv("GLM_KEY", "glm-secret");
    const cfg = makeBackend().config(coderSpec, { billingPool: "zai" });
    expect(cfg.env.GLM_KEY).toBeUndefined();
    expect(
      cfg.mounts.some((m) => m.sandboxPath.includes("opencode")),
    ).toBe(false);
  });

  it("boxConfig includes soulsMount() shape (hostPath/sandboxPath/readonly:true) at this site (#372)", () => {
    const cfg = makeBackend().config(coderSpec);
    const expected = soulsMount(soulsDir);
    expect(cfg.mounts).toContainEqual(expected);
    expect(expected).toEqual({ hostPath: soulsDir, sandboxPath: "/home/agent/.orchestrator/souls", readonly: true });
  });

  it("injects live issue coordinates and GH_TOKEN for the worker's gh issue read", () => {
    const cfg = makeBackend().config(coderSpec);
    expect(cfg.env[SANDBOX_ISSUE_NUMBER_ENV]).toBe("334");
    expect(cfg.env[SANDBOX_ISSUE_NUMBER_ALIAS_ENV]).toBe("334");
    expect(cfg.env[SANDBOX_REPO_ENV]).toBe("owner/name");
    expect(cfg.env[SANDBOX_GH_TOKEN_ENV]).toBe("gho_test");
  });

  it("mounts S5 fix findings at the documented worktree-root path read-only", () => {
    const cfg = makeBackend().config(coderSpec, {
      fixFindingsLanding: {
        path: "/host/.ledger-334/fix-findings.json",
        sandboxPath: ".orchestrator-fix-findings.json",
      },
    });

    expect(cfg.env[SANDBOX_FIX_FINDINGS_PATH_ENV]).toBe(
      ".orchestrator-fix-findings.json",
    );
    expect(cfg.mounts).toContainEqual({
      hostPath: "/host/.ledger-334/fix-findings.json",
      sandboxPath: ".orchestrator-fix-findings.json",
      readonly: true,
    });
  });

  it("marks the coder/agent container as an orchestrator-spawned, non-interactive session", () => {
    const cfg = makeBackend().config(coderSpec);
    expect(cfg.env.OPENCLAW_SESSION).toBe("1");
    expect(cfg.env.OPENCLAW_SESSION).toBe(SPAWNED_WORKER_ENV.OPENCLAW_SESSION);
  });

  it("constructs without a host skills option (#334)", () => {
    // The baked image provides
    // skills, so the host mount path is gone from the options contract.
    expect(() => makeBackend()).not.toThrow();
  });
});

// ─── (2) the versioned prompts are THIN — invoke the skill, not hand-copy it ──

describe("#334 thin prompts read souls (mounted live per #372) and do not hand-copy methodology", () => {
  const read = (f: string): string => readFileSync(join(promptsDir, f), "utf8");
  const readSoul = (f: string): string =>
    readFileSync(join(here, "..", "..", "image", "souls", f), "utf8");

  it("coder_implement.md is an entrypoint, not a TDD/review mini-wiki", () => {
    const p = read("coder_implement.md");
    expect(p).toMatch(/\/home\/agent\/\.orchestrator\/souls\/coder\.md/);
    expect(p).toMatch(/ORCHESTRATOR_ISSUE_NUMBER|ISSUE_NUMBER/);
    expect(p).toMatch(/ORCHESTRATOR_REPO/);
    expect(p).toMatch(/gh/i);
    expect(p).not.toMatch(/\.orchestrator-snapshot\.json.*read it FIRST/is);
    expect(p).not.toMatch(/\bRED\b|\bGREEN\b|\brefactor\b|Baseline commit|\bOpus\b|\bsubagent\b|ak-cross-m-review/i);
  });

  it("fix/review prompts stay entrypoints; #911 vacuum puts mechanical method in prompts", () => {
    const fix = read("coder_fix.md");
    expect(fix).toMatch(/\/home\/agent\/\.orchestrator\/souls\/coder\.md/);
    expect(fix).toMatch(/fix-findings path|fix-findings\.json/i);
    expect(fix).toMatch(/escalationAnswer/i);
    expect(fix).not.toMatch(/sibling ledger|legacy compatibility fallback|Prefer the sibling ledger/is);
    // #911 vacuum: gh issue view / fix-focus method live in the fix prompt.
    expect(fix).toMatch(/gh issue view/i);
    expect(fix).toMatch(/\.fix-focus\.md/);

    const familyShip = read("family_ship.md");
    expect(familyShip).toMatch(/\/home\/agent\/\.orchestrator\/souls\/ship\.md/);
    expect(familyShip).toMatch(/gstack-ship/i);
    expect(familyShip).not.toMatch(/gh pr view|idempotent success case|version bump/i);

    const review = read("reviewer_review.md");
    expect(review).toMatch(/\/home\/agent\/\.orchestrator\/souls\/reviewer\.md/);
    expect(review).toMatch(/role soul \(live-mounted\)|review character belongs to the role soul/i);
    expect(review).toMatch(/escalationAnswer/i);
    // Snapshot policy is stated as not-execution-input (allowed).
    expect(review).toMatch(/not execution input/i);
  });

  it("the worker image bakes the Matt code-review skill for reviewer workers", () => {
    const build = readFileSync(join(imageDir, "build.sh"), "utf8");
    const start = build.indexOf("SKILL_CLOSURE=(");
    const end = build.indexOf(")", start);
    const closureBlock = build.slice(start, end);
    expect(closureBlock).toMatch(/\bcode-review\b/);
    // #372/#911: souls (+ home env) are mounted live, not staged/copied in build.sh.
    // The presence in source souls/ is asserted by other reads; build no longer bakes souls.
  });

  it("author-aware live issue reads live in implement + fix prompts", () => {
    const implement = read("coder_implement.md");
    const fix = read("coder_fix.md");
    expect(implement).toMatch(/gh issue view/i);
    expect(fix).toMatch(/gh issue view/i);
  });

  it("#419/#911 integrated cmr prompts point at pass soul paths; cmr_* resolve to verify", () => {
    const completenessPrompt = read("integrated_cmr_completeness.md");
    const correctnessPrompt = read("integrated_cmr_correctness.md");
    expect(completenessPrompt).toMatch(
      /\/home\/agent\/\.orchestrator\/souls\/cmr_completeness\.md/,
    );
    expect(correctnessPrompt).toMatch(
      /\/home\/agent\/\.orchestrator\/souls\/cmr_correctness\.md/,
    );
    expect(completenessPrompt).toMatch(/\bak-cmr-completeness\b/);
    expect(completenessPrompt).not.toMatch(/\bak-cmr-correctness\b/);
    expect(correctnessPrompt).toMatch(/\bak-cmr-correctness\b/);
    expect(correctnessPrompt).not.toMatch(/\bak-cmr-completeness\b/);

    // FS structure: both mount names resolve to the same verify body.
    expect(readSoul("cmr_completeness.md")).toBe(readSoul("verify.md"));
    expect(readSoul("cmr_correctness.md")).toBe(readSoul("verify.md"));
  });

  it("every existing prompt still defines its structured output contract (tag + signal)", () => {
    // Thinning the METHOD must not drop the output contract route()/the seam
    // decode against — each worker must still emit its tag + completion signal.
    // #924: single-slice coder seats use T2 station-receipt on <coder> (no
    // dedicated <decision> tag). Family ship/merger still use decision-gate.
    const prompts = [
      ["coder_implement.md", /<coder>/, /CODER_STEP_COMPLETE/, false],
      ["coder_fix.md", /<coder>/, /CODER_STEP_COMPLETE/, false],
      ["reviewer_review.md", /<review>/, /REVIEWER_STEP_COMPLETE/, false],
      ["family_ship.md", /<ship>/, /SHIP_STEP_COMPLETE/, true],
      ["integrated_cmr_completeness.md", /<cmr>/, /CMR_STEP_COMPLETE/, false],
      ["integrated_cmr_correctness.md", /<cmr>/, /CMR_STEP_COMPLETE/, false],
      ["merger_resolve_conflict.md", /<merger>/, /MERGER_STEP_COMPLETE/, true],
    ] as const;

    for (const [promptName, tag, signal, needsDecisionTag] of prompts) {
      const prompt = read(promptName);
      expect(prompt).toMatch(tag);
      expect(prompt).toMatch(signal);
      expect(prompt).toMatch(/\$ORCHESTRATOR_OUTCOME_PATH/);
      expect(prompt).not.toMatch(/python3 -m json\.tool "\$ORCHESTRATOR_OUTCOME_PATH"/);
      // Optional decision-gate seats always emit a dedicated <decision> tag so
      // ordinary cargo stays outside Output.object (#899). Coder seats (#924)
      // put traffic on the station-receipt <coder> envelope instead.
      if (needsDecisionTag) {
        expect(prompt).toMatch(/<decision>/);
      }
    }
  });

  it("production CMR prompts always require the configured <cmr> Output.object tag", () => {
    // #899: production CMR mounts outcome sidecar AND Output.object({tag:"cmr"}).
    // The prompt must require the cmr tag even when ORCHESTRATOR_OUTCOME_PATH is set,
    // otherwise Sandcastle has nothing to validate / re-ask.
    for (const promptName of [
      "integrated_cmr_completeness.md",
      "integrated_cmr_correctness.md",
    ] as const) {
      const prompt = read(promptName);
      expect(prompt).toMatch(/Always emit the typed `<cmr>` tag/);
      expect(prompt).toMatch(/Output\.object/);
      expect(prompt).not.toMatch(
        /Without \$ORCHESTRATOR_OUTCOME_PATH.*emit the `<cmr>` tag/,
      );
    }
  });

  it("#911 output_protocol.md is gone; outcome path contract lives in prompts", () => {
    expect(() => readSoul("output_protocol.md")).toThrow();
    for (const promptName of [
      "coder_implement.md",
      "reviewer_review.md",
      "merger_resolve_conflict.md",
      "family_ship.md",
    ]) {
      const prompt = read(promptName);
      expect(prompt).toMatch(/\$ORCHESTRATOR_OUTCOME_PATH/);
      expect(prompt).not.toMatch(/python3 -m json\.tool "\$ORCHESTRATOR_OUTCOME_PATH"/);
    }
  });
});

// ─── (3) the runner dispatches S2/S3, then S5/S6 while blockers remain ──────

/** A fake backend that records dispatch + drives a one-round fix loop. */
class ReviewWorkerBackend implements Backend {
  async smokeModelRoute(route: any) {
    const { smokeRouteModels } = await import("../../src/modelRoutes.js");
    return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
  }
  readonly dispatched: string[] = [];
  readonly specs: WorkerSpec[] = [];
  readonly ctxs: DispatchContext[] = [];
  private reviewCount = 0;

  readonly worktree: WorktreeHandle = {
    branch: "feat/orchestrator/issue-334",
    base: "main",
    path: "/resident/worktrees/issue-334",
  };

  async findResumeState(): Promise<undefined> {
    return undefined;
  }
  async resumeSession(): Promise<StepOutput> {
    throw new Error("resumeSession should not be called directly (#334)");
  }
  async fetchIssueMeta(issueNumber: number): Promise<IssueMeta> {
    return {
      number: issueNumber,
      isReadyForAgent: true,
      hasSubIssues: false,
      isClosed: false,
      openBlockedBy: [],
    };
  }
  async fetchIssueSnapshot(issueNumber: number): Promise<IssueSnapshot> {
    return { number: issueNumber, body: "b", comments: [], agentBrief: "" };
  }
  async prepareWorktree(): Promise<WorktreeHandle> {
    return this.worktree;
  }
  async writeSnapshot(): Promise<void> {}
  async runStep(): Promise<StepOutput> {
    throw new Error("runStep should not be called directly (#334)");
  }
  async writeLedger(): Promise<void> {}

  async dispatchWorker(
    spec: WorkerSpec,
    ctx: DispatchContext,
  ): Promise<WorkerResult> {
    this.dispatched.push(`${spec.id}:${spec.kind}:${spec.skill ?? "—"}`);
    this.specs.push(spec);
    this.ctxs.push(ctx);
    if (spec.kind === "coder") {
      return {
        kind: "completed",
        output: { kind: "coder", committed: true, commitsAdded: 1 },
      };
    }
    if (spec.kind === "reviewer") {
      this.reviewCount += 1;
      // Explicit open-count declaration for the fixture (ADR 0131 / #899): never
      // derive findingsCount from findings.length as if that were production law.
      const findingsCount = this.reviewCount === 1 ? 1 : 0;
      const findings: Finding[] =
        findingsCount === 1
          ? [
              {
                severity: "high",
                category: "correctness",
                claim_quote: "x",
                location: "f.ts:1",
                suggested_fix: "fix it",
                action: "fix_now",
              },
            ]
          : [];
      // Legacy compatibility shape: a reviewer worker returns findings, not a
      // bare verdict. The active runner path no longer dispatches it normally.
      return {
        kind: "completed",
        output: {
          kind: "reviewer",
          findings,
          findingsCount,
          ...(this.reviewCount > 1
            ? {
                priorFindingDispositions: [
                  {
                    identityKey: "correctness|f.ts:1|x",
                    status: "verified-closed",
                  },
                ],
              }
             : {}),
        },
      };
    }
    throw new Error(`unexpected child worker kind: ${spec.kind}`);
  }
}

describe("#334 ADR 0030 worker routing", () => {
  it("the S2 build coder worker is dispatched with skill /tdd", async () => {
    const backend = new ReviewWorkerBackend();
    await runOrchestrator({ issueNumber: 334, backend });
    const s2 = backend.specs.find((s) => s.id === "S2");
    expect(s2?.kind).toBe("coder");
    expect(s2?.skill).toBe("/tdd");
  });

  it("blocking review dispatches S5 fix, then S6 fresh review before handoff", async () => {
    const backend = new ReviewWorkerBackend();
    const result = await runOrchestrator({ issueNumber: 334, backend });
    expect(result.status).toBe("success");
    expect(backend.dispatched).toEqual([
      "S2:coder:/tdd",
      "S3:reviewer:/code-review",
      "S5:coder:/tdd",
      "S6:reviewer:/code-review",
    ]);
  });

});

describe("launch-362.mjs bootstrap smoke (#372 unconditional)", () => {
  it("mocks execFileSync and asserts side-build tsc + swap + build.sh are invoked (tsc before driver import)", async () => {
    const cp = await import("node:child_process");
    const execMock = cp.execFileSync as unknown as ReturnType<typeof vi.fn>;
    execMock.mockClear();

    // #859 hermetic: the launcher derives ORCH from its own file location, so
    // import a COPY inside a mkdtemp dir — the smoke must never write into (or
    // clean up) the REAL serving orchestrator/dist. The old version of this
    // test pre-created a stub in the real dist and its finally-block
    // `rmSync(real dist, recursive)` was the #859 assassin: every full-suite
    // run deleted the serving dist that live family runs resolve per-dispatch.
    const orchTmp = mkdtempSync(join(tmpdir(), "launch-362-smoke-"));
    const launcherCopy = join(orchTmp, "launch-362.mjs");
    writeFileSync(
      launcherCopy,
      readFileSync(join(here, "..", "..", "launch-362.mjs"), "utf8"),
      "utf8",
    );
    // Stub serving dist inside the tmpdir (mv/rm execs are mocked, so the stub
    // stays in place for the launcher's dynamic import).
    mkdirSync(join(orchTmp, "dist"), { recursive: true });
    writeFileSync(
      join(orchTmp, "dist", "familyDriver.js"),
      'export const runFamilyDriver = async () => ({});\nexport const resolveImageTag = (t) => t || "tag";\n',
      "utf8",
    );

    try {
      await import(pathToFileURL(launcherCopy).href);

      const calls = execMock.mock.calls as any[][];
      // side-build clean targets dist.new/dist.old, never the serving dist
      expect(
        calls.some(
          (c) =>
            c[0] === "rm" &&
            Array.isArray(c[1]) &&
            c[1].some((a: string) => String(a).includes("dist.new")),
        ),
      ).toBe(true);
      expect(
        calls.some(
          (c) => c[0] === "rm" && Array.isArray(c[1]) && c[1].includes("dist"),
        ),
      ).toBe(false);
      // tsc builds BESIDE the serving dist
      expect(
        calls.some(
          (c) =>
            c[0] === "npx" &&
            c[1]?.[0] === "tsc" &&
            c[1]?.includes("dist.new"),
        ),
      ).toBe(true);
      // swap step present
      expect(
        calls.some((c) => c[0] === "mv" && c[1]?.[0] === "dist.new" && c[1]?.[1] === "dist"),
      ).toBe(true);
      // build.sh
      expect(
        calls.some((c) => c[0] === "bash" && String(c[1]?.[0] || "").includes("build.sh")),
      ).toBe(true);
    } finally {
      try {
        rmSync(orchTmp, { recursive: true, force: true });
      } catch {}
    }
  });
});
