/**
 * #334 — the first end-to-end tracer: the coder worker invokes `/tdd` and the
 * per-slice reviewer worker invokes `/review`, both through the unified
 * dispatchWorker seam (ADR 0026 / PRD #330), running on the baked 2b image.
 *
 * This slice makes the seam REAL in two ways the #331 prefactor only declared:
 *
 *   1. RealBackend's sandbox stops bind-mounting host skills at runtime
 *      (`skillsMount`) — the baked image's skills win (cross-slice note from
 *      #332/#333: the runtime mount SHADOWS the baked skills). The behaviour
 *      change is assertable on the pure `boxConfig()` seam (no container needed),
 *      mirroring the family `mergerSandboxConfig()` testability pattern.
 *
 *   2. The versioned promptFiles are THIN: they tell the worker to invoke the
 *      skill (`/tdd` for the coder, `/review` for the reviewer) and let the
 *      discipline come from the baked image's CLAUDE.md `## Skill routing` +
 *      baked skill — they do NOT hand-copy the TDD/review METHOD into the prompt
 *      (ADR 0026: "prompt 收薄到『实现 issue #N，按本仓 CLAUDE.md dev 流程做』").
 *
 * Plus the load-bearing [C] (PRD #330 R2): the per-slice reviewer worker returns
 * a `ReviewerResult{findings}` and the runner's single-slice fix-loop ROUTES on
 * those findings (S3 findings → S5 fix → S6 approve → S7). This is the consumer
 * `selectFixNowFindings`/`isBlockingFinding` depend on; a bare verdict breaks it.
 */

import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { runOrchestrator } from "../src/runner.js";
import {
  RealBackend,
  SANDBOX_CODEX_DIR,
  SANDBOX_SKILLS_DIR,
  SANDBOX_SOUL_ENV,
} from "../src/realBackend.js";
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
} from "../src/types.js";

const here = dirname(fileURLToPath(import.meta.url));
const promptsDir = join(here, "..", "prompts");

// ─── (1) RealBackend.boxConfig drops the runtime skillsMount (#334) ───────────

describe("#334 RealBackend.boxConfig drops the runtime skillsMount (baked skills win)", () => {
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
    public config(spec: StepSpec): {
      imageName: string;
      env: Record<string, string>;
      mounts: ReadonlyArray<{ hostPath: string; sandboxPath: string }>;
    } {
      return this.boxConfig(
        { authDir: "/tmp/auth-256", claudeToken: "tok" },
        spec,
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
    return new StubBackend({
      sourceRepo: "/tmp/source",
      remote: "https://github.com/owner/name.git",
      runKey: 999,
      repo: "owner/name",
      imageName: "ming-orchestrator-coder:latest",
      promptsDir,
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

  it("skillsMount is no longer a required RealBackendOptions field (#334)", () => {
    // Construction WITHOUT skillsMount must succeed — the baked image provides
    // skills, so the host mount path is gone from the options contract.
    expect(() => makeBackend()).not.toThrow();
  });
});

// ─── (2) the versioned prompts are THIN — invoke the skill, not hand-copy it ──

describe("#334 thin prompts invoke the skill, not the methodology", () => {
  const read = (f: string): string => readFileSync(join(promptsDir, f), "utf8");

  it("coder_implement.md tells the worker to invoke /tdd (Skill routing), not red/green steps", () => {
    const p = read("coder_implement.md");
    // It points at the skill / CLAUDE.md routing …
    expect(p).toMatch(/\/tdd|tdd skill|Skill routing|CLAUDE\.md/i);
    // … and does NOT hand-copy the TDD method (the discipline lives in the baked
    // skill, ADR 0026). The old prompt spelled out "Write the failing test(s) …
    // (RED). Make them pass … (GREEN); refactor".
    expect(p).not.toMatch(/Make them pass with the smallest correct change \(GREEN\)/);
  });

  it("coder_fix.md routes through /tdd too (a fix is test-first work)", () => {
    expect(read("coder_fix.md")).toMatch(/\/tdd|tdd skill|Skill routing|CLAUDE\.md/i);
  });

  it("reviewer_full_review.md tells the worker to invoke /review", () => {
    expect(read("reviewer_full_review.md")).toMatch(/\/review|review skill|Skill routing|CLAUDE\.md/i);
  });

  it("reviewer_rereview.md routes through /review too", () => {
    expect(read("reviewer_rereview.md")).toMatch(/\/review|review skill|Skill routing|CLAUDE\.md/i);
  });

  it("every prompt still defines its structured output contract (tag + signal)", () => {
    // Thinning the METHOD must not drop the output contract route()/the seam
    // decode against — the worker must still emit its tag + completion signal.
    expect(read("coder_implement.md")).toMatch(/<coder>/);
    expect(read("coder_implement.md")).toMatch(/CODER_STEP_COMPLETE/);
    expect(read("reviewer_full_review.md")).toMatch(/<review>/);
    expect(read("reviewer_full_review.md")).toMatch(/REVIEWER_STEP_COMPLETE/);
  });
});

// ─── (3) the per-slice reviewer returns findings + the fix-loop routes on them ─
//
// The load-bearing [C] (PRD #330 R2): the reviewer worker (S3/S6) routes /review
// and returns a ReviewerResult{findings}; the single-slice fix-loop consumes the
// findings (selectFixNowFindings → S5 fix). A bare verdict would break it.

/** A fake backend that records dispatch + drives a one-round fix loop. */
class ReviewWorkerBackend implements Backend {
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
  async cleanResidue(): Promise<void> {}
  async resumeSession(): Promise<StepOutput> {
    throw new Error("resumeSession should not be called directly (#334)");
  }
  async fetchIssueMeta(issueNumber: number): Promise<IssueMeta> {
    return { number: issueNumber, isReadyForAgent: true, hasSubIssues: false, openBlockedBy: [] };
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
  async push(): Promise<void> {
    throw new Error("push should not be called directly (#334)");
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
      const findings: Finding[] =
        this.reviewCount === 1
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
      // The reviewer worker returns a ReviewerResult{findings} — the [C] shape.
      return { kind: "completed", output: { kind: "reviewer", findings } };
    }
    return {
      kind: "completed",
      output: { kind: "ship", branch: this.worktree.branch, status: "pushed" },
    };
  }
}

describe("#334 the reviewer worker routes /review and the fix-loop routes on its findings", () => {
  it("the S3 reviewer worker is dispatched with skill /review", async () => {
    const backend = new ReviewWorkerBackend();
    await runOrchestrator({ issueNumber: 334, backend });
    const s3 = backend.specs.find((s) => s.id === "S3");
    expect(s3?.kind).toBe("reviewer");
    expect(s3?.skill).toBe("/review");
  });

  it("S3 findings → S5 fix → S6 approve → S7 (the reviewer findings drive the loop)", async () => {
    const backend = new ReviewWorkerBackend();
    const result = await runOrchestrator({ issueNumber: 334, backend });
    expect(result.status).toBe("success");
    // The S3 reviewer returned a fix_now finding; the runner routed it to an S5
    // fix worker carrying that finding, then S6 approved and S7 shipped.
    expect(backend.dispatched).toEqual([
      "S2:coder:/tdd",
      "S3:reviewer:/review",
      "S5:coder:/tdd",
      "S6:reviewer:/review",
      "S7:ship:gstack-ship",
    ]);
    const s5Idx = backend.specs.findIndex((s) => s.id === "S5");
    expect(backend.ctxs[s5Idx].prevFindings?.[0].action).toBe("fix_now");
  });

  it("an empty reviewer findings array approves straight to ship (no fix round)", async () => {
    // A backend whose reviewer always approves: S2→S3(empty)→S7, no S5/S6.
    class CleanReviewBackend extends ReviewWorkerBackend {
      override async dispatchWorker(
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
          return { kind: "completed", output: { kind: "reviewer", findings: [] } };
        }
        return {
          kind: "completed",
          output: { kind: "ship", branch: this.worktree.branch, status: "pushed" },
        };
      }
    }
    const backend = new CleanReviewBackend();
    const result = await runOrchestrator({ issueNumber: 334, backend });
    expect(result.status).toBe("success");
    expect(backend.dispatched).toEqual([
      "S2:coder:/tdd",
      "S3:reviewer:/review",
      "S7:ship:gstack-ship",
    ]);
  });
});

describe("#336 cmr S336 r4 — the terminal single-slice S7 gate re-asserts the ship contract", () => {
  /**
   * A clean-review backend whose S7 ship worker returns a `completed {kind:"ship"}`
   * payload with a configurable, possibly off-contract, ShipResult. The terminal
   * S7 gate must re-assert the single-slice contract independently of the backend
   * (defense-in-depth, symmetric to the family terminal gate): branch === the
   * resident worktree branch, status ∈ {pushed, pr_opened}, and pr_opened carries
   * a non-empty pr URL. An off-contract success must NOT route to S8(success).
   */
  class ShipPayloadBackend extends ReviewWorkerBackend {
    shipOutput: WorkerResult;
    constructor(shipOutput: WorkerResult) {
      super();
      this.shipOutput = shipOutput;
    }
    override async dispatchWorker(
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
        return { kind: "completed", output: { kind: "reviewer", findings: [] } };
      }
      return this.shipOutput;
    }
  }

  async function run(shipOutput: WorkerResult): Promise<string> {
    const backend = new ShipPayloadBackend(shipOutput);
    const result = await runOrchestrator({ issueNumber: 334, backend });
    return result.status;
  }

  const wtBranch = "feat/orchestrator/issue-334";

  it("a ship on the WRONG branch (≠ worktree) ⇒ error, not success", async () => {
    const status = await run({
      kind: "completed",
      output: { kind: "ship", branch: "main", status: "pushed" },
    });
    expect(status).toBe("error");
  });

  it("a ship with an unknown status ⇒ error, not success", async () => {
    const status = await run({
      kind: "completed",
      output: { kind: "ship", branch: wtBranch, status: "merged" },
    });
    expect(status).toBe("error");
  });

  it("a pr_opened ship missing its pr URL ⇒ error, not success", async () => {
    const status = await run({
      kind: "completed",
      output: { kind: "ship", branch: wtBranch, status: "pr_opened" },
    });
    expect(status).toBe("error");
  });

  it("a pr_opened ship with a blank pr URL ⇒ error, not success", async () => {
    const status = await run({
      kind: "completed",
      output: { kind: "ship", branch: wtBranch, status: "pr_opened", pr: "  " },
    });
    expect(status).toBe("error");
  });

  it("a legitimate pushed ship on the worktree branch ⇒ success (the contract holds)", async () => {
    const status = await run({
      kind: "completed",
      output: { kind: "ship", branch: wtBranch, status: "pushed" },
    });
    expect(status).toBe("success");
  });

  it("a legitimate pr_opened ship with a real pr URL ⇒ success", async () => {
    const status = await run({
      kind: "completed",
      output: { kind: "ship", branch: wtBranch, status: "pr_opened", pr: "https://gh/pr/1" },
    });
    expect(status).toBe("success");
  });
});
