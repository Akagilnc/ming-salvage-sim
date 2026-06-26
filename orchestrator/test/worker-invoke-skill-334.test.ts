/**
 * #334 — the first end-to-end tracer: the coder worker runs the whole slice
 * (build + per-slice review/fix loop) through the unified dispatchWorker seam
 * (ADR 0026 / PRD #330), running on the baked 2b image.
 *
 * This slice makes the seam REAL in two ways the #331 prefactor only declared:
 *
 *   1. RealBackend's sandbox stops bind-mounting host skills at runtime
 *      (`skillsMount`) — the baked image's skills win (cross-slice note from
 *      #332/#333: the runtime mount SHADOWS the baked skills). The behaviour
 *      change is assertable on the pure `boxConfig()` seam (no container needed),
 *      mirroring the family `mergerSandboxConfig()` testability pattern.
 *
 *   2. The versioned promptFiles are THIN entrypoints: they read the baked soul,
 *      live-fetch the issue through gh, and define the output contract. They do
 *      NOT hand-copy the TDD/review/fix METHOD into the prompt. The workflow lives
 *      in the baked soul + skills.
 *
 * Plus the load-bearing [C] (PRD #330 R2): the runner dispatches exactly the S2
 * coder worker and then S7 ship; there is no runner-driven reviewer/fix loop.
 */

import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { runOrchestrator } from "../src/runner.js";
import {
  RealBackend,
  SANDBOX_CODEX_DIR,
  SANDBOX_GH_TOKEN_ENV,
  SANDBOX_ISSUE_NUMBER_ALIAS_ENV,
  SANDBOX_ISSUE_NUMBER_ENV,
  SANDBOX_REPO_ENV,
  SANDBOX_SKILLS_DIR,
  SANDBOX_SOUL_ENV,
  SPAWNED_WORKER_ENV,
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
        { authDir: "/tmp/auth-256", claudeToken: "tok", ghToken: "gho_test" },
        spec,
        334,
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

  it("injects live issue coordinates and GH_TOKEN for the worker's gh issue read", () => {
    const cfg = makeBackend().config(coderSpec);
    expect(cfg.env[SANDBOX_ISSUE_NUMBER_ENV]).toBe("334");
    expect(cfg.env[SANDBOX_ISSUE_NUMBER_ALIAS_ENV]).toBe("334");
    expect(cfg.env[SANDBOX_REPO_ENV]).toBe("owner/name");
    expect(cfg.env[SANDBOX_GH_TOKEN_ENV]).toBe("gho_test");
  });

  it("marks the coder/agent container as an orchestrator-spawned, non-interactive session", () => {
    const cfg = makeBackend().config(coderSpec);
    expect(cfg.env.OPENCLAW_SESSION).toBe("1");
    expect(cfg.env.OPENCLAW_SESSION).toBe(SPAWNED_WORKER_ENV.OPENCLAW_SESSION);
  });

  it("skillsMount is no longer a required RealBackendOptions field (#334)", () => {
    // Construction WITHOUT skillsMount must succeed — the baked image provides
    // skills, so the host mount path is gone from the options contract.
    expect(() => makeBackend()).not.toThrow();
  });
});

// ─── (2) the versioned prompts are THIN — invoke the skill, not hand-copy it ──

describe("#334 thin prompts read baked souls and do not hand-copy methodology", () => {
  const read = (f: string): string => readFileSync(join(promptsDir, f), "utf8");

  it("coder_implement.md is an entrypoint, not a TDD/review mini-wiki", () => {
    const p = read("coder_implement.md");
    expect(p).toMatch(/\/home\/agent\/\.orchestrator\/souls\/coder\.md/);
    expect(p).toMatch(/ORCHESTRATOR_ISSUE_NUMBER|ISSUE_NUMBER/);
    expect(p).toMatch(/ORCHESTRATOR_REPO/);
    expect(p).toMatch(/gh/i);
    expect(p).not.toMatch(/\.orchestrator-snapshot\.json.*read it FIRST/is);
    expect(p).not.toMatch(/\bRED\b|\bGREEN\b|\brefactor\b|Baseline commit|\bOpus\b|\bsubagent\b|ak-cross-m-review/i);
  });

  it("the coder soul carries the per-slice process, including host-specific review routing", () => {
    const soul = readFileSync(join(here, "..", "image", "souls", "coder.md"), "utf8");
    expect(soul).toMatch(/Invoke `\/tdd`/i);
    expect(soul).toMatch(/Claude worker: invoke the builtin `\/review`/);
    expect(soul).toMatch(/Codex worker: use the baked review skill/i);
    expect(soul).toMatch(/one reviewer leg|single reviewer leg/i);
    expect(soul).toMatch(/do not invoke `ak-cross-m-review`/i);
    expect(soul).toMatch(/gh issue view/i);
    expect(soul).toMatch(/Snapshot files.*not execution input/is);
  });

  it("every existing prompt still defines its structured output contract (tag + signal)", () => {
    // Thinning the METHOD must not drop the output contract route()/the seam
    // decode against — each worker must still emit its tag + completion signal.
    // Only the surviving prompts exist (ADR 0026 deleted the reviewer/fix files):
    // the build coder (coder_implement.md) and the ship worker (ship.md).
    expect(read("coder_implement.md")).toMatch(/<coder>/);
    expect(read("coder_implement.md")).toMatch(/CODER_STEP_COMPLETE/);
    expect(read("ship.md")).toMatch(/<ship>/);
    expect(read("ship.md")).toMatch(/SHIP_STEP_COMPLETE/);
  });
});

// ─── (3) the runner dispatches one S2 coder worker, then S7 ship ─────────────

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
      // Legacy compatibility shape: a reviewer worker returns findings, not a
      // bare verdict. The active runner path no longer dispatches it normally.
      return { kind: "completed", output: { kind: "reviewer", findings } };
    }
    return {
      kind: "completed",
      output: { kind: "ship", branch: this.worktree.branch, status: "pushed" },
    };
  }
}

describe("#334 the build coder worker routes /tdd and a committed build ships (ADR 0026)", () => {
  it("the S2 build coder worker is dispatched with skill /tdd", async () => {
    const backend = new ReviewWorkerBackend();
    await runOrchestrator({ issueNumber: 334, backend });
    const s2 = backend.specs.find((s) => s.id === "S2");
    expect(s2?.kind).toBe("coder");
    expect(s2?.skill).toBe("/tdd");
  });

  it("a committed whole-slice build → S7 ship (no runner-driven reviewer/fix steps)", async () => {
    // ADR 0026: the per-slice review→fix→cmr loop runs INSIDE the S2 worker, so
    // the runner sees exactly ONE coder dispatch then the ship worker — never an
    // S3/S5/S6 reviewer/fix step.
    const backend = new ReviewWorkerBackend();
    const result = await runOrchestrator({ issueNumber: 334, backend });
    expect(result.status).toBe("success");
    expect(backend.dispatched).toEqual([
      "S2:coder:/tdd",
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
