import { describe, expect, it } from "vitest";
import { layerEpicIssues, type TopologyInput } from "./orchestratorKernel";
// @ts-ignore Workflow scripts are plain JavaScript outside the web src TypeScript program.
import { inlineLayerEpicIssues, normalizeWorkflowArgs, runEpicDiscoveryWorkflow } from "../orchestrator/epicOrchestrator.workflow.js";

const representativeTopologyInputs: TopologyInput[] = [
  {
    epicId: 217,
    issues: [
      { id: 218, epicId: 217, state: "closed" },
      { id: 219, epicId: 217, state: "open" },
      { id: 220, epicId: 217, state: "open" }
    ],
    blockedBy: [
      { issueId: 219, blockedByIssueId: 218 },
      { issueId: 220, blockedByIssueId: 219 }
    ]
  },
  {
    epicId: 217,
    issues: [
      { id: 220, epicId: 217, state: "open" },
      { id: 219, epicId: 217, state: "open" },
      { id: 218, epicId: 217, state: "open" }
    ],
    blockedBy: []
  },
  {
    epicId: 217,
    issues: [
      { id: "0123", epicId: 217, state: "open" },
      { id: "123", epicId: 217, state: "open" },
      { id: 900, epicId: 999, state: "open" }
    ],
    blockedBy: [{ issueId: "123", blockedByIssueId: 900 }]
  },
  {
    epicId: 217,
    issues: [
      { id: 2, epicId: 217, state: "open" },
      { id: 10, epicId: 217, state: "closed" },
      { id: 4, epicId: 217, state: "closed" },
      { id: 900, epicId: 999, state: "open" },
      { id: 800, epicId: 999, state: "open" }
    ],
    blockedBy: [
      { issueId: 2, blockedByIssueId: 900 },
      { issueId: 2, blockedByIssueId: 800 }
    ]
  }
];

function captureTopologyError(fn: () => unknown) {
  try {
    fn();
  } catch (error) {
    return {
      name: (error as { name?: string }).name,
      code: (error as { code?: string }).code,
      message: (error as { message?: string }).message
    };
  }
  throw new Error("Expected topology call to throw");
}

describe("epic orchestrator workflow inline kernel drift guard", () => {
  it("matches the S0 topology authority for ready, closed-skip, external, and ordering cases", () => {
    for (const input of representativeTopologyInputs) {
      expect(inlineLayerEpicIssues(input)).toEqual(layerEpicIssues(input));
    }
  });

  it("throws the same topology errors as the S0 authority for empty epic and cycle boundaries", () => {
    const boundaryInputs: TopologyInput[] = [
      { epicId: 217, issues: [], blockedBy: [] },
      {
        epicId: 217,
        issues: [
          { id: "A", epicId: 217, state: "open" },
          { id: "B", epicId: 217, state: "open" }
        ],
        blockedBy: [
          { issueId: "A", blockedByIssueId: "B" },
          { issueId: "B", blockedByIssueId: "A" }
        ]
      }
    ];

    for (const input of boundaryInputs) {
      expect(captureTopologyError(() => inlineLayerEpicIssues(input))).toEqual(captureTopologyError(() => layerEpicIssues(input)));
    }
  });
});

describe("epic orchestrator workflow spine", () => {
  it("normalizes numeric epic args and rejects missing or non-numeric args", () => {
    expect(normalizeWorkflowArgs(217)).toBe("217");
    expect(normalizeWorkflowArgs({ epicIssueNumber: " 217 " })).toBe("217");
    expect(() => normalizeWorkflowArgs({})).toThrow("epic-orchestrator requires args");
    expect(() => normalizeWorkflowArgs("217x")).toThrow("epic-orchestrator requires args");
  });

  it("returns a structured ordered execution plan and boundary copy from discovered gh JSON", async () => {
    const result = await runEpicDiscoveryWorkflow({
      args: 217,
      log: () => undefined,
      Bash: async () =>
        JSON.stringify({
          epicId: 217,
          issues: [
            { id: 218, epicId: 217, state: "closed", title: "S0", url: "https://example.test/218" },
            { id: 219, epicId: 217, state: "open", title: "S1", url: "https://example.test/219" },
            { id: 220, epicId: 217, state: "open", title: "S2", url: "https://example.test/220" }
          ],
          blockedBy: [
            { issueId: 219, blockedByIssueId: 218 },
            { issueId: 220, blockedByIssueId: 219 }
          ]
        })
    });

    expect(result).toEqual({
      epicIssueNumber: 217,
      topology: {
        status: "ready",
        layers: [[219], [220]],
        skippedClosedIssueIds: [218],
        externalPrerequisites: []
      },
      orderedPlan: [
        {
          layer: 1,
          issueNumbers: [219],
          issues: [{ issueNumber: 219, title: "S1", state: "open", url: "https://example.test/219" }]
        },
        {
          layer: 2,
          issueNumbers: [220],
          issues: [{ issueNumber: 220, title: "S2", state: "open", url: "https://example.test/220" }]
        }
      ],
      boundaryHandling: {
        action: "continue",
        skippedClosedIssueIds: [218],
        note: "empty epic and cycles throw TopologyError; closed child issues are skipped; closed blockers are treated as satisfied"
      },
      outOfScope: ["review", "worktree", "merge"]
    });
  });

  it("returns boundary handling instead of a work plan for unresolved cross-epic blockers", async () => {
    const result = await runEpicDiscoveryWorkflow({
      args: { epicIssueNumber: 217 },
      log: () => undefined,
      Bash: async () =>
        JSON.stringify({
          epicId: 217,
          issues: [
            { id: 219, epicId: 217, state: "open", title: "S1", url: "https://example.test/219" },
            { id: 900, epicId: "__external__", state: "open", title: "External", url: "https://example.test/900" }
          ],
          blockedBy: [{ issueId: 219, blockedByIssueId: 900 }]
        })
    });

    expect(result).toMatchObject({
      epicIssueNumber: 217,
      topology: {
        status: "external_prerequisite",
        layers: [],
        skippedClosedIssueIds: [],
        externalPrerequisites: [{ issueId: 219, blockedByIssueId: 900 }]
      },
      orderedPlan: [],
      boundaryHandling: {
        action: "return_to_main_session",
        reason: "one or more unresolved blockers are outside this epic",
        externalPrerequisites: [{ issueId: 219, blockedByIssueId: 900 }]
      },
      outOfScope: ["review", "worktree", "merge"]
    });
  });
});
