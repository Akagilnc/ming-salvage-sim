import { describe, expect, it } from "vitest";
import {
  buildHandoffPayload,
  continuationPlan,
  dismissalGate,
  familyReviewGate,
  judgeReviewDegradation,
  layerEpicIssues,
  routeFindings,
  shipOutcome,
  TopologyError,
  type Finding,
  type HandoffInput,
  type ModelReviewResult
} from "./orchestratorKernel";

describe("layerEpicIssues", () => {
  it("layers open epic children after their in-epic blockers", () => {
    const plan = layerEpicIssues({
      epicId: 217,
      issues: [
        { id: 218, epicId: 217, state: "open" },
        { id: 219, epicId: 217, state: "open" },
        { id: 220, epicId: 217, state: "open" },
        { id: 300, epicId: 999, state: "open" }
      ],
      blockedBy: [
        { issueId: 219, blockedByIssueId: 218 },
        { issueId: 220, blockedByIssueId: 218 }
      ]
    });

    expect(plan).toEqual({
      status: "ready",
      layers: [[218], [219, 220]],
      skippedClosedIssueIds: [],
      externalPrerequisites: []
    });
  });

  it("throws loudly for an empty epic", () => {
    expect(() =>
      layerEpicIssues({ epicId: 217, issues: [], blockedBy: [] })
    ).toThrowError(new TopologyError("empty_epic", "Epic 217 has no native sub-issues."));
  });

  it("throws loudly when open in-epic children form a cycle", () => {
    expect(() =>
      layerEpicIssues({
        epicId: 217,
        issues: [
          { id: "A", epicId: 217, state: "open" },
          { id: "B", epicId: 217, state: "open" }
        ],
        blockedBy: [
          { issueId: "A", blockedByIssueId: "B" },
          { issueId: "B", blockedByIssueId: "A" }
        ]
      })
    ).toThrowError(TopologyError);
  });

  it("halts with an external prerequisite for an open blocker outside the epic", () => {
    const plan = layerEpicIssues({
      epicId: 217,
      issues: [
        { id: 218, epicId: 217, state: "open" },
        { id: 900, epicId: 999, state: "open" }
      ],
      blockedBy: [{ issueId: 218, blockedByIssueId: 900 }]
    });

    expect(plan).toEqual({
      status: "external_prerequisite",
      layers: [],
      skippedClosedIssueIds: [],
      externalPrerequisites: [{ issueId: 218, blockedByIssueId: 900 }]
    });
  });

  it("skips closed children and treats them as satisfied blockers", () => {
    const plan = layerEpicIssues({
      epicId: 217,
      issues: [
        { id: 218, epicId: 217, state: "closed" },
        { id: 219, epicId: 217, state: "open" }
      ],
      blockedBy: [{ issueId: 219, blockedByIssueId: 218 }]
    });

    expect(plan).toEqual({
      status: "ready",
      layers: [[219]],
      skippedClosedIssueIds: [218],
      externalPrerequisites: []
    });
  });

  it("treats nullish child state as open instead of throwing", () => {
    const plan = layerEpicIssues({
      epicId: 217,
      issues: [
        { id: 218, epicId: 217, state: undefined },
        { id: 219, epicId: 217, state: null }
      ],
      blockedBy: [{ issueId: 219, blockedByIssueId: 218 }]
    });

    expect(plan).toEqual({
      status: "ready",
      layers: [[218], [219]],
      skippedClosedIssueIds: [],
      externalPrerequisites: []
    });
  });

  it("returns stable sorted closed skips and external prerequisites", () => {
    const plan = layerEpicIssues({
      epicId: 217,
      issues: [
        { id: 4, epicId: 217, state: "closed" },
        { id: 2, epicId: 217, state: "open" },
        { id: 10, epicId: 217, state: "closed" },
        { id: 900, epicId: 999, state: "open" },
        { id: 800, epicId: 999, state: "open" }
      ],
      blockedBy: [
        { issueId: 2, blockedByIssueId: 900 },
        { issueId: 2, blockedByIssueId: 800 }
      ]
    });

    expect(plan).toEqual({
      status: "external_prerequisite",
      layers: [],
      skippedClosedIssueIds: [4, 10],
      externalPrerequisites: [
        { issueId: 2, blockedByIssueId: 800 },
        { issueId: 2, blockedByIssueId: 900 }
      ]
    });
  });

  it("sorts decimal ids numerically and non-decimal ids lexically without numeric coercion", () => {
    const plan = layerEpicIssues({
      epicId: 217,
      issues: [
        { id: "0x10", epicId: 217, state: "open" },
        { id: " 2", epicId: 217, state: "open" },
        { id: "10", epicId: 217, state: "open" },
        { id: "2", epicId: 217, state: "open" },
        { id: "A", epicId: 217, state: "open" }
      ],
      blockedBy: []
    });

    expect(plan).toEqual({
      status: "ready",
      layers: [["2", "10", " 2", "0x10", "A"]],
      skippedClosedIssueIds: [],
      externalPrerequisites: []
    });
  });

  it("keeps numeric-equivalent decimal ids in deterministic lexical order", () => {
    const plan = layerEpicIssues({
      epicId: 217,
      issues: [
        { id: "123", epicId: 217, state: "open" },
        { id: "0123", epicId: 217, state: "open" }
      ],
      blockedBy: []
    });

    expect(plan).toEqual({
      status: "ready",
      layers: [["0123", "123"]],
      skippedClosedIssueIds: [],
      externalPrerequisites: []
    });
  });
});

describe("routeFindings", () => {
  it("returns no_findings for an empty review result", () => {
    expect(routeFindings([])).toEqual({
      status: "no_findings",
      autonomousBugFindings: [],
      decisionFindings: []
    });
  });

  it("escalates when any finding is a choice", () => {
    const findings: Finding[] = [
      { id: "F1", classification: "mechanical_bug" },
      { id: "F2", classification: "choice" }
    ];

    expect(routeFindings(findings)).toEqual({
      status: "needs_decision",
      autonomousBugFindings: [findings[0]],
      decisionFindings: [findings[1]]
    });
  });

  it("defaults ambiguous findings into the decision bucket", () => {
    const findings: Finding[] = [{ id: "F1", classification: "ambiguous" }];

    expect(routeFindings(findings)).toEqual({
      status: "needs_decision",
      autonomousBugFindings: [],
      decisionFindings: findings
    });
  });

  it("routes pure mechanical bugs to autonomous repair", () => {
    const findings: Finding[] = [
      { id: "F1", classification: "mechanical_bug" },
      { id: "F2", classification: "mechanical_bug" }
    ];

    expect(routeFindings(findings)).toEqual({
      status: "autonomous_repair",
      autonomousBugFindings: findings,
      decisionFindings: []
    });
  });

  it("tolerates null/undefined entries without crashing (routes them to the decision bucket)", () => {
    const findings = [null, { id: "F1", classification: "mechanical_bug" }, undefined] as unknown as Finding[];

    expect(routeFindings(findings)).toEqual({
      status: "needs_decision",
      autonomousBugFindings: [{ id: "F1", classification: "mechanical_bug" }],
      decisionFindings: [null, undefined]
    });
  });
});

describe("judgeReviewDegradation", () => {
  const ok = (model: string): ModelReviewResult => ({ model, available: true });
  const down = (model: string): ModelReviewResult => ({ model, available: false, reason: "quota" });

  it("continues with a flag when at least two models are available", () => {
    expect(
      judgeReviewDegradation({
        stage: "family_5a_5b",
        results: [ok("codex"), ok("claude"), down("agy")]
      })
    ).toEqual({ status: "continue", availableModels: ["codex", "claude"], missingModels: ["agy"], flags: ["review degraded: agy unavailable (quota)"] });
  });

  it("halts family 5a/5b when fewer than two models are available", () => {
    expect(
      judgeReviewDegradation({
        stage: "family_5a_5b",
        results: [ok("codex"), down("claude"), down("agy")]
      })
    ).toEqual({ status: "halt", availableModels: ["codex"], missingModels: ["claude", "agy"], flags: ["family 5a/5b requires at least two available models"] });
  });

  it("allows per-slice review to proceed on codex alone when agy is down", () => {
    expect(
      judgeReviewDegradation({
        stage: "per_slice",
        results: [ok("codex"), down("agy")]
      })
    ).toEqual({ status: "continue", availableModels: ["codex"], missingModels: ["agy"], flags: ["per-slice agy unavailable; proceeding codex-only"] });
  });

  it("allows per-slice review to proceed on codex alone even when agy is omitted", () => {
    expect(
      judgeReviewDegradation({
        stage: "per_slice",
        results: [ok("codex")]
      })
    ).toEqual({ status: "continue", availableModels: ["codex"], missingModels: [], flags: ["per-slice codex-only review"] });
  });

  it("counts distinct model names for availability thresholds", () => {
    expect(
      judgeReviewDegradation({
        stage: "family_5a_5b",
        results: [ok("codex"), ok("codex"), down("agy"), down("agy")]
      })
    ).toEqual({ status: "halt", availableModels: ["codex"], missingModels: ["agy"], flags: ["family 5a/5b requires at least two available models"] });
  });

  it("halts per-slice review when fewer than two models are available and the codex-only exception does not apply", () => {
    expect(
      judgeReviewDegradation({
        stage: "per_slice",
        results: [down("codex"), ok("agy")]
      })
    ).toEqual({ status: "halt", availableModels: ["agy"], missingModels: ["codex"], flags: ["review requires at least two available models unless the per-slice codex-only exception applies"] });
  });
});

describe("familyReviewGate", () => {
  it("escalates as soon as any decision finding is present", () => {
    expect(familyReviewGate({ escalateCount: 1, mechanicalCount: 0, round: 1, maxRounds: 3 })).toBe("escalate");
  });

  it("escalates even when mechanical bugs also exist (escalation takes priority)", () => {
    expect(familyReviewGate({ escalateCount: 1, mechanicalCount: 5, round: 1, maxRounds: 3 })).toBe("escalate");
  });

  it("escalates regardless of round, ignoring the fix budget", () => {
    expect(familyReviewGate({ escalateCount: 1, mechanicalCount: 0, round: 3, maxRounds: 3 })).toBe("escalate");
  });

  it("converges when there are no findings at all", () => {
    expect(familyReviewGate({ escalateCount: 0, mechanicalCount: 0, round: 1, maxRounds: 3 })).toBe("converged");
  });

  it("requests an autonomous fix when only mechanical bugs remain and rounds are left", () => {
    expect(familyReviewGate({ escalateCount: 0, mechanicalCount: 2, round: 1, maxRounds: 3 })).toBe("fix");
  });

  it("keeps fixing on intermediate rounds below the cap", () => {
    expect(familyReviewGate({ escalateCount: 0, mechanicalCount: 1, round: 2, maxRounds: 3 })).toBe("fix");
  });

  it("aborts (I1) when mechanical bugs persist at the final round", () => {
    expect(familyReviewGate({ escalateCount: 0, mechanicalCount: 1, round: 3, maxRounds: 3 })).toBe("abort");
  });

  it("aborts defensively if the round somehow exceeds the cap", () => {
    expect(familyReviewGate({ escalateCount: 0, mechanicalCount: 1, round: 4, maxRounds: 3 })).toBe("abort");
  });
});

describe("shipOutcome", () => {
  it("is ready when gstack-ship gates passed and the family PR was created", () => {
    expect(shipOutcome({ asked: false, gatesPassed: true, prCreated: true })).toBe("ready");
  });

  it("needs the user when gstack-ship raised an internal ASK", () => {
    expect(shipOutcome({ asked: true, gatesPassed: false, prCreated: false })).toBe("needs-user");
  });

  it("is unconverged when the ship gates did not pass", () => {
    expect(shipOutcome({ asked: false, gatesPassed: false, prCreated: false })).toBe("unconverged");
  });

  it("is unconverged when gates passed but no PR was created (guards the && prCreated)", () => {
    expect(shipOutcome({ asked: false, gatesPassed: true, prCreated: false })).toBe("unconverged");
  });

  it("prioritizes the ASK over passed gates (asked is checked first)", () => {
    expect(shipOutcome({ asked: true, gatesPassed: true, prCreated: false })).toBe("needs-user");
  });

  it("prioritizes the ASK even when every ready condition is also satisfied", () => {
    expect(shipOutcome({ asked: true, gatesPassed: true, prCreated: true })).toBe("needs-user");
  });
});

describe("buildHandoffPayload", () => {
  // wiki §段间交接 fixed field set: terminal state / parent epic / family branch + base SHA /
  // merged slices + commit hashes / dirty slices / pending question / degradation flags.
  const base: HandoffInput = {
    status: "ready",
    epic: 217,
    familyBranch: "family/217",
    baseAtStart: "base-sha-aaa",
    familyHead: "family-tip-zzz",
    merged: [
      { number: 220, reviewedCommit: "c220" },
      { number: 221, reviewedCommit: "c221" }
    ],
    dirty: [],
    flags: []
  };

  it("assembles the full §段间交接 field set for the ready terminal state", () => {
    const payload = buildHandoffPayload({
      ...base,
      status: "ready",
      prUrl: "https://github.com/Akagilnc/ming-salvage-sim/pull/999"
    });

    expect(payload).toEqual({
      status: "ready",
      epic: 217,
      familyBranch: "family/217",
      baseAtStart: "base-sha-aaa",
      familyHead: "family-tip-zzz",
      merged: [
        { number: 220, reviewedCommit: "c220" },
        { number: 221, reviewedCommit: "c221" }
      ],
      dirty: [],
      question: null,
      detail: null,
      flags: [],
      prUrl: "https://github.com/Akagilnc/ming-salvage-sim/pull/999"
    });
  });

  it("carries the gstack-ship ASK question for the needs-user terminal state", () => {
    const payload = buildHandoffPayload({
      ...base,
      status: "needs-user",
      reason: "gstack-ship-ask",
      question: "Version bump is MINOR or MAJOR?"
    });

    expect(payload).toEqual({
      status: "needs-user",
      epic: 217,
      familyBranch: "family/217",
      baseAtStart: "base-sha-aaa",
      familyHead: "family-tip-zzz",
      merged: [
        { number: 220, reviewedCommit: "c220" },
        { number: 221, reviewedCommit: "c221" }
      ],
      dirty: [],
      question: "Version bump is MINOR or MAJOR?",
      detail: null,
      flags: [],
      reason: "gstack-ship-ask",
      prUrl: null
    });
  });

  it("carries the blocking detail for the unconverged terminal state", () => {
    const payload = buildHandoffPayload({
      ...base,
      status: "unconverged",
      reason: "gstack-ship-failed",
      detail: "RedTeam gate failed"
    });

    expect(payload).toEqual({
      status: "unconverged",
      epic: 217,
      familyBranch: "family/217",
      baseAtStart: "base-sha-aaa",
      familyHead: "family-tip-zzz",
      merged: [
        { number: 220, reviewedCommit: "c220" },
        { number: 221, reviewedCommit: "c221" }
      ],
      dirty: [],
      question: null,
      detail: "RedTeam gate failed",
      flags: [],
      reason: "gstack-ship-failed",
      prUrl: null
    });
  });

  it("preserves dirty slices and degradation flags across every terminal state", () => {
    const payload = buildHandoffPayload({
      status: "unconverged",
      epic: 217,
      familyBranch: "family/217",
      baseAtStart: "base-sha-bbb",
      merged: [{ number: 220, reviewedCommit: "c220" }],
      dirty: [{ number: 221, decision: "rework auth gate" }],
      flags: ["family 5a/5b degraded: agy unavailable (quota)"],
      reason: "gstack-ship-failed",
      detail: "coverage hard gate below threshold"
    });

    expect(payload.dirty).toEqual([{ number: 221, decision: "rework auth gate" }]);
    expect(payload.flags).toEqual(["family 5a/5b degraded: agy unavailable (quota)"]);
    expect(payload.question).toBeNull();
  });

  it("defaults optional collections (merged / dirty / flags) to stable empty arrays", () => {
    const payload = buildHandoffPayload({
      status: "ready",
      epic: 217,
      familyBranch: "family/217",
      baseAtStart: "base-sha-aaa",
      prUrl: "https://example.test/pr/1"
    });

    expect(payload.merged).toEqual([]);
    expect(payload.dirty).toEqual([]);
    expect(payload.flags).toEqual([]);
    expect(payload.question).toBeNull();
    expect(payload.detail).toBeNull();
    expect(payload.familyHead).toBeNull();
  });
});

describe("continuationPlan", () => {
  it("skips a merged, non-dirty slice (git already has its commit on the family branch)", () => {
    expect(continuationPlan({ layers: [[218]], mergedNumbers: [218], dirty: [] })).toEqual({
      layers: [{ todo: [], skipped: [218], dirty: [] }],
      todoTotal: 0
    });
  });

  it("runs only slices the family branch does not yet have", () => {
    expect(continuationPlan({ layers: [[218, 219]], mergedNumbers: [218], dirty: [] })).toEqual({
      layers: [{ todo: [219], skipped: [218], dirty: [] }],
      todoTotal: 1
    });
  });

  it("re-runs a merged-but-dirty slice (into todo + dirty, not git-skipped)", () => {
    expect(continuationPlan({ layers: [[218, 219]], mergedNumbers: [218, 219], dirty: [218] })).toEqual({
      layers: [{ todo: [218], skipped: [219], dirty: [218] }],
      todoTotal: 1
    });
  });

  it("buckets a multi-layer mix per layer and accumulates todoTotal across layers", () => {
    expect(
      continuationPlan({ layers: [[218, 219], [220, 221]], mergedNumbers: [218, 219, 221], dirty: [219] })
    ).toEqual({
      layers: [
        { todo: [219], skipped: [218], dirty: [219] },
        { todo: [220], skipped: [221], dirty: [] }
      ],
      todoTotal: 2
    });
  });

  it("reports todoTotal 0 when every slice is merged and none are dirty", () => {
    const plan = continuationPlan({ layers: [[218], [219]], mergedNumbers: [218, 219], dirty: [] });
    expect(plan.todoTotal).toBe(0);
    expect(plan.layers.every((layer) => layer.todo.length === 0)).toBe(true);
  });

  it("treats an omitted dirty list as the empty set (first segment has no dirty concept)", () => {
    expect(continuationPlan({ layers: [[218]], mergedNumbers: [] })).toEqual({
      layers: [{ todo: [218], skipped: [], dirty: [] }],
      todoTotal: 1
    });
  });

  it("records a dirty slice that is not yet merged in the dirty bucket while still running it", () => {
    expect(continuationPlan({ layers: [[218, 219]], mergedNumbers: [218], dirty: [219] })).toEqual({
      layers: [{ todo: [219], skipped: [218], dirty: [219] }],
      todoTotal: 1
    });
  });

  it("does not mutate its input arrays", () => {
    const layers = [[218, 219]];
    const mergedNumbers = [218];
    const dirty = [219];
    continuationPlan({ layers, mergedNumbers, dirty });
    expect(layers).toEqual([[218, 219]]);
    expect(mergedNumbers).toEqual([218]);
    expect(dirty).toEqual([219]);
  });

  it("matches merged/dirty membership across string and number issue ids", () => {
    expect(continuationPlan({ layers: [["218", 219]], mergedNumbers: [218], dirty: ["219"] })).toEqual({
      layers: [{ todo: [219], skipped: ["218"], dirty: [219] }],
      todoTotal: 1
    });
  });
});

describe("dismissalGate", () => {
  it("does not HALT when the finding id matches a dismissed entry", () => {
    expect(dismissalGate({ finding: { id: "F1" }, dismissed: [{ id: "F1" }] })).toBe(false);
  });

  it("HALTs when the finding id does not match", () => {
    expect(dismissalGate({ finding: { id: "F2" }, dismissed: [{ id: "F1" }] })).toBe(true);
  });

  it("matches by claimQuote even when the id drifted across segments", () => {
    expect(
      dismissalGate({ finding: { id: "NEW-3", claimQuote: "此处 throw 缺测试" }, dismissed: [{ id: "OLD-7", claimQuote: "此处 throw 缺测试" }] })
    ).toBe(false);
  });

  it("matches by location even when the claim wording changed", () => {
    expect(
      dismissalGate({ finding: { id: "X", location: "decisionCore.ts:42" }, dismissed: [{ location: "decisionCore.ts:42" }] })
    ).toBe(false);
  });

  it("HALTs against an empty dismissal list", () => {
    expect(dismissalGate({ finding: { id: "F1", claimQuote: "q", location: "l" }, dismissed: [] })).toBe(true);
  });

  it("does not vacuously match when a dimension is undefined on both sides", () => {
    expect(dismissalGate({ finding: { id: "B" }, dismissed: [{ claimQuote: undefined, location: undefined, id: "A" }] })).toBe(true);
  });

  it("does not HALT when any one of multiple dismissals matches", () => {
    expect(dismissalGate({ finding: { id: "Z", location: "core.ts:9" }, dismissed: [{ id: "F1" }, { location: "core.ts:9" }] })).toBe(false);
  });

  it("matches a canonical snake_case claim_quote dismissal against a camelCase finding claimQuote", () => {
    expect(
      dismissalGate({ finding: { id: "NEW", claimQuote: "此处 throw 缺测试" }, dismissed: [{ claim_quote: "此处 throw 缺测试" }] })
    ).toBe(false);
  });

  it("matches a camelCase dismissal against a snake_case finding claim_quote", () => {
    expect(dismissalGate({ finding: { id: "X", claim_quote: "q" }, dismissed: [{ claimQuote: "q" }] })).toBe(false);
  });

  it("matches when both sides use snake_case claim_quote", () => {
    expect(dismissalGate({ finding: { id: "X", claim_quote: "q" }, dismissed: [{ claim_quote: "q" }] })).toBe(false);
  });

  it("tolerates a null/undefined finding without crashing (treats it as not-dismissed)", () => {
    const dismissed = [{ id: "F1" }];
    expect(dismissalGate({ finding: null as unknown as Finding, dismissed })).toBe(true);
    expect(dismissalGate({ finding: undefined as unknown as Finding, dismissed })).toBe(true);
  });
});
