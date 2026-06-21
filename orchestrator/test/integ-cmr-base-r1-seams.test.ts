/**
 * integ-cmr (merged base) round 1 — three fix_now seam gaps the integrated
 * review found (all behavioural, test-first):
 *
 *   F1 [high] malformed_step_output_coercion_hole — `escalate` is part of the
 *     step-output schema contract ({reason,diagnosis}), but isValidCoderOutput /
 *     isValidReviewerOutput never validated its SHAPE, and route()'s escalate
 *     edge treated ANY non-null `escalate` as a legitimate human-escalation stop
 *     signal. So `escalate:{}` (empty) or `{reason:123,diagnosis:'x'}` (wrong
 *     type) was accepted as a real escalate → S8(escalate), and the caller read
 *     escalate.reason/diagnosis as undefined/wrong-type. Fix: validate escalate
 *     shape (absent/null = no escalate; once present must be
 *     {reason:non-empty-string, diagnosis:non-empty-string}); a malformed
 *     escalate → S8(error), not S8(escalate).
 *
 *   F2 [medium] validation_precedence_drops_escalate — escalate is the GLOBAL
 *     stop edge (checked FIRST, per ADR 0018 / PRD route table). But the runner
 *     ran the full role-schema validation (isValidStepOutput) BEFORE route() saw
 *     the escalate field. A stuck step that carried a VALID escalate but an
 *     incomplete happy-path schema (coder missing committed, reviewer missing
 *     findings) was judged isValidStepOutput=false → S8(error), silently
 *     swallowing the escalate diagnosis. Fix: check a valid escalate FIRST; if
 *     present and valid, take the escalate edge without demanding the rest of the
 *     happy-path schema; only run the full role schema when there is no escalate.
 *
 *   F3 [medium] ledger_disk_memory_drift_resume_truth — when emitLedger throws on
 *     an agent step, errorTermination best-effort re-persisted the failing step
 *     but passed output=undefined, so the DISK ledger entry for that step lost
 *     its output while the in-memory entry kept it. Resume reads the disk ledger,
 *     so a crash there would resume from a step with no output (e.g. a reviewer
 *     S3 with no findings). Fix: errorTermination takes the failing step's output
 *     and re-persists it WITH output, so disk and memory agree on the error path.
 *
 * All paths use fake Backend injection — zero real Sandcastle / LLM calls.
 */

import { describe, expect, it } from "vitest";
import { runOrchestrator } from "../src/runner.js";
import { route } from "../src/route.js";
import {
  isValidCoderOutput,
  isValidReviewerOutput,
} from "../src/validate.js";
import type {
  Backend,
  CoderOutput,
  IssueMeta,
  IssueSnapshot,
  PersistentLedgerEntry,
  ReviewerOutput,
  StepOutput,
  StepSpec,
  WorktreeHandle,
} from "../src/types.js";

// ─── shared fixtures ───────────────────────────────────────────────────────

const COMPLIANT_META: IssueMeta = {
  number: 244,
  isReadyForAgent: true,
  hasAgentBrief: true,
  hasSubIssues: false,
  openBlockedBy: [],
};

const SNAPSHOT: IssueSnapshot = {
  number: 244,
  body: "issue body",
  comments: [],
  agentBrief: "## Agent Brief\nimplement the thing",
};

const WORKTREE: WorktreeHandle = {
  branch: "feat/orchestrator/issue-244",
  base: "main",
  path: "/resident/worktrees/issue-244",
};

/**
 * Base fake Backend. Override runStep / push / writeLedger per test.
 */
class SpyBackend implements Backend {
  readonly ledgerCalls: Array<{
    entry: PersistentLedgerEntry;
    stateDir: string;
  }> = [];
  readonly runStepIds: string[] = [];
  pushed = false;

  // #255 resume seam: fresh-run fake → no residue (runner consults this first).
  async findResumeState(): Promise<undefined> {
    return undefined;
  }
  async cleanResidue(): Promise<void> {
    // no-op
  }
  async resumeSession(spec: StepSpec): Promise<StepOutput> {
    return this.runStep(spec);
  }

  async fetchIssueMeta(_n: number): Promise<IssueMeta> {
    return COMPLIANT_META;
  }
  async fetchIssueSnapshot(_n: number): Promise<IssueSnapshot> {
    return SNAPSHOT;
  }
  async prepareWorktree(_n: number, _b: string): Promise<WorktreeHandle> {
    return WORKTREE;
  }
  async writeSnapshot(_w: WorktreeHandle, _s: IssueSnapshot): Promise<void> {}
  async runStep(spec: StepSpec): Promise<StepOutput> {
    this.runStepIds.push(spec.id);
    if (spec.role === "coder") {
      return { kind: "coder", committed: true, commitsAdded: 1 };
    }
    return { kind: "reviewer", findings: [] };
  }
  async push(_w: WorktreeHandle): Promise<void> {
    this.pushed = true;
  }
  async writeLedger(
    entry: PersistentLedgerEntry,
    stateDir: string,
  ): Promise<void> {
    this.ledgerCalls.push({ entry, stateDir });
  }
}

/** A backend whose S2/S3 returns a chosen output (the step under test). */
function stepReturning(stepId: "S2" | "S3", out: StepOutput): SpyBackend {
  const backend = new SpyBackend();
  backend.runStep = async (spec: StepSpec) => {
    backend.runStepIds.push(spec.id);
    if (spec.id === stepId) return out;
    if (spec.role === "coder") {
      return { kind: "coder", committed: true, commitsAdded: 1 };
    }
    return { kind: "reviewer", findings: [] };
  };
  return backend;
}

// ═══════════════════════════════════════════════════════════════════════════
// F1 [high] — escalate SHAPE validation: a malformed escalate is NOT a real
// human-escalation stop signal. It → S8(error), never S8(escalate).
// ═══════════════════════════════════════════════════════════════════════════

describe("F1: escalate shape validation (guards)", () => {
  it("isValidCoderOutput rejects a coder output with escalate:{} (empty)", () => {
    const out = {
      kind: "coder",
      committed: true,
      commitsAdded: 1,
      escalate: {},
    } as unknown as StepOutput;
    expect(isValidCoderOutput(out)).toBe(false);
  });

  it("isValidCoderOutput rejects escalate with non-string reason", () => {
    const out = {
      kind: "coder",
      committed: true,
      commitsAdded: 1,
      escalate: { reason: 123, diagnosis: "x" },
    } as unknown as StepOutput;
    expect(isValidCoderOutput(out)).toBe(false);
  });

  it("isValidCoderOutput rejects escalate missing diagnosis", () => {
    const out = {
      kind: "coder",
      committed: true,
      commitsAdded: 1,
      escalate: { reason: "stuck" },
    } as unknown as StepOutput;
    expect(isValidCoderOutput(out)).toBe(false);
  });

  it("isValidCoderOutput rejects escalate with empty-string fields", () => {
    const out = {
      kind: "coder",
      committed: true,
      commitsAdded: 1,
      escalate: { reason: "", diagnosis: "" },
    } as unknown as StepOutput;
    expect(isValidCoderOutput(out)).toBe(false);
  });

  it("isValidReviewerOutput rejects a reviewer output with escalate:{}", () => {
    const out = {
      kind: "reviewer",
      findings: [],
      escalate: {},
    } as unknown as StepOutput;
    expect(isValidReviewerOutput(out)).toBe(false);
  });

  it("isValidReviewerOutput rejects escalate with non-string diagnosis", () => {
    const out = {
      kind: "reviewer",
      findings: [],
      escalate: { reason: "x", diagnosis: 9 },
    } as unknown as StepOutput;
    expect(isValidReviewerOutput(out)).toBe(false);
  });

  it("isValidCoderOutput ACCEPTS a valid escalate (regression)", () => {
    const out: CoderOutput = {
      kind: "coder",
      committed: false,
      commitsAdded: 0,
      escalate: { reason: "stuck on X", diagnosis: "design gap Y" },
    };
    expect(isValidCoderOutput(out)).toBe(true);
  });

  it("isValidReviewerOutput ACCEPTS a valid escalate (regression)", () => {
    const out: ReviewerOutput = {
      kind: "reviewer",
      findings: [],
      escalate: { reason: "stuck on X", diagnosis: "design gap Y" },
    };
    expect(isValidReviewerOutput(out)).toBe(true);
  });

  it("isValidCoderOutput ACCEPTS absent/undefined/null escalate (regression)", () => {
    expect(
      isValidCoderOutput({ kind: "coder", committed: true, commitsAdded: 1 }),
    ).toBe(true);
    expect(
      isValidCoderOutput({
        kind: "coder",
        committed: true,
        commitsAdded: 1,
        escalate: undefined,
      }),
    ).toBe(true);
    expect(
      isValidCoderOutput({
        kind: "coder",
        committed: true,
        commitsAdded: 1,
        escalate: null,
      } as unknown as StepOutput),
    ).toBe(true);
  });
});

describe("F1: malformed escalate → S8(error), not S8(escalate) (runner end-to-end)", () => {
  it("coder S2 with escalate:{} → S8(error), NOT escalate, NOT pushed", async () => {
    const backend = stepReturning("S2", {
      kind: "coder",
      committed: true,
      commitsAdded: 1,
      escalate: {} as unknown as CoderOutput["escalate"],
    });

    const result = await runOrchestrator({ issueNumber: 244, backend });

    expect(result.status).toBe("error");
    expect(result.errorPackage?.failedStep).toBe("S2");
    expect(backend.pushed).toBe(false);
  });

  it("coder S2 with escalate reason:123 → S8(error)", async () => {
    const backend = stepReturning("S2", {
      kind: "coder",
      committed: true,
      commitsAdded: 1,
      escalate: { reason: 123, diagnosis: "x" } as unknown as CoderOutput["escalate"],
    });

    const result = await runOrchestrator({ issueNumber: 244, backend });
    expect(result.status).toBe("error");
    expect(result.errorPackage?.failedStep).toBe("S2");
  });

  it("reviewer S3 with escalate missing diagnosis → S8(error), NOT escalate", async () => {
    const backend = stepReturning("S3", {
      kind: "reviewer",
      findings: [],
      escalate: { reason: "stuck" } as unknown as ReviewerOutput["escalate"],
    });

    const result = await runOrchestrator({ issueNumber: 244, backend });
    expect(result.status).toBe("error");
    expect(result.errorPackage?.failedStep).toBe("S3");
    expect(backend.pushed).toBe(false);
  });

  it("regression: a VALID escalate on coder S2 still → S8(escalate)", async () => {
    const backend = stepReturning("S2", {
      kind: "coder",
      committed: false,
      commitsAdded: 0,
      escalate: { reason: "stuck on X", diagnosis: "design gap Y" },
    });

    const result = await runOrchestrator({ issueNumber: 244, backend });
    expect(result.status).toBe("escalate");
  });
});

describe("F1: route() rejects a malformed escalate (defense in depth)", () => {
  it("S2 with escalate:{} → handoff(error), not handoff(escalate)", () => {
    const decision = route({
      from: "S2",
      output: {
        kind: "coder",
        committed: true,
        commitsAdded: 1,
        escalate: {} as unknown as CoderOutput["escalate"],
      },
    });
    expect(decision).toEqual({ kind: "handoff", status: "error" });
  });

  it("S3 with escalate {reason:123,diagnosis:'x'} → handoff(error)", () => {
    const decision = route({
      from: "S3",
      output: {
        kind: "reviewer",
        findings: [],
        escalate: {
          reason: 123,
          diagnosis: "x",
        } as unknown as ReviewerOutput["escalate"],
      },
    });
    expect(decision).toEqual({ kind: "handoff", status: "error" });
  });

  it("regression: a valid escalate → handoff(escalate)", () => {
    const decision = route({
      from: "S2",
      output: {
        kind: "coder",
        committed: false,
        commitsAdded: 0,
        escalate: { reason: "stuck", diagnosis: "design gap" },
      },
    });
    expect(decision).toEqual({ kind: "handoff", status: "escalate" });
  });
});

// ═══════════════════════════════════════════════════════════════════════════
// F2 [medium] — escalate is the GLOBAL stop edge, checked FIRST. A step that
// carries a VALID escalate but an incomplete happy-path schema (coder missing
// committed, reviewer missing findings) must STILL take the escalate edge —
// the escalate diagnosis must not be swallowed by the role-schema check.
// ═══════════════════════════════════════════════════════════════════════════

describe("F2: valid escalate takes precedence over incomplete role schema", () => {
  it("coder S2 with valid escalate but MISSING committed → S8(escalate), not error", async () => {
    const backend = stepReturning("S2", {
      kind: "coder",
      // committed + commitsAdded intentionally absent — the step is stuck.
      escalate: { reason: "stuck mid-implement", diagnosis: "design gap" },
    } as unknown as StepOutput);

    const result = await runOrchestrator({ issueNumber: 244, backend });

    expect(result.status).toBe("escalate");
    expect(backend.pushed).toBe(false);
  });

  it("reviewer S3 with valid escalate but MISSING findings → S8(escalate), not error", async () => {
    const backend = stepReturning("S3", {
      kind: "reviewer",
      // findings intentionally absent — the reviewer got stuck.
      escalate: { reason: "cannot review", diagnosis: "spec ambiguous" },
    } as unknown as StepOutput);

    const result = await runOrchestrator({ issueNumber: 244, backend });

    expect(result.status).toBe("escalate");
    // Must not have routed to S4 (escalate stops first).
    expect(result.stepLedger.map((e) => e.step)).not.toContain("S4");
  });

  it("the escalate output (with incomplete schema) is recorded in the ledger", async () => {
    const escalation = { reason: "stuck", diagnosis: "design gap Z" };
    const backend = stepReturning("S2", {
      kind: "coder",
      escalate: escalation,
    } as unknown as StepOutput);

    const result = await runOrchestrator({ issueNumber: 244, backend });

    const s2 = result.stepLedger.find((e) => e.step === "S2");
    expect((s2?.output as CoderOutput | undefined)?.escalate).toEqual(
      escalation,
    );
  });

  it("regression: an INVALID escalate on an incomplete coder output → S8(error)", async () => {
    // No happy-path schema AND no valid escalate → genuine malformed output.
    const backend = stepReturning("S2", {
      kind: "coder",
      escalate: { reason: "" }, // invalid escalate
    } as unknown as StepOutput);

    const result = await runOrchestrator({ issueNumber: 244, backend });
    expect(result.status).toBe("error");
    expect(result.errorPackage?.failedStep).toBe("S2");
  });

  it("regression: incomplete coder output with NO escalate → S8(error)", async () => {
    const backend = stepReturning("S2", {
      kind: "coder",
      // missing committed + commitsAdded, no escalate
    } as unknown as StepOutput);

    const result = await runOrchestrator({ issueNumber: 244, backend });
    expect(result.status).toBe("error");
    expect(result.errorPackage?.failedStep).toBe("S2");
  });
});

// ═══════════════════════════════════════════════════════════════════════════
// F3 [medium] — ledger disk/memory drift: when emitLedger throws on an agent
// step, the best-effort re-persist must carry the failing step's OUTPUT so the
// disk ledger entry is not left output-less (resume reads the disk ledger).
// ═══════════════════════════════════════════════════════════════════════════

describe("F3: error-path re-persist carries the failing step's output", () => {
  it("S3 emitLedger throws → the re-persisted S3 disk entry still has reviewer output", async () => {
    const reviewerOut: ReviewerOutput = {
      kind: "reviewer",
      findings: [
        {
          severity: "low",
          category: "clarity",
          claim_quote: "x",
          location: "src/foo.ts:1",
          suggested_fix: "y",
          action: "defer",
        },
      ],
    };

    const backend = new SpyBackend();
    backend.runStep = async (spec) => {
      backend.runStepIds.push(spec.id);
      if (spec.role === "coder") {
        return { kind: "coder", committed: true, commitsAdded: 1 };
      }
      return reviewerOut;
    };
    let s3Thrown = false;
    backend.writeLedger = async (entry, stateDir) => {
      if (entry.step === "S3" && !s3Thrown) {
        s3Thrown = true;
        throw new Error("writeLedger: transient I/O fault on S3");
      }
      backend.ledgerCalls.push({ entry, stateDir });
    };

    const result = await runOrchestrator({ issueNumber: 244, backend });

    expect(result.status).toBe("error");
    // The disk-persisted S3 entry must carry the reviewer output (not undefined),
    // so a resume from disk sees the findings, not an output-less S3.
    const diskS3 = backend.ledgerCalls.find((c) => c.entry.step === "S3");
    expect(diskS3).toBeDefined();
    expect(diskS3?.entry.output).toEqual(reviewerOut);
  });

  it("S2 emitLedger throws → the re-persisted S2 disk entry still has coder output", async () => {
    const coderOut: CoderOutput = {
      kind: "coder",
      committed: true,
      commitsAdded: 3,
    };
    const backend = new SpyBackend();
    backend.runStep = async (spec) => {
      backend.runStepIds.push(spec.id);
      if (spec.role === "coder") return coderOut;
      return { kind: "reviewer", findings: [] };
    };
    let s2Thrown = false;
    backend.writeLedger = async (entry, stateDir) => {
      if (entry.step === "S2" && !s2Thrown) {
        s2Thrown = true;
        throw new Error("writeLedger: transient I/O fault on S2");
      }
      backend.ledgerCalls.push({ entry, stateDir });
    };

    const result = await runOrchestrator({ issueNumber: 244, backend });

    expect(result.status).toBe("error");
    const diskS2 = backend.ledgerCalls.find((c) => c.entry.step === "S2");
    expect(diskS2).toBeDefined();
    expect(diskS2?.entry.output).toEqual(coderOut);
  });

  it("disk and in-memory S3 entries agree on output after the write fault", async () => {
    const reviewerOut: ReviewerOutput = {
      kind: "reviewer",
      findings: [],
    };
    const backend = new SpyBackend();
    backend.runStep = async (spec) => {
      backend.runStepIds.push(spec.id);
      if (spec.role === "coder") {
        return { kind: "coder", committed: true, commitsAdded: 1 };
      }
      return reviewerOut;
    };
    let s3Thrown = false;
    backend.writeLedger = async (entry, stateDir) => {
      if (entry.step === "S3" && !s3Thrown) {
        s3Thrown = true;
        throw new Error("transient");
      }
      backend.ledgerCalls.push({ entry, stateDir });
    };

    const result = await runOrchestrator({ issueNumber: 244, backend });

    const memS3 = result.stepLedger.find((e) => e.step === "S3");
    const diskS3 = backend.ledgerCalls.find((c) => c.entry.step === "S3");
    expect(memS3?.output).toEqual(reviewerOut);
    expect(diskS3?.entry.output).toEqual(reviewerOut);
    // They agree.
    expect(diskS3?.entry.output).toEqual(memS3?.output);
  });
});
