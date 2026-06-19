import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { layerEpicIssues, type TopologyInput } from "./orchestratorKernel";
// @ts-ignore Workflow scripts are plain JavaScript outside the web src TypeScript program.
import { inlineLayerEpicIssues, normalizeWorkflowArgs, runEpicDiscoveryWorkflow, runEpicLayeredPipeline, runEpicSingleSlicePipeline } from "../orchestrator/epicOrchestrator.workflow.js";

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

    const guardCommand = calls.find((command) => command.includes("enforce I7 commit discipline"));
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

    const secondGuardCommand = calls.filter((command) => command.includes("enforce I7 commit discipline"))[1];
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
        if (command.includes("enforce I7 commit discipline")) return JSON.stringify({ status: "passed" });
        if (command.includes("npm --prefix web test")) return JSON.stringify({ status: "passed" });
        if (command.includes("reviewer=codex")) return JSON.stringify({ status: "passed", findings: [] });
        if (command.includes("reviewer=agy")) return JSON.stringify({ status: "passed", findings: [] });
        if (command.includes("merge reviewed commit")) {
          const reviewedCommit = command.match(/implementedCommit='([^']+)'/)?.[1] ?? "unknown";
          events.push(`merge-${reviewedCommit}`);
          return JSON.stringify({ mergeCommit: `merge-${reviewedCommit}` });
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
          if (command.includes("enforce I7 commit discipline") || command.includes("merge reviewed commit")) {
            return execFileSync("bash", ["-l", "-c", command], { encoding: "utf8" });
          }
          return JSON.stringify({ status: "passed" });
        }
      });

      expect(result.status).toBe("merged");
      const mergeWorktrees = result.mergeQueue.map((entry: any) => entry.mergeWorktree);
      expect(mergeWorktrees[0]).toBeTruthy();
      expect(mergeWorktrees[1]).toBe(mergeWorktrees[0]);
      const familyWorktrees = git(repoPath, "worktree", "list", "--porcelain").split("\n").filter((line: string) => line === "branch refs/heads/family/217");
      expect(familyWorktrees).toHaveLength(1);
      const finalParents = git(repoPath, "rev-list", "--parents", "-n", "1", result.mergeQueue.at(-1).mergeCommit).split(" ").slice(1);
      expect(finalParents).toContain(commit221);
      expect(git(repoPath, "merge-base", "--is-ancestor", commit220, result.mergeQueue.at(-1).mergeCommit)).toBe("");
    } finally {
      rmSync(repoPath, { recursive: true, force: true });
    }
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
