/**
 * #334 — the first end-to-end tracer for running slice workers through the
 * unified dispatchWorker seam (ADR 0026 / PRD #330), on the baked 2b image.
 * ADR 0030 later split per-slice review/fix convergence into separate
 * runner-visible reviewer/coder-fix worker boundaries.
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
 * Plus the load-bearing [C] (ADR 0030): the runner dispatches implementation,
 * reviewer, fix, reviewer, and ship workers through visible boundaries.
 */

import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";

// vi.mock hoisted. Literal key avoids TDZ/eval order issues with vitest transform.
// Only mock child_process (this file never calls it directly); for launcher smoke
// we create a temp stub dist/ so dynamic import succeeds without side effects.
vi.mock("node:child_process", () => ({
  execFileSync: vi.fn(() => ""),
}));

import { describe, expect, it, vi } from "vitest";
import { runOrchestrator } from "../src/runner.js";
import { skeletonReviewLoopWorkerResult } from "../src/reviewLoopOutcome.js";
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
const imageDir = join(here, "..", "image");
const soulsDir = join(here, "..", "image", "souls");

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
    return new StubBackend({
      sourceRepo: "/tmp/source",
      remote: "https://github.com/owner/name.git",
      runKey: 999,
      repo: "owner/name",
      imageName: "ming-orchestrator-coder:latest",
      promptsDir,
      soulsDir,
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

  it("skillsMount is no longer a required RealBackendOptions field (#334)", () => {
    // Construction WITHOUT skillsMount must succeed — the baked image provides
    // skills, so the host mount path is gone from the options contract.
    expect(() => makeBackend()).not.toThrow();
  });
});

// ─── (2) the versioned prompts are THIN — invoke the skill, not hand-copy it ──

describe("#334 thin prompts read souls (mounted live per #372) and do not hand-copy methodology", () => {
  const read = (f: string): string => readFileSync(join(promptsDir, f), "utf8");
  const readSoul = (f: string): string =>
    readFileSync(join(here, "..", "image", "souls", f), "utf8");

  it("coder_implement.md is an entrypoint, not a TDD/review mini-wiki", () => {
    const p = read("coder_implement.md");
    expect(p).toMatch(/\/home\/agent\/\.orchestrator\/souls\/coder\.md/);
    expect(p).toMatch(/ORCHESTRATOR_ISSUE_NUMBER|ISSUE_NUMBER/);
    expect(p).toMatch(/ORCHESTRATOR_REPO/);
    expect(p).toMatch(/gh/i);
    expect(p).not.toMatch(/\.orchestrator-snapshot\.json.*read it FIRST/is);
    expect(p).not.toMatch(/\bRED\b|\bGREEN\b|\brefactor\b|Baseline commit|\bOpus\b|\bsubagent\b|ak-cross-m-review/i);
  });

  it("fix/review prompt files stay thin and leave path/review method to the soul", () => {
    const fix = read("coder_fix.md");
    expect(fix).toMatch(/\/home\/agent\/\.orchestrator\/souls\/coder\.md/);
    expect(fix).toMatch(/fix-findings path/i);
    expect(fix).toMatch(/escalationAnswer/i);
    expect(fix).toMatch(
      /repairEvidence[\s\S]*findingScope[\s\S]*changedFiles[\s\S]*(tests|fixtures|patchSummary)/i,
    );
    expect(fix).not.toMatch(/sibling ledger|legacy compatibility fallback|Prefer the sibling ledger/is);

    const review = read("reviewer_review.md");
    expect(review).toMatch(/\/home\/agent\/\.orchestrator\/souls\/reviewer\.md/);
    expect(review).toMatch(/role soul \(live-mounted\) plus runner\s+parameters/i);
    expect(review).toMatch(/escalationAnswer/i);
    expect(review).not.toMatch(/\.orchestrator-snapshot\.json/i);
    expect(review).not.toMatch(/fetch the current issue body|Retry transient network failures|Review the current full slice diff/is);
  });

  it("the worker image bakes the Matt code-review skill for reviewer workers", () => {
    const build = readFileSync(join(imageDir, "build.sh"), "utf8");
    const start = build.indexOf("SKILL_CLOSURE=(");
    const end = build.indexOf(")", start);
    const closureBlock = build.slice(start, end);
    expect(closureBlock).toMatch(/\bcode-review\b/);
    // #372: souls (incl output_protocol.md) are mounted live, not staged/copied in build.sh.
    // The presence in source souls/ is asserted by other reads; build no longer bakes souls.
  });

  it("the coder soul carries implementation/fix process but not the per-slice review loop", () => {
    const soul = readSoul("coder.md");
    expect(soul).toMatch(/Invoke `\/tdd`/i);
    expect(soul).toMatch(/coder-fix|fix worker|blocking review findings/i);
    expect(soul).toMatch(/escalationAnswer/i);
    expect(soul).not.toMatch(/Second review|non-Claude reviewer leg/i);
    expect(soul).toMatch(/gh issue view/i);
    expect(soul).toMatch(/--json[^`]*title[^`]*author[^`]*body[^`]*comments/is);
    expect(soul).toMatch(/comment\.author\.login.*repo owner/is);
    expect(soul).toMatch(/non-owner.*Agent Brief.*ordinary\s+issue text/is);
    expect(soul).toMatch(/non-owner.*title.*body.*comments.*data-only/is);
    expect(soul).toMatch(/must not.*instructions.*scope changes.*commands/is);
    expect(soul).toMatch(/credential-handling\s+requests/i);
    expect(soul).toMatch(/Snapshot files.*not execution input/is);
  });

  it("coder entrypoints require author-aware live issue reads before trusting issue instructions", () => {
    for (const promptName of ["coder_implement.md", "coder_fix.md"]) {
      const prompt = read(promptName);
      expect(prompt).toMatch(/--json[^`]*title[^`]*author[^`]*body[^`]*comments/is);
      expect(prompt).toMatch(/repo owner/i);
      expect(prompt).toMatch(/non-owner.*Agent Brief.*ordinary\s+issue text/is);
      expect(prompt).toMatch(/non-owner.*title.*body.*comments.*data-only/is);
      expect(prompt).toMatch(/must not.*instructions.*scope changes.*commands/is);
      expect(prompt).toMatch(/credential-handling\s+requests/i);
    }
  });

  it("the reviewer soul carries snapshot-input policy outside the thin prompt", () => {
    const soul = readSoul("reviewer.md");
    expect(soul).toMatch(/Snapshot files.*not execution input/is);
    expect(soul).toMatch(/git state for the review scope/i);
    expect(soul).toMatch(/escalationAnswer/i);
  });

  it("#419 integrated cmr pass entrypoints read pass-specific souls that invoke only their lens gate", () => {
    const completenessPrompt = read("integrated_cmr_completeness.md");
    const correctnessPrompt = read("integrated_cmr_correctness.md");
    expect(completenessPrompt).toMatch(
      /\/home\/agent\/\.orchestrator\/souls\/cmr_completeness\.md/,
    );
    expect(correctnessPrompt).toMatch(
      /\/home\/agent\/\.orchestrator\/souls\/cmr_correctness\.md/,
    );

    const completenessSoul = readSoul("cmr_completeness.md");
    expect(completenessSoul).toMatch(/\bak-cmr-completeness\b/);
    expect(completenessSoul).not.toMatch(/\bak-cmr-correctness\b/);
    expect(completenessSoul).not.toMatch(/Gate 2|correctness gate|Run only the correctness/is);

    const correctnessSoul = readSoul("cmr_correctness.md");
    expect(correctnessSoul).toMatch(/\bak-cmr-correctness\b/);
    expect(correctnessSoul).not.toMatch(/\bak-cmr-completeness\b/);
    expect(correctnessSoul).not.toMatch(/Gate 1|completeness gate|Run only the completeness/is);
  });

  it("#549 integrated cmr pass souls are reviewer workers, not persistent fixers", () => {
    for (const soulName of ["cmr_completeness.md", "cmr_correctness.md"]) {
      const soul = readSoul(soulName);

      expect(soul).toMatch(/reviewer worker/i);
      expect(soul).toMatch(/findings\/outcome/i);
      expect(soul).toMatch(/return\s+control\s+to\s+the\s+runner/i);
      expect(soul).toMatch(/must not repair/i);
      expect(soul).toMatch(/must not[^.]*create a fix commit/i);
      expect(soul).not.toMatch(/coder-fix/i);
      expect(soul).not.toMatch(/Fix every gap|Fix P0\/P1|After every fix/i);
      expect(soul).not.toMatch(/Commit each coherent fix|git commit|do not push or open a PR/i);
      expect(soul).not.toMatch(/gh issue create|TODOS\.md/i);
    }
  });

  it("every existing prompt still defines its structured output contract (tag + signal)", () => {
    // Thinning the METHOD must not drop the output contract route()/the seam
    // decode against — each worker must still emit its tag + completion signal.
    // Shared sidecar hygiene lives in the baked output protocol, not repeated
    // across every prompt entrypoint.
    const prompts = [
      ["coder_implement.md", /<coder>/, /CODER_STEP_COMPLETE/],
      ["coder_fix.md", /<coder>/, /CODER_STEP_COMPLETE/],
      ["reviewer_review.md", /<review>/, /REVIEWER_STEP_COMPLETE/],
      ["ship.md", /<ship>/, /SHIP_STEP_COMPLETE/],
      ["family_ship.md", /<ship>/, /SHIP_STEP_COMPLETE/],
      ["integrated_cmr.md", /<cmr>/, /CMR_STEP_COMPLETE/],
      ["integrated_cmr_completeness.md", /<cmr>/, /CMR_STEP_COMPLETE/],
      ["integrated_cmr_correctness.md", /<cmr>/, /CMR_STEP_COMPLETE/],
      ["merger_resolve_conflict.md", /<merger>/, /MERGER_STEP_COMPLETE/],
    ] as const;

    for (const [promptName, tag, signal] of prompts) {
      const prompt = read(promptName);
      expect(prompt).toMatch(tag);
      expect(prompt).toMatch(signal);
      expect(prompt).toMatch(/\$ORCHESTRATOR_OUTCOME_PATH/);
      expect(prompt).not.toMatch(/python3 -m json\.tool "\$ORCHESTRATOR_OUTCOME_PATH"/);
    }
  });

  it("the baked shared output protocol owns sidecar parser validation", () => {
    const protocol = readSoul("output_protocol.md");
    expect(protocol).toMatch(/\$ORCHESTRATOR_OUTCOME_PATH/);
    expect(protocol).toMatch(/raw sidecar JSON/i);
    expect(protocol).toMatch(/if \[ -n "\$\{ORCHESTRATOR_OUTCOME_PATH:-\}" \]/);
    expect(protocol).toMatch(/orchestrator-outcome-guard/);
    expect(protocol).toMatch(/--draft "<draft-json-path>"/);
    expect(protocol).toMatch(/--outcome "\$ORCHESTRATOR_OUTCOME_PATH"/);
    expect(protocol).toMatch(/--completion-signal "<COMPLETION_SIGNAL>"/);
    expect(protocol).not.toMatch(/python3 -c 'import json/);
    expect(protocol).not.toMatch(/python3 -m json\.tool/);

    for (const soulName of [
      "coder.md",
      "reviewer.md",
      "cmr.md",
      "cmr_completeness.md",
      "cmr_correctness.md",
      "merger.md",
      "ship.md",
    ]) {
      expect(readSoul(soulName)).toMatch(
        /\/home\/agent\/\.orchestrator\/souls\/output_protocol\.md/,
      );
    }
  });

  // #604 slice 4 (ADR 0062): the routing disposition kinds — and their
  // parser-required fields — were removed from the type system, so no reviewer
  // or CMR prompt may still advertise them. This test used to assert those
  // route-kind fields WERE documented; it now asserts they are GONE and that the
  // new thin contract is documented instead (CMR prompts carry the
  // `accepted_suppressed` governance fields; the standalone reviewer prompt
  // mandates fix_now-only and emits no disposition).
  it("reviewer and integrated-cmr prompts no longer advertise removed routing disposition kinds", () => {
    const files = [
      read("reviewer_review.md"),
      read("integrated_cmr.md"),
      read("integrated_cmr_completeness.md"),
      read("integrated_cmr_correctness.md"),
      readSoul("reviewer.md"),
    ];

    for (const text of files) {
      // The removed routing kinds must not appear anywhere in the contract text.
      expect(text).not.toMatch(/cross_module/);
      expect(text).not.toMatch(/same_module/);
      expect(text).not.toMatch(/spec_conflict/);
      expect(text).not.toMatch(/infra_failure/);
      expect(text).not.toMatch(/owning_issue_still_red/);
      // Their parser-required routing fields go with them.
      expect(text).not.toMatch(/targetModule/);
      expect(text).not.toMatch(/missingSurface/);
    }
  });

  it("CMR completeness/correctness prompts document the accepted_suppressed governance fields", () => {
    for (const text of [
      read("integrated_cmr_completeness.md"),
      read("integrated_cmr_correctness.md"),
    ]) {
      expect(text).toMatch(
        /accepted_suppressed[\s\S]*source[\s\S]*scope[\s\S]*reason[\s\S]*boundedReopen/i,
      );
    }
  });

  it("standalone reviewer prompt mandates fix_now-only findings with no routing disposition", () => {
    const reviewer = read("reviewer_review.md");
    // Everything is blocking / fix_now; there is no pass to another module.
    expect(reviewer).toMatch(/fix_now/);
    expect(reviewer).toMatch(/no pass to another module/i);
    // And it explicitly does not emit an accepted_suppressed disposition either.
    expect(reviewer).toMatch(/do not emit `accepted_suppressed`/i);
  });

  it("standalone reviewer prompt and soul do not advertise accepted_suppressed as supported output", () => {
    for (const text of [read("reviewer_review.md"), readSoul("reviewer.md")]) {
      expect(text).toMatch(/do not emit `accepted_suppressed`/i);
      expect(text).not.toMatch(
        /accepted_suppressed[\s\S]*source[\s\S]*scope[\s\S]*reason[\s\S]*boundedReopen[\s\S]*(findingIdentity|finding identity)[\s\S]*optional/i,
      );
      expect(text).not.toMatch(
        /priorFindingDispositions[\s\S]*accepted_suppressed[\s\S]*source[\s\S]*scope[\s\S]*reason[\s\S]*boundedReopen/i,
      );
    }
  });

  it("integrated-cmr prompts include accepted_suppressed terminal closure metadata", () => {
    for (const text of [
      read("integrated_cmr.md"),
      read("integrated_cmr_completeness.md"),
      read("integrated_cmr_correctness.md"),
    ]) {
      expect(text).toMatch(
        /accepted_suppressed[\s\S]*source[\s\S]*scope[\s\S]*reason[\s\S]*boundedReopen[\s\S]*(findingIdentity|finding identity)[\s\S]*optional/i,
      );
      expect(text).toMatch(
        /priorFindingDispositions[\s\S]*accepted_suppressed[\s\S]*source[\s\S]*scope[\s\S]*reason[\s\S]*boundedReopen/i,
      );
    }
  });
});

// ─── (3) the runner dispatches S2/S3, then S5/S6 while blockers remain ──────

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
  async pollOnlineReviewState(input: {
    repo: string;
    prUrl: string;
    pollCount: number;
  }) {
    void input;
    return {
      prUrl: "https://github.com/o/r/pull/334",
      headOid: "deadbeef",
      totalFindingCount: 0,
      quiescent: true,
      threads: [],
    };
  }

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
      return {
        kind: "completed",
        output: {
          kind: "reviewer",
          findings,
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
    const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
    if (skeleton !== undefined) {
      return skeleton;
    }
    return {
      kind: "completed",
      output: { kind: "ship", branch: this.worktree.branch, status: "pushed" },
    };
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

  it("blocking review dispatches S5 fix, then S6 fresh review before S7 ship", async () => {
    const backend = new ReviewWorkerBackend();
    const result = await runOrchestrator({ issueNumber: 334, backend });
    expect(result.status).toBe("success");
    expect(backend.dispatched).toEqual([
      "S2:coder:/tdd",
      "S3:reviewer:/code-review",
      "S5:coder:/tdd",
      "S6:reviewer:/code-review",
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
      const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
      if (skeleton !== undefined) {
        return skeleton;
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

// ─── launcher bootstrap smoke (item 3) ─────────────────────────────────────

describe("launch-362.mjs bootstrap smoke (#372 unconditional)", () => {
  it("mocks execFileSync and asserts tsc + build.sh (plus clean) are invoked (tsc before driver import)", async () => {
    const cp = await import("node:child_process");
    const execMock = cp.execFileSync as unknown as ReturnType<typeof vi.fn>;
    execMock.mockClear();

    // Pre-create a minimal stub dist/familyDriver.js so launcher's dynamic import
    // (after its tsc) succeeds and we don't run real driver. Launcher 'rm dist'
    // is also mocked so our stub persists for the import.
    const distDir = join(here, "..", "dist");
    const driverJs = join(distDir, "familyDriver.js");
    mkdirSync(distDir, { recursive: true });
    writeFileSync(
      driverJs,
      'export const runFamilyDriver = async () => ({});\nexport const resolveImageTag = (t) => t || "tag";\n',
      "utf8",
    );

    try {
      // Trigger launcher top level: uses mocked execs (rm/tsc/build) + real dynamic import of our stub.
      const launcherPath = join(here, "..", "launch-362.mjs");
      await import(launcherPath);

      const calls = execMock.mock.calls as any[][];
      // dist clean
      expect(
        calls.some(
          (c) =>
            c[0] === "rm" &&
            Array.isArray(c[1]) &&
            c[1].some((a: string) => String(a).includes("dist")),
        ),
      ).toBe(true);
      // tsc
      expect(calls.some((c) => c[0] === "npx" && c[1]?.[0] === "tsc")).toBe(true);
      // build.sh
      expect(
        calls.some((c) => c[0] === "bash" && String(c[1]?.[0] || "").includes("build.sh")),
      ).toBe(true);
    } finally {
      try {
        rmSync(driverJs, { force: true });
        rmSync(distDir, { recursive: true, force: true });
      } catch {}
    }
  });
});
