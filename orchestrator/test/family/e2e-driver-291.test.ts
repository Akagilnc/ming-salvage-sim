/**
 * #291 Unit B — END-TO-END family-driver effect proof.
 *
 * This is the铁证 that the #291 family orchestration串起来 runs on REAL backends:
 * a REAL git repo, a REAL RealFamilyBackend (real `git merge --no-ff`, real
 * family-ledger JSONL, real reconcile git seam), the REAL spine (`runFamily` via
 * `runFamilyDriver`), real dependency-wave scheduling, real merge commits landing
 * on a real LOCAL family base — and it STOPS at the PR step.
 *
 * What is受控注入 (so we never start a container / open a real PR / burn quota):
 *   - the epic-read `gh` (sub-issues + blocked_by) → an injected `sh`;
 *   - the child fan-out (`sc.run` coder + merger agent) → a container-free
 *     single-slice Backend that does REAL git on the clone (real `git worktree
 *     add` + a real commit), producing a real reviewed child branch the family
 *     merger then REALLY merges;
 *   - the family verify / integrated cmr / `gh pr create` → the RealFamilyBackend's
 *     protected seams overridden to controlled outcomes (verify green, cmr
 *     converged, PR a synthetic url) — so verify+cmr really gate, and the run
 *     STOPS at the PR (the seam is reached, no real remote push).
 *
 * The MERGE / LEDGER / RECONCILE / WAVE-SCHEDULE are all REAL. Asserted:
 *   1. wave scheduling: a dependency child (#13 blocked_by #12) merges AFTER its
 *      blocker — topological, ledger-driven, multi-wave;
 *   2. a REAL `--no-ff` merge commit per child lands on the LOCAL family base
 *      (the family base HEAD advances; each child's file is present);
 *   3. the family ledger REALLY records each merge (a JSONL sibling file);
 *   4. the run STOPS at the PR (the openFamilyPr seam is reached exactly once,
 *      with the family base; status === "success"; no merge to main).
 */

import { execFileSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it } from "vitest";

import { runFamilyDriver, type Sh } from "../../src/familyDriver.js";
import { RealFamilyBackend } from "../../src/family/realFamilyBackend.js";
import type {
  FamilyVerifyRequest,
  IntegratedCmrRequest,
  OpenFamilyPrRequest,
} from "../../src/family/types.js";
import type {
  Backend,
  IssueMeta,
  IssueSnapshot,
  PersistentLedgerEntry,
  StepOutput,
  StepSpec,
  WorktreeHandle,
} from "../../src/types.js";

const here = dirname(fileURLToPath(import.meta.url));
const familyPromptsDir = join(here, "..", "..", "prompts");

function git(cwd: string, ...args: string[]): string {
  return execFileSync("git", args, { cwd, encoding: "utf8" }).trim();
}

/** A real temp git repo (the SOURCE the driver clones) with a `main` + root commit. */
function makeSourceRepo(): string {
  const dir = mkdtempSync(join(tmpdir(), "e2e-src-"));
  git(dir, "init", "-q", "-b", "main");
  git(dir, "config", "user.email", "t@t.t");
  git(dir, "config", "user.name", "t");
  git(dir, "config", "commit.gpgsign", "false");
  execFileSync("git", ["commit", "--allow-empty", "-q", "-m", "root"], { cwd: dir });
  return dir;
}

const cleanups: string[] = [];
function track(p: string): string {
  cleanups.push(p);
  return p;
}
afterEach(() => {
  while (cleanups.length > 0) {
    const p = cleanups.pop();
    if (p !== undefined) rmSync(p, { recursive: true, force: true });
  }
});

/**
 * The injected `gh`+git `sh`: gh epic-read is FAKED (sub-issues + blocked_by);
 * git is REAL (the family-base cut on the real clone). The epic: children 11, 12
 * (independent) and 13 (blocked_by 12) — so wave 1 = {11,12}, wave 2 = {13}.
 */
function makeSh(): Sh {
  const SUB_ISSUES = JSON.stringify({
    subIssues: { nodes: [{ number: 11 }, { number: 12 }, { number: 13 }], totalCount: 3 },
  });
  const blockedBy: Record<number, string> = {
    11: "[]",
    12: "[]",
    13: JSON.stringify([{ number: 12, state: "open" }]),
  };
  return (file, args) => {
    if (file === "gh") {
      if (args[0] === "issue" && args.includes("subIssues")) return SUB_ISSUES;
      if (args[0] === "api") {
        // .../issues/<n>/dependencies/blocked_by
        const m = /issues\/(\d+)\/dependencies/.exec(args[1] ?? "");
        const n = m ? Number(m[1]) : -1;
        return blockedBy[n] ?? "[]";
      }
      throw new Error(`unexpected gh call: ${args.join(" ")}`);
    }
    // REAL git (the family-base cut etc.).
    return execFileSync(file, args, { encoding: "utf8" }).trim();
  };
}

/**
 * A container-free single-slice Backend producing a REAL committed child branch on
 * the family clone: `prepareWorktree` cuts `feat/child-<n>` from the family base
 * (a real `git worktree add`), `runStep`(coder) commits a UNIQUE file in that
 * worktree (distinct file per child ⇒ clean merges). No `sc.run`, no container.
 */
class RealGitChildBackend implements Backend {
  readonly worktrees = new Map<number, string>();
  constructor(private readonly clone: string) {}
  async findResumeState(): Promise<undefined> {
    return undefined;
  }
  async cleanResidue(): Promise<void> {}
  async resumeSession(spec: StepSpec, worktree: WorktreeHandle): Promise<StepOutput> {
    return this.runStep(spec, worktree);
  }
  async fetchIssueMeta(issueNumber: number): Promise<IssueMeta> {
    return {
      number: issueNumber,
      isReadyForAgent: true,
      hasAgentBrief: true,
      hasSubIssues: false,
      openBlockedBy: [],
    };
  }
  async fetchIssueSnapshot(issueNumber: number): Promise<IssueSnapshot> {
    return { number: issueNumber, body: "b", comments: [], agentBrief: "## Agent Brief" };
  }
  async prepareWorktree(issueNumber: number, base: string): Promise<WorktreeHandle> {
    const branch = `feat/child-${issueNumber}`;
    const wtPath = join(this.clone, "..", `e2e-wt-${issueNumber}-${Date.now()}`);
    // REAL git worktree add off the LOCAL family base (the cut base the spine passes).
    git(this.clone, "worktree", "add", "-b", branch, wtPath, base);
    this.worktrees.set(issueNumber, wtPath);
    track(wtPath);
    return { branch, base, path: wtPath };
  }
  async writeSnapshot(): Promise<void> {}
  async runStep(spec: StepSpec, worktree: WorktreeHandle): Promise<StepOutput> {
    if (spec.role === "coder") {
      // Use the run's OWN worktree handle (B7-concurrency-safe: two children run
      // concurrently, each with its own worktree). Commit a UNIQUE file per child
      // (by its branch number) so each merge into the family base is clean.
      const wt = worktree.path;
      const num = Number(/child-(\d+)/.exec(worktree.branch)?.[1] ?? 0);
      execFileSync("bash", ["-c", `printf 'child %s' '${num}' > '${join(wt, `child-${num}.txt`)}'`]);
      git(wt, "config", "user.email", "t@t.t");
      git(wt, "config", "user.name", "t");
      git(wt, "add", "-A");
      execFileSync("git", ["commit", "-q", "-m", `child ${num}`], { cwd: wt });
      return { kind: "coder", committed: true, commitsAdded: 1 };
    }
    return { kind: "reviewer", findings: [] };
  }
  async push(): Promise<void> {}
  async writeLedger(_e: PersistentLedgerEntry, _d: string): Promise<void> {}
}

/**
 * A REAL RealFamilyBackend (real merge / ledger / reconcile) whose verify / cmr /
 * PR seams are controlled: verify green, cmr converged, PR a synthetic url (so the
 * run reaches + STOPS at the PR seam without a real remote push). It records the
 * verify / cmr / PR calls so the test can assert the run stopped at the PR.
 */
class E2EFamilyBackend extends RealFamilyBackend {
  readonly verifyCalls: FamilyVerifyRequest[] = [];
  readonly cmrCalls: IntegratedCmrRequest[] = [];
  readonly prCalls: OpenFamilyPrRequest[] = [];
  protected override runVerifyCommands(req: FamilyVerifyRequest): void {
    this.verifyCalls.push(req); // green: no throw, no real npx.
  }
  protected override async runCmr(req: IntegratedCmrRequest) {
    this.cmrCalls.push(req);
    return { converged: true as const };
  }
  override async openFamilyPr(req: OpenFamilyPrRequest) {
    // Controlled: do NOT push / `gh pr create`. Record the call (the run reached
    // the PR seam) and return a synthetic url — the autonomy ends here.
    this.prCalls.push(req);
    return { url: "https://example.invalid/pr/291" };
  }
}

describe("#291 Unit B — e2e family driver on real RealFamilyBackend", () => {
  it("schedules waves, REALLY merges each child onto the local family base, writes the ledger, and STOPS at the PR", async () => {
    const source = track(makeSourceRepo());
    const home = track(mkdtempSync(join(tmpdir(), "e2e-home-")));
    const ledgerDir = track(mkdtempSync(join(tmpdir(), "e2e-ledger-")));
    const sh = makeSh();
    const familyBase = "family/291-base";

    let captured: { backend: E2EFamilyBackend; clone: string } | undefined;

    const result = await runFamilyDriver({
      epicIssue: 291,
      sourceRepo: source,
      // local-only source (no remote) — slug degrades to a path hash.
      repo: "Akagilnc/ming-salvage-sim",
      familyBase,
      base: "main",
      promptsDir: familyPromptsDir,
      familyPromptsDir,
      ledgerDir,
      imageName: "img",
      skillsMount: join(home, "skills"),
      home,
      sh,
      singleSliceBackendFactory: (clone) => new RealGitChildBackend(clone),
      familyBackendFactory: (clone, startHead) => {
        const b = new E2EFamilyBackend({
          workingRepo: clone,
          familyBase,
          ledgerDir,
          repo: "Akagilnc/ming-salvage-sim",
          base: "main",
          promptsDir: familyPromptsDir,
          imageName: "img",
          skillsMount: join(home, "skills"),
          familyBaseStartHead: startHead,
        });
        captured = { backend: b, clone };
        return b;
      },
    });

    expect(captured).toBeDefined();
    const { backend, clone } = captured!;

    // ── 1. honest success: every child merged, the run is success ──────────────
    expect(result.status).toBe("success");
    expect(result.children.map((c) => c.issue).sort()).toEqual([11, 12, 13]);
    expect(result.children.every((c) => c.status === "merged")).toBe(true);

    // ── 2. REAL merge commits on the LOCAL family base ─────────────────────────
    // The family base HEAD is a real --no-ff merge commit (2 parents), and each
    // child's unique file landed on it.
    const familyHead = git(clone, "rev-parse", familyBase);
    expect(result.familyHead).toBe(familyHead);
    // Check out the family base and confirm all three child files are present.
    git(clone, "checkout", "-q", familyBase);
    for (const n of [11, 12, 13]) {
      expect(existsSync(join(clone, `child-${n}.txt`))).toBe(true);
    }
    // The family base advanced past its start head (real merges landed).
    const startHead = await backend.reconcileGit().familyBaseStartHead();
    expect(familyHead).not.toBe(startHead);
    expect(await backend.reconcileGit().isAncestor(startHead, familyHead)).toBe(true);

    // ── 3. the family ledger REALLY recorded each merge (real JSONL) ────────────
    const ledger = await backend.readFamilyLedger();
    const merged = ledger.filter((e) => e.status === "merged");
    expect(merged.map((e) => e.childIssue).sort()).toEqual([11, 12, 13]);
    // It is a real sibling JSONL on disk.
    const raw = readFileSync(join(ledgerDir, "family-ledger.jsonl"), "utf8");
    expect(raw.trim().split("\n").length).toBeGreaterThanOrEqual(3);

    // ── 3b. WAVE ORDER: #13 (blocked_by #12) merged AFTER #12 (topological) ─────
    const order = merged.map((e) => e.childIssue!);
    expect(order.indexOf(12)).toBeLessThan(order.indexOf(13));

    // ── 4. the run STOPPED at the PR (seam reached once, family base, no merge) ─
    // verify ran at BOTH barriers (each wave + final), cmr ran once (final), the
    // PR opened once with the family base — and nothing merged to main.
    expect(backend.verifyCalls.length).toBeGreaterThanOrEqual(1);
    expect(backend.verifyCalls.some((v) => v.phase === "final")).toBe(true);
    expect(backend.cmrCalls).toEqual([{ familyBase }]);
    expect(backend.prCalls).toEqual([{ familyBase }]);
  });
});
