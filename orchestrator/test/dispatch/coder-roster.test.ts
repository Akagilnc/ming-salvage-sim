/**
 * #767 — design-time Coder-Rec roster lookup.
 * #920 — pool isolation removed: same model may occupy coder + review/CMR seats.
 * ADR 0132 / #919 CR — round-threshold selection deleted (first seat stay-put).
 *
 * Seams under test:
 *   1. parseCoderRec(issueBody) — read the designer marking line
 *   2. resolveCoderRecOrder — roster-valid fallback order (or default)
 *   3. selectCoderRecEntry — first seat only (no rounds argument)
 *   4. #920 pool isolation gone — no review-slot conflict filter / exhaust throw
 *   5. applyCoderRecToRoute / runner dispatch — first valid entry sticky
 *   6. runner mid-loop — no model rotation / re-smoke after N S6 rounds
 *   7. resume re-fetches issue body so first-seat Coder-Rec survives
 *   8. S0 smokes the final Coder-Rec route once (not preset-then-override)
 *   9. resume Coder-Rec re-fetch degrades safely (meta throw → snapshot;
 *      both throw → route preset + diagnostic, no error termination)
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  CODER_ROSTER,
  CODER_ROSTER_VERSION,
  CoderRecError,
  DEFAULT_CODER_REC_ORDER,
  lookupCoderRosterEntry,
  parseCoderRec,
  resolveCoderRecOrder,
  selectCoderRecEntry,
} from "../../src/coderRoster.js";
import {
  applyCoderRecToRoute,
  resolveRouteModels,
} from "../../src/modelRoutes.js";
import { runOrchestrator } from "../../src/runner.js";
import { findingIdentityKey } from "../../src/findings.js";
import type {
  Backend,
  Finding,
  IssueMeta,
  PersistentLedgerEntry,
  ResumeState,
  SliceStepId,
  StepId,
  StepOutput,
  StepSpec,
  WorktreeHandle,
} from "../../src/types.js";

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

describe("#906 Coder-Rec — markdown parse + fail-closed", () => {
  it("parses bold-wrapped Coder-Rec (#899 accident fixture)", () => {
    // Machine treated markdown bold as "no marking" and silently fell to route
    // default coder. After #906 the stripped text must yield the legal order.
    expect(
      parseCoderRec("- **Coder-Rec: grok-4.5 → sol@med**\n"),
    ).toEqual(["grok-4.5", "sol@med"]);
  });

  it("parses inline-code and linked Coder-Rec lines", () => {
    expect(
      parseCoderRec("- `Coder-Rec: grok-4.5 → terra@med`\n"),
    ).toEqual(["grok-4.5", "terra@med"]);
    expect(
      parseCoderRec(
        "[Coder-Rec: grok-4.5 → luna@med](https://example.com/roster)\n",
      ),
    ).toEqual(["grok-4.5", "luna@med"]);
  });

  it("fail-closes when stripped text still has a broken Coder-Rec mark", () => {
    expect(() => parseCoderRec("Please set Coder-Rec carefully.\n")).toThrow(
      CoderRecError,
    );
    expect(() => parseCoderRec("Coder-Rec:   \n")).toThrow(/Coder-Rec/i);
    expect(() => parseCoderRec("- **Coder-Rec** alone\n")).toThrow(
      /could not be parsed|no model token/i,
    );
  });

  it("N4: broken-mark presence probe is case-insensitive (matches line /i)", () => {
    // Line match is /i; presence probe must not miss alternate casing and
    // silently treat a broken mark as "absent" (would weaken #906 fail-closed).
    expect(() => parseCoderRec("Please set coder-rec carefully.\n")).toThrow(
      CoderRecError,
    );
    expect(() => parseCoderRec("CODER-REC alone without tokens\n")).toThrow(
      /could not be parsed|Coder-Rec/i,
    );
    // Legal line with alternate casing still parses (line regex already /i).
    expect(parseCoderRec("coder-rec: grok-4.5 → terra@med\n")).toEqual([
      "grok-4.5",
      "terra@med",
    ]);
  });

  it("B2: parses Coder-Rec from a GFM table cell (tableCell toString)", () => {
    // Without tableCell extraction, presence only sees plain lines → silent
    // default roster while the designer mark is clearly in the issue body.
    const body = [
      "| Field | Value |",
      "| --- | --- |",
      "| roster | Coder-Rec: grok-4.5 → terra@med |",
      "",
    ].join("\n");
    expect(parseCoderRec(body)).toEqual(["grok-4.5", "terra@med"]);
    expect(resolveCoderRecOrder(body).map((e) => e.id)).toEqual([
      "grok-4.5",
      "terra@med",
    ]);
  });

  it("B2: fail-closed when Coder-Rec mark is only in raw HTML (AST miss)", () => {
    // raw HTML is not walked into plain lines; raw-body presence must still
    // fail-closed rather than treat the mark as absent.
    expect(() => parseCoderRec("<div>Coder-Rec carefully broken</div>\n")).toThrow(
      CoderRecError,
    );
  });

  it("errors on unregistered model tokens and lists legal roster ids", () => {
    expect(() =>
      resolveCoderRecOrder(
        "Coder-Rec: grok-4.5 → not-a-model → terra@med",
      ),
    ).toThrow(CoderRecError);
    try {
      resolveCoderRecOrder("Coder-Rec: totally-bogus → also-fake");
      expect.unreachable("expected unregistered tokens to throw");
    } catch (err) {
      expect(err).toBeInstanceOf(CoderRecError);
      const message = (err as Error).message;
      expect(message).toMatch(/unregistered|unknown|not.?registered|invalid/i);
      expect(message).toMatch(/totally-bogus/);
      for (const id of CODER_ROSTER.map((e) => e.id)) {
        expect(message).toContain(id);
      }
    }
  });

  it("keeps route preset when the body has no Coder-Rec mark at all", () => {
    expect(parseCoderRec("## Scope\nNo marking here.\n")).toBeUndefined();
    const base = resolveRouteModels("normal", {});
    const applied = applyCoderRecToRoute(
      base,
      "## Scope\nNo marking here.\n",
    );
    expect(applied.skippedForMissingMarking).toBe(true);
    expect(applied.route.slots.coder).toBe(base.slots.coder);
    expect(applied.entry).toBeUndefined();
  });
});

describe("#767 Coder-Rec roster — table + resolve order", () => {
  it("ships a versioned roster covering the ratified coder pool", () => {
    expect(CODER_ROSTER_VERSION).toMatch(/^\d{4}-\d{2}-\d{2}/);
    expect(CODER_ROSTER.map((e) => e.id)).toEqual(
      expect.arrayContaining([
        "grok-4.5",
        "terra@med",
        "luna@med",
        "sol@med",
        "sonnet-5",
        "haiku-4.5",
      ]),
    );
    expect(lookupCoderRosterEntry("terra@med+fast")?.id).toBe("terra@med");
    expect(lookupCoderRosterEntry("Sonnet 5")?.slug).toBe("sonnet");
    expect(lookupCoderRosterEntry("Haiku 4.5")?.slug).toBe("haiku");
    expect(lookupCoderRosterEntry("haiku")?.id).toBe("haiku-4.5");
  });

  it("accepts sol@med as a difficult-slice convergence fallback", () => {
    const sol = lookupCoderRosterEntry("sol@med");
    expect(sol).toMatchObject({
      id: "sol@med",
      slug: "gpt-5.6-sol",
      pool: "codex",
    });
    expect(lookupCoderRosterEntry("gpt-5.6-sol")?.id).toBe("sol@med");
    expect(
      resolveCoderRecOrder("Coder-Rec: terra@med → sol@med").map((e) => e.id),
    ).toEqual(["terra@med", "sol@med"]);
  });

  it("falls back to the roster default order when the marking is absent", () => {
    const order = resolveCoderRecOrder("## Scope\nnothing\n");
    expect(order.map((e) => e.id)).toEqual([...DEFAULT_CODER_REC_ORDER]);
  });
});

describe("#767 Coder-Rec roster — first seat stay-put (ADR 0132 / #919 CR)", () => {
  it("selectCoderRecEntry returns only the first roster-valid entry", () => {
    const order = resolveCoderRecOrder(
      "Coder-Rec: grok-4.5 → terra@med → luna@med",
    );
    expect(selectCoderRecEntry(order).id).toBe("grok-4.5");
    // Order length must not rotate selection — first seat only.
    expect(order.map((e) => e.id)).toEqual([
      "grok-4.5",
      "terra@med",
      "luna@med",
    ]);
    expect(selectCoderRecEntry(order).id).toBe("grok-4.5");
  });
});

describe("#920 pool isolation removed — same model across roles is legal", () => {
  it("selects the top roster entry even when its slug shares review / CMR seats", () => {
    const order = resolveCoderRecOrder(
      "Coder-Rec: terra@med → grok-4.5 → luna@med",
    );
    // Pre-#920 this skipped terra because gpt-5.6-terra was treated as a
    // reviewer conflict; isolation is gone so the marked top entry wins.
    expect(selectCoderRecEntry(order).id).toBe("terra@med");
  });

  it("admits Sol as Coder-Rec even when sol occupies review and CMR seats", () => {
    for (const routeName of ["normal", "codex-cheap"] as const) {
      const base = resolveRouteModels(routeName, {});
      const applied = applyCoderRecToRoute(base, "Coder-Rec: sol@med");
      expect(applied.entry?.id).toBe("sol@med");
      expect(applied.route.slots.coder).toBe("gpt-5.6-sol");
      // #899 run8 / AC: cmrReview leg may keep the same slug as coder.
      expect(
        applied.route.legCollections.cmrReview.map((leg) => leg.slug),
      ).toContain("gpt-5.6-sol");
    }
  });

  it("never throws a pool-separation exhaustion path on multi-entry collision", () => {
    const order = resolveCoderRecOrder("Coder-Rec: sol@med → terra@med");
    expect(selectCoderRecEntry(order).id).toBe("sol@med");
  });

  it("keeps a single-entry roster on the top seat (never exhausts)", () => {
    const order = resolveCoderRecOrder("Coder-Rec: sol@med");
    expect(order).toHaveLength(1);
    expect(selectCoderRecEntry(order).id).toBe("sol@med");
    const applied = applyCoderRecToRoute(
      resolveRouteModels("normal", {}),
      "Coder-Rec: sol@med",
    );
    expect(applied.entry?.id).toBe("sol@med");
    expect(applied.route.slots.coder).toBe("gpt-5.6-sol");
  });

  it("does not skip a roster entry that equals the cmrCorrectness gate slot", () => {
    const base = resolveRouteModels("normal", {
      cmrCorrectness: "grok-4.5",
    });
    const applied = applyCoderRecToRoute(
      base,
      "Coder-Rec: grok-4.5 → terra@med → luna@med",
    );
    expect(applied.entry?.id).toBe("grok-4.5");
    expect(applied.route.slots.coder).toBe("grok-4.5");
    expect(applied.route.slots.cmrCorrectness).toBe("grok-4.5");
  });

  /**
   * #789 still holds as a roster fact (sonnet/haiku ≠ opus); #920 no longer
   * filters on slug equality — first seat stays put (ADR 0132).
   */
  it("#789 selectCoderRecEntry keeps first Claude backup seat", () => {
    const order = resolveCoderRecOrder(
      "Coder-Rec: grok-4.5 → sonnet-5 → haiku-4.5",
    );
    expect(selectCoderRecEntry(order).id).toBe("grok-4.5");
  });
});

describe("#789 Coder-Rec — Claude backup tokens + fallback chain", () => {
  it("parses and resolves Coder-Rec lines that include sonnet-5 / haiku-4.5", () => {
    const body =
      "Coder-Rec: grok-4.5 → sonnet-5 → haiku-4.5\n";
    expect(parseCoderRec(body)).toEqual([
      "grok-4.5",
      "sonnet-5",
      "haiku-4.5",
    ]);
    expect(resolveCoderRecOrder(body).map((e) => e.id)).toEqual([
      "grok-4.5",
      "sonnet-5",
      "haiku-4.5",
    ]);
  });

  it("accepts haiku aliases and maps them to the haiku-4.5 roster entry", () => {
    expect(lookupCoderRosterEntry("haiku-4.5")?.id).toBe("haiku-4.5");
    expect(lookupCoderRosterEntry("haiku")?.id).toBe("haiku-4.5");
    expect(lookupCoderRosterEntry("Haiku 4.5")?.slug).toBe("haiku");
    const order = resolveCoderRecOrder(
      "Coder-Rec: grok-4.5 → Haiku 4.5 → sonnet",
    );
    expect(order.map((e) => e.id)).toEqual([
      "grok-4.5",
      "haiku-4.5",
      "sonnet-5",
    ]);
  });

  it("Claude backup chain stays on first seat", () => {
    const order = resolveCoderRecOrder(
      "Coder-Rec: grok-4.5 → sonnet-5 → haiku-4.5",
    );
    expect(selectCoderRecEntry(order).id).toBe("grok-4.5");
  });

  it("applyCoderRecToRoute wires first Claude backup slug (sticky)", () => {
    const base = resolveRouteModels("normal", {});
    const first = applyCoderRecToRoute(
      base,
      "Coder-Rec: grok-4.5 → sonnet-5 → haiku-4.5",
    );
    expect(first.entry?.id).toBe("grok-4.5");
    expect(first.route.slots.coder).toBe("grok-4.5");
    expect(first.route.slots.coderFix).toBe("grok-4.5");
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
    );
    expect(applied.entry?.id).toBe("grok-4.5");
    expect(applied.route.slots.coder).toBe("grok-4.5");
    expect(applied.route.slots.coderFix).toBe("grok-4.5");
    // Judge (verify) + CMR legs untouched.
    expect(applied.route.slots.verify).toBe(base.slots.verify);
  });

  it("leaves the route coder untouched when the issue has no Coder-Rec line", () => {
    const base = resolveRouteModels("normal", {});
    const applied = applyCoderRecToRoute(base, "## Scope\nnothing\n");
    expect(applied.skippedForMissingMarking).toBe(true);
    expect(applied.route.slots.coder).toBe(base.slots.coder);
  });

  it("negative: leftover CODER_MODEL env does not skip Coder-Rec (#936)", () => {
    const base = resolveRouteModels("normal", { coder: "sonnet" });
    const applied = applyCoderRecToRoute(
      base,
      "Coder-Rec: grok-4.5 → terra@med",
    );
    // Coder-Rec wins; env override is deleted.
    expect(applied.route.slots.coder).toBe("grok-4.5");
  });

  it("#906 S1: broken Coder-Rec mark fails closed even with leftover env", () => {
    const base = resolveRouteModels("normal", { coder: "sonnet" });
    expect(() =>
      applyCoderRecToRoute(
        base,
        "Coder-Rec: totally-bogus → also-fake",
      ),
    ).toThrow(CoderRecError);
    expect(() =>
      applyCoderRecToRoute(
        base,
        "Please set Coder-Rec carefully.\n",
      ),
    ).toThrow(CoderRecError);
    const applied = applyCoderRecToRoute(
      base,
      "Coder-Rec: grok-4.5 → terra@med",
    );
    expect(applied.route.slots.coder).toBe("grok-4.5");
  });

  it("Coder-Rec rewrites both coder and coderFix (no env preserve path) (#936)", () => {
    const base = resolveRouteModels("normal", { coderFix: "opus" });
    const applied = applyCoderRecToRoute(
      base,
      "Coder-Rec: grok-4.5 → terra@med",
    );

    expect(applied.route.slots.coder).toBe("grok-4.5");
    expect(applied.route.slots.coderFix).toBe("grok-4.5");
  });

  it("recomputes tight-family violations after Coder-Rec substitutes a tight-family coder", () => {
    const base = resolveRouteModels("codex-tight", {});
    expect(base.tightFamilyViolations).toEqual([]);

    const applied = applyCoderRecToRoute(
      base,
      "Coder-Rec: terra@med",
    );

    expect(applied.route.tightFamilyViolations).toEqual([
      { slot: "coder", slug: "gpt-5.6-terra", family: "codex" },
      { slot: "coderFix", slug: "gpt-5.6-terra", family: "codex" },
    ]);
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
    step: SliceStepId,
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
    constructor(private readonly coderRecBody = CODER_REC_BODY) {}

    async smokeModelRoute(route: any) {
      this.smokedCoderSlugs.push(route.slots.coder);
      this.events.push(`smoke:${route.slots.coder}`);
      const { smokeRouteModels } = await import("../../src/modelRoutes.js");
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

    async findResumeState(): Promise<ResumeState | undefined> {
      return undefined;
    }
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
        body: this.coderRecBody,
      };
    }
    async prepareWorktree(): Promise<WorktreeHandle> {
      return this.worktree;
    }
    async runStep(spec: StepSpec): Promise<StepOutput> {
      if (spec.role === "coder") {
        this.coderModels.push(spec.model);
        this.events.push(`dispatch:${spec.model}`);
      }
      if ((spec.role === "reviewer" || spec.role === "verify")) {
        return { kind: "judge", status: "converged" };
      }
      return { kind: "coder", committed: true, commitsAdded: 1 };
    }
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
      if ((spec.role === "reviewer" || spec.role === "verify")) {
        const attempt = this.reviewerAttempts;
        this.reviewerAttempts += 1;
        // S3: initial blocking. S6#1: still-active. S6#2: severity drop
        // (reviewer-observed progress) so the no-progress bound does not fire
        // before the post-threshold S5 advance. S6#3: close.
        if (attempt === 0) {
          return { kind: "reviewer", findings: [blockingFinding], findingsCount: 1, fixPacketBody: "fixture residual authored body" };
        }
        if (attempt === 1) {
          return {
            kind: "reviewer", findings: [blockingFinding], findingsCount: 1, fixPacketBody: "fixture residual authored body",
            priorFindingDispositions: [
              { identityKey: blockingKey, status: "still-active" },
            ],
          };
        }
        if (attempt === 2) {
          return {
            kind: "reviewer", findings: [{ ...blockingFinding, severity: "medium" }], findingsCount: 1, fixPacketBody: "fixture residual authored body",
            priorFindingDispositions: [
              { identityKey: blockingKey, status: "still-active" },
            ],
          };
        }
        return { kind: "judge", status: "converged" };
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
            kind: "reviewer", findings: [blockingFinding], findingsCount: 1, fixPacketBody: "fixture residual authored body",
          }),
          ledgerEntry("S4"),
          ledgerEntry("S5", {
            kind: "coder",
            committed: true,
            commitsAdded: 1,
          }),
          ledgerEntry("S6", {
            kind: "reviewer", findings: [blockingFinding], findingsCount: 1, fixPacketBody: "fixture residual authored body",
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
            kind: "reviewer", findings: [mediumBlocking], findingsCount: 1, fixPacketBody: "fixture residual authored body",
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
      if ((spec.role === "reviewer" || spec.role === "verify")) {
        return { kind: "judge", status: "converged" };
      }
      return { kind: "coder", committed: true, commitsAdded: 1 };
    }
  }

  it("S2 dispatches the first roster-valid Coder-Rec entry from the issue body", async () => {
    vi.stubEnv("ORCHESTRATOR_CODER_MODEL", "");
    const backend = new CoderRecBackend();
    const result = await runOrchestrator({ issueNumber: 767, backend });
    expect(result.status).toBe("completed");
    expect(backend.coderModels).toEqual(["grok-4.5"]);
  });

  it("runs Coder-Rec Terra end-to-end on the default route", async () => {
    vi.stubEnv("ORCHESTRATOR_CODER_MODEL", "");
    const backend = new CoderRecBackend("Coder-Rec: terra@med");

    const result = await runOrchestrator({ issueNumber: 767, backend });

    expect(result.status).toBe("completed");
    expect(backend.coderModels).toEqual(["gpt-5.6-terra"]);
  });

  it("escalates at S0 instead of dispatching a Coder-Rec slug that violates a tight route", async () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "codex-tight");
    vi.stubEnv("ORCHESTRATOR_CODER_MODEL", "");
    class TightRouteBackend extends CoderRecBackend {
      override async fetchIssueMeta(issueNumber: number): Promise<IssueMeta> {
        return {
          ...(await super.fetchIssueMeta(issueNumber)),
          body: "Coder-Rec: terra@med",
        };
      }
    }

    const backend = new TightRouteBackend();
    const result = await runOrchestrator({ issueNumber: 767, backend });

    expect(result.status).toBe("failed");
    expect(result.errorPackage?.failedStep).toBe("S0");
    expect(result.errorPackage?.reason).toMatch(/tight route violation.*coder=.*gpt-5\.6-terra/i);
    expect(backend.coderModels).toEqual([]);
  });

  it("#906: bold Coder-Rec (#899 fixture) applies and dispatches the marked coder", async () => {
    vi.stubEnv("ORCHESTRATOR_CODER_MODEL", "");
    // #920: sol is a legal coder even when it also owns review/CMR seats.
    const backend = new CoderRecBackend(
      "- **Coder-Rec: grok-4.5 → sol@med**\n",
    );
    const result = await runOrchestrator({ issueNumber: 899, backend });
    expect(result.status).toBe("completed");
    expect(backend.coderModels).toEqual(["grok-4.5"]);
    expect(backend.coderModels).not.toContain("sonnet");
  });

  it("#899 run8 / #920: sol coder + sol cmrReview leg lights without rejection", async () => {
    vi.stubEnv("ORCHESTRATOR_CODER_MODEL", "");
    class SolSameModelBackend extends CoderRecBackend {
      cmrReviewOnSmoke: string[] = [];
      override async smokeModelRoute(route: any) {
        this.cmrReviewOnSmoke = route.legCollections.cmrReview.map(
          (leg: { slug: string }) => leg.slug,
        );
        // Same-model coder↔cmrReview must not be rejected at ignition.
        expect(route.slots.coder).toBe("gpt-5.6-sol");
        expect(this.cmrReviewOnSmoke).toContain("gpt-5.6-sol");
        return super.smokeModelRoute(route);
      }
    }
    const backend = new SolSameModelBackend("Coder-Rec: sol@med\n");
    const result = await runOrchestrator({ issueNumber: 899, backend });
    expect(result.status).toBe("completed");
    expect(backend.coderModels[0]).toBe("gpt-5.6-sol");
    expect(backend.cmrReviewOnSmoke).toContain("gpt-5.6-sol");
  });

  it("#906: broken Coder-Rec mark fail-closes at admission with zero dispatch", async () => {
    vi.stubEnv("ORCHESTRATOR_CODER_MODEL", "");
    const backend = new CoderRecBackend("Please set Coder-Rec carefully.\n");
    const result = await runOrchestrator({ issueNumber: 906, backend });
    expect(result.status).toBe("failed");
    expect(result.errorPackage?.failedStep).toBe("S0");
    expect(result.errorPackage?.reason).toMatch(/Coder-Rec/i);
    expect(backend.coderModels).toEqual([]);
    expect(backend.events.filter((e) => e.startsWith("dispatch:"))).toEqual([]);
  });

  it("#906: unregistered Coder-Rec model fail-closes and lists legal roster ids", async () => {
    vi.stubEnv("ORCHESTRATOR_CODER_MODEL", "");
    const backend = new CoderRecBackend(
      "Coder-Rec: totally-bogus → also-fake\n",
    );
    const result = await runOrchestrator({ issueNumber: 906, backend });
    expect(result.status).toBe("failed");
    expect(result.errorPackage?.failedStep).toBe("S0");
    expect(result.errorPackage?.reason).toMatch(/totally-bogus/);
    for (const id of CODER_ROSTER.map((e) => e.id)) {
      expect(result.errorPackage?.reason).toContain(id);
    }
    expect(backend.coderModels).toEqual([]);
  });

  it("#906 S1: env override + dirty Coder-Rec body fail-closes at admission (not mid-run)", async () => {
    // ORCHESTRATOR_CODER_MODEL used to short-circuit before body parse; relay
    // later bare-called resolveCoderRecOrder and could throw uncaught.
    vi.stubEnv("ORCHESTRATOR_CODER_MODEL", "sonnet");
    const backend = new CoderRecBackend(
      "Coder-Rec: totally-bogus → also-fake\n",
    );
    const result = await runOrchestrator({ issueNumber: 906, backend });
    expect(result.status).toBe("failed");
    expect(result.errorPackage?.failedStep).toBe("S0");
    expect(result.errorPackage?.reason).toMatch(/totally-bogus|Coder-Rec/i);
    expect(backend.coderModels).toEqual([]);
    expect(backend.events.filter((e) => e.startsWith("dispatch:"))).toEqual([]);
  });

  it("S0 smokes the Coder-Rec final route once, not the preset then the override", async () => {
    vi.stubEnv("ORCHESTRATOR_CODER_MODEL", "");
    const backend = new CoderRecBackend();
    const result = await runOrchestrator({ issueNumber: 767, backend });
    expect(result.status).toBe("completed");
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

  it("resume after S5 keeps the first Coder-Rec entry (no round advance)", async () => {
    vi.stubEnv("ORCHESTRATOR_CODER_MODEL", "");
    const backend = new CoderRecResumeAfterS5Backend();
    const result = await runOrchestrator({ issueNumber: 767, backend });
    expect(result.status).toBe("completed");
    // ADR 0132: completed S6 rounds on the restored ledger do not rotate models.
    expect(backend.coderModels[0]).toBe("grok-4.5");
  });

  it("resume: fetchIssueMeta throw degrades to route preset (no snapshot dual court) (#936)", async () => {
    vi.stubEnv("ORCHESTRATOR_CODER_MODEL", "");
    class MetaThrowBackend extends CoderRecResumeAfterS5Backend {
      override async fetchIssueMeta(_issueNumber: number): Promise<IssueMeta> {
        throw new Error("meta unavailable");
      }
    }
    const backend = new MetaThrowBackend();
    const result = await runOrchestrator({ issueNumber: 767, backend });
    expect(result.status).toBe("completed");
    // #936: no snapshot fallback — continue with route preset coder.
    expect(backend.coderModels[0]).toBe("gpt-5.6-terra");
  });

  it("resume: both re-fetch throws degrade to route preset without error termination", async () => {
    vi.stubEnv("ORCHESTRATOR_CODER_MODEL", "");
    const info = vi.spyOn(console, "info").mockImplementation(() => {});
    class BothRefetchThrowBackend extends CoderRecResumeAfterS5Backend {
      override async fetchIssueMeta(_issueNumber: number): Promise<IssueMeta> {
        throw new Error("meta unavailable");
      }
    }
    try {
      const backend = new BothRefetchThrowBackend();
      const result = await runOrchestrator({ issueNumber: 767, backend });
      expect(result.status).toBe("completed");
      // Coder-Rec is optional: continue with the route preset coder (normal → terra).
      expect(backend.coderModels[0]).toBe("gpt-5.6-terra");
      expect(info).toHaveBeenCalledWith(
        expect.stringMatching(
          /Coder-Rec.*(?:re-?fetch|resume).*(?:fail|degrad|unavailable|preset)/i,
        ),
      );
    } finally {
      info.mockRestore();
    }
  });

  it("never mid-loop advances / re-smokes a later Coder-Rec seat from S6 count", async () => {
    vi.stubEnv("ORCHESTRATOR_CODER_MODEL", "");
    const backend = new CoderRecAdvanceBackend();
    const result = await runOrchestrator({ issueNumber: 767, backend });
    expect(result.status).toBe("completed");
    expect(backend.events).not.toContain("smoke:gpt-5.6-terra");
    expect(backend.events).not.toContain("dispatch:gpt-5.6-terra");
    expect(backend.coderModels.every((m) => m === "grok-4.5")).toBe(true);
  });

  it("keeps the DISPATCHED coder on the first seat after multiple completed S6 rounds", async () => {
    vi.stubEnv("ORCHESTRATOR_CODER_MODEL", "");
    const backend = new CoderRecAdvanceBackend();
    const result = await runOrchestrator({ issueNumber: 767, backend });
    expect(result.status).toBe("completed");

    // Multi-round S6 path must not rotate the coder model (ADR 0132 / #919 CR).
    const s6Count = backend.ledgerWrites.filter((e) => e.step === "S6").length;
    expect(s6Count).toBeGreaterThanOrEqual(2);

    // S2 + all S5 stay on Grok — no selection-by-rounds dual-track.
    expect(backend.coderModels[0]).toBe("grok-4.5");
    expect(
      backend.coderModels.filter((m) => m === "grok-4.5").length,
    ).toBe(backend.coderModels.length);
    expect(backend.coderModels).not.toContain("gpt-5.6-terra");
  });
});
