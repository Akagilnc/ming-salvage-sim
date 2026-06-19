import { describe, expect, it } from "vitest";
import { layerEpicIssues, type TopologyInput } from "./orchestratorKernel";
// @ts-ignore Workflow scripts are plain JavaScript outside the web tsconfig include set.
import { inlineLayerEpicIssues, runEpicDiscoveryWorkflow } from "../../.claude/workflows/epic-discovery-spine.js";

const cases: TopologyInput[] = [
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
      { id: "0123", epicId: 217, state: "open" },
      { id: "123", epicId: 217, state: "open" },
      { id: 900, epicId: 999, state: "open" }
    ],
    blockedBy: [{ issueId: "123", blockedByIssueId: 900 }]
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

describe("epic discovery workflow inline kernel drift guard", () => {
  it("matches the S0 topology authority for representative boundary inputs", () => {
    for (const input of cases) {
      expect(inlineLayerEpicIssues(input)).toEqual(layerEpicIssues(input));
    }
  });

  it("throws the same topology errors as S0 authority for empty epic and cycle boundaries", () => {
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
        note: "空 epic 与成环会抛出 TopologyError；已关闭子 issue 会跳过；已关闭 blocker 视为已满足"
      },
      outOfScope: ["review", "worktree", "merge"]
    });
  });
});
