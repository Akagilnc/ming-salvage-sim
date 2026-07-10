/**
 * #767 — design-time Coder-Rec roster lookup.
 *
 * Seams under test:
 *   1. parseCoderRec(issueBody) — read the designer marking line
 *   2. resolveCoderRecOrder — roster-valid fallback order (or default)
 *   3. selectCoderRecEntry — advance after N non-converging review rounds
 *   4. poolSeparationViolation — coder roster entry must not double as a reviewer leg
 *   5. applyCoderRecToRoute / runner dispatch — first valid entry on S2, advance on S5
 *   6. reviewerSlugsFromRoute — includes CMR gate slots (completeness/correctness/verify)
 *   7. runner mid-loop advance — re-smoke before first dispatch of advanced slug
 *   8. runner ledger wiring — 2 completed S6 rounds advance the DISPATCHED coder
 *   9. resume re-fetches issue body so Coder-Rec (+ advance position) survives
 *  10. S0 smokes the final Coder-Rec route once (not preset-then-override)
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
  reviewerSlugsFromRoute,
  selectCoderRecEntry,
} from "../src/coderRoster.js";
import {
  applyCoderRecToRoute,
  resolveRouteModels,
} from "../src/modelRoutes.js";
import { runOrchestrator } from "../src/runner.js";
import { findingIdentityKey } from "../src/findings.js";
import type {
  Backend,
  Finding,
  IssueMeta,
  IssueSnapshot,
  PersistentLedgerEntry,
  ResumeState,
  StepId,
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

  it("parses Markdown-bulleted Coder-Rec lines", () => {
    expect(
      parseCoderRec("- Coder-Rec: grok-4.5 → terra@med → luna@med\n"),
    ).toEqual(["grok-4.5", "terra@med", "luna@med"]);
    expect(
      parseCoderRec("* Coder-Rec: grok-4.5 → terra@med\n"),
    ).toEqual(["grok-4.5", "terra@med"]);
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

  it("logs a one-line diagnostic when invalid tokens are dropped", () => {
    const info = vi.spyOn(console, "info").mockImplementation(() => {});
    const order = resolveCoderRecOrder(
      "Coder-Rec: grok-4.5 → not-a-model → terra@med",
    );
    expect(order.map((e) => e.id)).toEqual(["grok-4.5", "terra@med"]);
    expect(info).toHaveBeenCalledWith(
      expect.stringMatching(/dropped.*not-a-model|invalid Coder-Rec/i),
    );
    info.mockRestore();
  });

  it("logs a one-line diagnostic when the whole line degrades to the default order", () => {
    const info = vi.spyOn(console, "info").mockImplementation(() => {});
    const order = resolveCoderRecOrder("Coder-Rec: totally-bogus → also-fake");
    expect(order.map((e) => e.id)).toEqual([...DEFAULT_CODER_REC_ORDER]);
    expect(info).toHaveBeenCalledWith(
      expect.stringMatching(/degrad|default order|all.?invalid/i),
    );
    info.mockRestore();
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

  it("collects cmrCompleteness / cmrCorrectness / verify gate slots as reviewer pool slugs", () => {
    const route = resolveRouteModels("normal", {
      cmrCompleteness: "opus",
      cmrCorrectness: "grok-4.5",
      verify: "gpt-5.6-luna",
    });
    const slugs = reviewerSlugsFromRoute(route);
    expect(slugs).toEqual(
      expect.arrayContaining([
        route.slots.reviewer,
        "opus",
        "grok-4.5",
        "gpt-5.6-luna",
        ...route.legCollections.cmrReview.map((leg) => leg.slug),
      ]),
    );
  });

  it("filters a roster entry whose slug equals the cmrCorrectness gate slot", () => {
    const base = resolveRouteModels("normal", {
      cmrCorrectness: "grok-4.5",
    });
    const applied = applyCoderRecToRoute(
      base,
      "Coder-Rec: grok-4.5 → terra@med → luna@med",
      0,
      {},
    );
    expect(applied.entry?.id).toBe("terra@med");
    expect(applied.route.slots.coder).toBe("gpt-5.6-terra");
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

  const CODER_REC_BODY =
    "Coder-Rec: grok-4.5 → terra@med → luna@med\n";

  const blockingFinding: Finding = {
    severity: "high",
    category: "Correctness",
    claim_quote: "must fix before shipping",
    location: "src/coderRoster.ts:1",
    suggested_fix: "fix it",
    action: "fix_now",
  };
  const blockingKey = findingIdentityKey(blockingFinding);

  function ledgerEntry(
    step: StepId,
    output?: StepOutput,
  ): PersistentLedgerEntry {
    return {
      step,
      sessionId: "session-prior",
      prompt_hash: `hash-${step}`,
      branchHEAD: "deadbeefcommitsha",
      ts: "2026-07-10T00:00:00.000Z",
      ...(output !== undefined ? { output } : {}),
    };
  }

  class CoderRecBackend implements Backend {
    async smokeModelRoute(route: any) {
      this.smokedCoderSlugs.push(route.slots.coder);
      this.events.push(`smoke:${route.slots.coder}`);
      const { smokeRouteModels } = await import("../src/modelRoutes.js");
      return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
    }
    readonly coderModels: string[] = [];
    readonly smokedCoderSlugs: string[] = [];
    readonly events: string[] = [];
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
        body: CODER_REC_BODY,
      };
    }
    async fetchIssueSnapshot(issueNumber: number): Promise<IssueSnapshot> {
      return {
        number: issueNumber,
        body: CODER_REC_BODY,
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
        this.events.push(`dispatch:${spec.model}`);
      }
      if (spec.role === "reviewer") {
        return { kind: "reviewer", findings: [] };
      }
      return { kind: "coder", committed: true, commitsAdded: 1 };
    }
    async push(): Promise<void> {}
    async writeLedger(_e: PersistentLedgerEntry): Promise<void> {}
  }

  /** Drives S3 + two S6 rounds with still-active findings, then a clean S6. */
  class CoderRecAdvanceBackend extends CoderRecBackend {
    private reviewerAttempts = 0;
    readonly ledgerWrites: PersistentLedgerEntry[] = [];

    override async writeLedger(entry: PersistentLedgerEntry): Promise<void> {
      this.ledgerWrites.push(entry);
    }

    override async runStep(spec: StepSpec): Promise<StepOutput> {
      if (spec.role === "coder") {
        this.coderModels.push(spec.model);
        this.events.push(`dispatch:${spec.model}`);
        return { kind: "coder", committed: true, commitsAdded: 1 };
      }
      if (spec.role === "reviewer") {
        const attempt = this.reviewerAttempts;
        this.reviewerAttempts += 1;
        // S3: initial blocking. S6#1: still-active. S6#2: severity drop
        // (reviewer-observed progress) so the no-progress bound does not fire
        // before the post-threshold S5 advance. S6#3: close.
        if (attempt === 0) {
          return { kind: "reviewer", findings: [blockingFinding] };
        }
        if (attempt === 1) {
          return {
            kind: "reviewer",
            findings: [blockingFinding],
            priorFindingDispositions: [
              { identityKey: blockingKey, status: "still-active" },
            ],
          };
        }
        if (attempt === 2) {
          return {
            kind: "reviewer",
            findings: [{ ...blockingFinding, severity: "medium" }],
            priorFindingDispositions: [
              { identityKey: blockingKey, status: "still-active" },
            ],
          };
        }
        return {
          kind: "reviewer",
          findings: [],
          priorFindingDispositions: [
            { identityKey: blockingKey, status: "verified-closed" },
          ],
        };
      }
      return { kind: "coder", committed: true, commitsAdded: 1 };
    }
  }

  /**
   * Crash after S5 with 2 completed S6 rounds already on the ledger, then
   * resume into the next S5. Without a resume-path body re-fetch, Coder-Rec
   * is undefined → skippedForMissingMarking → preset coder (sonnet).
   */
  class CoderRecResumeAfterS5Backend extends CoderRecBackend {
    override async findResumeState(): Promise<ResumeState> {
      const mediumBlocking = { ...blockingFinding, severity: "medium" as const };
      return {
        worktree: this.worktree,
        stateDir: "/resident/ledgers/issue-767",
        ledger: [
          ledgerEntry("S0"),
          ledgerEntry("S1"),
          ledgerEntry("S2", {
            kind: "coder",
            committed: true,
            commitsAdded: 1,
          }),
          ledgerEntry("S3", {
            kind: "reviewer",
            findings: [blockingFinding],
          }),
          ledgerEntry("S4"),
          ledgerEntry("S5", {
            kind: "coder",
            committed: true,
            commitsAdded: 1,
          }),
          ledgerEntry("S6", {
            kind: "reviewer",
            findings: [blockingFinding],
            priorFindingDispositions: [
              { identityKey: blockingKey, status: "still-active" },
            ],
          }),
          ledgerEntry("S4"),
          ledgerEntry("S5", {
            kind: "coder",
            committed: true,
            commitsAdded: 1,
          }),
          ledgerEntry("S6", {
            kind: "reviewer",
            findings: [mediumBlocking],
            priorFindingDispositions: [
              { identityKey: blockingKey, status: "still-active" },
            ],
          }),
          // Crash after the post-threshold S5 was about to run: last durable
          // boundary is S4 with blocking still open → planResume → S5.
          ledgerEntry("S4"),
        ],
      };
    }

    override async runStep(spec: StepSpec): Promise<StepOutput> {
      if (spec.role === "coder") {
        this.coderModels.push(spec.model);
        this.events.push(`dispatch:${spec.model}`);
        return { kind: "coder", committed: true, commitsAdded: 1 };
      }
      if (spec.role === "reviewer") {
        return {
          kind: "reviewer",
          findings: [],
          priorFindingDispositions: [
            { identityKey: blockingKey, status: "verified-closed" },
          ],
        };
      }
      return { kind: "coder", committed: true, commitsAdded: 1 };
    }
  }

  it("S2 dispatches the first roster-valid Coder-Rec entry from the issue body", async () => {
    vi.stubEnv("ORCHESTRATOR_CODER_MODEL", "");
    const backend = new CoderRecBackend();
    const result = await runOrchestrator({ issueNumber: 767, backend });
    expect(result.status).toBe("success");
    expect(backend.coderModels).toEqual(["grok-4.5"]);
  });

  it("S0 smokes the Coder-Rec final route once, not the preset then the override", async () => {
    vi.stubEnv("ORCHESTRATOR_CODER_MODEL", "");
    const backend = new CoderRecBackend();
    const result = await runOrchestrator({ issueNumber: 767, backend });
    expect(result.status).toBe("success");
    // First smoke must already see the Coder-Rec coder — not the route preset
    // (sonnet) that would force a full re-smoke after applyCoderRecSelection.
    expect(backend.smokedCoderSlugs[0]).toBe("grok-4.5");
    expect(backend.smokedCoderSlugs).not.toContain("sonnet");
    const firstDispatch = backend.events.findIndex((e) =>
      e.startsWith("dispatch:"),
    );
    const smokesBeforeDispatch = backend.events
      .slice(0, firstDispatch)
      .filter((e) => e.startsWith("smoke:"));
    expect(smokesBeforeDispatch).toEqual(["smoke:grok-4.5"]);
  });

  it("resume after S5 keeps the Coder-Rec entry at the ledger advance position", async () => {
    vi.stubEnv("ORCHESTRATOR_CODER_MODEL", "");
    const backend = new CoderRecResumeAfterS5Backend();
    const result = await runOrchestrator({ issueNumber: 767, backend });
    expect(result.status).toBe("success");
    // 2 completed S6 rounds on the restored ledger → advance to terra@med,
    // not the route preset (sonnet) and not the first Coder-Rec entry.
    expect(backend.coderModels[0]).toBe("gpt-5.6-terra");
    expect(backend.coderModels).not.toContain("sonnet");
  });

  it("re-smokes the advanced coder slug before its first mid-loop S5 dispatch", async () => {
    vi.stubEnv("ORCHESTRATOR_CODER_MODEL", "");
    const backend = new CoderRecAdvanceBackend();
    const result = await runOrchestrator({ issueNumber: 767, backend });
    expect(result.status).toBe("success");
    const terraSmokeAt = backend.events.indexOf("smoke:gpt-5.6-terra");
    const terraDispatchAt = backend.events.indexOf("dispatch:gpt-5.6-terra");
    expect(terraSmokeAt).toBeGreaterThanOrEqual(0);
    expect(terraDispatchAt).toBeGreaterThanOrEqual(0);
    expect(terraSmokeAt).toBeLessThan(terraDispatchAt);
  });

  it("advances the DISPATCHED coder after 2 completed S6 rounds via ledger wiring", async () => {
    vi.stubEnv("ORCHESTRATOR_CODER_MODEL", "");
    const backend = new CoderRecAdvanceBackend();
    const result = await runOrchestrator({ issueNumber: 767, backend });
    expect(result.status).toBe("success");

    const s6Count = backend.ledgerWrites.filter((e) => e.step === "S6").length;
    expect(s6Count).toBeGreaterThanOrEqual(CODER_REC_FALLBACK_AFTER_ROUNDS);

    // S2 + S5×2 stay on grok; the S5 after 2 S6 rounds advances to terra.
    expect(backend.coderModels[0]).toBe("grok-4.5");
    expect(
      backend.coderModels.filter((m) => m === "grok-4.5").length,
    ).toBeGreaterThanOrEqual(1 + CODER_REC_FALLBACK_AFTER_ROUNDS);
    expect(backend.coderModels).toContain("gpt-5.6-terra");
    const firstTerra = backend.coderModels.indexOf("gpt-5.6-terra");
    expect(firstTerra).toBe(1 + CODER_REC_FALLBACK_AFTER_ROUNDS);
  });
});
