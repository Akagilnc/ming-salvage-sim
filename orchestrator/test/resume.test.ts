/**
 * #255 — Idempotent resume tests (RED → GREEN).
 *
 * Crash-resume and escalate-resume share ONE machine: when the same issue is
 * re-fed and a resident slice branch/worktree already exists (crash residue or
 * escalate residue), the runner reuses the existing HEAD and continues from the
 * step recorded in the ledger — it does NOT re-cut from S0, does NOT re-run
 * already-completed steps, and does NOT re-burn the LLM on prior steps.
 *
 * Acceptance criteria (issue #255):
 *   AC1 — fake Backend reports "branch/worktree already exists" → assert reuse
 *         of existing HEAD (no re-cut); before reuse, the residue-clean action
 *         (reset --hard / clean -fd / worktree prune) is invoked while committed
 *         progress is preserved.
 *   AC2 — backend call dies mid-run → "re-feed same issue" → assert crash-resume
 *         path: read ledger, continue from the recorded next step, lose no
 *         committed progress, do not re-burn the LLM from scratch.
 *   AC3 — escalate blocker, human gives an answer, re-feed → assert it goes
 *         through Sandcastle-native `resumeSession` (carrying the ledger's
 *         sessionId) to resume the real agent session — SAME machine as
 *         crash-resume, continuing from the breakpoint, not re-running from S0.
 *   AC4 — assert recovery reads the ledger (incl. sessionId) + branch HEAD to
 *         decide the next step, NOT any in-memory / LLM state.
 *
 * Strategy: extend the Backend fake with
 *   - findResumeState(issueNumber) → ResumeState | undefined  (the host-side
 *     check that detects an existing resident worktree + persisted ledger)
 *   - cleanResidue(worktree)                                  (reset/clean/prune)
 *   - resumeSession(spec, worktree, sessionId)                (Sandcastle-native)
 * A fresh run returns undefined from findResumeState (no residue) → behaves
 * exactly like before. A resume run pre-loads a ResumeState whose ledger stops
 * at step k, then asserts the runner reuses, cleans, and continues from k+1.
 */

import { describe, expect, it } from "vitest";
import { runOrchestrator } from "../src/runner.js";
import type {
  Backend,
  IssueMeta,
  IssueSnapshot,
  PersistentLedgerEntry,
  ResumeState,
  StepId,
  StepOutput,
  StepSpec,
  WorktreeHandle,
} from "../src/types.js";

// ─── shared fixtures ──────────────────────────────────────────────────────────

const WORKTREE: WorktreeHandle = {
  branch: "feat/orchestrator/issue-255",
  base: "main",
  path: "/resident/worktrees/issue-255",
};

const STATE_DIR = "/resident/worktrees/.ledger-255";

/** Build a persisted ledger entry (the resume truth on disk). */
function entry(
  step: StepId,
  output?: StepOutput,
  sessionId = "session-prior",
): PersistentLedgerEntry {
  return {
    step,
    sessionId,
    prompt_hash: `hash-${step}`,
    branchHEAD: "deadbeefcommitsha",
    ts: "2026-06-21T00:00:00.000Z",
    ...(output !== undefined ? { output } : {}),
  };
}

/** Build a terminal S8 entry tagged with its handoff status (#255). */
function s8(handoffStatus: "success" | "escalate" | "error"): PersistentLedgerEntry {
  return {
    step: "S8",
    sessionId: "session-prior",
    prompt_hash: "hash-S8",
    branchHEAD: "deadbeefcommitsha",
    ts: "2026-06-21T00:00:00.000Z",
    handoffStatus,
  };
}

/**
 * A configurable resume-aware fake Backend.
 *
 * - If `resumeState` is provided, findResumeState returns it (the issue has
 *   residue: existing worktree + persisted ledger). Otherwise it returns
 *   undefined (fresh run).
 * - Records cleanResidue / prepareWorktree / resumeSession / runStep calls so
 *   the tests can assert reuse-vs-recut and resume-vs-fresh-session.
 */
class ResumeBackend implements Backend {
  readonly calls: string[] = [];
  readonly runStepIds: string[] = [];
  /** Each resumeSession call: [stepId, sessionId]. */
  readonly resumeSessionCalls: Array<[string, string]> = [];
  prepareWorktreeCount = 0;
  cleanResidueCount = 0;
  pushCount = 0;

  constructor(private readonly resumeState?: ResumeState) {}

  async findResumeState(
    issueNumber: number,
  ): Promise<ResumeState | undefined> {
    this.calls.push(`findResumeState(${issueNumber})`);
    return this.resumeState;
  }

  async cleanResidue(_worktree: WorktreeHandle): Promise<void> {
    this.calls.push("cleanResidue");
    this.cleanResidueCount += 1;
  }

  async resumeSession(
    spec: StepSpec,
    _worktree: WorktreeHandle,
    sessionId: string,
  ): Promise<StepOutput> {
    this.calls.push(`resumeSession(${spec.id}, ${sessionId})`);
    this.resumeSessionCalls.push([spec.id, sessionId]);
    this.runStepIds.push(spec.id);
    if (spec.role === "coder") {
      return { kind: "coder", committed: true, commitsAdded: 1 };
    }
    return { kind: "reviewer", findings: [] };
  }

  async fetchIssueMeta(issueNumber: number): Promise<IssueMeta> {
    this.calls.push(`fetchIssueMeta(${issueNumber})`);
    return {
      number: issueNumber,
      isReadyForAgent: true,
      hasAgentBrief: true,
      hasSubIssues: false,
      openBlockedBy: [],
    };
  }

  async fetchIssueSnapshot(issueNumber: number): Promise<IssueSnapshot> {
    this.calls.push(`fetchIssueSnapshot(${issueNumber})`);
    return {
      number: issueNumber,
      body: "issue body",
      comments: [],
      agentBrief: "## Agent Brief\nimplement the thing",
    };
  }

  async prepareWorktree(
    issueNumber: number,
    base: string,
  ): Promise<WorktreeHandle> {
    this.calls.push(`prepareWorktree(${issueNumber}, ${base})`);
    this.prepareWorktreeCount += 1;
    return WORKTREE;
  }

  async writeSnapshot(
    worktree: WorktreeHandle,
    snapshot: IssueSnapshot,
  ): Promise<void> {
    this.calls.push(`writeSnapshot(${worktree.branch}, #${snapshot.number})`);
  }

  async runStep(spec: StepSpec): Promise<StepOutput> {
    this.calls.push(`runStep(${spec.id})`);
    this.runStepIds.push(spec.id);
    if (spec.role === "coder") {
      return { kind: "coder", committed: true, commitsAdded: 1 };
    }
    return { kind: "reviewer", findings: [] };
  }

  async push(worktree: WorktreeHandle): Promise<void> {
    this.calls.push(`push(${worktree.branch})`);
    this.pushCount += 1;
  }

  async writeLedger(
    _entry: PersistentLedgerEntry,
    _stateDir: string,
  ): Promise<void> {
    // no-op
  }
}

// ─── AC: fresh run is unaffected (no residue) ────────────────────────────────

describe("fresh run (no residue) is unchanged (#255)", () => {
  it("findResumeState returns undefined → runs full S0→S8, cuts a fresh worktree", async () => {
    const backend = new ResumeBackend(); // no resumeState

    const result = await runOrchestrator({ issueNumber: 255, backend });

    expect(result.status).toBe("success");
    // Full happy path executed (gate + load + agent steps).
    expect(result.stepLedger.map((e) => e.step)).toEqual([
      "S0", "S1", "S2", "S3", "S4", "S7", "S8",
    ]);
    // Fresh cut: prepareWorktree called once; cleanResidue never called.
    expect(backend.prepareWorktreeCount).toBe(1);
    expect(backend.cleanResidueCount).toBe(0);
    // No resumeSession on a fresh run.
    expect(backend.resumeSessionCalls).toHaveLength(0);
  });

  it("findResumeState is consulted at the very start of the run", async () => {
    const backend = new ResumeBackend();

    await runOrchestrator({ issueNumber: 255, backend });

    // The resume check is the first Backend interaction (before the S0 gate).
    expect(backend.calls[0]).toBe("findResumeState(255)");
  });
});

// ─── AC1 + AC2: crash-resume — branch/worktree exists, ledger stops at S2 ─────

describe("crash-resume: residue exists, ledger stops mid-run (#255 AC1/AC2)", () => {
  /**
   * Crash scenario: the prior run completed S0, S1, S2 (coder committed) and
   * then died before S3. The ledger on disk therefore ends at S2 with the
   * coder output. Re-feeding the same issue must reuse the worktree, clean the
   * uncommitted residue, and continue from S3 (the route() successor of S2).
   */
  function crashedAtS2(): ResumeState {
    return {
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        entry("S0"),
        entry("S1"),
        entry("S2", { kind: "coder", committed: true, commitsAdded: 1 }),
      ],
    };
  }

  it("AC1: reuses the existing worktree (no re-cut) and cleans residue first", async () => {
    const backend = new ResumeBackend(crashedAtS2());

    await runOrchestrator({ issueNumber: 255, backend });

    // No fresh cut — the resident worktree is reused.
    expect(backend.prepareWorktreeCount).toBe(0);
    // Residue clean (reset --hard / clean -fd / prune) ran before reuse.
    expect(backend.cleanResidueCount).toBe(1);
    // cleanResidue must come before any agent step dispatch.
    const cleanIdx = backend.calls.indexOf("cleanResidue");
    const firstRun = backend.calls.findIndex(
      (c) => c.startsWith("runStep(") || c.startsWith("resumeSession("),
    );
    expect(cleanIdx).toBeGreaterThanOrEqual(0);
    expect(cleanIdx).toBeLessThan(firstRun);
  });

  it("AC2: continues from S3 (route successor of S2) — does NOT re-run S0/S1/S2", async () => {
    const backend = new ResumeBackend(crashedAtS2());

    const result = await runOrchestrator({ issueNumber: 255, backend });

    // The run resumes: S2 is never re-dispatched; S3 is the first agent step.
    expect(backend.runStepIds).toEqual(["S3"]);
    // S0/S1 are not re-executed either (no re-gate, no re-cut, no re-snapshot).
    expect(backend.calls).not.toContain("fetchIssueMeta(255)");
    expect(backend.calls).not.toContain("prepareWorktree(255, main)");

    // The run completes from the resumed point.
    expect(result.status).toBe("success");
    expect(result.branch).toBe(WORKTREE.branch);
  });

  it("AC2: committed progress (prior ledger) is preserved in the result ledger", async () => {
    const backend = new ResumeBackend(crashedAtS2());

    const result = await runOrchestrator({ issueNumber: 255, backend });

    // The prior committed steps survive into the final ledger (not lost), and
    // the new steps are appended after them.
    const steps = result.stepLedger.map((e) => e.step);
    // Prior S0/S1/S2 + resumed S3/S4/S7/S8.
    expect(steps).toEqual(["S0", "S1", "S2", "S3", "S4", "S7", "S8"]);
    // The preserved S2 entry still carries its committed output.
    const s2 = result.stepLedger.find((e) => e.step === "S2");
    expect(s2?.output).toEqual({ kind: "coder", committed: true, commitsAdded: 1 });
  });
});

// ─── AC3 + AC4: escalate-resume — SAME machine, via resumeSession + sessionId ─

describe("escalate-resume: human answered, re-feed → resumeSession (#255 AC3/AC4)", () => {
  /**
   * Escalate scenario: the prior run escalated at S2 (coder hit a design-level
   * blocker). The ledger therefore ends with an S2 escalate entry and an S8
   * handoff(escalate). The human answers the blocker, then re-feeds the issue.
   *
   * The SAME machine resumes: read the ledger, reuse the worktree, and resume
   * the prior agent session via Sandcastle-native resumeSession (carrying the
   * recorded sessionId) — NOT a fresh sandbox.run from S0.
   *
   * After escalate, the resumed step is the escalated step itself (S2): the
   * human's answer lets the coder finish what it was stuck on, in the SAME
   * agent session (resumeSession, not a fresh run).
   */
  function escalatedAtS2(): ResumeState {
    return {
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        entry("S0"),
        entry("S1"),
        entry(
          "S2",
          {
            kind: "coder",
            committed: false,
            commitsAdded: 0,
            escalate: {
              reason: "design ambiguity",
              diagnosis: "needs product decision on field X",
            },
          },
          "session-escalated-S2",
        ),
        entry("S8"),
      ],
    };
  }

  it("AC3: resumes the escalated step via resumeSession (Sandcastle-native), not a fresh run", async () => {
    const backend = new ResumeBackend(escalatedAtS2());

    const result = await runOrchestrator({ issueNumber: 255, backend });

    // The escalated step resumes through resumeSession — NOT a fresh runStep.
    expect(backend.resumeSessionCalls.length).toBeGreaterThan(0);
    // The very first dispatched step on resume is the escalated S2.
    expect(backend.resumeSessionCalls[0]![0]).toBe("S2");
    // The run continues to completion (human answer unblocked the coder).
    expect(result.status).toBe("success");
  });

  it("AC3: same machine — reuses worktree + cleans residue (no re-cut from S0)", async () => {
    const backend = new ResumeBackend(escalatedAtS2());

    await runOrchestrator({ issueNumber: 255, backend });

    // Identical reuse/clean behaviour as the crash-resume path.
    expect(backend.prepareWorktreeCount).toBe(0);
    expect(backend.cleanResidueCount).toBe(1);
    // S0 gate / S1 load are NOT re-run.
    expect(backend.calls).not.toContain("fetchIssueMeta(255)");
    expect(backend.calls).not.toContain("fetchIssueSnapshot(255)");
  });

  it("AC4: resume carries the ledger's recorded sessionId into resumeSession", async () => {
    const backend = new ResumeBackend(escalatedAtS2());

    await runOrchestrator({ issueNumber: 255, backend });

    // The sessionId handed to resumeSession is the one recorded in the ledger
    // for that step (resume reads disk, not in-memory LLM state).
    const [, sessionId] = backend.resumeSessionCalls[0]!;
    expect(sessionId).toBe("session-escalated-S2");
  });
});

// ─── AC4: recovery decides next step from ledger, not memory ──────────────────

describe("recovery reads the ledger to decide next step (#255 AC4)", () => {
  it("ledger stopping at S3 (reviewer approve) resumes at the route successor S4→S7, not S0", async () => {
    // Prior run got through S3 with empty findings (approve) but died before
    // S4/S7. Resume must route S3→S4→S7→S8 from the recorded output.
    const resumeState: ResumeState = {
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        entry("S0"),
        entry("S1"),
        entry("S2", { kind: "coder", committed: true, commitsAdded: 1 }),
        entry("S3", { kind: "reviewer", findings: [] }),
      ],
    };
    const backend = new ResumeBackend(resumeState);

    const result = await runOrchestrator({ issueNumber: 255, backend });

    // No agent steps re-dispatched (S3 already done; S4/S7 are runner actions).
    expect(backend.runStepIds).toEqual([]);
    expect(backend.resumeSessionCalls).toHaveLength(0);
    // Pushed and succeeded — resumed purely from ledger truth.
    expect(backend.pushCount).toBe(1);
    expect(result.status).toBe("success");
    expect(result.stepLedger.map((e) => e.step)).toEqual([
      "S0", "S1", "S2", "S3", "S4", "S7", "S8",
    ]);
  });

  it("a ledger already ending at S8 (run already complete) does not re-cut or re-run agents", async () => {
    // Defensive: re-feeding a fully-completed issue must be a no-op resume —
    // no fresh worktree, no agent dispatch.
    const resumeState: ResumeState = {
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        entry("S0"),
        entry("S1"),
        entry("S2", { kind: "coder", committed: true, commitsAdded: 1 }),
        entry("S3", { kind: "reviewer", findings: [] }),
        entry("S4"),
        entry("S7"),
        s8("success"),
      ],
    };
    const backend = new ResumeBackend(resumeState);

    const result = await runOrchestrator({ issueNumber: 255, backend });

    expect(backend.prepareWorktreeCount).toBe(0);
    expect(backend.runStepIds).toEqual([]);
    expect(backend.resumeSessionCalls).toHaveLength(0);
    // The completed run reports success against the resident branch.
    expect(result.status).toBe("success");
    expect(result.branch).toBe(WORKTREE.branch);
  });

  it("a legacy S8 entry without a handoffStatus tag is inferred from the prior step (untagged success → success)", async () => {
    // Older ledgers (written before the handoffStatus tag) end at a bare S8.
    // Recovery must infer the terminal status from the prior step (S7 → success)
    // rather than calling route() out of S8 (which throws).
    const resumeState: ResumeState = {
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        entry("S0"),
        entry("S1"),
        entry("S2", { kind: "coder", committed: true, commitsAdded: 1 }),
        entry("S3", { kind: "reviewer", findings: [] }),
        entry("S4"),
        entry("S7"),
        entry("S8"), // untagged legacy terminal entry
      ],
    };
    const backend = new ResumeBackend(resumeState);

    const result = await runOrchestrator({ issueNumber: 255, backend });

    expect(result.status).toBe("success");
    expect(result.branch).toBe(WORKTREE.branch);
    expect(backend.runStepIds).toEqual([]);
  });
});

// ─── #255 review fix: a prior ERROR/ESCALATE must not masquerade as success ───

describe("re-feeding a terminated run reports its TRUE status (#255 review fix)", () => {
  it("prior ERROR handoff (tagged S8) re-fed → status error, NOT success", async () => {
    // A 0-commit coder failure terminated the prior run with an error handoff.
    // The S8 entry carries handoffStatus:'error'. Re-feeding must report error
    // (with an error package), never a hardcoded success.
    const resumeState: ResumeState = {
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        entry("S0"),
        entry("S1"),
        entry("S2", { kind: "coder", committed: false, commitsAdded: 0 }),
        s8("error"),
      ],
    };
    const backend = new ResumeBackend(resumeState);

    const result = await runOrchestrator({ issueNumber: 255, backend });

    expect(result.status).toBe("error");
    expect(result.branch).toBeUndefined();
    expect(result.errorPackage).toBeDefined();
    // No agent steps re-run; this is a pure status report.
    expect(backend.runStepIds).toEqual([]);
    expect(backend.resumeSessionCalls).toHaveLength(0);
  });

  it("prior crash with last entry = coder committed:false (no S8 yet) → status error, NOT success", async () => {
    // The prior run crashed AFTER persisting the 0-commit coder entry but
    // BEFORE writing the S8 handoff. route(S2, committed:false) → error handoff.
    // Recovery must report error, not collapse it into success.
    const resumeState: ResumeState = {
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        entry("S0"),
        entry("S1"),
        entry("S2", { kind: "coder", committed: false, commitsAdded: 0 }),
      ],
    };
    const backend = new ResumeBackend(resumeState);

    const result = await runOrchestrator({ issueNumber: 255, backend });

    expect(result.status).toBe("error");
    expect(result.branch).toBeUndefined();
    expect(result.errorPackage).toBeDefined();
    expect(backend.runStepIds).toEqual([]);
  });

  it("prior crash with last entry = MALFORMED S5 (committed:true, commitsAdded:0) → status error, never re-run S6/push", async () => {
    // The prior run crashed AFTER persisting a malformed S5 coder output
    // (committed:true but 0 commits — a contract violation) but BEFORE the S8
    // write. planResume drives route({from:'S5', output: thatEntry}); route() is
    // the resume path's ONLY guard on this recorded shape (no isValidStepOutput
    // re-check). It must judge the malformed S5 → S8(error), NOT fall through to
    // S6 and re-review / push unvalidated code.
    const resumeState: ResumeState = {
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        entry("S0"),
        entry("S1"),
        entry("S2", { kind: "coder", committed: true, commitsAdded: 1 }),
        entry("S3", { kind: "reviewer", findings: [] }),
        entry("S4"),
        entry("S5", {
          kind: "coder",
          committed: true,
          commitsAdded: 0,
        } as unknown as StepOutput),
      ],
    };
    const backend = new ResumeBackend(resumeState);

    const result = await runOrchestrator({ issueNumber: 255, backend });

    expect(result.status).toBe("error");
    expect(result.branch).toBeUndefined();
    expect(result.errorPackage).toBeDefined();
    // No agent step re-run: S6 must NEVER be dispatched, and push never called.
    expect(backend.runStepIds).toEqual([]);
    expect(backend.resumeSessionCalls).toHaveLength(0);
    expect(backend.pushCount).toBe(0);
  });

  it("prior crash with last entry = MALFORMED S6 reviewer (no findings array) → status error, never re-run / push / reject", async () => {
    // The prior run crashed AFTER persisting a malformed S6 reviewer output
    // ({kind:'reviewer'} with NO findings array — a contract violation) but
    // BEFORE the S8 write. planResume drives route({from:'S6', output: thatEntry}),
    // and the resume path then rebuilds the defer list from plan.lastOutput. Both
    // seams must treat the malformed reviewer as a contract violation → S8(error):
    //   • route()'s S6 edge must NOT blindly route to S4 (defense-in-depth).
    //   • the resume defer-rebuild must NOT call `.findings.filter(...)` on a
    //     missing/garbage findings field and throw a raw TypeError (the MAIN hole:
    //     that TypeError escaped before any try/catch and rejected the promise,
    //     bypassing the malformed→S8(error) decision + US#30 error package).
    const resumeState: ResumeState = {
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        entry("S0"),
        entry("S1"),
        entry("S2", { kind: "coder", committed: true, commitsAdded: 1 }),
        entry("S3", { kind: "reviewer", findings: [] }),
        entry("S4"),
        entry("S5", { kind: "coder", committed: true, commitsAdded: 1 }),
        entry("S6", { kind: "reviewer" } as unknown as StepOutput),
      ],
    };
    const backend = new ResumeBackend(resumeState);

    // Must RESOLVE to error — never reject with a raw TypeError.
    const result = await runOrchestrator({ issueNumber: 255, backend });

    expect(result.status).toBe("error");
    expect(result.branch).toBeUndefined();
    expect(result.errorPackage).toBeDefined();
    // No agent step re-run, and push never called.
    expect(backend.runStepIds).toEqual([]);
    expect(backend.resumeSessionCalls).toHaveLength(0);
    expect(backend.pushCount).toBe(0);
    // The defer list is NOT rebuilt from a malformed reviewer output.
    expect(result.deferredFindings).toEqual([]);
  });

  it("prior crash with last entry = MALFORMED S6 reviewer (findings NON-array) → status error, never re-run / push / reject", async () => {
    // Same seam, second malformed shape: `findings` present but not an array.
    // `{kind:'reviewer'}` passes the discriminant check; `.findings.filter(...)`
    // throws on a non-array. Must still resolve to S8(error), not reject.
    const resumeState: ResumeState = {
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        entry("S0"),
        entry("S1"),
        entry("S2", { kind: "coder", committed: true, commitsAdded: 1 }),
        entry("S3", { kind: "reviewer", findings: [] }),
        entry("S4"),
        entry("S5", { kind: "coder", committed: true, commitsAdded: 1 }),
        entry("S6", {
          kind: "reviewer",
          findings: "not-an-array",
        } as unknown as StepOutput),
      ],
    };
    const backend = new ResumeBackend(resumeState);

    const result = await runOrchestrator({ issueNumber: 255, backend });

    expect(result.status).toBe("error");
    expect(result.branch).toBeUndefined();
    expect(result.errorPackage).toBeDefined();
    expect(backend.runStepIds).toEqual([]);
    expect(backend.resumeSessionCalls).toHaveLength(0);
    expect(backend.pushCount).toBe(0);
    expect(result.deferredFindings).toEqual([]);
  });

  it("MALFORMED reviewer entry MID-ledger (not last) → progress reconstruction does not raw-throw; resume continues", async () => {
    // Same-class as the defer-rebuild hole (integ-cmr m2 r4 self-check): the
    // resume path's no-progress reconstruction folds over EVERY persisted
    // reviewer entry, not just the last one. A malformed reviewer entry EARLIER
    // in the ledger (findings missing / non-array) made `normalizeFindingsKey`
    // call `.map(...)` on a non-array and throw a raw TypeError — rejecting the
    // promise instead of continuing the resume. The live loop never scores a
    // malformed reviewer (it bails to S8), so reconstruction must likewise SKIP
    // malformed reviewer entries (validate-then-score), not crash on them.
    //
    // Shape: last entry is a coder S5 (valid) so the defer-rebuild guard does
    // NOT fire and terminalStatus is undefined — execution reaches the
    // reconstruction. An S6 mid-ledger is malformed.
    const resumeState: ResumeState = {
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        entry("S0"),
        entry("S1"),
        entry("S2", { kind: "coder", committed: true, commitsAdded: 1 }),
        entry("S3", { kind: "reviewer", findings: [] }),
        entry("S4"),
        entry("S5", { kind: "coder", committed: true, commitsAdded: 1 }),
        entry("S6", { kind: "reviewer" } as unknown as StepOutput),
        entry("S4"),
        entry("S5", { kind: "coder", committed: true, commitsAdded: 1 }),
      ],
    };
    const backend = new ResumeBackend(resumeState);

    // Must NOT reject with a raw TypeError. The resume continues from S6 (the
    // route() successor of the last S5); the fake reviewer returns empty findings
    // → S4 approve → S7 push → success.
    const result = await runOrchestrator({ issueNumber: 255, backend });

    expect(result.status).toBe("success");
    // Reconstruction did not crash and the resume reached the push.
    expect(backend.pushCount).toBe(1);
  });

  it("a terminal-status resume does NOT run cleanResidue (a clean failure must not flip a finished run's status)", async () => {
    // Re-feeding a completed run is a pure status report — no worktree mutation.
    // cleanResidue must NOT be invoked, so a transient git failure during clean
    // can never turn an already-finished success into an error.
    const resumeState: ResumeState = {
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        entry("S0"),
        entry("S1"),
        entry("S2", { kind: "coder", committed: true, commitsAdded: 1 }),
        entry("S3", { kind: "reviewer", findings: [] }),
        entry("S4"),
        entry("S7"),
        s8("success"),
      ],
    };
    const backend = new ResumeBackend(resumeState);

    const result = await runOrchestrator({ issueNumber: 255, backend });

    expect(result.status).toBe("success");
    expect(backend.cleanResidueCount).toBe(0);
  });
});
