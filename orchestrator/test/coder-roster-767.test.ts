/**
 * #767 — design-time Coder-Rec roster lookup.
 *
 * Seams under test:
 *   1. parseCoderRec(issueBody) — read the designer marking line
 *   2. resolveCoderRecOrder — roster-valid fallback order (or default)
 *   3. selectCoderRecEntry — advance after N non-converging review rounds
 *   4. poolSeparationViolation — coder roster entry must not double as a reviewer leg
 *   5. applyCoderRecToRoute / runner dispatch — first valid entry on S2, advance on S5
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  CODER_REC_FALLBACK_AFTER_ROUNDS,
  CODER_ROSTER,
  CODER_ROSTER_VERSION,
  DEFAULT_CODER_REC_ORDER,
  lookupCoderRosterEntry,
  parseCoderRec,
  poolSeparationViolation,
  resolveCoderRecOrder,
  selectCoderRecEntry,
} from "../src/coderRoster.js";
import {
  applyCoderRecToRoute,
  resolveRouteModels,
} from "../src/modelRoutes.js";
import { runOrchestrator } from "../src/runner.js";
import type {
  Backend,
  IssueMeta,
  IssueSnapshot,
  PersistentLedgerEntry,
  StepOutput,
  StepSpec,
  WorktreeHandle,
} from "../src/types.js";

describe("#767 Coder-Rec roster — parse", () => {
  it("parses a Coder-Rec fallback order line from the issue body", () => {
    const body = [
      "## Scope",
      "Do the thing.",
      "",
      "Coder-Rec: grok-4.5 → terra@med → luna@med",
      "",
      "## Acceptance",
      "- green tests",
    ].join("\n");

    expect(parseCoderRec(body)).toEqual([
      "grok-4.5",
      "terra@med",
      "luna@med",
    ]);
  });

  it("returns undefined when the issue body has no Coder-Rec line", () => {
    expect(parseCoderRec("## Scope\nNo marking here.\n")).toBeUndefined();
  });

  it("tolerates ASCII arrows, commas, and extra whitespace", () => {
    expect(parseCoderRec("Coder-Rec:  grok-4.5 -> terra@med, luna@med  ")).toEqual([
      "grok-4.5",
      "terra@med",
      "luna@med",
    ]);
  });
});

describe("#767 Coder-Rec roster — table + resolve order", () => {
  it("ships a versioned roster covering the ratified coder pool", () => {
    expect(CODER_ROSTER_VERSION).toMatch(/^\d{4}-\d{2}-\d{2}/);
    expect(CODER_ROSTER.map((e) => e.id)).toEqual(
      expect.arrayContaining(["grok-4.5", "terra@med", "luna@med", "sonnet-5"]),
    );
    expect(lookupCoderRosterEntry("terra@med+fast")?.id).toBe("terra@med");
    expect(lookupCoderRosterEntry("Sonnet 5")?.slug).toBe("sonnet");
  });

  it("keeps only roster-valid entries from a Coder-Rec line", () => {
    const order = resolveCoderRecOrder(
      "Coder-Rec: grok-4.5 → not-a-model → terra@med → luna@med",
    );
    expect(order.map((e) => e.id)).toEqual([
      "grok-4.5",
      "terra@med",
      "luna@med",
    ]);
  });

  it("falls back to the roster default order when the marking is absent", () => {
    const order = resolveCoderRecOrder("## Scope\nnothing\n");
    expect(order.map((e) => e.id)).toEqual([...DEFAULT_CODER_REC_ORDER]);
  });
});

describe("#767 Coder-Rec roster — fallback after non-converging rounds", () => {
  it("dispatches the first roster-valid entry before the fallback threshold", () => {
    const order = resolveCoderRecOrder(
      "Coder-Rec: grok-4.5 → terra@med → luna@med",
    );
    expect(selectCoderRecEntry(order, 0).id).toBe("grok-4.5");
    expect(selectCoderRecEntry(order, CODER_REC_FALLBACK_AFTER_ROUNDS - 1).id).toBe(
      "grok-4.5",
    );
  });

  it("advances to the next entry once the review loop burns the threshold rounds", () => {
    const order = resolveCoderRecOrder(
      "Coder-Rec: grok-4.5 → terra@med → luna@med",
    );
    expect(selectCoderRecEntry(order, CODER_REC_FALLBACK_AFTER_ROUNDS).id).toBe(
      "terra@med",
    );
    expect(selectCoderRecEntry(order, CODER_REC_FALLBACK_AFTER_ROUNDS * 2).id).toBe(
      "luna@med",
    );
    // Past the end: stay on the last entry (no wrap inventing new coders).
    expect(
      selectCoderRecEntry(order, CODER_REC_FALLBACK_AFTER_ROUNDS * 99).id,
    ).toBe("luna@med");
  });
});

describe("#767 Coder-Rec roster — pool separation", () => {
  it("flags a coder roster entry that doubles as an active reviewer leg", () => {
    const terra = lookupCoderRosterEntry("terra@med");
    expect(terra).toBeDefined();
    expect(
      poolSeparationViolation(terra!, ["gpt-5.6-sol", "gpt-5.6-terra"]),
    ).toMatch(/must not double as.*reviewer/i);
  });

  it("allows a coder whose slug is not among the active reviewer legs", () => {
    const grok = lookupCoderRosterEntry("grok-4.5");
    expect(grok).toBeDefined();
    expect(
      poolSeparationViolation(grok!, ["gpt-5.6-sol", "opus", "agy"]),
    ).toBeUndefined();
  });

  it("skips colliding entries when selecting, preferring the next roster-valid coder", () => {
    const order = resolveCoderRecOrder(
      "Coder-Rec: terra@med → grok-4.5 → luna@med",
    );
    const selected = selectCoderRecEntry(order, 0, {
      reviewerSlugs: ["gpt-5.6-terra", "gpt-5.6-sol"],
    });
    // terra@med doubles as reviewer → skip to grok-4.5
    expect(selected.id).toBe("grok-4.5");
  });
});

describe("#767 Coder-Rec — applyCoderRecToRoute dispatch wiring", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("overrides coder + coderFix to the first roster-valid Coder-Rec entry", () => {
    const base = resolveRouteModels("normal", {});
    const applied = applyCoderRecToRoute(
      base,
      "Coder-Rec: grok-4.5 → terra@med → luna@med",
      0,
      {},
    );
    expect(applied.skippedForEnvOverride).toBe(false);
    expect(applied.entry?.id).toBe("grok-4.5");
    expect(applied.route.slots.coder).toBe("grok-4.5");
    expect(applied.route.slots.coderFix).toBe("grok-4.5");
    // Reviewer legs untouched.
    expect(applied.route.slots.reviewer).toBe(base.slots.reviewer);
  });

  it("advances the route coder after the fallback threshold of non-converging rounds", () => {
    const base = resolveRouteModels("normal", {});
    const applied = applyCoderRecToRoute(
      base,
      "Coder-Rec: grok-4.5 → terra@med → luna@med",
      CODER_REC_FALLBACK_AFTER_ROUNDS,
      {},
    );
    expect(applied.entry?.id).toBe("terra@med");
    expect(applied.route.slots.coder).toBe("gpt-5.6-terra");
  });

  it("leaves the route coder untouched when the issue has no Coder-Rec line", () => {
    const base = resolveRouteModels("normal", {});
    const applied = applyCoderRecToRoute(base, "## Scope\nnothing\n", 0, {});
    expect(applied.skippedForMissingMarking).toBe(true);
    expect(applied.route.slots.coder).toBe(base.slots.coder);
  });

  it("lets ORCHESTRATOR_CODER_MODEL win over the design-time marking", () => {
    const base = resolveRouteModels("normal", { coder: "sonnet" });
    const applied = applyCoderRecToRoute(
      base,
      "Coder-Rec: grok-4.5 → terra@med",
      0,
      { ORCHESTRATOR_CODER_MODEL: "opus" },
    );
    expect(applied.skippedForEnvOverride).toBe(true);
    expect(applied.route.slots.coder).toBe("sonnet");
  });
});

describe("#767 Coder-Rec — runner dispatches the selected coder model", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  class CoderRecBackend implements Backend {
    async smokeModelRoute(route: any) {
      const { smokeRouteModels } = await import("../src/modelRoutes.js");
      return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
    }
    readonly coderModels: string[] = [];
    readonly worktree: WorktreeHandle = {
      branch: "feat/767-coder-roster",
      base: "main",
      path: "/resident/worktrees/issue-767",
    };

    async findResumeState(): Promise<undefined> {
      return undefined;
    }
    async cleanResidue(): Promise<void> {}
    async resumeSession(spec: StepSpec): Promise<StepOutput> {
      return this.runStep(spec);
    }
    async fetchIssueMeta(issueNumber: number): Promise<IssueMeta> {
      return {
        number: issueNumber,
        isReadyForAgent: true,
        hasSubIssues: false,
        isClosed: false,
        openBlockedBy: [],
        body: "Coder-Rec: grok-4.5 → terra@med → luna@med\n",
      };
    }
    async fetchIssueSnapshot(issueNumber: number): Promise<IssueSnapshot> {
      return {
        number: issueNumber,
        body: "Coder-Rec: grok-4.5 → terra@med → luna@med\n",
        comments: [],
        agentBrief: "",
      };
    }
    async prepareWorktree(): Promise<WorktreeHandle> {
      return this.worktree;
    }
    async writeSnapshot(): Promise<void> {}
    async runStep(spec: StepSpec): Promise<StepOutput> {
      if (spec.role === "coder") {
        this.coderModels.push(spec.model);
      }
      if (spec.role === "reviewer") {
        return { kind: "reviewer", findings: [] };
      }
      return { kind: "coder", committed: true, commitsAdded: 1 };
    }
    async push(): Promise<void> {}
    async writeLedger(_e: PersistentLedgerEntry): Promise<void> {}
  }

  it("S2 dispatches the first roster-valid Coder-Rec entry from the issue body", async () => {
    vi.stubEnv("ORCHESTRATOR_CODER_MODEL", "");
    const backend = new CoderRecBackend();
    const result = await runOrchestrator({ issueNumber: 767, backend });
    expect(result.status).toBe("success");
    expect(backend.coderModels).toEqual(["grok-4.5"]);
  });
});
