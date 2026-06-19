import { describe, expect, it } from "vitest";
import {
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
});

describe("routeFindings", () => {
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

  it("halts per-slice review when fewer than two models are available and the codex-only exception does not apply", () => {
    expect(
      judgeReviewDegradation({
        stage: "per_slice",
        results: [down("codex"), ok("agy")]
      })
    ).toEqual({ status: "halt", availableModels: ["agy"], missingModels: ["codex"], flags: ["review requires at least two available models unless the per-slice codex-only exception applies"] });
  });
});
