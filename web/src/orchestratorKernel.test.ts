import { describe, expect, it } from "vitest";
import {
  familyReviewGate,
  judgeReviewDegradation,
  layerEpicIssues,
  routeFindings,
  TopologyError,
  type Finding,
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
