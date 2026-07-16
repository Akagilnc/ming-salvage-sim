import { afterEach, describe, expect, it, vi } from "vitest";
import {
  activeModelRoute,
  applyRuntimeTightRoutePolicy,
  applyTightRoutePolicy,
  MODEL_ROUTE_SLOTS,
  modelRouteFingerprint,
  modelForSlot,
  printableRouteLineup,
  resolveRouteModels,
  degradeOptionalRouteSmokeFailures,
} from "../../src/modelRoutes.js";
import { skeletonReviewLoopWorkerResult } from "../../src/reviewLoopOutcome.js";
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
} from "../../src/types.js";
import type {
  FamilyBackend,
  FamilyLedgerEntry,
  MergeRequest,
  MergeResult,
} from "../../src/family/types.js";

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
      coderFix: "gpt-5.6-terra",
      ship: "sonnet",
      merger: "sonnet",
      cmrCompleteness: "gpt-5.6-sol",
      cmrCorrectness: "gpt-5.6-sol",
      verify: "gpt-5.6-sol",
      fixer: "sonnet",
      cleanup: "sonnet",
      docRelease: "sonnet",
    });
    expect(printableRouteLineup(resolved)).toEqual(
      [
        "route=normal",
        "coder=gpt-5.6-terra",
        "coderFix=gpt-5.6-terra",
        "ship=sonnet",
        "merger=sonnet",
        "cmrCompleteness=gpt-5.6-sol",
        "cmrCorrectness=gpt-5.6-sol",
        "verify=gpt-5.6-sol",
        "fixer=sonnet",
        "cleanup=sonnet",
        "docRelease=sonnet",
        "cmrReview=[codex:gpt-5.6-sol,claude:opus,agy:agy]",
      ].join("\n"),
    );
  });

  it("marks every preset agy CMR leg optional while operator override legs stay hard", () => {
    for (const routeName of ["normal", "codex-cheap", "codex-tight", "claude-cheap", "claude-tight"]) {
      const agy = resolveRouteModels(routeName, {}).legCollections.cmrReview.find((leg) => leg.slug === "agy");
      expect(agy, routeName).toMatchObject({ slug: "agy", optional: true });
    }

    const overridden = resolveRouteModels("normal", {}, { cmrReview: ["gpt-5.6-sol", "opus", "agy"] });
    expect(overridden.legCollections.cmrReview.every((leg) => leg.optional !== true)).toBe(true);
  });

  it("preserves historical fingerprints for unmarked legs and fingerprints optional markers", () => {
    const route = resolveRouteModels("normal", {}, { cmrReview: ["gpt-5.6-sol", "opus", "agy"] });
    const historical = JSON.stringify({
      routeName: route.routeName,
      slots: MODEL_ROUTE_SLOTS.map((slot) => [slot, route.slots[slot]]),
      legCollections: [["cmrReview", [["codex", "gpt-5.6-sol"], ["claude", "opus"], ["agy", "agy"]]]],
    });
    expect(modelRouteFingerprint(route)).toBe(historical);
    expect(modelRouteFingerprint(resolveRouteModels("normal", {}))).not.toBe(historical);
  });

  it("drops only failed optional smoke legs from the effective lineup", () => {
    const route = resolveRouteModels("normal", {}, {}, {
      "cmrReview:agy": { state: "failed", at: "2026-07-11T00:00:00.000Z", error: "agy unavailable" },
    });

    const degraded = degradeOptionalRouteSmokeFailures(route);

    expect(degraded.dropped).toEqual([{ slug: "agy", reason: "agy unavailable" }]);
    expect(degraded.route.legCollections.cmrReview.map((leg) => leg.slug)).toEqual(["gpt-5.6-sol", "opus"]);
    expect(printableRouteLineup(degraded.route)).toContain("cmrReview=[codex:gpt-5.6-sol,claude:opus]");
  });

  it("keeps anchor and env-override smoke failures hard", () => {
    const anchor = resolveRouteModels("normal", {}, {}, {
      "cmrReview:opus": { state: "failed", at: "2026-07-11T00:00:00.000Z", error: "claude unavailable" },
    });
    expect(degradeOptionalRouteSmokeFailures(anchor).dropped).toEqual([]);

    const overridden = resolveRouteModels("normal", {}, { cmrReview: ["gpt-5.6-sol", "opus", "agy"] }, {
      "cmrReview:agy": { state: "failed", at: "2026-07-11T00:00:00.000Z", error: "agy unavailable" },
    });
    expect(degradeOptionalRouteSmokeFailures(overridden).dropped).toEqual([]);
  });

  it("single-slot overrides win over the selected base route", () => {
    const resolved = resolveRouteModels("normal", {
      verify: "opus",
      ship: "gpt-5.6-terra",
    });

    expect(resolved.slots.verify).toBe("opus");
    expect(resolved.slots.ship).toBe("gpt-5.6-terra");
    expect(resolved.slots.coder).toBe("gpt-5.6-terra");
  });

  it("rejects retired 5.5 from every live route surface", () => {
    expect(() => resolveRouteModels("normal", { ship: "gpt-5.5" })).toThrow(
      /unknown model slug/i,
    );
    expect(() =>
      resolveRouteModels("normal", {}, { cmrReview: ["gpt-5.5", "agy"] }),
    ).toThrow(/unknown cmr review leg slug/i);
    expect(() =>
      activeModelRoute({
        ORCHESTRATOR_ROUTE: "normal",
        ORCHESTRATOR_VERIFY_MODEL: "gpt-5.5",
      }),
    ).toThrow(/unknown model slug/i);
  });

  it("cheap routes keep only the pressured family's CMR strong leg", () => {
    const claudeCheap = resolveRouteModels("claude-cheap", {});
    const claudeTight = resolveRouteModels("claude-tight", {});
    const codexCheap = resolveRouteModels("codex-cheap", {});
    const codexTight = resolveRouteModels("codex-tight", {});

    // #916: claude-tight factory lineup diverges from claude-cheap (grok coder +
    // sol-low utility seats + grok CMR leg); only verify/cmr gates stay sol@med.
    expect(claudeCheap.slots.verify).toBe("gpt-5.6-sol");
    expect(claudeTight.slots).toMatchObject({
      coder: "grok-4.5",
      coderFix: "grok-4.5",
      verify: "gpt-5.6-sol",
      ship: "gpt-5.6-sol-low",
    });
    expect(claudeCheap.legCollections.cmrReview.map((leg) => leg.slug)).toEqual([
      "gpt-5.6-sol",
      "agy",
      "opus",
    ]);
    expect(claudeTight.legCollections.cmrReview.map((leg) => leg.slug)).toEqual([
      "gpt-5.6-sol",
      "grok-4.5",
      "agy",
    ]);

    expect(codexCheap.slots.coder).toBe("gpt-5.6-terra");
    expect(codexCheap.slots.verify).toBe("gpt-5.6-sol");
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

  it("assigns Sol to the unified verify judge seat and every judging gate in every Codex-enabled preset", () => {
    for (const routeName of ["normal", "codex-cheap", "claude-cheap"] as const) {
      const { slots } = resolveRouteModels(routeName, {});

      expect(slots).toMatchObject({
        coder: "gpt-5.6-terra",
        coderFix: "gpt-5.6-terra",
        cmrCompleteness: "gpt-5.6-sol",
        cmrCorrectness: "gpt-5.6-sol",
        verify: "gpt-5.6-sol",
      });
      expect(slots).not.toHaveProperty("reviewer");
    }

    // #916 claude-tight: grok coder + sol-low utility; verify/cmr still sol@med.
    expect(resolveRouteModels("claude-tight", {}).slots).toMatchObject({
      coder: "grok-4.5",
      coderFix: "grok-4.5",
      cmrCompleteness: "gpt-5.6-sol",
      cmrCorrectness: "gpt-5.6-sol",
      verify: "gpt-5.6-sol",
      ship: "gpt-5.6-sol-low",
    });
    expect(resolveRouteModels("claude-tight", {}).slots).not.toHaveProperty("reviewer");

    expect(resolveRouteModels("codex-tight", {}).slots).toMatchObject({
      cmrCompleteness: "opus",
      cmrCorrectness: "opus",
      verify: "opus",
    });
  });

  it("fails closed for unknown routes, slots, and slugs", () => {
    expect(() => resolveRouteModels("missing", {})).toThrow(/unknown route/i);
    expect(() =>
      resolveRouteModels("normal", { nope: "gpt-5.6-sol" }),
    ).toThrow(/unknown model slot/i);
    expect(() =>
      resolveRouteModels("normal", { coder: "does-not-exist" }),
    ).toThrow(/unknown model slug/i);
  });

  it("verify-TARGETED: mis/unconfigured verify slot fails closed (no silent fallback to cheap tier per AC3)", () => {
    expect(() =>
      resolveRouteModels("normal", { verify: "does-not-exist" }),
    ).toThrow(/unknown model slug/i);
    // Default preset for verify on "normal" is the ratified xhigh Sol officer.
    const resolved = resolveRouteModels("normal", {});
    expect(resolved.slots.verify).toBe("gpt-5.6-sol");
    // bad explicit still caught above; the targeted proves verify slot participates in fail-closed
  });

  it("claude-tight has no Claude-family slots across every slot", () => {
    const resolved = resolveRouteModels("claude-tight", {});

    expect(resolved.tightFamilyViolations).toEqual([]);
    expect(new Set(Object.values(resolved.slots))).toEqual(
      new Set(["grok-4.5", "gpt-5.6-sol", "gpt-5.6-sol-low"]),
    );
    expect(resolved.legCollections.cmrReview.map((leg) => leg.family)).not.toContain(
      "claude",
    );
  });

  it("flags an override or review leg that breaks a tight route invariant", () => {
    const overridden = resolveRouteModels("claude-tight", { merger: "opus" });

    expect(overridden.tightFamilyViolations).toEqual([
      { slot: "merger", slug: "opus", family: "claude" },
    ]);

    const badLeg = resolveRouteModels("claude-tight", {}, { cmrReview: ["gpt-5.6-sol", "opus"] });

    expect(badLeg.tightFamilyViolations).toEqual([
      { slot: "cmrReview", slug: "opus", family: "claude" },
    ]);
  });

  it("reads ORCHESTRATOR_ROUTE plus slot env overrides for runtime selection", () => {
    expect(
      activeModelRoute({
        ORCHESTRATOR_ROUTE: "claude-tight",
      }).slots.coder,
    ).toBe("grok-4.5");

    expect(() =>
      activeModelRoute({
        ORCHESTRATOR_ROUTE: "claude-tight",
        ORCHESTRATOR_SHIP_MODEL: "sonnet",
      }),
    ).toThrow(/tight route violation/i);

    expect(
      modelForSlot("ship", {
        ORCHESTRATOR_ROUTE: "normal",
        ORCHESTRATOR_SHIP_MODEL: "gpt-5.6-terra",
      }),
    ).toBe("gpt-5.6-terra");

    expect(() =>
      activeModelRoute({
        ORCHESTRATOR_ROUTE: "claude-tight",
        ORCHESTRATOR_CMR_REVIEW_LEG_SLUGS: "gpt-5.6-sol,opus",
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
      "grok-4.5",
      "agy",
    ]);

    const overridden = activeModelRoute({
      ORCHESTRATOR_ROUTE: "normal",
      ORCHESTRATOR_CMR_REVIEW_LEG_SLUGS: '"gpt-5.6-sol", \'opus\'',
    });

    expect(overridden.legCollections.cmrReview.map((leg) => leg.slug)).toEqual([
      "gpt-5.6-sol",
      "opus",
    ]);
  });

  it("fails closed for unregistered CMR leg override slugs", () => {
    expect(() =>
      resolveRouteModels("normal", {}, { cmrReview: ["glm"] }),
    ).toThrow(/unknown cmr review leg slug/i);

    expect(
      resolveRouteModels("normal", {}, { cmrReview: ["gpt-5.6-sol", "agy"] })
        .legCollections.cmrReview,
    ).toEqual([
      { family: "codex", slug: "gpt-5.6-sol" },
      { family: "agy", slug: "agy" },
    ]);
  });

  it("feeds the resolved route into every worker spec model slot", async () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "claude-tight");
    vi.resetModules();

    const { stepSpecsForEnv } = await import("../../src/runner.js");
    const { cmrWorkerSpec, familyShipWorkerSpec } = await import(
      "../../src/family/dispatchFamilyWorker.js"
    );
    const { mergerModel } = await import("../../src/family/realFamilyBackend.js");

    const stepSpecs = stepSpecsForEnv();
    expect(stepSpecs.S2.model).toBe("grok-4.5");
    expect(stepSpecs.S3.model).toBe("gpt-5.6-sol");
    expect(stepSpecs.S5.model).toBe("grok-4.5");
    expect(stepSpecs.S6.model).toBe("gpt-5.6-sol");
    expect(cmrWorkerSpec("fresh", "completeness").model).toBe("gpt-5.6-sol");
    expect(cmrWorkerSpec("fresh", "correctness").model).toBe("gpt-5.6-sol");
    expect(familyShipWorkerSpec().model).toBe("gpt-5.6-sol-low");
    expect(mergerModel()).toBe("gpt-5.6-sol-low");
  });

  it("dispatches worker specs from the per-run route, not the route at module import time", async () => {
    vi.unstubAllEnvs();
    vi.resetModules();
    const { runOrchestrator } = await import("../../src/runner.js");
    vi.stubEnv("ORCHESTRATOR_ROUTE", "claude-tight");

    class RecordingBackend implements Backend {
  async smokeModelRoute(route: any) {
    const { smokeRouteModels } = await import("../../src/modelRoutes.js");
    return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
  }
      readonly specs: WorkerSpec[] = [];
      async findResumeState(): Promise<undefined> {
        return undefined;
      }
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
        if ((spec.kind === "reviewer" || spec.kind === "verify")) {
          return { kind: "completed", output: { kind: "judge", status: "converged" } };
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
      async writeLedger(): Promise<void> {}
    }

    const backend = new RecordingBackend();
    const result = await runOrchestrator({ issueNumber: 422, backend });

    expect(result.status).toBe("success");
    expect(backend.specs.filter((spec) => spec.id === "S2").map((spec) => spec.model)).toEqual([
      "grok-4.5",
    ]);
  });

  it("turns tight-route violations into a structured non-interactive stop decision", () => {
    const route = resolveRouteModels("claude-tight", { verify: "opus" });

    const decision = applyTightRoutePolicy(route, { interactive: false });

    expect(decision.kind).toBe("stop");
    if (decision.kind === "stop") {
      expect(decision.escalation.reason).toMatch(/tight route violation/i);
      expect(decision.escalation.diagnosis).toContain("verify=opus(claude)");
    }
  });

  it("lets the interactive policy seam warn and continue only on explicit confirmation", () => {
    const route = resolveRouteModels("claude-tight", { verify: "opus" });
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
    expect(warnings.some((message) => message.includes("verify=opus(claude)"))).toBe(true);
  });

  it("runtime tight-route policy accepts an async interactive confirmation seam", async () => {
    const route = resolveRouteModels("claude-tight", { verify: "opus" });
    const decision = await applyRuntimeTightRoutePolicy(route, {
      interactive: true,
      confirm: async () => true,
    });

    expect(decision.kind).toBe("continue");
  });

  it("runner startup returns a structured non-interactive escalate before backend work", async () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "claude-tight");
    vi.stubEnv("ORCHESTRATOR_VERIFY_MODEL", "opus");
    vi.resetModules();

    class BackendShouldNotRun implements Backend {
  async smokeModelRoute(route: any) {
    const { smokeRouteModels } = await import("../../src/modelRoutes.js");
    return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
  }
      async findResumeState(): Promise<undefined> {
        throw new Error("backend should not run");
      }
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
      async writeLedger(): Promise<void> {}
    }

    const { runOrchestrator } = await import("../../src/runner.js");
    const result = await runOrchestrator({
      issueNumber: 422,
      backend: new BackendShouldNotRun(),
    });

    expect(result.status).toBe("escalate");
    expect(result.errorPackage?.failedStep).toBe("S0");
    expect(result.errorPackage?.reason).toContain("verify=opus(claude)");
  });

  it("family runner startup returns a structured non-interactive escalation before backend work", async () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "claude-tight");
    vi.stubEnv("ORCHESTRATOR_VERIFY_MODEL", "opus");
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

    const { runFamily } = await import("../../src/family/runner.js");
    const result = await runFamily({
      epic: { issue: 376, children: [{ issue: 428, blockedBy: [] }] },
      familyBackend,
      singleSliceBackend,
      familyBase: "family/376-base",
    });

    expect(result.status).toBe("escalated");
    expect(result.familyBase).toBe("family/376-base");
    expect(result.escalation?.reason).toMatch(/tight route violation/i);
    expect(result.escalation?.diagnosis).toContain("verify=opus(claude)");
    expect(result.children).toEqual([{ issue: 428, status: "skipped" }]);
  });
});
