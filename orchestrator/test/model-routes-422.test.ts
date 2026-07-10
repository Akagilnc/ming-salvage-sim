import { afterEach, describe, expect, it, vi } from "vitest";
import {
  activeModelRoute,
  applyRuntimeTightRoutePolicy,
  applyTightRoutePolicy,
  MODEL_ROUTE_SLOTS,
  cmrLegAccountingFailure,
  modelForSlot,
  printableRouteLineup,
  resolveRouteModels,
} from "../src/modelRoutes.js";
import { skeletonReviewLoopWorkerResult } from "../src/reviewLoopOutcome.js";
import type {
  Backend,
  DispatchContext,
  IssueMeta,
  IssueSnapshot,
  StepOutput,
  StepSpec,
  WorkerResult,
  WorkerSpec,
  WorktreeHandle,
} from "../src/types.js";
import type {
  FamilyBackend,
  FamilyLedgerEntry,
  MergeRequest,
  MergeResult,
} from "../src/family/types.js";

describe("#422 model route presets", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.resetModules();
  });

  it("normal is an explicit full-slot route and can be printed before a run", () => {
    const resolved = resolveRouteModels("normal", {});

    expect(Object.keys(resolved.slots).sort()).toEqual(
      [...MODEL_ROUTE_SLOTS].sort(),
    );
    expect(resolved.slots).toEqual({
      coder: "gpt-5.6-terra",
      reviewer: "gpt-5.6-sol",
      coderFix: "gpt-5.6-terra",
      ship: "sonnet",
      merger: "sonnet",
      cmrCompleteness: "gpt-5.6-terra",
      cmrCorrectness: "gpt-5.6-terra",
      verify: "gpt-5.6-terra",
      fixer: "sonnet",
      cleanup: "sonnet",
      docRelease: "sonnet",
    });
    expect(printableRouteLineup(resolved)).toEqual(
      [
        "route=normal",
        "coder=gpt-5.6-terra",
        "reviewer=gpt-5.6-sol",
        "coderFix=gpt-5.6-terra",
        "ship=sonnet",
        "merger=sonnet",
        "cmrCompleteness=gpt-5.6-terra",
        "cmrCorrectness=gpt-5.6-terra",
        "verify=gpt-5.6-terra",
        "fixer=sonnet",
        "cleanup=sonnet",
        "docRelease=sonnet",
        "cmrReview=[codex:gpt-5.6-sol,claude:opus,agy:agy]",
      ].join("\n"),
    );
  });

  it("single-slot overrides win over the selected base route", () => {
    const resolved = resolveRouteModels("normal", {
      reviewer: "opus",
      ship: "gpt-5.5",
    });

    expect(resolved.slots.reviewer).toBe("opus");
    expect(resolved.slots.ship).toBe("gpt-5.5");
    expect(resolved.slots.coder).toBe("gpt-5.6-terra");
  });

  it("cheap routes keep only the pressured family's CMR strong leg", () => {
    const claudeCheap = resolveRouteModels("claude-cheap", {});
    const claudeTight = resolveRouteModels("claude-tight", {});
    const codexCheap = resolveRouteModels("codex-cheap", {});
    const codexTight = resolveRouteModels("codex-tight", {});

    expect(claudeCheap.slots).toEqual(claudeTight.slots);
    expect(claudeCheap.legCollections.cmrReview.map((leg) => leg.slug)).toEqual([
      "gpt-5.6-sol",
      "agy",
      "opus",
    ]);
    expect(claudeTight.legCollections.cmrReview.map((leg) => leg.slug)).toEqual([
      "gpt-5.6-sol",
      "agy",
    ]);

    expect(codexCheap.slots.coder).toBe("gpt-5.6-terra");
    expect(codexCheap.slots.reviewer).toBe("gpt-5.6-sol");
    expect(codexCheap.slots.verify).toBe("gpt-5.6-terra");
    expect(codexCheap.legCollections.cmrReview.map((leg) => leg.slug)).toEqual([
      "opus",
      "agy",
      "gpt-5.6-sol",
    ]);
    expect(codexTight.legCollections.cmrReview.map((leg) => leg.slug)).toEqual([
      "opus",
      "agy",
    ]);
  });

  it("fails closed for unknown routes, slots, and slugs", () => {
    expect(() => resolveRouteModels("missing", {})).toThrow(/unknown route/i);
    expect(() =>
      resolveRouteModels("normal", { nope: "gpt-5.5" }),
    ).toThrow(/unknown model slot/i);
    expect(() =>
      resolveRouteModels("normal", { coder: "does-not-exist" }),
    ).toThrow(/unknown model slug/i);
  });

  it("verify-TARGETED: mis/unconfigured verify slot fails closed (no silent fallback to cheap tier per AC3)", () => {
    expect(() =>
      resolveRouteModels("normal", { verify: "does-not-exist" }),
    ).toThrow(/unknown model slug/i);
    // default preset for verify on "normal" is the ratified xhigh terra officer.
    const resolved = resolveRouteModels("normal", {});
    expect(resolved.slots.verify).toBe("gpt-5.6-terra");
    // bad explicit still caught above; the targeted proves verify slot participates in fail-closed
  });

  it("claude-tight has no Claude-family slots across every slot", () => {
    const resolved = resolveRouteModels("claude-tight", {});

    expect(resolved.tightFamilyViolations).toEqual([]);
    expect(new Set(Object.values(resolved.slots))).toEqual(new Set(["gpt-5.6-terra", "gpt-5.6-sol"]));
    expect(resolved.legCollections.cmrReview.map((leg) => leg.family)).not.toContain(
      "claude",
    );
  });

  it("flags an override or review leg that breaks a tight route invariant", () => {
    const overridden = resolveRouteModels("claude-tight", { merger: "opus" });

    expect(overridden.tightFamilyViolations).toEqual([
      { slot: "merger", slug: "opus", family: "claude" },
    ]);

    const badLeg = resolveRouteModels(
      "claude-tight",
      {},
      { cmrReview: ["gpt-5.5", "opus"] },
    );

    expect(badLeg.tightFamilyViolations).toEqual([
      { slot: "cmrReview", slug: "opus", family: "claude" },
    ]);
  });

  it("reads ORCHESTRATOR_ROUTE plus slot env overrides for runtime selection", () => {
    expect(
      activeModelRoute({
        ORCHESTRATOR_ROUTE: "claude-tight",
      }).slots.coder,
    ).toBe("gpt-5.6-terra");

    expect(() =>
      activeModelRoute({
        ORCHESTRATOR_ROUTE: "claude-tight",
        ORCHESTRATOR_SHIP_MODEL: "sonnet",
      }),
    ).toThrow(/tight route violation/i);

    expect(
      modelForSlot("ship", {
        ORCHESTRATOR_ROUTE: "normal",
        ORCHESTRATOR_SHIP_MODEL: "gpt-5.5",
      }),
    ).toBe("gpt-5.5");

    expect(() =>
      activeModelRoute({
        ORCHESTRATOR_ROUTE: "claude-tight",
        ORCHESTRATOR_CMR_REVIEW_LEG_SLUGS: "gpt-5.5,opus",
      }),
    ).toThrow(/tight route violation/i);
  });

  it("keeps route override slugs separate from worker JSON leg objects", () => {
    const route = activeModelRoute({
      ORCHESTRATOR_ROUTE: "claude-tight",
      ORCHESTRATOR_CMR_REVIEW_LEGS: JSON.stringify([
        { family: "claude", slug: "opus" },
      ]),
    });

    expect(route.legCollections.cmrReview.map((leg) => leg.slug)).toEqual([
      "gpt-5.6-sol",
      "agy",
    ]);

    const overridden = activeModelRoute({
      ORCHESTRATOR_ROUTE: "normal",
      ORCHESTRATOR_CMR_REVIEW_LEG_SLUGS: '"gpt-5.5", \'opus\'',
    });

    expect(overridden.legCollections.cmrReview.map((leg) => leg.slug)).toEqual([
      "gpt-5.5",
      "opus",
    ]);
  });

  it("fails closed for unregistered CMR leg override slugs", () => {
    expect(() =>
      resolveRouteModels("normal", {}, { cmrReview: ["glm"] }),
    ).toThrow(/unknown cmr review leg slug/i);

    expect(
      resolveRouteModels("normal", {}, { cmrReview: ["gpt-5.5", "agy"] })
        .legCollections.cmrReview,
    ).toEqual([
      { family: "codex", slug: "gpt-5.5" },
      { family: "agy", slug: "agy" },
    ]);
  });

  it("rejects duplicate CMR leg accounting entries before set-based reconciliation", () => {
    expect(
      cmrLegAccountingFailure({
        successfulLegs: ["gpt-5.6-sol", "gpt-5.6-sol", "opus"],
        skippedLegs: [{ slug: "agy", reason: "quota" }],
      }),
    ).toMatch(/duplicate successful legs.*gpt-5\.6-sol/i);

    expect(
      cmrLegAccountingFailure({
        successfulLegs: ["gpt-5.6-sol", "opus"],
        skippedLegs: [
          { slug: "agy", reason: "quota" },
          { slug: "agy", reason: "quota again" },
        ],
      }),
    ).toMatch(/duplicate skipped legs.*agy/i);
  });

  it("does not treat shallow route-shaped objects as resolved routes", () => {
    const malformedRoute = {
      slots: {},
      legCollections: { cmrReview: "gpt-5.5,opus,agy" },
      tightFamilyViolations: "none",
    };

    expect(
      cmrLegAccountingFailure(
        { successfulLegs: ["gpt-5.6-sol", "opus", "agy"] },
        malformedRoute as never,
      ),
    ).toBeUndefined();
  });

  it("does not throw on null nested route-shaped properties", () => {
    const malformedRoute = {
      slots: null,
      legCollections: null,
      tightFamilyViolations: [],
    };

    expect(() =>
      cmrLegAccountingFailure(
        { successfulLegs: ["gpt-5.6-sol", "opus", "agy"] },
        malformedRoute as never,
      ),
    ).not.toThrow();
    expect(
      cmrLegAccountingFailure(
        { successfulLegs: ["gpt-5.6-sol", "opus", "agy"] },
        malformedRoute as never,
      ),
    ).toBeUndefined();
  });

  it("falls back to the active environment when CMR leg accounting receives null route input", () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "normal");

    expect(() =>
      cmrLegAccountingFailure(
        { successfulLegs: ["gpt-5.6-sol", "opus", "agy"] },
        null as never,
      ),
    ).not.toThrow();
    expect(
      cmrLegAccountingFailure(
        { successfulLegs: ["gpt-5.6-sol", "opus", "agy"] },
        null as never,
      ),
    ).toBeUndefined();
  });

  it("feeds the resolved route into every worker spec model slot", async () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "claude-tight");
    vi.resetModules();

    const { stepSpecsForEnv } = await import("../src/runner.js");
    const { shipWorkerSpec } = await import("../src/dispatchWorker.js");
    const { cmrWorkerSpec, familyShipWorkerSpec } = await import(
      "../src/family/dispatchFamilyWorker.js"
    );
    const { mergerModel } = await import("../src/family/realFamilyBackend.js");

    const stepSpecs = stepSpecsForEnv();
    expect(stepSpecs.S2.model).toBe("gpt-5.6-terra");
    expect(stepSpecs.S3.model).toBe("gpt-5.6-sol");
    expect(stepSpecs.S5.model).toBe("gpt-5.6-terra");
    expect(stepSpecs.S6.model).toBe("gpt-5.6-sol");
    expect(shipWorkerSpec().model).toBe("gpt-5.6-terra");
    expect(cmrWorkerSpec("fresh", "completeness").model).toBe("gpt-5.6-terra");
    expect(cmrWorkerSpec("fresh", "correctness").model).toBe("gpt-5.6-terra");
    expect(familyShipWorkerSpec().model).toBe("gpt-5.6-terra");
    expect(mergerModel()).toBe("gpt-5.6-terra");
  });

  it("dispatches worker specs from the per-run route, not the route at module import time", async () => {
    vi.unstubAllEnvs();
    vi.resetModules();
    const { runOrchestrator } = await import("../src/runner.js");
    vi.stubEnv("ORCHESTRATOR_ROUTE", "claude-tight");

    class RecordingBackend implements Backend {
  async smokeModelRoute(route: any) {
    const { smokeRouteModels } = await import("../src/modelRoutes.js");
    return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
  }
      readonly specs: WorkerSpec[] = [];
      async findResumeState(): Promise<undefined> {
        return undefined;
      }
      async cleanResidue(): Promise<void> {}
      async resumeSession(): Promise<StepOutput> {
        throw new Error("not used");
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
        return { number: issueNumber, body: "body", comments: [], agentBrief: "" };
      }
      async prepareWorktree(issueNumber: number, base: string): Promise<WorktreeHandle> {
        return { branch: `feat/${issueNumber}`, base, path: `/tmp/model-route-${issueNumber}` };
      }
      async writeSnapshot(): Promise<void> {}
      async runStep(): Promise<StepOutput> {
        throw new Error("not used");
      }
      async dispatchWorker(spec: WorkerSpec, ctx: DispatchContext): Promise<WorkerResult> {
        this.specs.push(spec);
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
        return {
          kind: "completed",
          output: {
            kind: "ship",
            branch: ctx.worktree?.branch ?? "missing",
            status: "pushed",
          },
        };
      }
      async push(): Promise<void> {}
      async writeLedger(): Promise<void> {}
    }

    const backend = new RecordingBackend();
    const result = await runOrchestrator({ issueNumber: 422, backend });

    expect(result.status).toBe("success");
    expect(backend.specs.filter((spec) => spec.id === "S2").map((spec) => spec.model)).toEqual([
      "gpt-5.6-terra",
    ]);
  });

  it("turns tight-route violations into a structured non-interactive stop decision", () => {
    const route = resolveRouteModels("claude-tight", { reviewer: "opus" });

    const decision = applyTightRoutePolicy(route, { interactive: false });

    expect(decision.kind).toBe("stop");
    if (decision.kind === "stop") {
      expect(decision.escalation.reason).toMatch(/tight route violation/i);
      expect(decision.escalation.diagnosis).toContain("reviewer=opus(claude)");
    }
  });

  it("lets the interactive policy seam warn and continue only on explicit confirmation", () => {
    const route = resolveRouteModels("claude-tight", { reviewer: "opus" });
    const warnings: string[] = [];

    const declined = applyTightRoutePolicy(route, {
      interactive: true,
      warn: (message) => warnings.push(message),
      confirm: () => false,
    });
    const accepted = applyTightRoutePolicy(route, {
      interactive: true,
      warn: (message) => warnings.push(message),
      confirm: () => true,
    });

    expect(declined.kind).toBe("stop");
    expect(accepted.kind).toBe("continue");
    expect(warnings.some((message) => message.includes("reviewer=opus(claude)"))).toBe(true);
  });

  it("runtime tight-route policy accepts an async interactive confirmation seam", async () => {
    const route = resolveRouteModels("claude-tight", { reviewer: "opus" });
    const decision = await applyRuntimeTightRoutePolicy(route, {
      interactive: true,
      confirm: async () => true,
    });

    expect(decision.kind).toBe("continue");
  });

  it("runner startup returns a structured non-interactive escalate before backend work", async () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "claude-tight");
    vi.stubEnv("ORCHESTRATOR_REVIEWER_MODEL", "opus");
    vi.resetModules();

    class BackendShouldNotRun implements Backend {
  async smokeModelRoute(route: any) {
    const { smokeRouteModels } = await import("../src/modelRoutes.js");
    return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
  }
      async findResumeState(): Promise<undefined> {
        throw new Error("backend should not run");
      }
      async cleanResidue(): Promise<void> {}
      async resumeSession(_spec: StepSpec): Promise<StepOutput> {
        throw new Error("backend should not run");
      }
      async fetchIssueMeta(_issueNumber: number): Promise<IssueMeta> {
        throw new Error("backend should not run");
      }
      async fetchIssueSnapshot(_issueNumber: number): Promise<IssueSnapshot> {
        throw new Error("backend should not run");
      }
      async prepareWorktree(): Promise<WorktreeHandle> {
        throw new Error("backend should not run");
      }
      async writeSnapshot(): Promise<void> {}
      async runStep(): Promise<StepOutput> {
        throw new Error("backend should not run");
      }
      async push(): Promise<void> {
        throw new Error("backend should not run");
      }
      async writeLedger(): Promise<void> {}
    }

    const { runOrchestrator } = await import("../src/runner.js");
    const result = await runOrchestrator({
      issueNumber: 422,
      backend: new BackendShouldNotRun(),
    });

    expect(result.status).toBe("escalate");
    expect(result.errorPackage?.failedStep).toBe("S0");
    expect(result.errorPackage?.reason).toContain("reviewer=opus(claude)");
  });

  it("family runner startup returns a structured non-interactive escalation before backend work", async () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "claude-tight");
    vi.stubEnv("ORCHESTRATOR_REVIEWER_MODEL", "opus");
    vi.resetModules();

    const familyBackend: FamilyBackend = {
      async mergeChildIntoFamilyBase(_child: MergeRequest): Promise<MergeResult> {
        throw new Error("family backend should not run");
      },
      async appendFamilyLedger(_entry: FamilyLedgerEntry): Promise<void> {
        throw new Error("family backend should not run");
      },
      async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
        throw new Error("family backend should not run");
      },
    };
    const singleSliceBackend = {
      async findResumeState(): Promise<undefined> {
        throw new Error("single slice backend should not run");
      },
    } as unknown as Backend;

    const { runFamily } = await import("../src/family/runner.js");
    const result = await runFamily({
      epic: { issue: 376, children: [{ issue: 428, blockedBy: [] }] },
      familyBackend,
      singleSliceBackend,
      familyBase: "family/376-base",
    });

    expect(result.status).toBe("escalated");
    expect(result.familyBase).toBe("family/376-base");
    expect(result.escalation?.reason).toMatch(/tight route violation/i);
    expect(result.escalation?.diagnosis).toContain("reviewer=opus(claude)");
    expect(result.children).toEqual([{ issue: 428, status: "skipped" }]);
  });
});
