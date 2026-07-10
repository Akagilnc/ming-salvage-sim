import { describe, expect, it } from "vitest";
import { runOrchestrator } from "../src/runner.js";
import type {
  Backend,
  CoderOutput,
  Escalation,
  IssueMeta,
  IssueSnapshot,
  PersistentLedgerEntry,
  StepOutput,
  StepSpec,
  WorktreeHandle,
} from "../src/types.js";

/**
 * Shared compliant issue metadata (gate always passes in this suite —
 * the focus is escalate stop, not gate validation).
 */
const COMPLIANT_META: IssueMeta = {
  number: 251,
  isReadyForAgent: true,
  hasSubIssues: false,
  isClosed: false,
  openBlockedBy: [],
};

const COMPLIANT_SNAPSHOT: IssueSnapshot = {
  number: 251,
  body: "escalate test issue body",
  comments: [],
  agentBrief: "## Agent Brief\nimplement the escalate stop edge",
};

const WORKTREE: WorktreeHandle = {
  branch: "feat/orchestrator/issue-251",
  base: "main",
  path: "/resident/worktrees/issue-251",
};

/**
 * Configurable fake Backend.  `runStepOutputs` is a map from StepId → the
 * StepOutput that call should return.  Any unspecified step falls back to a
 * sane default (coder committed:true, reviewer clean).
 */
class ConfigurableBackend implements Backend {
  async smokeModelRoute(route: any) {
    const { smokeRouteModels } = await import("../src/modelRoutes.js");
    return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
  }
  readonly calls: string[] = [];
  readonly runStepIds: string[] = [];
  pushCount = 0;

  constructor(
    private readonly runStepOutputs: Map<string, StepOutput> = new Map(),
  ) {}

  // #255: fresh-run defaults (this suite tests escalate routing, not resume).
  async findResumeState(): Promise<undefined> {
    return undefined;
  }
  async cleanResidue(): Promise<void> {
    // no-op
  }
  async resumeSession(spec: StepSpec): Promise<StepOutput> {
    return this.runStep(spec);
  }

  async fetchIssueMeta(_issueNumber: number): Promise<IssueMeta> {
    this.calls.push("fetchIssueMeta");
    return COMPLIANT_META;
  }

  async fetchIssueSnapshot(_issueNumber: number): Promise<IssueSnapshot> {
    this.calls.push("fetchIssueSnapshot");
    return COMPLIANT_SNAPSHOT;
  }

  async prepareWorktree(
    _issueNumber: number,
    _base: string,
  ): Promise<WorktreeHandle> {
    this.calls.push("prepareWorktree");
    return WORKTREE;
  }

  async writeSnapshot(
    _worktree: WorktreeHandle,
    _snapshot: IssueSnapshot,
  ): Promise<void> {
    this.calls.push("writeSnapshot");
  }

  async runStep(spec: StepSpec): Promise<StepOutput> {
    this.calls.push(`runStep(${spec.id})`);
    this.runStepIds.push(spec.id);

    const override = this.runStepOutputs.get(spec.id);
    if (override !== undefined) return override;

    if (spec.role === "reviewer") {
      return { kind: "reviewer", findings: [] };
    }
    // Default output: the coder worker committed.
    return { kind: "coder", committed: true, commitsAdded: 1 };
  }

  async push(_worktree: WorktreeHandle): Promise<void> {
    this.calls.push("push");
    this.pushCount += 1;
  }

  // #249 integration: writeLedger is part of the Backend seam. This suite
  // asserts escalate routing, not ledger persistence, so it is a no-op.
  async writeLedger(
    _entry: PersistentLedgerEntry,
    _stateDir: string,
  ): Promise<void> {
    // no-op
  }
}

// ─────────────────────── helper factories ───────────────────────

function coderWithEscalate(escalation: Escalation): CoderOutput {
  return {
    kind: "coder",
    committed: false,
    commitsAdded: 0,
    escalate: escalation,
  };
}

const STUCK: Escalation = {
  reason: "Design-level ambiguity: unclear whether field X should be optional",
  diagnosis: "The spec says 'optional' in one place but 'required' in another; this requires product decision before implementation can proceed.",
};

// ─────────────────────── tests ───────────────────────

describe("escalate stop edge (#251, ADR 0026)", () => {
  // ── coder step (S2) escalates ──────────────────────────────────

  describe("coder S2 build worker escalates", () => {
    it("routes to S8 handoff(status=escalate), not S7", async () => {
      const backend = new ConfigurableBackend(
        new Map([["S2", coderWithEscalate(STUCK)]]),
      );

      const result = await runOrchestrator({ issueNumber: 251, backend });

      expect(result.status).toBe("escalate");
    });

    it("does NOT proceed to S7 ship (runner stops immediately)", async () => {
      const backend = new ConfigurableBackend(
        new Map([["S2", coderWithEscalate(STUCK)]]),
      );

      const result = await runOrchestrator({ issueNumber: 251, backend });

      // The escalate stop happens at S2 → S8; S7 is never reached.
      expect(result.stepLedger.map((e) => e.step)).not.toContain("S7");
      // Consequently no push either.
      expect(backend.pushCount).toBe(0);
    });

    it("records S2 escalate output in ledger", async () => {
      const backend = new ConfigurableBackend(
        new Map([["S2", coderWithEscalate(STUCK)]]),
      );

      const result = await runOrchestrator({ issueNumber: 251, backend });

      const s2entry = result.stepLedger.find((e) => e.step === "S2");
      expect(s2entry).toBeDefined();
      expect((s2entry?.output as CoderOutput | undefined)?.escalate).toEqual(STUCK);
    });

    it("records S8 terminal entry in ledger", async () => {
      const backend = new ConfigurableBackend(
        new Map([["S2", coderWithEscalate(STUCK)]]),
      );

      const result = await runOrchestrator({ issueNumber: 251, backend });

      expect(result.stepLedger.map((e) => e.step)).toContain("S8");
    });

    it("returns no branch on escalate (branch is undefined)", async () => {
      const backend = new ConfigurableBackend(
        new Map([["S2", coderWithEscalate(STUCK)]]),
      );

      const result = await runOrchestrator({ issueNumber: 251, backend });

      expect(result.branch).toBeUndefined();
    });
  });

  // ── escalate overrides co-present committed ─────────────────────

  describe("escalate is prioritised over a co-present committed flag", () => {
    it("escalate on coder output overrides committed:true → still escalate, not S7", async () => {
      const outputWithBoth: CoderOutput = {
        kind: "coder",
        committed: true,
        commitsAdded: 1,
        escalate: STUCK,
      };

      const backend = new ConfigurableBackend(
        new Map([["S2", outputWithBoth]]),
      );

      const result = await runOrchestrator({ issueNumber: 251, backend });

      // escalate wins over the committed:true edge.
      expect(result.status).toBe("escalate");
      expect(result.stepLedger.map((e) => e.step)).not.toContain("S7");
    });
  });

  // ── no-escalate = no change to happy path ──────────────────────

  describe("no escalate signal = happy path unchanged", () => {
    it("normal coder output (no escalate) reaches S7 ship", async () => {
      // Default backend: no overrides → coder committed:true.
      const backend = new ConfigurableBackend();

      const result = await runOrchestrator({ issueNumber: 251, backend });

      expect(result.status).toBe("success");
      // ADR 0030: a committed build reaches S7 only after S3/S4 find no blocking
      // review findings.
      expect(result.stepLedger.map((e) => e.step)).toContain("S7");
      expect(backend.pushCount).toBe(1);
    });

    it("undefined escalate field on coder output is not treated as escalate", async () => {
      // Explicitly undefined escalate (same as absent field after spread).
      const noEscalate: CoderOutput = {
        kind: "coder",
        committed: true,
        commitsAdded: 1,
        escalate: undefined,
      };
      const backend = new ConfigurableBackend(new Map([["S2", noEscalate]]));

      const result = await runOrchestrator({ issueNumber: 251, backend });

      expect(result.status).toBe("success");
    });

    it("null escalate field on coder output (real backend JSON) is not treated as escalate", async () => {
      // Real backends may return JSON with `escalate: null` when the model
      // outputs the field but sets it to null. This must NOT trigger the
      // escalate stop edge — only a truthy Escalation object should.
      const nullEscalate: CoderOutput = {
        kind: "coder",
        committed: true,
        commitsAdded: 1,
        escalate: null as unknown as undefined,
      };
      const backend = new ConfigurableBackend(new Map([["S2", nullEscalate]]));

      const result = await runOrchestrator({ issueNumber: 251, backend });

      // null escalate must not divert to handoff(status=escalate).
      expect(result.status).toBe("success");
      // The normal next step (S7 ship) must still have been reached.
      expect(result.stepLedger.map((e) => e.step)).toContain("S7");
    });
  });

  // ── diagnosis field carries to ledger / result ─────────────────

  describe("diagnosis field from model reaches ledger (US#20 / US#22)", () => {
    it("full escalation object (reason + diagnosis) is preserved in ledger entry", async () => {
      const detailedEscalation: Escalation = {
        reason: "Implementation blocker: missing seam for auth token injection",
        diagnosis:
          "This is a design-level gap (not an implementation path choice): " +
          "the Backend interface has no provision for passing auth; " +
          "requires product/arch decision on whether to add a method or use env.",
      };

      const backend = new ConfigurableBackend(
        new Map([["S2", coderWithEscalate(detailedEscalation)]]),
      );

      const result = await runOrchestrator({ issueNumber: 251, backend });

      const s2entry = result.stepLedger.find((e) => e.step === "S2");
      const escalate = (s2entry?.output as CoderOutput | undefined)?.escalate;
      expect(escalate?.reason).toBe(detailedEscalation.reason);
      expect(escalate?.diagnosis).toBe(detailedEscalation.diagnosis);
    });

    it("runner does NOT reclassify diagnosis (impl vs design is the model's call)", async () => {
      // The runner just stops and records; it doesn't set a 'kind' field
      // of its own or try to parse the diagnosis string.
      const backend = new ConfigurableBackend(
        new Map([["S2", coderWithEscalate(STUCK)]]),
      );

      const result = await runOrchestrator({ issueNumber: 251, backend });

      // The only escalation data in the result comes from the model output
      // verbatim — the runner adds nothing beyond status=escalate.
      expect(result.status).toBe("escalate");
      // No extra classification key added by runner.
      const resultKeys = Object.keys(result);
      expect(resultKeys).not.toContain("escalateKind");
      expect(resultKeys).not.toContain("escalateClassification");
    });
  });
});
