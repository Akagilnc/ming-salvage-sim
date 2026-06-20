import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { familyReviewGate, judgeReviewDegradation, layerEpicIssues, routeFindings, type FamilyReviewGateInput, type Finding, type ModelReviewResult, type TopologyInput } from "./orchestratorKernel";
// @ts-ignore Workflow scripts are plain JavaScript outside the web src TypeScript program.
import { inlineFamilyReviewGate, inlineJudgeFamilyDegradation, inlineLayerEpicIssues, inlineRouteFindings, normalizeWorkflowArgs, runEpicDiscoveryWorkflow, runEpicLayeredPipeline, runEpicSingleSlicePipeline } from "../orchestrator/epicOrchestrator.workflow.js";

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
  it("normalizes positive numeric epic args and rejects missing, non-numeric, or non-positive args", () => {
    expect(normalizeWorkflowArgs(217)).toBe("217");
    expect(normalizeWorkflowArgs({ epicIssueNumber: " 217 " })).toBe("217");
    expect(() => normalizeWorkflowArgs({})).toThrow("epic-orchestrator requires args");
    expect(() => normalizeWorkflowArgs("217x")).toThrow("epic-orchestrator requires args");
    expect(() => normalizeWorkflowArgs(0)).toThrow("positive parent epic issue number");
    expect(() => normalizeWorkflowArgs("000")).toThrow("positive parent epic issue number");
  });

  it("uses a bounded gh discovery script that resolves the repository at runtime", async () => {
    let discoveryCommand = "";

    await runEpicDiscoveryWorkflow({
      args: 217,
      log: () => undefined,
      Bash: async (command: string) => {
        discoveryCommand = command;
        return JSON.stringify({
          epicId: 217,
          issues: [{ id: 219, epicId: 217, state: "open", title: "S1", url: "https://example.test/219" }],
          blockedBy: []
        });
      }
    });

    expect(discoveryCommand).toContain("GITHUB_REPOSITORY");
    expect(discoveryCommand).toContain('["repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"]');
    expect(discoveryCommand).toContain("timeout=30");
    expect(discoveryCommand).toContain("TimeoutExpired");
    expect(discoveryCommand).not.toContain('REPO = "Akagilnc/ming-salvage-sim"');
  });

  it("requests paginated gh api discovery for sub-issues and blockers", async () => {
    let discoveryCommand = "";

    await runEpicDiscoveryWorkflow({
      args: 217,
      log: () => undefined,
      Bash: async (command: string) => {
        discoveryCommand = command;
        return JSON.stringify({
          epicId: 217,
          issues: [{ id: 219, epicId: 217, state: "open", title: "S1", url: "https://example.test/219" }],
          blockedBy: []
        });
      }
    });

    expect(discoveryCommand).toContain('"--paginate"');
    expect(discoveryCommand).toContain('"--slurp"');
    expect(discoveryCommand).toContain('"--method", "GET"');
    expect(discoveryCommand).toContain('"-f", "per_page=100"');
    expect(discoveryCommand).toContain('return [item for page in pages for item in page]');
    expect(discoveryCommand).toContain('gh_json(f"/repos/{REPO}/issues/{epic}/sub_issues")');
    expect(discoveryCommand).toContain('gh_json(f"/repos/{REPO}/issues/{child_number}/dependencies/blocked_by")');
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

describe("epic orchestrator S2 single-slice pipeline", () => {
  it("runs exactly one planned slice through worktree implementation, local verify, codex+agy review, and family merge", async () => {
    const calls: string[] = [];
    const agentCalls: unknown[] = [];

    const result: any = await runEpicSingleSlicePipeline({
      args: { epicIssueNumber: 217, familyBranch: "family/217", verifyCommands: ["npm --prefix web test"] },
      log: () => undefined,
      agent: async (request: unknown) => {
        agentCalls.push(request);
        return {
          commit: "abc123",
          worktreePath: "/repo/.worktrees/issue-220",
          observabilityEvidence: { loudFailure: true, locatorLogs: true, notApplicableReason: "tooling slice" }
        };
      },
      Bash: async (command: string) => {
        calls.push(command);
        if (command.includes("/sub_issues")) {
          return JSON.stringify({
            epicId: 217,
            issues: [
              { id: 219, epicId: 217, state: "closed", title: "S1", url: "https://example.test/219" },
              { id: 220, epicId: 217, state: "open", title: "S2", url: "https://example.test/220" },
              { id: 221, epicId: 217, state: "open", title: "S3", url: "https://example.test/221" }
            ],
            blockedBy: [
              { issueId: 220, blockedByIssueId: 219 },
              { issueId: 221, blockedByIssueId: 220 }
            ]
          });
        }
        if (command.includes("reviewer=codex")) return JSON.stringify({ status: "passed", findings: [] });
        if (command.includes("reviewer=agy")) return JSON.stringify({ status: "passed", findings: [], diffOnly: true });
        if (command.includes("merge reviewed commit")) return JSON.stringify({ mergeCommit: "def456" });
        return JSON.stringify({ status: "passed" });
      }
    });

    expect(result.plannedSlice).toMatchObject({ issueNumber: 220, isolation: "worktree" });
    expect(result.implementation).toMatchObject({ commit: "abc123", worktreePath: "/repo/.worktrees/issue-220" });
    expect(result.verification).toMatchObject({ status: "passed" });
    expect(result.verification.commands).toEqual(["npm --prefix web run typecheck:orch", "npm --prefix web test", "npm --prefix web run build"]);
    expect(result.review).toMatchObject({
      status: "passed",
      reviewers: [
        { model: "codex", status: "passed", groundingFallback: true },
        { model: "agy", status: "passed", diffOnly: true, hiddenWorktree: true }
      ]
    });
    expect(result.merge).toEqual({ status: "merged", familyBranch: "family/217", reviewedCommit: "abc123", mergeCommit: "def456" });
    expect(result.i7).toEqual({ sliceCommit: "abc123", amendmentsForbidden: true, reviewFixesRequireNewCommits: true });
    expect(result.i8).toMatchObject({ required: true, loudFailure: true, locatorLogs: true });
    expect(agentCalls).toHaveLength(1);
    expect(JSON.stringify(agentCalls[0])).toContain("isolation");
    expect(JSON.stringify(agentCalls[0])).toContain("worktree");
    expect(calls.join("\n")).toContain("reviewer=codex");
    expect(calls.join("\n")).toContain("codex exec --skip-git-repo-check --ephemeral -");
    expect(calls.join("\n")).toContain("reviewer=agy");
    expect(calls.join("\n")).toContain("--diff-only");
  });

  it("parses reviewer JSON when codex stdout includes diff stat context before the machine result", async () => {
    const calls: string[] = [];

    const result: any = await runEpicSingleSlicePipeline({
      args: { epicIssueNumber: 217, familyBranch: "family/217", verifyCommands: ["npm --prefix web test"] },
      log: () => undefined,
      agent: async () => ({
        commit: "abc123",
        worktreePath: "/repo/.worktrees/issue-220",
        observabilityEvidence: { loudFailure: true, locatorLogs: true, notApplicableReason: "tooling slice" }
      }),
      Bash: async (command: string) => {
        calls.push(command);
        if (command.includes("/sub_issues")) {
          return JSON.stringify({
            epicId: 217,
            issues: [{ id: 220, epicId: 217, state: "open", title: "S2", url: "https://example.test/220" }],
            blockedBy: []
          });
        }
        if (command.includes("reviewer=codex")) return " web/orchestrator/epicOrchestrator.workflow.js | 1 +\n{\"status\":\"passed\",\"findings\":[]}";
        if (command.includes("reviewer=agy")) return JSON.stringify({ status: "passed", findings: [] });
        if (command.includes("merge reviewed commit")) return JSON.stringify({ mergeCommit: "def456" });
        return JSON.stringify({ status: "passed" });
      }
    });

    expect(result.review.reviewers[0]).toMatchObject({ model: "codex", status: "passed", findings: [] });
    expect(calls.find((command) => command.includes("reviewer=codex"))).toContain("Return only one JSON object");
  });

  it("merges reviewed commits into an existing family branch without resetting that branch", async () => {
    let mergeCommand = "";

    await runEpicSingleSlicePipeline({
      args: { epicIssueNumber: 217, familyBranch: "family/217", verifyCommands: ["npm --prefix web test"] },
      log: () => undefined,
      agent: async () => ({
        commit: "abc123",
        worktreePath: "/repo/.worktrees/issue-220",
        observabilityEvidence: { loudFailure: true, locatorLogs: true, notApplicableReason: "tooling slice" }
      }),
      Bash: async (command: string) => {
        if (command.includes("/sub_issues")) {
          return JSON.stringify({
            epicId: 217,
            issues: [{ id: 220, epicId: 217, state: "open", title: "S2", url: "https://example.test/220" }],
            blockedBy: []
          });
        }
        if (command.includes("reviewer=codex")) return JSON.stringify({ status: "passed", findings: [] });
        if (command.includes("reviewer=agy")) return JSON.stringify({ status: "passed", findings: [] });
        if (command.includes("merge reviewed commit")) {
          mergeCommand = command;
          return JSON.stringify({ mergeCommit: "def456" });
        }
        return JSON.stringify({ status: "passed" });
      }
    });

    expect(mergeCommand).toContain('show-ref --verify --quiet "refs/heads/${familyBranch}"');
    expect(mergeCommand).toContain('worktree add "$mergeWorktree" "$familyBranch"');
    expect(mergeCommand).toContain('worktree add -b "$familyBranch" "$mergeWorktree" "origin/${familyBranch}"');
    expect(mergeCommand).toContain('worktree add -b "$familyBranch" "$mergeWorktree" "${implementedCommit}^"');
    expect(mergeCommand).not.toContain("switch -C ${familyBranch}");
    expect(mergeCommand).not.toContain('switch "$familyBranch"');
  });

  it("fails fast when reviewer output starts with an invalid JSON object", async () => {
    await expect(runEpicSingleSlicePipeline({
      args: { epicIssueNumber: 217, verifyCommands: ["npm --prefix web test"] },
      log: () => undefined,
      agent: async () => ({
        commit: "abc123",
        worktreePath: "/repo/.worktrees/issue-220",
        observabilityEvidence: { loudFailure: true, locatorLogs: true, notApplicableReason: "tooling slice" }
      }),
      Bash: async (command: string) => {
        if (command.includes("/sub_issues")) {
          return JSON.stringify({
            epicId: 217,
            issues: [{ id: 220, epicId: 217, state: "open", title: "S2", url: "https://example.test/220" }],
            blockedBy: []
          });
        }
        if (command.includes("reviewer=codex")) return "{not reviewer json";
        return JSON.stringify({ status: "passed" });
      }
    })).rejects.toThrow("codex review did not return parseable reviewer JSON");
  });

  it("returns structured merge JSON when a real git merge writes status lines", async () => {
    const repoPath = mkdtempSync(join(tmpdir(), ".epic-orchestrator-merge-"));
    const git = (...args: string[]) => execFileSync("git", args, { cwd: repoPath, encoding: "utf8" }).trim();

    try {
      git("init");
      git("config", "user.email", "orchestrator@example.test");
      git("config", "user.name", "Epic Orchestrator Test");
      writeFileSync(join(repoPath, "base.txt"), "base\n");
      git("add", ".");
      git("commit", "-m", "base");
      const baseCommit = git("rev-parse", "HEAD");

      git("switch", "-c", "family/217");
      writeFileSync(join(repoPath, "family.txt"), "family\n");
      git("add", ".");
      git("commit", "-m", "family progress");
      const familyHead = git("rev-parse", "HEAD");

      git("switch", "-c", "slice-220", baseCommit);
      writeFileSync(join(repoPath, "slice.txt"), "slice\n");
      git("add", ".");
      git("commit", "-m", "slice implementation");
      const sliceCommit = git("rev-parse", "HEAD");

      const result: any = await runEpicSingleSlicePipeline({
        args: { epicIssueNumber: 217, familyBranch: "family/217", verifyCommands: ["npm --prefix web test"] },
        log: () => undefined,
        agent: async () => ({
          commit: sliceCommit,
          worktreePath: repoPath,
          observabilityEvidence: { loudFailure: true, locatorLogs: true, notApplicableReason: "tooling slice" }
        }),
        Bash: async (command: string) => {
          if (command.includes("/sub_issues")) {
            return JSON.stringify({
              epicId: 217,
              issues: [{ id: 220, epicId: 217, state: "open", title: "S2", url: "https://example.test/220" }],
              blockedBy: []
            });
          }
          if (command.includes("reviewer=codex")) return JSON.stringify({ status: "passed", findings: [] });
          if (command.includes("reviewer=agy")) return JSON.stringify({ status: "passed", findings: [] });
          if (command.includes("merge reviewed commit")) {
            return execFileSync("bash", ["-l", "-c", command], { encoding: "utf8" });
          }
          return JSON.stringify({ status: "passed" });
        }
      });

      expect(result.merge).toMatchObject({ status: "merged", familyBranch: "family/217", reviewedCommit: sliceCommit });
      const mergeParents = git("rev-list", "--parents", "-n", "1", result.merge.mergeCommit).split(" ").slice(1);
      expect(mergeParents).toEqual([familyHead, sliceCommit]);
    } finally {
      rmSync(repoPath, { recursive: true, force: true });
    }
  });

  it("stops before review and merge when local verification fails", async () => {
    const calls: string[] = [];

    const result: any = await runEpicSingleSlicePipeline({
      args: { epicIssueNumber: 217, verifyCommands: ["npm --prefix web test"] },
      log: () => undefined,
      agent: async () => ({
        commit: "abc123",
        worktreePath: "/repo/.worktrees/issue-220",
        observabilityEvidence: { loudFailure: true, locatorLogs: true, notApplicableReason: "tooling slice" }
      }),
      Bash: async (command: string) => {
        calls.push(command);
        if (command.includes("/sub_issues")) {
          return JSON.stringify({
            epicId: 217,
            issues: [{ id: 220, epicId: 217, state: "open", title: "S2", url: "https://example.test/220" }],
            blockedBy: []
          });
        }
        if (command.includes("npm --prefix web test")) return JSON.stringify({ status: "failed", output: "red" });
        return JSON.stringify({ status: "passed" });
      }
    });

    expect(result.status).toBe("verify_failed");
    expect(result.review).toBeUndefined();
    expect(result.merge).toBeUndefined();
    expect(calls.join("\n")).not.toContain("reviewer=codex");
    expect(calls.join("\n")).not.toContain("merge reviewed commit");
  });

  it("verifies the exact clean worktree commit before local verification", async () => {
    const calls: string[] = [];

    await runEpicSingleSlicePipeline({
      args: { epicIssueNumber: 217, familyBranch: "family/217", verifyCommands: ["npm --prefix web test"] },
      log: () => undefined,
      agent: async () => ({
        commit: "abc123",
        worktreePath: "/repo/.worktrees/issue-220",
        observabilityEvidence: { loudFailure: true, locatorLogs: true, notApplicableReason: "tooling slice" }
      }),
      Bash: async (command: string) => {
        calls.push(command);
        if (command.includes("/sub_issues")) {
          return JSON.stringify({
            epicId: 217,
            issues: [{ id: 220, epicId: 217, state: "open", title: "S2", url: "https://example.test/220" }],
            blockedBy: []
          });
        }
        if (command.includes("reviewer=codex")) return JSON.stringify({ status: "passed", findings: [] });
        if (command.includes("reviewer=agy")) return JSON.stringify({ status: "passed", findings: [] });
        if (command.includes("merge reviewed commit")) return JSON.stringify({ mergeCommit: "merge789" });
        return JSON.stringify({ status: "passed" });
      }
    });

    const guardCommand = calls.find((command) => command.includes("为切片执行 I7 commit 纪律检查"));
    expect(guardCommand).toContain("rev-parse HEAD");
    expect(guardCommand).toContain("implementedCommit");
    expect(guardCommand).toContain("status --porcelain");
    expect(guardCommand).not.toContain("diff --quiet");
  });

  it("reruns the same slice after review failure, re-verifies, re-reviews, and merges the new reviewed commit", async () => {
    const calls: string[] = [];
    const agentCalls: any[] = [];

    const result: any = await runEpicSingleSlicePipeline({
      args: { epicIssueNumber: 217, familyBranch: "family/217", verifyCommands: ["npm --prefix web test"], maxReviewRounds: 2 },
      log: () => undefined,
      agent: async (request: any) => {
        agentCalls.push(request);
        const commit = agentCalls.length === 1 ? "abc123" : "fix456";
        return {
          commit,
          worktreePath: "/repo/.worktrees/issue-220",
          observabilityEvidence: { loudFailure: true, locatorLogs: true, notApplicableReason: "tooling slice" }
        };
      },
      Bash: async (command: string) => {
        calls.push(command);
        if (command.includes("/sub_issues")) {
          return JSON.stringify({
            epicId: 217,
            issues: [{ id: 220, epicId: 217, state: "open", title: "S2", url: "https://example.test/220" }],
            blockedBy: []
          });
        }
        if (command.includes("reviewer=codex") && command.includes("abc123")) return JSON.stringify({ status: "failed", findings: [{ severity: "P1", issue: "missing retry" }] });
        if (command.includes("reviewer=agy") && command.includes("abc123")) return JSON.stringify({ status: "passed", findings: [] });
        if (command.includes("reviewer=codex")) return JSON.stringify({ status: "passed", findings: [] });
        if (command.includes("reviewer=agy")) return JSON.stringify({ status: "passed", findings: [], diffOnly: true });
        if (command.includes("merge reviewed commit")) return JSON.stringify({ mergeCommit: "merge789" });
        return JSON.stringify({ status: "passed" });
      }
    });

    expect(result.status).toBe("merged");
    expect(agentCalls).toHaveLength(2);
    expect(agentCalls[1]).toMatchObject({
      isolation: "worktree",
      issueNumber: 220,
      reviewFix: { failedCommit: "abc123" }
    });
    expect(JSON.stringify(agentCalls[1])).toContain("missing retry");
    expect(result.implementation).toEqual({ commit: "fix456", worktreePath: "/repo/.worktrees/issue-220" });
    expect(result.reviewAttempts.map((attempt: any) => attempt.commit)).toEqual(["abc123", "fix456"]);
    expect(result.verificationAttempts.map((attempt: any) => attempt.commit)).toEqual(["abc123", "fix456"]);
    expect(result.merge).toEqual({ status: "merged", familyBranch: "family/217", reviewedCommit: "fix456", mergeCommit: "merge789" });
    expect(result.i7).toEqual({ sliceCommit: "fix456", amendmentsForbidden: true, reviewFixesRequireNewCommits: true, reviewFixCommits: ["fix456"] });
    expect(calls.join("\n")).toContain("fix456");
  });

  it("requires each review-fix commit to descend from the failed reviewed commit", async () => {
    const calls: string[] = [];
    const agentCalls: any[] = [];

    await runEpicSingleSlicePipeline({
      args: { epicIssueNumber: 217, familyBranch: "family/217", verifyCommands: ["npm --prefix web test"], maxReviewRounds: 2 },
      log: () => undefined,
      agent: async (request: any) => {
        agentCalls.push(request);
        return {
          commit: agentCalls.length === 1 ? "abc123" : "fix456",
          worktreePath: "/repo/.worktrees/issue-220",
          observabilityEvidence: { loudFailure: true, locatorLogs: true, notApplicableReason: "tooling slice" }
        };
      },
      Bash: async (command: string) => {
        calls.push(command);
        if (command.includes("/sub_issues")) {
          return JSON.stringify({
            epicId: 217,
            issues: [{ id: 220, epicId: 217, state: "open", title: "S2", url: "https://example.test/220" }],
            blockedBy: []
          });
        }
        if (command.includes("reviewer=codex") && command.includes("abc123")) return JSON.stringify({ status: "failed", findings: [{ severity: "P1", issue: "missing retry" }] });
        if (command.includes("reviewer=agy") && command.includes("abc123")) return JSON.stringify({ status: "passed", findings: [] });
        if (command.includes("reviewer=codex")) return JSON.stringify({ status: "passed", findings: [] });
        if (command.includes("reviewer=agy")) return JSON.stringify({ status: "passed", findings: [] });
        if (command.includes("merge reviewed commit")) return JSON.stringify({ mergeCommit: "merge789" });
        return JSON.stringify({ status: "passed" });
      }
    });

    const secondGuardCommand = calls.filter((command) => command.includes("为切片执行 I7 commit 纪律检查"))[1];
    expect(secondGuardCommand).toContain("merge-base --is-ancestor");
    expect(secondGuardCommand).toContain("abc123");
    expect(secondGuardCommand).toContain("fix456");
  });

  it("aborts loudly without merge when review failures exhaust the bounded same-slice retry budget", async () => {
    const calls: string[] = [];
    const agentCalls: unknown[] = [];

    const result: any = await runEpicSingleSlicePipeline({
      args: { epicIssueNumber: 217, familyBranch: "family/217", verifyCommands: ["npm --prefix web test"], maxReviewRounds: 2 },
      log: () => undefined,
      agent: async (request: unknown) => {
        agentCalls.push(request);
        return {
          commit: agentCalls.length === 1 ? "abc123" : "fix456",
          worktreePath: "/repo/.worktrees/issue-220",
          observabilityEvidence: { loudFailure: true, locatorLogs: true, notApplicableReason: "tooling slice" }
        };
      },
      Bash: async (command: string) => {
        calls.push(command);
        if (command.includes("/sub_issues")) {
          return JSON.stringify({
            epicId: 217,
            issues: [{ id: 220, epicId: 217, state: "open", title: "S2", url: "https://example.test/220" }],
            blockedBy: []
          });
        }
        if (command.includes("reviewer=codex")) return JSON.stringify({ status: "failed", findings: [{ severity: "P1", issue: "still failing" }] });
        if (command.includes("reviewer=agy")) return JSON.stringify({ status: "passed", findings: [] });
        return JSON.stringify({ status: "passed" });
      }
    });

    expect(result.status).toBe("review_failed");
    expect(result.i1).toEqual({ status: "aborted", reason: "max_review_rounds", maxReviewRounds: 2 });
    expect(agentCalls).toHaveLength(2);
    expect(result.reviewAttempts.map((attempt: any) => attempt.commit)).toEqual(["abc123", "fix456"]);
    expect(result.merge).toBeUndefined();
    expect(calls.join("\n")).not.toContain("merge reviewed commit");
  });
});

describe("epic orchestrator S3 layered parallel pipeline", () => {
  it("captures startup target HEAD by fetching the configured remote branch and fails closed when unresolved", async () => {
    const commands: string[] = [];

    const result: any = await runEpicLayeredPipeline({
      args: { epicIssueNumber: 217, familyBranch: "family/217", verifyCommands: ["true"], targetBranch: "upstream/release" },
      log: () => undefined,
      agent: async (request: any) => ({
        commit: `commit-${request.issueNumber}`,
        worktreePath: `/repo/.worktrees/issue-${request.issueNumber}`,
        observabilityEvidence: { loudFailure: true, locatorLogs: true, notApplicableReason: "tooling slice" }
      }),
      Bash: async (command: string) => {
        commands.push(command);
        if (command.includes("/sub_issues")) return JSON.stringify({ epicId: 217, issues: [{ id: 220, epicId: 217, state: "open", title: "S2", url: "https://example.test/220" }], blockedBy: [] });
        if (command.includes("orchestrator base target HEAD capture")) return JSON.stringify({ status: "unresolved", targetBranch: "upstream/release" });
        if (command.includes("reviewer=codex")) return JSON.stringify({ status: "passed", findings: [] });
        if (command.includes("reviewer=agy")) return JSON.stringify({ status: "passed", findings: [] });
        if (command.includes("merge reviewed commit")) return JSON.stringify({ status: "merged", mergeCommit: "merge-220", mergeWorktree: "/repo/.epic-orchestrator/family" });
        if (command.includes("家族集成 verify")) return JSON.stringify({ status: "passed", exitCode: 0, output: "ok" });
        if (command.includes("base management")) {
          expect(command).toContain('if [ "$startupTargetHead" = "unknown" ]; then');
          return JSON.stringify({ status: "conflict", reason: "startup_target_head_unresolved" });
        }
        return JSON.stringify({ status: "passed" });
      }
    });

    const captureCommand = commands.find((command) => command.includes("orchestrator base target HEAD capture")) ?? "";
    expect(captureCommand).toContain('git fetch "$targetRemote" "+refs/heads/$targetRemoteBranch:refs/remotes/$targetRemote/$targetRemoteBranch"');
    expect(captureCommand).not.toContain("if [ \"$targetBranch\" = \"origin/main\" ]");
    expect(result.status).toBe("return_to_main_session");
    expect(result.reason).toBe("startup_target_head_unresolved");
    expect(result.i10).toEqual({ status: "aborted", reason: "startup_target_head_unresolved" });
  });

  it("passes the merged family base to dependent-layer slice agents after blockers merge", async () => {
    const calls: string[] = [];
    const agentCalls: any[] = [];

    const result: any = await runEpicLayeredPipeline({
      args: { epicIssueNumber: 217, familyBranch: "family/217", verifyCommands: ["npm --prefix web test"] },
      log: () => undefined,
      agent: async (request: any) => {
        agentCalls.push(request);
        return {
          commit: `commit-${request.issueNumber}`,
          worktreePath: `/repo/.worktrees/issue-${request.issueNumber}`,
          observabilityEvidence: { loudFailure: true, locatorLogs: true, notApplicableReason: "tooling slice" }
        };
      },
      Bash: async (command: string) => {
        calls.push(command);
        if (command.includes("/sub_issues")) {
          return JSON.stringify({
            epicId: 217,
            issues: [
              { id: 220, epicId: 217, state: "open", title: "S2-blocker", url: "https://example.test/220" },
              { id: 221, epicId: 217, state: "open", title: "S3-dependent", url: "https://example.test/221" }
            ],
            blockedBy: [{ issueId: 221, blockedByIssueId: 220 }]
          });
        }
        if (command.includes("为切片执行 I7 commit 纪律检查")) return JSON.stringify({ status: "passed" });
        if (command.includes("npm --prefix web test")) return JSON.stringify({ status: "passed" });
        if (command.includes("reviewer=codex")) return JSON.stringify({ status: "passed", findings: [] });
        if (command.includes("reviewer=agy")) return JSON.stringify({ status: "passed", findings: [] });
        if (command.includes("merge reviewed commit")) {
          const reviewedCommit = command.match(/implementedCommit='([^']+)'/)?.[1] ?? "unknown";
          return JSON.stringify({ mergeCommit: `merge-${reviewedCommit}`, mergeWorktree: "/repo/.epic-orchestrator/family" });
        }
        return JSON.stringify({ status: "passed" });
      }
    });

    expect(result.status).toBe("merged");
    const implementationCalls = agentCalls.filter((call) => call.role === undefined);
    expect(implementationCalls.map((call) => call.issueNumber)).toEqual([220, 221]);
    expect(implementationCalls[0]).not.toHaveProperty("baseRef");
    expect(implementationCalls[1]).toMatchObject({
      familyBranch: "family/217",
      baseBranch: "family/217",
      baseRef: "merge-commit-220",
      lastMergeCommit: "merge-commit-220",
      mergeQueue: [{ familyBranch: "family/217", reviewedCommit: "commit-220", mergeCommit: "merge-commit-220" }]
    });
    expect(implementationCalls[1].prompt).toContain("Base this worktree on family branch family/217 at merge-commit-220");
    const dependentGuardCommand = calls.filter((command) => command.includes("为切片执行 I7 commit 纪律检查"))[1];
    expect(dependentGuardCommand).toContain("baseRef=");
    expect(dependentGuardCommand).toContain("merge-commit-220");
    expect(dependentGuardCommand).toContain("merge-base --is-ancestor \"$baseRef\" \"$implementedCommit\"");
  });

  it("rejects non-positive maxReviewRounds before a layered slice loop can return undefined", async () => {
    await expect(runEpicLayeredPipeline({
      args: { epicIssueNumber: 217, familyBranch: "family/217", verifyCommands: ["npm --prefix web test"], maxReviewRounds: 0 },
      log: () => undefined,
      agent: async () => ({
        commit: "commit-220",
        worktreePath: "/repo/.worktrees/issue-220",
        observabilityEvidence: { loudFailure: true, locatorLogs: true, notApplicableReason: "tooling slice" }
      }),
      Bash: async (command: string) => {
        if (command.includes("/sub_issues")) {
          return JSON.stringify({
            epicId: 217,
            issues: [{ id: 220, epicId: 217, state: "open", title: "S2", url: "https://example.test/220" }],
            blockedBy: []
          });
        }
        return JSON.stringify({ status: "passed" });
      }
    })).rejects.toThrow("maxReviewRounds 必须是正整数");
  });

  it("runs same-layer slices concurrently, waits at layer barriers, then merges reviewed commits serially", async () => {
    const events: string[] = [];
    const release: Record<string, () => void> = {};

    const resultPromise: Promise<any> = runEpicLayeredPipeline({
      args: { epicIssueNumber: 217, familyBranch: "family/217", verifyCommands: ["npm --prefix web test"] },
      log: () => undefined,
      agent: async (request: any) => {
        events.push(`agent-start-${request.issueNumber}`);
        if (request.issueNumber === 220 || request.issueNumber === 221) {
          await new Promise<void>((resolve) => {
            release[String(request.issueNumber)] = resolve;
          });
        }
        events.push(`agent-end-${request.issueNumber}`);
        return {
          commit: `commit-${request.issueNumber}`,
          worktreePath: `/repo/.worktrees/issue-${request.issueNumber}`,
          observabilityEvidence: { loudFailure: true, locatorLogs: true, notApplicableReason: "tooling slice" }
        };
      },
      Bash: async (command: string) => {
        if (command.includes("/sub_issues")) {
          return JSON.stringify({
            epicId: 217,
            issues: [
              { id: 220, epicId: 217, state: "open", title: "S2-A", url: "https://example.test/220" },
              { id: 221, epicId: 217, state: "open", title: "S2-B", url: "https://example.test/221" },
              { id: 222, epicId: 217, state: "open", title: "S2-dependent", url: "https://example.test/222" }
            ],
            blockedBy: [
              { issueId: 222, blockedByIssueId: 220 },
              { issueId: 222, blockedByIssueId: 221 }
            ]
          });
        }
        if (command.includes("为切片执行 I7 commit 纪律检查")) return JSON.stringify({ status: "passed" });
        if (command.includes("npm --prefix web test")) return JSON.stringify({ status: "passed" });
        if (command.includes("reviewer=codex")) return JSON.stringify({ status: "passed", findings: [] });
        if (command.includes("reviewer=agy")) return JSON.stringify({ status: "passed", findings: [] });
        if (command.includes("merge reviewed commit")) {
          const reviewedCommit = command.match(/implementedCommit='([^']+)'/)?.[1] ?? "unknown";
          events.push(`merge-${reviewedCommit}`);
          return JSON.stringify({ mergeCommit: `merge-${reviewedCommit}`, mergeWorktree: "/repo/.epic-orchestrator/family" });
        }
        return JSON.stringify({ status: "passed" });
      }
    });

    while (!release["220"] || !release["221"]) await new Promise((resolve) => setTimeout(resolve, 0));
    expect(events).toEqual(["agent-start-220", "agent-start-221"]);
    release["221"]();
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(events).not.toContain("agent-start-222");
    release["220"]();

    const result = await resultPromise;

    expect(events.indexOf("agent-start-222")).toBeGreaterThan(events.indexOf("agent-end-220"));
    expect(events.indexOf("agent-start-222")).toBeGreaterThan(events.indexOf("agent-end-221"));
    expect(events.filter((event) => event.startsWith("merge-"))).toEqual(["merge-commit-220", "merge-commit-221", "merge-commit-222"]);
    expect(result.status).toBe("merged");
    expect(result.layers.map((layer: any) => layer.issueNumbers)).toEqual([[220, 221], [222]]);
    expect(result.mergeQueue.map((entry: any) => entry.reviewedCommit)).toEqual(["commit-220", "commit-221", "commit-222"]);
  });

  it("merges reviewed commits from different slice worktrees through one dedicated family worktree", async () => {
    const repoPath = mkdtempSync(join(tmpdir(), ".epic-orchestrator-s3-"));
    const git = (cwd: string, ...args: string[]) => execFileSync("git", args, { cwd, encoding: "utf8" }).trim();

    try {
      git(repoPath, "init");
      git(repoPath, "config", "user.email", "orchestrator@example.test");
      git(repoPath, "config", "user.name", "Epic Orchestrator Test");
      writeFileSync(join(repoPath, "base.txt"), "base\n");
      git(repoPath, "add", ".");
      git(repoPath, "commit", "-m", "base");
      const baseCommit = git(repoPath, "rev-parse", "HEAD");

      const issue220Path = join(repoPath, ".worktrees", "issue-220");
      const issue221Path = join(repoPath, ".worktrees", "issue-221");
      git(repoPath, "worktree", "add", "-b", "slice-220", issue220Path, baseCommit);
      git(repoPath, "worktree", "add", "-b", "slice-221", issue221Path, baseCommit);
      writeFileSync(join(issue220Path, "slice-220.txt"), "slice 220\n");
      git(issue220Path, "add", ".");
      git(issue220Path, "commit", "-m", "slice 220");
      const commit220 = git(issue220Path, "rev-parse", "HEAD");
      writeFileSync(join(issue221Path, "slice-221.txt"), "slice 221\n");
      git(issue221Path, "add", ".");
      git(issue221Path, "commit", "-m", "slice 221");
      const commit221 = git(issue221Path, "rev-parse", "HEAD");

      const result: any = await runEpicLayeredPipeline({
        args: { epicIssueNumber: 217, familyBranch: "family/217", verifyCommands: ["npm --prefix web test"] },
        log: () => undefined,
        agent: async (request: any) => ({
          commit: request.issueNumber === 220 ? commit220 : commit221,
          worktreePath: request.issueNumber === 220 ? issue220Path : issue221Path,
          observabilityEvidence: { loudFailure: true, locatorLogs: true, notApplicableReason: "tooling slice" }
        }),
        Bash: async (command: string) => {
          if (command.includes("/sub_issues")) {
            return JSON.stringify({
              epicId: 217,
              issues: [
                { id: 220, epicId: 217, state: "open", title: "S2-A", url: "https://example.test/220" },
                { id: 221, epicId: 217, state: "open", title: "S2-B", url: "https://example.test/221" }
              ],
              blockedBy: []
            });
          }
          if (command.includes("reviewer=codex")) return JSON.stringify({ status: "passed", findings: [] });
          if (command.includes("reviewer=agy")) return JSON.stringify({ status: "passed", findings: [] });
          if (command.includes("为切片执行 I7 commit 纪律检查") || command.includes("merge reviewed commit")) {
            return execFileSync("bash", ["-l", "-c", command], { encoding: "utf8" });
          }
          return JSON.stringify({ status: "passed" });
        }
      });

      expect(result.status).toBe("merged");
      const mergeWorktrees = result.mergeQueue.map((entry: any) => entry.mergeWorktree);
      expect(mergeWorktrees[0]).toBeTruthy();
      expect(mergeWorktrees[1]).toBe(mergeWorktrees[0]);
      expect(mergeWorktrees[0].startsWith(repoPath)).toBe(false);
      const familyWorktrees = git(repoPath, "worktree", "list", "--porcelain").split("\n").filter((line: string) => line === "branch refs/heads/family/217");
      expect(familyWorktrees).toHaveLength(1);
      const finalParents = git(repoPath, "rev-list", "--parents", "-n", "1", result.mergeQueue.at(-1).mergeCommit).split(" ").slice(1);
      expect(finalParents).toContain(commit221);
      expect(git(repoPath, "merge-base", "--is-ancestor", commit220, result.mergeQueue.at(-1).mergeCommit)).toBe("");
    } finally {
      rmSync(repoPath, { recursive: true, force: true });
    }
  });

  it("replaces an existing non-worktree merge path instead of reusing a parent repository by upward traversal", async () => {
    const repoPath = mkdtempSync(join(tmpdir(), ".epic-orchestrator-strict-worktree-"));
    const git = (cwd: string, ...args: string[]) => execFileSync("git", args, { cwd, encoding: "utf8" }).trim();

    try {
      git(repoPath, "init");
      git(repoPath, "config", "user.email", "orchestrator@example.test");
      git(repoPath, "config", "user.name", "Epic Orchestrator Test");
      writeFileSync(join(repoPath, "base.txt"), "base\n");
      git(repoPath, "add", ".");
      git(repoPath, "commit", "-m", "base");
      const baseCommit = git(repoPath, "rev-parse", "HEAD");

      const sourcePath = join(repoPath, ".worktrees", "issue-220");
      git(repoPath, "worktree", "add", "-b", "slice-220", sourcePath, baseCommit);
      writeFileSync(join(sourcePath, "slice.txt"), "slice\n");
      git(sourcePath, "add", ".");
      git(sourcePath, "commit", "-m", "slice");
      const sliceCommit = git(sourcePath, "rev-parse", "HEAD");

      const sourceRoot = git(sourcePath, "rev-parse", "--show-toplevel");
      const expectedMergeWorktree = join(sourceRoot, "..", ".epic-orchestrator", "family-family_217");
      mkdirSync(expectedMergeWorktree, { recursive: true });
      writeFileSync(join(expectedMergeWorktree, "stale.txt"), "not a git worktree\n");

      const result: any = await runEpicLayeredPipeline({
        args: { epicIssueNumber: 217, familyBranch: "family/217", verifyCommands: ["true"] },
        log: () => undefined,
        agent: async () => ({
          commit: sliceCommit,
          worktreePath: sourcePath,
          observabilityEvidence: { loudFailure: true, locatorLogs: true, notApplicableReason: "tooling slice" }
        }),
        Bash: async (command: string) => {
          if (command.includes("/sub_issues")) return JSON.stringify({ epicId: 217, issues: [{ id: 220, epicId: 217, state: "open", title: "S2", url: "https://example.test/220" }], blockedBy: [] });
          if (command.includes("reviewer=codex")) return JSON.stringify({ status: "passed", findings: [] });
          if (command.includes("reviewer=agy")) return JSON.stringify({ status: "passed", findings: [] });
          if (command.includes("为切片执行 I7 commit 纪律检查") || command.includes("merge reviewed commit")) {
            return execFileSync("bash", ["-l", "-c", command], { encoding: "utf8" });
          }
          return JSON.stringify({ status: "passed", exitCode: 0, output: "ok" });
        }
      });

      expect(result.status).toBe("merged");
      expect(result.mergeQueue[0].mergeWorktree).toBe(expectedMergeWorktree);
      expect(git(expectedMergeWorktree, "rev-parse", "--abbrev-ref", "HEAD")).toBe("family/217");
      expect(git(repoPath, "rev-parse", "HEAD")).toBe(baseCommit);
    } finally {
      rmSync(repoPath, { recursive: true, force: true });
    }
  });

  it("uses Python 3.8-compatible worktree porcelain parsing in the merge script", async () => {
    let mergeCommand = "";

    await runEpicLayeredPipeline({
      args: { epicIssueNumber: 217, familyBranch: "family/217", verifyCommands: ["npm --prefix web test"] },
      log: () => undefined,
      agent: async () => ({
        commit: "commit-220",
        worktreePath: "/repo/.worktrees/issue-220",
        observabilityEvidence: { loudFailure: true, locatorLogs: true, notApplicableReason: "tooling slice" }
      }),
      Bash: async (command: string) => {
        if (command.includes("/sub_issues")) {
          return JSON.stringify({
            epicId: 217,
            issues: [{ id: 220, epicId: 217, state: "open", title: "S2", url: "https://example.test/220" }],
            blockedBy: []
          });
        }
        if (command.includes("reviewer=codex")) return JSON.stringify({ status: "passed", findings: [] });
        if (command.includes("reviewer=agy")) return JSON.stringify({ status: "passed", findings: [] });
        if (command.includes("merge reviewed commit")) {
          mergeCommand = command;
          return JSON.stringify({ mergeCommit: "merge-commit-220" });
        }
        return JSON.stringify({ status: "passed" });
      }
    });

    expect(mergeCommand).toContain("current = line[9:]");
    expect(mergeCommand).not.toContain("removeprefix");
  });

  it("rejects a first-layer slice whose commit does not descend from the startup target head", async () => {
    const parentPath = mkdtempSync(join(tmpdir(), ".epic-orchestrator-stale-base-"));
    const repoPath = join(parentPath, "repo");
    mkdirSync(repoPath);
    const git = (cwd: string, ...args: string[]) => execFileSync("git", args, { cwd, encoding: "utf8" }).trim();
    const agentCalls: any[] = [];

    try {
      git(repoPath, "init");
      git(repoPath, "config", "user.email", "orchestrator@example.test");
      git(repoPath, "config", "user.name", "Epic Orchestrator Test");
      git(repoPath, "branch", "-M", "main");
      writeFileSync(join(repoPath, "base.txt"), "old target\n");
      git(repoPath, "add", ".");
      git(repoPath, "commit", "-m", "old target");
      const oldTargetHead = git(repoPath, "rev-parse", "HEAD");

      writeFileSync(join(repoPath, "target.txt"), "startup target\n");
      git(repoPath, "add", ".");
      git(repoPath, "commit", "-m", "startup target");
      const startupTargetHead = git(repoPath, "rev-parse", "HEAD");

      const slicePath = join(repoPath, ".worktrees", "issue-220");
      git(repoPath, "worktree", "add", "-b", "slice-220", slicePath, oldTargetHead);
      writeFileSync(join(slicePath, "slice.txt"), "stale first-layer slice\n");
      git(slicePath, "add", ".");
      git(slicePath, "commit", "-m", "stale slice");
      const staleSliceCommit = git(slicePath, "rev-parse", "HEAD");

      await expect(runEpicLayeredPipeline({
        args: { epicIssueNumber: 217, familyBranch: "family/217", verifyCommands: ["true"], startupTargetHead, targetBranch: "main" },
        log: () => undefined,
        agent: async (request: any) => {
          agentCalls.push(request);
          return {
            commit: staleSliceCommit,
            worktreePath: slicePath,
            observabilityEvidence: { loudFailure: true, locatorLogs: true, notApplicableReason: "tooling slice" }
          };
        },
        Bash: async (command: string) => {
          if (command.includes("/sub_issues")) return JSON.stringify({ epicId: 217, issues: [{ id: 220, epicId: 217, state: "open", title: "S2", url: "https://example.test/220" }], blockedBy: [] });
          if (command.includes("reviewer=codex")) return JSON.stringify({ status: "passed", findings: [] });
          if (command.includes("reviewer=agy")) return JSON.stringify({ status: "passed", findings: [] });
          if (command.includes("家族集成 verify") || command.includes("npm --prefix web") || command.includes("\n( true )")) {
            return JSON.stringify({ status: "passed", exitCode: 0, output: "ok" });
          }
          return execFileSync("bash", ["-l", "-c", command], { encoding: "utf8" });
        }
      })).rejects.toThrow(/merge-base --is-ancestor/);

      expect(agentCalls[0]).toMatchObject({ baseRef: startupTargetHead, targetBranch: "main" });
      expect(agentCalls[0].prompt).toContain(startupTargetHead);
    } finally {
      rmSync(parentPath, { recursive: true, force: true });
    }
  });

  it("fails closed before slice execution when discovery has no open sub-issues", async () => {
    const commands: string[] = [];

    const result: any = await runEpicLayeredPipeline({
      args: { epicIssueNumber: 217, familyBranch: "family/217", verifyCommands: ["npm --prefix web test"], startupTargetHead: "base-start", targetBranch: "origin/main" },
      log: () => undefined,
      agent: async () => {
        throw new Error("must not run slice agents without open sub-issues");
      },
      Bash: async (command: string) => {
        commands.push(command);
        if (command.includes("/sub_issues")) return JSON.stringify({ epicId: 217, issues: [{ id: 220, epicId: 217, state: "closed", title: "S2", url: "https://example.test/220" }], blockedBy: [] });
        if (command.includes("merge reviewed commit")) throw new Error("must not merge without open sub-issues");
        if (command.includes("家族集成 verify") || command.includes("base management")) throw new Error("must not run I9/I10 without a family worktree");
        return JSON.stringify({ status: "passed" });
      }
    });

    expect(result.status).toBe("return_to_main_session");
    expect(result.reason).toBe("no_open_subissues");
    expect(result.i9).toEqual({ status: "aborted", reason: "no_open_subissues" });
    expect(result.merge).toBeUndefined();
    expect(commands.join("\n")).not.toContain("merge reviewed commit");
    expect(commands.join("\n")).not.toContain("家族集成 verify");
    expect(commands.join("\n")).not.toContain("base management");
  });

  it("returns to the main session instead of running family verify when no merge worktree is available", async () => {
    const commands: string[] = [];

    const result: any = await runEpicLayeredPipeline({
      args: { epicIssueNumber: 217, familyBranch: "family/217", verifyCommands: ["npm --prefix web test"], startupTargetHead: "base-start", targetBranch: "origin/main" },
      log: () => undefined,
      agent: async (request: any) => ({
        commit: `commit-${request.issueNumber}`,
        worktreePath: `/repo/.worktrees/issue-${request.issueNumber}`,
        observabilityEvidence: { loudFailure: true, locatorLogs: true, notApplicableReason: "tooling slice" }
      }),
      Bash: async (command: string) => {
        commands.push(command);
        if (command.includes("/sub_issues")) return JSON.stringify({ epicId: 217, issues: [{ id: 220, epicId: 217, state: "open", title: "S2", url: "https://example.test/220" }], blockedBy: [] });
        if (command.includes("reviewer=codex")) return JSON.stringify({ status: "passed", findings: [] });
        if (command.includes("reviewer=agy")) return JSON.stringify({ status: "passed", findings: [] });
        if (command.includes("merge reviewed commit")) return JSON.stringify({ status: "merged", mergeCommit: "merge-220" });
        if (command.includes("家族集成 verify") || command.includes("base management")) throw new Error("must not run I9/I10 without a family worktree");
        return JSON.stringify({ status: "passed" });
      }
    });

    expect(result.status).toBe("return_to_main_session");
    expect(result.reason).toBe("missing_family_worktree");
    expect(result.i9).toEqual({ status: "aborted", reason: "missing_family_worktree" });
    expect(commands.join("\n")).not.toContain("家族集成 verify");
    expect(commands.join("\n")).not.toContain("base management");
  });

  it("runs whole-family integration verify on the merged family worktree after all slices merge", async () => {
    const familyVerifyCommands: string[] = [];

    const result: any = await runEpicLayeredPipeline({
      args: { epicIssueNumber: 217, familyBranch: "family/217", verifyCommands: ["npm --prefix web test"], startupTargetHead: "base-start", targetBranch: "origin/main" },
      log: () => undefined,
      agent: async (request: any) => ({
        commit: `commit-${request.issueNumber}`,
        worktreePath: `/repo/.worktrees/issue-${request.issueNumber}`,
        observabilityEvidence: { loudFailure: true, locatorLogs: true, notApplicableReason: "tooling slice" }
      }),
      Bash: async (command: string) => {
        if (command.includes("/sub_issues")) {
          return JSON.stringify({
            epicId: 217,
            issues: [{ id: 220, epicId: 217, state: "open", title: "S2", url: "https://example.test/220" }],
            blockedBy: []
          });
        }
        if (command.includes("reviewer=codex")) return JSON.stringify({ status: "passed", findings: [] });
        if (command.includes("reviewer=agy")) return JSON.stringify({ status: "passed", findings: [] });
        if (command.includes("merge reviewed commit")) return JSON.stringify({ status: "merged", mergeCommit: "merge-220", mergeWorktree: "/repo/.epic-orchestrator/family" });
        if (command.includes("家族集成 verify")) {
          familyVerifyCommands.push(command);
          expect(command).toContain("cd '/repo/.epic-orchestrator/family'");
          return JSON.stringify({ status: "passed", exitCode: 0, output: "family ok" });
        }
        if (command.includes("base management")) return JSON.stringify({ status: "no_drift", startupTargetHead: "base-start", currentTargetHead: "base-start" });
        return JSON.stringify({ status: "passed" });
      }
    });

    expect(result.status).toBe("merged");
    expect(result.familyVerification).toMatchObject({ status: "passed" });
    expect(result.baseManagement).toMatchObject({ status: "no_drift" });
    expect(familyVerifyCommands).toHaveLength(3);
  });

  it("stops before base management when whole-family integration verify fails", async () => {
    const commands: string[] = [];

    const result: any = await runEpicLayeredPipeline({
      args: { epicIssueNumber: 217, familyBranch: "family/217", verifyCommands: ["npm --prefix web test"], startupTargetHead: "base-start", targetBranch: "origin/main" },
      log: () => undefined,
      agent: async (request: any) => ({
        commit: `commit-${request.issueNumber}`,
        worktreePath: `/repo/.worktrees/issue-${request.issueNumber}`,
        observabilityEvidence: { loudFailure: true, locatorLogs: true, notApplicableReason: "tooling slice" }
      }),
      Bash: async (command: string) => {
        commands.push(command);
        if (command.includes("/sub_issues")) return JSON.stringify({ epicId: 217, issues: [{ id: 220, epicId: 217, state: "open", title: "S2", url: "https://example.test/220" }], blockedBy: [] });
        if (command.includes("reviewer=codex")) return JSON.stringify({ status: "passed", findings: [] });
        if (command.includes("reviewer=agy")) return JSON.stringify({ status: "passed", findings: [] });
        if (command.includes("merge reviewed commit")) return JSON.stringify({ status: "merged", mergeCommit: "merge-220", mergeWorktree: "/repo/.epic-orchestrator/family" });
        if (command.includes("家族集成 verify") && command.includes("npm --prefix web test")) return JSON.stringify({ status: "failed", exitCode: 1, output: "cross-slice failure" });
        if (command.includes("家族集成 verify")) return JSON.stringify({ status: "passed", exitCode: 0, output: "family ok" });
        if (command.includes("base management")) return JSON.stringify({ status: "no_drift" });
        return JSON.stringify({ status: "passed" });
      }
    });

    expect(result.status).toBe("family_verify_failed");
    expect(result.i9).toEqual({ status: "failed", reason: "family_integration_verify_failed" });
    expect(commands.join("\n")).not.toContain("base management");
  });

  it("rebases the family worktree when the startup target branch advanced and reruns family integration verify", async () => {
    const events: string[] = [];

    const result: any = await runEpicLayeredPipeline({
      args: { epicIssueNumber: 217, familyBranch: "family/217", verifyCommands: ["npm --prefix web test"], startupTargetHead: "base-start", targetBranch: "origin/main" },
      log: () => undefined,
      agent: async (request: any) => ({
        commit: `commit-${request.issueNumber}`,
        worktreePath: `/repo/.worktrees/issue-${request.issueNumber}`,
        observabilityEvidence: { loudFailure: true, locatorLogs: true, notApplicableReason: "tooling slice" }
      }),
      Bash: async (command: string) => {
        if (command.includes("/sub_issues")) {
          return JSON.stringify({ epicId: 217, issues: [{ id: 220, epicId: 217, state: "open", title: "S2", url: "https://example.test/220" }], blockedBy: [] });
        }
        if (command.includes("reviewer=codex")) return JSON.stringify({ status: "passed", findings: [] });
        if (command.includes("reviewer=agy")) return JSON.stringify({ status: "passed", findings: [] });
        if (command.includes("merge reviewed commit")) return JSON.stringify({ status: "merged", mergeCommit: "merge-220", mergeWorktree: "/repo/.epic-orchestrator/family" });
        if (command.includes("家族集成 verify")) {
          events.push("verify");
          return JSON.stringify({ status: "passed", exitCode: 0, output: "family ok" });
        }
        if (command.includes("base management")) {
          events.push("rebase");
          expect(command).toContain("rebase \"$currentTargetHead\"");
          return JSON.stringify({ status: "rebased", startupTargetHead: "base-start", currentTargetHead: "base-new", rebaseHead: "rebased-family" });
        }
        return JSON.stringify({ status: "passed" });
      }
    });

    expect(events).toEqual(["verify", "verify", "verify", "rebase", "verify", "verify", "verify"]);
    expect(result.baseManagement).toMatchObject({ status: "rebased", currentTargetHead: "base-new" });
    expect(result.mergeQueue.at(-1).mergeCommit).toBe("rebased-family");
    expect(result.mergeQueue.at(-1).familyHead).toBe("rebased-family");
    expect(result.merge?.mergeCommit).toBe("rebased-family");
    expect(result.merge?.familyHead).toBe("rebased-family");
    expect(result.familyVerificationAfterRebase).toMatchObject({ status: "passed" });
  });

  it("returns to the main session when base rebase conflicts before family CMR", async () => {
    const result: any = await runEpicLayeredPipeline({
      args: { epicIssueNumber: 217, familyBranch: "family/217", verifyCommands: ["npm --prefix web test"], startupTargetHead: "base-start", targetBranch: "origin/main" },
      log: () => undefined,
      agent: async (request: any) => ({
        commit: `commit-${request.issueNumber}`,
        worktreePath: `/repo/.worktrees/issue-${request.issueNumber}`,
        observabilityEvidence: { loudFailure: true, locatorLogs: true, notApplicableReason: "tooling slice" }
      }),
      Bash: async (command: string) => {
        if (command.includes("/sub_issues")) return JSON.stringify({ epicId: 217, issues: [{ id: 220, epicId: 217, state: "open", title: "S2", url: "https://example.test/220" }], blockedBy: [] });
        if (command.includes("reviewer=codex")) return JSON.stringify({ status: "passed", findings: [] });
        if (command.includes("reviewer=agy")) return JSON.stringify({ status: "passed", findings: [] });
        if (command.includes("merge reviewed commit")) return JSON.stringify({ status: "merged", mergeCommit: "merge-220", mergeWorktree: "/repo/.epic-orchestrator/family" });
        if (command.includes("家族集成 verify")) return JSON.stringify({ status: "passed", exitCode: 0, output: "family ok" });
        if (command.includes("base management")) return JSON.stringify({ status: "conflict", reason: "base_rebase_conflict", output: "CONFLICT" });
        return JSON.stringify({ status: "passed" });
      }
    });

    expect(result.status).toBe("return_to_main_session");
    expect(result.reason).toBe("base_rebase_conflict");
    expect(result.i10).toEqual({ status: "aborted", reason: "base_rebase_conflict" });
  });
  it("returns to the main session when the serial merge queue hits an unresolved conflict", async () => {
    const result: any = await runEpicLayeredPipeline({
      args: { epicIssueNumber: 217, familyBranch: "family/217", verifyCommands: ["npm --prefix web test"] },
      log: () => undefined,
      agent: async (request: any) => ({
        commit: `commit-${request.issueNumber}`,
        worktreePath: `/repo/.worktrees/issue-${request.issueNumber}`,
        observabilityEvidence: { loudFailure: true, locatorLogs: true, notApplicableReason: "tooling slice" }
      }),
      Bash: async (command: string) => {
        if (command.includes("/sub_issues")) {
          return JSON.stringify({
            epicId: 217,
            issues: [
              { id: 220, epicId: 217, state: "open", title: "S2-A", url: "https://example.test/220" },
              { id: 221, epicId: 217, state: "open", title: "S2-B", url: "https://example.test/221" }
            ],
            blockedBy: []
          });
        }
        if (command.includes("reviewer=codex")) return JSON.stringify({ status: "passed", findings: [] });
        if (command.includes("reviewer=agy")) return JSON.stringify({ status: "passed", findings: [] });
        if (command.includes("merge reviewed commit") && command.includes("commit-221")) {
          return JSON.stringify({ status: "conflict", reason: "merge conflict", output: "CONFLICT (content): file.txt" });
        }
        if (command.includes("merge reviewed commit")) return JSON.stringify({ mergeCommit: "merge-ok" });
        return JSON.stringify({ status: "passed" });
      }
    });

    expect(result.status).toBe("return_to_main_session");
    expect(result.i4).toEqual({ status: "aborted", reason: "merge_conflict" });
    expect(result.mergeQueue.map((entry: any) => entry.status)).toEqual(["merged", "conflict"]);
  });
});

describe("epic orchestrator workflow inline familyReviewGate drift guard", () => {
  it("matches the S4b familyReviewGate authority across the full decision battery", () => {
    const battery: FamilyReviewGateInput[] = [
      { escalateCount: 1, mechanicalCount: 0, round: 1, maxRounds: 3 },
      { escalateCount: 1, mechanicalCount: 5, round: 1, maxRounds: 3 },
      { escalateCount: 1, mechanicalCount: 0, round: 3, maxRounds: 3 },
      { escalateCount: 0, mechanicalCount: 0, round: 1, maxRounds: 3 },
      { escalateCount: 0, mechanicalCount: 2, round: 1, maxRounds: 3 },
      { escalateCount: 0, mechanicalCount: 1, round: 2, maxRounds: 3 },
      { escalateCount: 0, mechanicalCount: 1, round: 3, maxRounds: 3 },
      { escalateCount: 0, mechanicalCount: 1, round: 4, maxRounds: 3 },
      { escalateCount: 0, mechanicalCount: 0, round: 3, maxRounds: 3 },
      { escalateCount: 2, mechanicalCount: 2, round: 3, maxRounds: 3 },
      { escalateCount: 0, mechanicalCount: 7, round: 1, maxRounds: 1 }
    ];

    for (const input of battery) {
      expect(inlineFamilyReviewGate(input)).toBe(familyReviewGate(input));
    }
  });

  it("matches the routeFindings authority across classification mixes", () => {
    const battery: Finding[][] = [
      [],
      [{ id: "F1", classification: "mechanical_bug" }],
      [{ id: "F1", classification: "choice" }],
      [{ id: "F1", classification: "ambiguous" }],
      [{ id: "F1" }],
      [{ id: "F1", classification: "mechanical_bug" }, { id: "F2", classification: "choice" }],
      [{ id: "F1", classification: "mechanical_bug" }, { id: "F2", classification: "mechanical_bug" }]
    ];

    for (const findings of battery) {
      expect(inlineRouteFindings(findings)).toEqual(routeFindings(findings));
    }

    // null/undefined entries must be handled identically by both copies (kernel had no guard before).
    const withNulls = [null, { id: "F1", classification: "mechanical_bug" }, undefined] as unknown as Finding[];
    expect(inlineRouteFindings(withNulls)).toEqual(routeFindings(withNulls));
  });

  it("matches the family_5a_5b judgeReviewDegradation authority across availability mixes", () => {
    const battery: ModelReviewResult[][] = [
      [{ model: "codex", available: true }, { model: "claude", available: true }, { model: "agy", available: true }],
      [{ model: "codex", available: true }, { model: "claude", available: true }, { model: "agy", available: false, reason: "quota" }],
      [{ model: "codex", available: true }, { model: "claude", available: false }, { model: "agy", available: false }],
      [{ model: "codex", available: false }, { model: "claude", available: false }, { model: "agy", available: false }],
      [{ model: "codex", available: true }, { model: "codex", available: true }, { model: "agy", available: false }]
    ];

    for (const results of battery) {
      expect(inlineJudgeFamilyDegradation(results)).toEqual(judgeReviewDegradation({ stage: "family_5a_5b", results }));
    }
  });
});

describe("epic orchestrator S4b family 5a/5b CMR", () => {
  // Drives the layered pipeline straight through to the family-review phase: every slice
  // implements, verifies, per-slice reviews, merges; family integration verify + base
  // management pass; then the 5a/5b family CMR runs. The familyReview hook lets each test
  // script the codex-family / agy-family Bash legs and the Claude review/fix agent legs.
  async function runToFamilyReview({ familyReview }: { familyReview: (round: number) => any }) {
    const agentCalls: any[] = [];
    const bashCalls: string[] = [];
    let cmrRound = 0;

    const result: any = await runEpicLayeredPipeline({
      args: { epicIssueNumber: 217, familyBranch: "family/217", verifyCommands: ["npm --prefix web test"], startupTargetHead: "base-start", targetBranch: "origin/main", maxReviewRounds: 3 },
      log: () => undefined,
      agent: async (request: any) => {
        agentCalls.push(request);
        if (request.role === "family_review") {
          return familyReview(request.round).claude ?? { findings: [] };
        }
        if (request.role === "family_review_fix") {
          return { fixed: true };
        }
        return {
          commit: `commit-${request.issueNumber}`,
          worktreePath: `/repo/.worktrees/issue-${request.issueNumber}`,
          observabilityEvidence: { loudFailure: true, locatorLogs: true, notApplicableReason: "tooling slice" }
        };
      },
      Bash: async (command: string) => {
        bashCalls.push(command);
        if (command.includes("family-review reviewed HEAD")) return "reviewed-head-sha";
        if (command.includes("/sub_issues")) return JSON.stringify({ epicId: 217, issues: [{ id: 220, epicId: 217, state: "open", title: "S2", url: "https://example.test/220" }], blockedBy: [] });
        if (command.includes("reviewer=codex-family")) return JSON.stringify(familyReview(cmrRound + 1).codex ?? { status: "passed", findings: [] });
        if (command.includes("reviewer=agy-family")) {
          const reply = JSON.stringify(familyReview(cmrRound + 1).agy ?? { status: "passed", findings: [] });
          cmrRound += 1;
          return reply;
        }
        if (command.includes("reviewer=codex")) return JSON.stringify({ status: "passed", findings: [] });
        if (command.includes("reviewer=agy")) return JSON.stringify({ status: "passed", findings: [] });
        if (command.includes("merge reviewed commit")) return JSON.stringify({ status: "merged", mergeCommit: "merge-220", mergeWorktree: "/repo/.epic-orchestrator/family" });
        if (command.includes("家族集成 verify")) return JSON.stringify({ status: "passed", exitCode: 0, output: "family ok" });
        if (command.includes("base management")) return JSON.stringify({ status: "no_drift", startupTargetHead: "base-start", currentTargetHead: "base-start" });
        return JSON.stringify({ status: "passed" });
      }
    });

    return { result, agentCalls, bashCalls };
  }

  it("runs codex+Claude+agy on the merged family branch (agy diff-based with review instructions) and converges clean", async () => {
    const { result, agentCalls, bashCalls } = await runToFamilyReview({
      familyReview: () => ({ codex: { status: "passed", findings: [] }, agy: { status: "passed", findings: [] }, claude: { findings: [] } })
    });

    expect(result.status).toBe("merged");
    expect(result.familyReview).toMatchObject({ status: "converged", round: 1 });
    expect(result.outOfScope).toEqual(["online_pr_review_loop"]);
    expect(result.outOfScope).not.toContain("family_5a_5b");

    const codexFamily = bashCalls.find((command) => command.includes("reviewer=codex-family")) ?? "";
    const agyFamily = bashCalls.find((command) => command.includes("reviewer=agy-family")) ?? "";
    expect(codexFamily).toContain("cd '/repo/.epic-orchestrator/family'");
    expect(codexFamily).toContain("codex exec --skip-git-repo-check --ephemeral -");
    expect(agyFamily).toContain("cd '/repo/.epic-orchestrator/family'");
    expect(agyFamily).toContain("agy --sandbox --print ''");
    // agy gets real review instructions + JSON schema on stdin (not a bare diff) and a hard read-only constraint.
    expect(agyFamily).toContain("REVIEW ONLY");
    expect(agyFamily).toContain("Return only one JSON object");
    expect(agyFamily).toContain("cross-slice completeness (5a)");
    // both legs diff against the I10 startup target base (base-start), not a hardcoded origin/main.
    expect(codexFamily).toContain("git rev-parse 'base-start^{commit}'");
    expect(agyFamily).toContain("git rev-parse 'base-start^{commit}'");

    const claudeReviewCall = agentCalls.find((call) => call.role === "family_review");
    expect(claudeReviewCall).toBeTruthy();
    expect(claudeReviewCall.familyBranch).toBe("family/217");
  });

  it("autonomously fixes a mechanical bug then converges on the next clean round and merges", async () => {
    const { result, agentCalls } = await runToFamilyReview({
      familyReview: (round: number) =>
        round === 1
          ? { codex: { status: "failed", findings: [{ id: "F1", classification: "mechanical_bug", location: "a.ts" }] }, agy: { status: "passed", findings: [] }, claude: { findings: [] } }
          : { codex: { status: "passed", findings: [] }, agy: { status: "passed", findings: [] }, claude: { findings: [] } }
    });

    expect(result.status).toBe("merged");
    expect(result.familyReview.status).toBe("converged");
    expect(result.familyReview.round).toBe(2);
    expect(result.outOfScope).not.toContain("family_5a_5b");
    const fixCall = agentCalls.find((call) => call.role === "family_review_fix");
    expect(fixCall).toBeTruthy();
    expect(fixCall.autonomousBugFindings).toEqual([{ id: "F1", classification: "mechanical_bug", location: "a.ts" }]);
    // a fix round advanced the family HEAD, so the merge entry must report the reviewed HEAD, not the stale pre-review commit.
    expect(result.merge.familyHead).toBe("reviewed-head-sha");
    expect(result.merge.mergeCommit).toBe("reviewed-head-sha");
  });

  it("escalates to the main session when a decision finding appears (ambiguous defaults to choice)", async () => {
    const { result, agentCalls } = await runToFamilyReview({
      familyReview: () => ({
        codex: { status: "failed", findings: [{ id: "F1", classification: "mechanical_bug" }] },
        agy: { status: "failed", findings: [{ id: "F2", classification: "ambiguous", claim_quote: "unclear contract" }] },
        claude: { findings: [] }
      })
    });

    expect(result.status).toBe("return_to_main_session");
    expect(result.reason).toBe("family_review_needs_decision");
    expect(result.decisionFindings).toEqual([{ id: "F2", classification: "ambiguous", claim_quote: "unclear contract" }]);
    expect(result.i5).toMatchObject({ status: "escalated", reason: "decision_findings" });
    expect(result.outOfScope).toContain("online_pr_review_loop");
    expect(agentCalls.some((call) => call.role === "family_review_fix")).toBe(false);
  });

  it("aborts (I1) when mechanical bugs never converge before maxReviewRounds", async () => {
    const { result } = await runToFamilyReview({
      familyReview: () => ({
        codex: { status: "failed", findings: [{ id: "F1", classification: "mechanical_bug" }] },
        agy: { status: "passed", findings: [] },
        claude: { findings: [] }
      })
    });

    expect(result.status).toBe("return_to_main_session");
    expect(result.reason).toBe("family_review_unconverged");
    expect(result.i1).toEqual({ status: "aborted", reason: "max_review_rounds", maxReviewRounds: 3 });
  });

  it("halts and returns to the main session when fewer than two family models are available (I2)", async () => {
    const result: any = await runEpicLayeredPipeline({
      args: { epicIssueNumber: 217, familyBranch: "family/217", verifyCommands: ["npm --prefix web test"], startupTargetHead: "base-start", targetBranch: "origin/main", maxReviewRounds: 3 },
      log: () => undefined,
      agent: async (request: any) => {
        if (request.role === "family_review") return { available: false, reason: "claude quota", findings: [] };
        if (request.role === "family_review_fix") return { fixed: true };
        return {
          commit: `commit-${request.issueNumber}`,
          worktreePath: `/repo/.worktrees/issue-${request.issueNumber}`,
          observabilityEvidence: { loudFailure: true, locatorLogs: true, notApplicableReason: "tooling slice" }
        };
      },
      Bash: async (command: string) => {
        if (command.includes("/sub_issues")) return JSON.stringify({ epicId: 217, issues: [{ id: 220, epicId: 217, state: "open", title: "S2", url: "https://example.test/220" }], blockedBy: [] });
        if (command.includes("reviewer=codex-family")) return JSON.stringify({ status: "passed", findings: [] });
        if (command.includes("reviewer=agy-family")) throw new Error("agy not logged in");
        if (command.includes("reviewer=codex")) return JSON.stringify({ status: "passed", findings: [] });
        if (command.includes("reviewer=agy")) return JSON.stringify({ status: "passed", findings: [] });
        if (command.includes("merge reviewed commit")) return JSON.stringify({ status: "merged", mergeCommit: "merge-220", mergeWorktree: "/repo/.epic-orchestrator/family" });
        if (command.includes("家族集成 verify")) return JSON.stringify({ status: "passed", exitCode: 0, output: "family ok" });
        if (command.includes("base management")) return JSON.stringify({ status: "no_drift", startupTargetHead: "base-start", currentTargetHead: "base-start" });
        return JSON.stringify({ status: "passed" });
      }
    });

    expect(result.status).toBe("return_to_main_session");
    expect(result.reason).toBe("review_degraded");
    expect(result.i2).toMatchObject({ status: "halt", stage: "family_5a_5b" });
    expect(result.i2.availableModels).toEqual(["codex"]);
    // halt = the gate never ran (degraded before review), so family_5a_5b stays out of scope.
    expect(result.outOfScope).toContain("family_5a_5b");
  });

  it("never triggers the online PR review loop on a converged family review (online_pr_review_loop stays out of scope)", async () => {
    const { result, bashCalls, agentCalls } = await runToFamilyReview({
      familyReview: () => ({ codex: { status: "passed", findings: [] }, agy: { status: "passed", findings: [] }, claude: { findings: [] } })
    });

    expect(result.status).toBe("merged");
    expect(result.outOfScope).toContain("online_pr_review_loop");
    expect(bashCalls.join("\n")).not.toContain("gh pr create");
    expect(bashCalls.join("\n")).not.toContain("pr-review-loop");
    expect(agentCalls.some((call) => call.role === "online_review" || call.role === "pr_review_loop")).toBe(false);
  });
});
