import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { buildHandoffPayload, continuationPlan, dismissalGate, familyReviewGate, judgeReviewDegradation, layerEpicIssues, routeFindings, shipOutcome, type ContinuationInput, type DismissalGateInput, type FamilyReviewGateInput, type Finding, type HandoffInput, type ModelReviewResult, type ShipOutcomeInput, type TopologyInput } from "./orchestratorKernel";
// @ts-ignore Workflow scripts are plain JavaScript outside the web src TypeScript program.
import { inlineBuildHandoffPayload, inlineContinuationPlan, inlineDismissalGate, inlineFamilyReviewGate, inlineJudgeFamilyDegradation, inlineLayerEpicIssues, inlineRouteFindings, inlineShipOutcome, normalizeWorkflowArgs, runEpicDiscoveryWorkflow, runEpicLayeredPipeline, runEpicSingleSlicePipeline } from "../orchestrator/epicOrchestrator.workflow.js";

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
    // the prior handoff object uses `epic` (not `epicIssueNumber`) — accept it so the whole handoff
    // round-trips as relaunch args (alongside merged->mergedNumbers + baseAtStart->startupTargetHead).
    expect(normalizeWorkflowArgs({ epic: 217 })).toBe("217");
    expect(normalizeWorkflowArgs({ epic: 217, merged: [{ number: 220, reviewedCommit: "c220" }], baseAtStart: "sha", familyBranch: "family/217" })).toBe("217");
    expect(() => normalizeWorkflowArgs({ familyBranch: "family/217" })).toThrow("positive parent epic issue number"); // object with neither epic nor epicIssueNumber
  });

  it("rejects a familyBranch / targetBranch carrying a newline or control char (Bash comment-injection guard)", async () => {
    // discovery (gh sub_issues) runs first; the ref guard fires in normalizePipelineArgs right after,
    // before any ref reaches a Bash command. Mock discovery so the run reaches the guard.
    const harness = {
      log: () => undefined,
      agent: async () => ({}),
      Bash: async (command: string) =>
        command.includes("/sub_issues")
          ? JSON.stringify({ epicId: 217, issues: [{ id: 220, epicId: 217, state: "open", title: "S2", url: "https://example.test/220" }], blockedBy: [] })
          : "{}"
    };
    await expect(
      runEpicLayeredPipeline({ args: { epicIssueNumber: 217, familyBranch: "family/217\nrm -rf /" }, ...harness })
    ).rejects.toThrow(/familyBranch contains a control character or newline/);
    await expect(
      runEpicLayeredPipeline({ args: { epicIssueNumber: 217, targetBranch: "origin/main\n# evil" }, ...harness })
    ).rejects.toThrow(/targetBranch contains a control character or newline/);
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
    // canonical agy invocation (no -p/--diff-only — both break the leg; agy auto-degrades to diff-only
    // on the hidden worktree). Matches the family agy leg.
    expect(calls.join("\n")).toContain("agy --sandbox --print ''");
    expect(calls.join("\n")).not.toContain("--diff-only");
    // per-slice agy gets review instructions + JSON schema on stdin (not a bare diff) so parseReviewerJson
    // gets parseable output, mirroring the family agy leg.
    const agyCall = calls.find((c) => c.includes("reviewer=agy")) ?? "";
    expect(agyCall).toContain("Return only one JSON object");
    expect(agyCall).toContain("REVIEW ONLY");

    // the merge command prunes stale worktree registrations BEFORE scanning the worktree list (symmetric
    // with resolveExistingFamilyWorktree), so a registered-but-missing path is never selected for the merge.
    const mergeCall = calls.find((c) => c.includes("merge reviewed commit")) ?? "";
    expect(mergeCall).toContain("worktree prune");
    // prune runs before the worktree-list scan (the existingMergeWorktree assignment).
    expect(mergeCall.indexOf("worktree prune")).toBeLessThan(mergeCall.indexOf("existingMergeWorktree="));
    expect(mergeCall).toContain("current != main_repo"); // main-repo exclusion (r10)
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
        if (command.includes("reviewer=gstack-ship-family")) return JSON.stringify({ asked: false, gatesPassed: true, prCreated: true, prUrl: "https://example.test/pr/1", familyHead: "shipped-head" });
        return JSON.stringify({ status: "passed" });
      }
    });

    expect(result.status).toBe("ready");
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
        if (command.includes("reviewer=gstack-ship-family")) return JSON.stringify({ asked: false, gatesPassed: true, prCreated: true, prUrl: "https://example.test/pr/1", familyHead: "shipped-head" });
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
    expect(result.status).toBe("ready");
    expect(result.layers.map((layer: any) => layer.issueNumbers)).toEqual([[220, 221], [222]]);
    expect(result.mergeQueue.map((entry: any) => entry.reviewedCommit)).toEqual(["commit-220", "commit-221", "commit-222"]);
    // §段间交接: the handoff maps EVERY slice (not just mergeQueue.at(-1)) to its OWN stable per-slice
    // reviewed commit — these never go stale on a family rebase/fix because they are not the rewritten
    // family-branch hash. The current family tip is reported once as familyHead.
    expect(result.handoff.merged).toEqual([
      { number: 220, reviewedCommit: "commit-220" },
      { number: 221, reviewedCommit: "commit-221" },
      { number: 222, reviewedCommit: "commit-222" }
    ]);
    expect(result.handoff.familyHead).toBe("shipped-head");
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
          if (command.includes("reviewer=gstack-ship-family")) return JSON.stringify({ asked: false, gatesPassed: true, prCreated: true, prUrl: "https://example.test/pr/1", familyHead: "shipped-head" });
          if (command.includes("为切片执行 I7 commit 纪律检查") || command.includes("merge reviewed commit")) {
            return execFileSync("bash", ["-l", "-c", command], { encoding: "utf8" });
          }
          return JSON.stringify({ status: "passed" });
        }
      });

      expect(result.status).toBe("ready");
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
          if (command.includes("reviewer=gstack-ship-family")) return JSON.stringify({ asked: false, gatesPassed: true, prCreated: true, prUrl: "https://example.test/pr/1", familyHead: "shipped-head" });
          if (command.includes("为切片执行 I7 commit 纪律检查") || command.includes("merge reviewed commit")) {
            return execFileSync("bash", ["-l", "-c", command], { encoding: "utf8" });
          }
          return JSON.stringify({ status: "passed", exitCode: 0, output: "ok" });
        }
      });

      expect(result.status).toBe("ready");
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
        if (command.includes("reviewer=gstack-ship-family")) return JSON.stringify({ asked: false, gatesPassed: true, prCreated: true, prUrl: "https://example.test/pr/1", familyHead: "shipped-head" });
        return JSON.stringify({ status: "passed" });
      }
    });

    expect(result.status).toBe("ready");
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
        if (command.includes("reviewer=gstack-ship-family")) return JSON.stringify({ asked: false, gatesPassed: true, prCreated: true, prUrl: "https://example.test/pr/1", familyHead: "shipped-head" });
        return JSON.stringify({ status: "passed" });
      }
    });

    expect(result.status).toBe("ready");
    // §段间交接: baseAtStart is the I10-verified startup target the family branched from, NOT the
    // family tip — even after a rebase. The current family tip is the top-level handoff familyHead;
    // `merged` carries only stable per-slice reviewedCommit values.
    expect(result.handoff.baseAtStart).toBe("base-start");
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

  it("matches the S5 shipOutcome authority across the full asked/gates/pr battery", () => {
    const battery: ShipOutcomeInput[] = [
      { asked: false, gatesPassed: true, prCreated: true },
      { asked: false, gatesPassed: false, prCreated: false },
      { asked: false, gatesPassed: true, prCreated: false },
      { asked: false, gatesPassed: false, prCreated: true },
      { asked: true, gatesPassed: false, prCreated: false },
      { asked: true, gatesPassed: true, prCreated: true },
      { asked: true, gatesPassed: true, prCreated: false }
    ];

    for (const input of battery) {
      expect(inlineShipOutcome(input)).toBe(shipOutcome(input));
    }
  });

  it("matches the S5 buildHandoffPayload authority across the three terminal states + field mixes", () => {
    const battery: HandoffInput[] = [
      { status: "ready", epic: 217, familyBranch: "family/217", baseAtStart: "b", familyHead: "tip", merged: [{ number: 220, reviewedCommit: "c220" }], dirty: [], flags: [], prUrl: "https://example.test/pr/1" },
      { status: "needs-user", epic: 217, familyBranch: "family/217", baseAtStart: "b", merged: [{ number: 220, reviewedCommit: "c220" }], reason: "gstack-ship-ask", question: "MINOR or MAJOR?" },
      { status: "unconverged", epic: 217, familyBranch: "family/217", baseAtStart: "b", reason: "gstack-ship-failed", detail: "RedTeam failed", flags: ["agy down"], dirty: [{ number: 221, decision: "rework" }] },
      // optional collections omitted -> both copies must default to the same empty arrays / nulls.
      { status: "ready", epic: "E1", familyBranch: "family/E1", baseAtStart: "deadbeef", prUrl: "https://example.test/pr/2" }
    ];

    for (const input of battery) {
      expect(inlineBuildHandoffPayload(input)).toEqual(buildHandoffPayload(input));
    }
  });

  it("matches the S6 continuationPlan authority across merged/dirty/multi-layer/id-coercion mixes", () => {
    const battery: ContinuationInput[] = [
      { layers: [[218]], mergedNumbers: [218], dirty: [] },
      { layers: [[218, 219]], mergedNumbers: [218], dirty: [] },
      { layers: [[218, 219]], mergedNumbers: [218, 219], dirty: [218] },
      { layers: [[218, 219], [220, 221]], mergedNumbers: [218, 219, 221], dirty: [219] },
      { layers: [[218], [219]], mergedNumbers: [218, 219], dirty: [] },
      { layers: [[218]], mergedNumbers: [] },
      { layers: [[218, 219]], mergedNumbers: [218], dirty: [219] },
      { layers: [["218", 219]], mergedNumbers: [218], dirty: ["219"] }
    ];

    for (const input of battery) {
      expect(inlineContinuationPlan(input)).toEqual(continuationPlan(input));
    }
  });

  it("matches the S6 dismissalGate authority across id/claim/location/casing mixes", () => {
    const battery: DismissalGateInput[] = [
      { finding: { id: "F1" }, dismissed: [{ id: "F1" }] },
      { finding: { id: "F2" }, dismissed: [{ id: "F1" }] },
      { finding: { id: "NEW-3", claimQuote: "此处 throw 缺测试" }, dismissed: [{ id: "OLD-7", claimQuote: "此处 throw 缺测试" }] },
      { finding: { id: "X", location: "decisionCore.ts:42" }, dismissed: [{ location: "decisionCore.ts:42" }] },
      { finding: { id: "F1", claimQuote: "q", location: "l" }, dismissed: [] },
      { finding: { id: "B" }, dismissed: [{ claimQuote: undefined, location: undefined, id: "A" }] },
      { finding: { id: "Z", location: "core.ts:9" }, dismissed: [{ id: "F1" }, { location: "core.ts:9" }] },
      { finding: { id: "NEW", claimQuote: "此处 throw 缺测试" }, dismissed: [{ claim_quote: "此处 throw 缺测试" }] },
      { finding: { id: "X", claim_quote: "q" }, dismissed: [{ claimQuote: "q" }] }
    ];

    for (const input of battery) {
      expect(inlineDismissalGate(input)).toBe(dismissalGate(input));
    }
  });
});

describe("epic orchestrator S4b family 5a/5b CMR", () => {
  // Drives the layered pipeline straight through to the family-review phase: every slice
  // implements, verifies, per-slice reviews, merges; family integration verify + base
  // management pass; then the 5a/5b family CMR runs. The familyReview hook lets each test
  // script the codex-family / agy-family Bash legs and the Claude review/fix agent legs.
  async function runToFamilyReview({ familyReview, ship }: { familyReview: (round: number) => any; ship?: any }) {
    const agentCalls: any[] = [];
    const bashCalls: string[] = [];
    let cmrRound = 0;
    // Default: gstack-ship runs clean — gates pass + family PR created -> ready terminal state.
    const shipReport = ship ?? { asked: false, gatesPassed: true, prCreated: true, prUrl: "https://example.test/pr/1", familyHead: "shipped-head" };

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
        if (command.includes("family-review pre-fix HEAD")) return "pre-fix-head";
        if (command.includes("family-review I7 fix-commit discipline")) return "";
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
        if (command.includes("reviewer=gstack-ship-family")) return JSON.stringify(shipReport);
        return JSON.stringify({ status: "passed" });
      }
    });

    return { result, agentCalls, bashCalls };
  }

  it("runs codex+Claude+agy on the merged family branch (agy diff-based with review instructions) and converges clean", async () => {
    const { result, agentCalls, bashCalls } = await runToFamilyReview({
      familyReview: () => ({ codex: { status: "passed", findings: [] }, agy: { status: "passed", findings: [] }, claude: { findings: [] } })
    });

    expect(result.status).toBe("ready");
    expect(result.familyReview).toMatchObject({ status: "converged", round: 1 });
    expect(result.outOfScope).toEqual(["online_pr_review_loop"]);
    expect(result.outOfScope).not.toContain("family_5a_5b");

    const codexFamily = bashCalls.find((command) => command.includes("reviewer=codex-family")) ?? "";
    const agyFamily = bashCalls.find((command) => command.includes("reviewer=agy-family")) ?? "";
    expect(codexFamily).toContain("cd '/repo/.epic-orchestrator/family'");
    expect(codexFamily).toContain("codex exec --skip-git-repo-check --ephemeral -");
    expect(agyFamily).toContain("cd '/repo/.epic-orchestrator/family'");
    // canonical agy invocation (no --diff-only — that is not a real agy flag; agy auto-degrades to
    // diff-only on the hidden .epic-orchestrator worktree). Prompt + diff ride stdin.
    expect(agyFamily).toContain("agy --sandbox --print ''");
    expect(agyFamily).not.toContain("--diff-only");
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
    // the Claude leg must also receive the diff base so it diffs against the startup target, not a guess.
    expect(claudeReviewCall.diffBase).toBe("base-start");
    expect(claudeReviewCall.prompt).toContain("base-start");
  });

  it("autonomously fixes a mechanical bug then converges on the next clean round and merges", async () => {
    const { result, agentCalls } = await runToFamilyReview({
      familyReview: (round: number) =>
        round === 1
          ? { codex: { status: "failed", findings: [{ id: "F1", classification: "mechanical_bug", location: "a.ts" }] }, agy: { status: "passed", findings: [] }, claude: { findings: [] } }
          : { codex: { status: "passed", findings: [] }, agy: { status: "passed", findings: [] }, claude: { findings: [] } }
    });

    expect(result.status).toBe("ready");
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

  it("does NOT converge a status:failed family leg whose only findings are garbage (sanitize-before-length)", async () => {
    // A {status:"failed", findings:[null]} report must not short-circuit as "has findings" (then have the
    // null silently dropped downstream by routeFindings) and converge — the failed status is a contradiction.
    const { result } = await runToFamilyReview({
      familyReview: () => ({
        codex: { status: "failed", findings: [null] },
        agy: { status: "passed", findings: [] },
        claude: { findings: [] }
      })
    });

    expect(result.status).toBe("return_to_main_session");
    expect(result.reason).toBe("family_review_needs_decision");
    expect(result.decisionFindings).toEqual([
      expect.objectContaining({ id: "codex-family-status-failed", classification: "choice" })
    ]);
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

  it("rejects a malformed Claude family reply ({} with no findings array) as unavailable, not a clean review (I2)", async () => {
    // The Claude leg carries no status field, so a reply with no findings array is malformed (not clean).
    // With agy down, a malformed Claude must NOT be counted toward the >=2-model gate — only codex is real -> halt.
    const result: any = await runEpicLayeredPipeline({
      args: { epicIssueNumber: 217, familyBranch: "family/217", verifyCommands: ["npm --prefix web test"], startupTargetHead: "base-start", targetBranch: "origin/main", maxReviewRounds: 3 },
      log: () => undefined,
      agent: async (request: any) => {
        if (request.role === "family_review") return {}; // truthy, available!==false, but no findings array -> malformed
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
    expect(result.i2).toMatchObject({ status: "halt", stage: "family_5a_5b" });
    expect(result.i2.availableModels).toEqual(["codex"]); // malformed Claude rejected, agy down
  });

  it("never triggers the online PR review loop on a converged family review (online_pr_review_loop stays out of scope)", async () => {
    const { result, bashCalls, agentCalls } = await runToFamilyReview({
      familyReview: () => ({ codex: { status: "passed", findings: [] }, agy: { status: "passed", findings: [] }, claude: { findings: [] } })
    });

    expect(result.status).toBe("ready");
    expect(result.outOfScope).toContain("online_pr_review_loop");
    expect(bashCalls.join("\n")).not.toContain("gh pr create");
    expect(bashCalls.join("\n")).not.toContain("pr-review-loop");
    expect(agentCalls.some((call) => call.role === "online_review" || call.role === "pr_review_loop")).toBe(false);
  });
});

describe("epic orchestrator S5 Ship phase (gstack-ship + terminal states + handoff)", () => {
  // Reuses the S4b runToFamilyReview harness (real-ish layered pipeline through a converged family
  // review), then scripts the gstack-ship Bash leg via the `ship` hook to exercise each terminal state.
  async function runToShip({ ship }: { ship: any }) {
    const agentCalls: any[] = [];
    const bashCalls: string[] = [];
    let cmrRound = 0;
    const passClean = () => ({ codex: { status: "passed", findings: [] }, agy: { status: "passed", findings: [] }, claude: { findings: [] } });

    const result: any = await runEpicLayeredPipeline({
      args: { epicIssueNumber: 217, familyBranch: "family/217", verifyCommands: ["npm --prefix web test"], startupTargetHead: "base-start", targetBranch: "origin/main", maxReviewRounds: 3 },
      log: () => undefined,
      agent: async (request: any) => {
        agentCalls.push(request);
        if (request.role === "family_review") return passClean().claude;
        if (request.role === "family_review_fix") return { fixed: true };
        return {
          commit: `commit-${request.issueNumber}`,
          worktreePath: `/repo/.worktrees/issue-${request.issueNumber}`,
          observabilityEvidence: { loudFailure: true, locatorLogs: true, notApplicableReason: "tooling slice" }
        };
      },
      Bash: async (command: string) => {
        bashCalls.push(command);
        if (command.includes("family-review pre-fix HEAD")) return "pre-fix-head";
        if (command.includes("family-review I7 fix-commit discipline")) return "";
        if (command.includes("family-review reviewed HEAD")) return "reviewed-head-sha";
        if (command.includes("/sub_issues")) return JSON.stringify({ epicId: 217, issues: [{ id: 220, epicId: 217, state: "open", title: "S2", url: "https://example.test/220" }], blockedBy: [] });
        if (command.includes("reviewer=codex-family")) return JSON.stringify(passClean().codex);
        if (command.includes("reviewer=agy-family")) { cmrRound += 1; return JSON.stringify(passClean().agy); }
        if (command.includes("reviewer=codex")) return JSON.stringify({ status: "passed", findings: [] });
        if (command.includes("reviewer=agy")) return JSON.stringify({ status: "passed", findings: [] });
        if (command.includes("merge reviewed commit")) return JSON.stringify({ status: "merged", mergeCommit: "merge-220", mergeWorktree: "/repo/.epic-orchestrator/family" });
        if (command.includes("家族集成 verify")) return JSON.stringify({ status: "passed", exitCode: 0, output: "family ok" });
        if (command.includes("base management")) return JSON.stringify({ status: "no_drift", startupTargetHead: "base-start", currentTargetHead: "base-start" });
        if (command.includes("reviewer=gstack-ship-family")) return JSON.stringify(ship);
        return JSON.stringify({ status: "passed" });
      }
    });

    return { result, agentCalls, bashCalls };
  }

  it("ready: gstack-ship gates pass + family PR created -> ready terminal state + full handoff", async () => {
    const { result, bashCalls } = await runToShip({
      ship: { asked: false, gatesPassed: true, prCreated: true, prUrl: "https://github.com/Akagilnc/ming-salvage-sim/pull/777", familyHead: "post-ship-head" }
    });

    expect(result.status).toBe("ready");
    // gstack-ship is driven FULL on the merged family worktree against the startup target base.
    const shipCall = bashCalls.find((command) => command.includes("reviewer=gstack-ship-family")) ?? "";
    expect(shipCall).toContain("cd '/repo/.epic-orchestrator/family'");
    expect(shipCall).toContain("gstack-ship --json --base 'origin/main'");
    // gstack-ship exits nonzero on a failed gate / internal ASK but still prints its report; the leg
    // must capture stdout under `set +e` so pipefail doesn't abort the needs-user/unconverged paths.
    expect(shipCall).toContain("set +e");
    expect(shipCall).toMatch(/shipReport=\$\(gstack-ship --json --base 'origin\/main'\)/);
    // stderr is NOT suppressed -> gstack-ship diagnostics flow to the orchestrator on failure.
    expect(shipCall).not.toContain("2>/dev/null");
    // full §段间交接 handoff payload.
    expect(result.handoff).toMatchObject({
      status: "ready",
      epic: 217,
      familyBranch: "family/217",
      baseAtStart: "base-start",
      prUrl: "https://github.com/Akagilnc/ming-salvage-sim/pull/777",
      question: null,
      detail: null,
      dirty: [],
      flags: []
    });
    expect(result.handoff.merged).toEqual([{ number: 220, reviewedCommit: "commit-220" }]);
    // gstack-ship's version-bump commit advanced the family HEAD; the handoff reports the post-ship tip.
    expect(result.handoff.familyHead).toBe("post-ship-head");
  });

  it("needs-user: gstack-ship internal ASK fires -> needs-user terminal state + handoff carries the ASK question", async () => {
    const { result } = await runToShip({
      ship: { asked: true, gatesPassed: false, prCreated: false, askDetail: "Version bump is MINOR or MAJOR?" }
    });

    expect(result.status).toBe("needs-user");
    expect(result.handoff).toMatchObject({
      status: "needs-user",
      epic: 217,
      familyBranch: "family/217",
      reason: "gstack-ship-ask",
      question: "Version bump is MINOR or MAJOR?",
      detail: null,
      prUrl: null
    });
    expect(result.handoff.merged).toEqual([{ number: 220, reviewedCommit: "commit-220" }]);
    expect(result.handoff.familyHead).toBe("merge-220");
  });

  it("unconverged: gstack-ship gates fail (non-ASK) -> unconverged terminal state + handoff carries the blocking detail", async () => {
    const { result } = await runToShip({
      ship: { asked: false, gatesPassed: false, prCreated: false, shipDetail: "RedTeam gate failed: unsafe shell injection" }
    });

    expect(result.status).toBe("unconverged");
    expect(result.handoff).toMatchObject({
      status: "unconverged",
      epic: 217,
      familyBranch: "family/217",
      reason: "gstack-ship-failed",
      detail: "RedTeam gate failed: unsafe shell injection",
      question: null,
      prUrl: null
    });
    expect(result.handoff.merged).toEqual([{ number: 220, reviewedCommit: "commit-220" }]);
    expect(result.handoff.familyHead).toBe("merge-220");
  });

  it("none of the three terminal states triggers the online bot / pr-review-loop (online_pr_review_loop stays out of scope)", async () => {
    for (const ship of [
      { asked: false, gatesPassed: true, prCreated: true, prUrl: "https://example.test/pr/1", familyHead: "shipped-head" },
      { asked: true, gatesPassed: false, prCreated: false, askDetail: "pre-landing ASK" },
      { asked: false, gatesPassed: false, prCreated: false, shipDetail: "coverage hard gate below threshold" }
    ]) {
      const { result, bashCalls, agentCalls } = await runToShip({ ship });

      expect(["ready", "needs-user", "unconverged"]).toContain(result.status);
      expect(result.outOfScope).toContain("online_pr_review_loop");
      // ship is the last step: create the PR, never drive the online bot loop.
      expect(bashCalls.join("\n")).not.toContain("pr-review-loop");
      expect(bashCalls.join("\n")).not.toContain("gh pr review");
      expect(bashCalls.join("\n")).not.toContain("--resolve");
      expect(agentCalls.some((call) => call.role === "online_review" || call.role === "pr_review_loop")).toBe(false);
    }
  });

  it("fails loudly when gstack-ship omits the load-bearing detail field for its terminal state", async () => {
    // ready outcome but no prUrl -> the handoff would carry prUrl:null, so the Ship phase must throw.
    await expect(runToShip({ ship: { asked: false, gatesPassed: true, prCreated: true } })).rejects.toThrow(/missing load-bearing field prUrl/);
  });

  it("fails loudly on the ready path when gstack-ship omits its post-ship familyHead", async () => {
    // ready means gstack-ship committed a version bump; a missing post-ship head must NOT silently
    // fall back to the stale pre-ship merge tip — the Ship phase fails loud instead.
    await expect(
      runToShip({ ship: { asked: false, gatesPassed: true, prCreated: true, prUrl: "https://example.test/pr/9" } })
    ).rejects.toThrow(/missing load-bearing field familyHead/);
  });

  it("fails loudly when a parseable gstack-ship report violates the boolean contract", async () => {
    // a truthy non-boolean (string "false") would misclassify as ready under JS truthiness; reject it.
    await expect(
      runToShip({ ship: { asked: false, gatesPassed: "false", prCreated: true, prUrl: "https://example.test/pr/1", familyHead: "h" } as any })
    ).rejects.toThrow(/field "gatesPassed" must be a boolean/);
  });

  it("fails loudly when a parseable gstack-ship report is missing a required boolean", async () => {
    await expect(
      runToShip({ ship: { asked: false, gatesPassed: true } as any })
    ).rejects.toThrow(/field "prCreated" must be a boolean/);
  });
});

describe("epic orchestrator S6 cross-segment continuation (relaunch + git-skip + dirty + dismissal)", () => {
  // Drives the layered pipeline through a full clean ready run, but the harness lets each test set
  // S6 args (mergedNumbers / dirty / dismissals / decisions) and a per-round familyReview script,
  // then asserts which slices' implement legs ran (git-skip), which re-ran (dirty), and whether a
  // dismissed decision finding still halts (it must not) while staying in the reviewers output.
  async function runContinuation({
    subIssues,
    blockedBy = [],
    args,
    familyReview,
    ship
  }: {
    subIssues: any[];
    blockedBy?: any[];
    args: any;
    familyReview?: (round: number) => any;
    ship?: any;
  }) {
    const agentCalls: any[] = [];
    const bashCalls: string[] = [];
    let cmrRound = 0;
    const passClean = () => ({ codex: { status: "passed", findings: [] }, agy: { status: "passed", findings: [] }, claude: { findings: [] } });
    const review = familyReview ?? (() => passClean());
    const shipReport = ship ?? { asked: false, gatesPassed: true, prCreated: true, prUrl: "https://example.test/pr/1", familyHead: "shipped-head" };

    const result: any = await runEpicLayeredPipeline({
      args: { epicIssueNumber: 217, familyBranch: "family/217", verifyCommands: ["npm --prefix web test"], startupTargetHead: "base-start", targetBranch: "origin/main", maxReviewRounds: 3, ...args },
      log: () => undefined,
      agent: async (request: any) => {
        agentCalls.push(request);
        if (request.role === "family_review") return review(request.round).claude ?? { findings: [] };
        if (request.role === "family_review_fix") return { fixed: true };
        return {
          commit: `commit-${request.issueNumber}`,
          worktreePath: `/repo/.worktrees/issue-${request.issueNumber}`,
          observabilityEvidence: { loudFailure: true, locatorLogs: true, notApplicableReason: "tooling slice" }
        };
      },
      Bash: async (command: string) => {
        bashCalls.push(command);
        if (command.includes("family-review pre-fix HEAD")) return "pre-fix-head";
        if (command.includes("family-review I7 fix-commit discipline")) return "";
        if (command.includes("family-review reviewed HEAD")) return "reviewed-head-sha";
        if (command.includes("/sub_issues")) return JSON.stringify({ epicId: 217, issues: subIssues, blockedBy });
        if (command.includes("reviewer=codex-family")) return JSON.stringify(review(cmrRound + 1).codex ?? { status: "passed", findings: [] });
        if (command.includes("reviewer=agy-family")) { const reply = JSON.stringify(review(cmrRound + 1).agy ?? { status: "passed", findings: [] }); cmrRound += 1; return reply; }
        if (command.includes("reviewer=codex")) return JSON.stringify({ status: "passed", findings: [] });
        if (command.includes("reviewer=agy")) return JSON.stringify({ status: "passed", findings: [] });
        if (command.includes("merge reviewed commit")) {
          const reviewedCommit = command.match(/implementedCommit='([^']+)'/)?.[1] ?? "unknown";
          return JSON.stringify({ status: "merged", mergeCommit: `merge-${reviewedCommit}`, mergeWorktree: "/repo/.epic-orchestrator/family" });
        }
        if (command.includes("resolve existing family worktree")) return JSON.stringify({ status: "resolved", familyWorktree: "/repo/.epic-orchestrator/family" });
        if (command.includes("resolve existing family HEAD")) return "family-head-sha";
        if (command.includes("家族集成 verify")) return JSON.stringify({ status: "passed", exitCode: 0, output: "family ok" });
        if (command.includes("base management")) return JSON.stringify({ status: "no_drift", startupTargetHead: "base-start", currentTargetHead: "base-start" });
        if (command.includes("reviewer=gstack-ship-family")) return JSON.stringify(shipReport);
        return JSON.stringify({ status: "passed" });
      }
    });

    const implementedIssues = agentCalls.filter((call) => call.role === undefined).map((call) => call.issueNumber);
    return { result, agentCalls, bashCalls, implementedIssues };
  }

  it("relaunch git-skips an already-merged slice: only the not-yet-merged slice implements + merges", async () => {
    const { result, implementedIssues, bashCalls } = await runContinuation({
      subIssues: [
        { id: 220, epicId: 217, state: "open", title: "S2-A", url: "https://example.test/220" },
        { id: 221, epicId: 217, state: "open", title: "S2-B", url: "https://example.test/221" }
      ],
      args: { mergedNumbers: [220] }
    });

    expect(result.status).toBe("ready");
    // 220 is on the family branch already (git state) -> no implement leg, no merge for it.
    expect(implementedIssues).toEqual([221]);
    expect(bashCalls.join("\n")).toContain("implementedCommit='commit-221'");
    expect(bashCalls.join("\n")).not.toContain("implementedCommit='commit-220'");
    // the continuation plan is reported for the handoff/observability.
    expect(result.continuation.todoTotal).toBe(1);
    expect(result.continuation.layers[0]).toMatchObject({ todo: [221], skipped: [220] });
  });

  it("dirty: a merged slice flagged dirty re-runs impl+verify even though the family branch has its commit", async () => {
    const { result, implementedIssues } = await runContinuation({
      subIssues: [
        { id: 220, epicId: 217, state: "open", title: "S2-A", url: "https://example.test/220" },
        { id: 221, epicId: 217, state: "open", title: "S2-B", url: "https://example.test/221" }
      ],
      args: { mergedNumbers: [220, 221], dirty: [220] }
    });

    expect(result.status).toBe("ready");
    // both merged, but 220 is dirty -> 220 re-implements; 221 is git-skipped.
    expect(implementedIssues).toEqual([220]);
    expect(result.continuation.todoTotal).toBe(1);
    expect(result.continuation.layers[0]).toMatchObject({ todo: [220], skipped: [221], dirty: [220] });
  });

  it("todoTotal 0: every slice merged and none dirty -> no implement legs, straight to family review + ship", async () => {
    const { result, implementedIssues, bashCalls } = await runContinuation({
      subIssues: [
        { id: 220, epicId: 217, state: "open", title: "S2-A", url: "https://example.test/220" },
        { id: 221, epicId: 217, state: "open", title: "S2-B", url: "https://example.test/221" }
      ],
      args: { mergedNumbers: [220, 221] }
    });

    expect(result.status).toBe("ready");
    expect(implementedIssues).toEqual([]);
    expect(bashCalls.join("\n")).not.toContain("merge reviewed commit");
    // family review + ship still ran on the existing merged family branch.
    expect(result.familyReview).toMatchObject({ status: "converged" });
    expect(result.continuation.todoTotal).toBe(0);
  });

  it("dismissal: a dismissed decision finding no longer halts (converges) but stays in the reviewers output (full re-review)", async () => {
    const { result, agentCalls } = await runContinuation({
      subIssues: [{ id: 220, epicId: 217, state: "open", title: "S2", url: "https://example.test/220" }],
      args: { mergedNumbers: [220], dismissals: [{ id: "DEC-1", claimQuote: "design choice X" }] },
      familyReview: () => ({
        codex: { status: "failed", findings: [{ id: "DEC-1", classification: "choice", claim_quote: "design choice X", location: "a.ts" }] },
        agy: { status: "passed", findings: [] },
        claude: { findings: [] }
      })
    });

    // dismissed decision finding does not escalate -> the run converges to ready instead of returning for a decision.
    expect(result.status).toBe("ready");
    expect(result.familyReview.status).toBe("converged");
    expect(agentCalls.some((call) => call.role === "family_review_fix")).toBe(false);
    // full re-review discipline: the dismissed finding is STILL present in the converged round's reviewers output.
    const convergedRound = result.familyReview.rounds.at(-1);
    const allFindings = convergedRound.reviewers.flatMap((reviewer: any) => reviewer.findings ?? []);
    expect(allFindings).toContainEqual({ id: "DEC-1", classification: "choice", claim_quote: "design choice X", location: "a.ts" });
  });

  it("a NON-dismissed decision finding still escalates to the main session", async () => {
    const { result } = await runContinuation({
      subIssues: [{ id: 220, epicId: 217, state: "open", title: "S2", url: "https://example.test/220" }],
      args: { mergedNumbers: [220], dismissals: [{ id: "DEC-OTHER" }] },
      familyReview: () => ({
        codex: { status: "failed", findings: [{ id: "DEC-1", classification: "choice", claim_quote: "still unresolved" }] },
        agy: { status: "passed", findings: [] },
        claude: { findings: [] }
      })
    });

    expect(result.status).toBe("return_to_main_session");
    expect(result.reason).toBe("family_review_needs_decision");
    expect(result.decisionFindings).toContainEqual({ id: "DEC-1", classification: "choice", claim_quote: "still unresolved" });
  });

  it("normalizes mergedNumbers / dirty / dismissals / decisions args (arrays + element coercion + shell-safety)", async () => {
    // mixed string/number ids must coerce; non-array fields default to empty; decisions passes through.
    const { result, implementedIssues } = await runContinuation({
      subIssues: [
        { id: 220, epicId: 217, state: "open", title: "S2-A", url: "https://example.test/220" },
        { id: 221, epicId: 217, state: "open", title: "S2-B", url: "https://example.test/221" }
      ],
      args: { mergedNumbers: ["220"], dirty: [], dismissals: undefined, decisions: "用户裁定：DEC-1 不算" }
    });

    expect(result.status).toBe("ready");
    // "220" (string) coerces and matches numeric 220 from topology -> git-skip; only 221 implements.
    expect(implementedIssues).toEqual([221]);
    expect(result.continuation.layers[0]).toMatchObject({ todo: [221], skipped: [220] });
  });

  it("relaunch with a merged blocker (layer 1 skipped) bases the dependent (layer 2 todo) on the family HEAD, not the startup target", async () => {
    // The dependency-preserving fix: with mergeQueue empty (the blocker was git-skipped, not merged
    // this segment), the dependent must still base on the existing family branch HEAD (which contains
    // the blocker), NOT startupTargetHead — else 221 is built without 220's changes.
    const { result, agentCalls } = await runContinuation({
      subIssues: [
        { id: 220, epicId: 217, state: "open", title: "S2-blocker", url: "https://example.test/220" },
        { id: 221, epicId: 217, state: "open", title: "S2-dependent", url: "https://example.test/221" }
      ],
      blockedBy: [{ issueId: 221, blockedByIssueId: 220 }],
      args: { mergedNumbers: [220] }
    });

    expect(result.status).toBe("ready");
    const dependentCall = agentCalls.find((call) => call.role === undefined && call.issueNumber === 221);
    expect(dependentCall).toBeTruthy();
    expect(dependentCall.baseRef).toBe("family-head-sha");
    expect(dependentCall.baseRef).not.toBe("base-start");
    // and it must base on the FAMILY branch (not the target branch) — the prompt/base-branch path too.
    expect(dependentCall.baseBranch).toBe("family/217");
    expect(dependentCall.baseBranch).not.toBe("origin/main");
    expect(dependentCall.startupTargetHead).toBe("base-start"); // baseAtStart/diffBase keep the real startup target
  });

  it("accepts dirty as the handoff's {number, decision} object shape (round-trips without unwrapping)", async () => {
    // The prior segment's handoff carries dirty as [{number, decision}]; passing it straight back as
    // args.dirty must still flag the slice (else it stringifies to '[object Object]' and never matches).
    const { result, implementedIssues } = await runContinuation({
      subIssues: [
        { id: 220, epicId: 217, state: "open", title: "S2-A", url: "https://example.test/220" },
        { id: 221, epicId: 217, state: "open", title: "S2-B", url: "https://example.test/221" }
      ],
      args: { mergedNumbers: [{ number: 220, reviewedCommit: "c220" }, { number: 221, reviewedCommit: "c221" }], dirty: [{ number: 220, decision: "rework auth" }] }
    });

    expect(result.status).toBe("ready");
    expect(implementedIssues).toEqual([220]);
    expect(result.continuation.layers[0]).toMatchObject({ todo: [220], skipped: [221], dirty: [220] });
  });

  it("a no-fresh-merge continuation that hits a gstack-ship ASK still reports the existing family HEAD (not null)", async () => {
    // todoTotal=0 means mergeQueue is empty; the needs-user handoff familyHead must come from the
    // resolved existing family worktree, not fall through to null and break the next continuation.
    const { result } = await runContinuation({
      subIssues: [{ id: 220, epicId: 217, state: "open", title: "S2", url: "https://example.test/220" }],
      args: { mergedNumbers: [220] },
      ship: { asked: true, gatesPassed: false, prCreated: false, askDetail: "Version bump MINOR or MAJOR?" }
    });

    expect(result.status).toBe("needs-user");
    expect(result.handoff.familyHead).toBe("family-head-sha");
  });

  it("handoff.merged is cumulative and preserves the prior segment's reviewedCommit across the relaunch round-trip", async () => {
    // The handoff feeds the next relaunch's mergedNumbers, so a slice merged in a prior segment
    // (git-skipped now) must still appear AND keep its stable reviewedCommit when the prior
    // handoff's {number, reviewedCommit} entry is passed straight back — else the next relaunch
    // re-runs it or loses the commit identity.
    const { result } = await runContinuation({
      subIssues: [
        { id: 220, epicId: 217, state: "open", title: "S2-A", url: "https://example.test/220" },
        { id: 221, epicId: 217, state: "open", title: "S2-B", url: "https://example.test/221" }
      ],
      args: { mergedNumbers: [{ number: 220, reviewedCommit: "c220-prior" }] }
    });

    expect(result.status).toBe("ready");
    const mergedNumbers = result.handoff.merged.map((entry: any) => entry.number);
    expect(mergedNumbers).toContain(220); // prior-segment, git-skipped this segment
    expect(mergedNumbers).toContain(221); // ran this segment
    expect(result.handoff.merged).toContainEqual({ number: 220, reviewedCommit: "c220-prior" }); // preserved
    expect(result.handoff.merged).toContainEqual({ number: 221, reviewedCommit: "commit-221" });
  });

  it("rejects a mergedNumbers object element that lacks a 'number' field (fails loud, not '[object Object]')", async () => {
    await expect(
      runContinuation({
        subIssues: [{ id: 220, epicId: 217, state: "open", title: "S2", url: "https://example.test/220" }],
        args: { mergedNumbers: [{ issueNumber: 220 }] }
      })
    ).rejects.toThrow(/object element must carry a 'number' field/);
  });

  it("a no-fresh-merge continuation whose family review fixes a bug reports the POST-fix family HEAD", async () => {
    // todoTotal=0 + a family_review_fix advances the existing family HEAD; currentFamilyHead must
    // track that so the needs-user handoff reports the post-fix tip, not the stale pre-resolve HEAD.
    const { result } = await runContinuation({
      subIssues: [{ id: 220, epicId: 217, state: "open", title: "S2", url: "https://example.test/220" }],
      args: { mergedNumbers: [220] },
      familyReview: (round: number) =>
        round === 1
          ? { codex: { status: "failed", findings: [{ id: "M1", classification: "mechanical_bug", location: "a.ts" }] }, agy: { status: "passed", findings: [] }, claude: { findings: [] } }
          : { codex: { status: "passed", findings: [] }, agy: { status: "passed", findings: [] }, claude: { findings: [] } },
      ship: { asked: true, gatesPassed: false, prCreated: false, askDetail: "pre-landing ASK" }
    });

    expect(result.status).toBe("needs-user");
    // pre-resolve HEAD was family-head-sha; the fix advanced it to reviewed-head-sha.
    expect(result.handoff.familyHead).toBe("reviewed-head-sha");
  });

  it("a family reviewer reporting status:failed with NO findings list escalates (does not falsely converge)", async () => {
    // The load-bearing family CMR must not silently treat a "failed, no findings" report as []
    // findings (which would converge). It is surfaced as an escalatable decision finding.
    const { result } = await runContinuation({
      subIssues: [{ id: 220, epicId: 217, state: "open", title: "S2", url: "https://example.test/220" }],
      args: { mergedNumbers: [220] },
      familyReview: () => ({ codex: { status: "failed" }, agy: { status: "passed", findings: [] }, claude: { findings: [] } })
    });

    expect(result.status).toBe("return_to_main_session");
    expect(result.reason).toBe("family_review_needs_decision");
    expect(result.decisionFindings.some((f: any) => /codex-family did not report status="passed"/.test(f.claim_quote ?? ""))).toBe(true);
  });

  it("a status-contract leg reporting status:failed with an EMPTY findings array still escalates (no false converge)", async () => {
    // ship-pre gap: an explicit empty findings array with a non-pass status must not be returned as []
    // (which would converge). Distinct from the missing-findings-field case above.
    const { result } = await runContinuation({
      subIssues: [{ id: 220, epicId: 217, state: "open", title: "S2", url: "https://example.test/220" }],
      args: { mergedNumbers: [220] },
      familyReview: () => ({ codex: { status: "failed", findings: [] }, agy: { status: "passed", findings: [] }, claude: { findings: [] } })
    });

    expect(result.status).toBe("return_to_main_session");
    expect(result.reason).toBe("family_review_needs_decision");
  });

  it("a status-contract leg returning an empty object {} (no status, no findings) escalates, not converges", async () => {
    const { result } = await runContinuation({
      subIssues: [{ id: 220, epicId: 217, state: "open", title: "S2", url: "https://example.test/220" }],
      args: { mergedNumbers: [220] },
      familyReview: () => ({ codex: {}, agy: { status: "passed", findings: [] }, claude: { findings: [] } })
    });

    expect(result.status).toBe("return_to_main_session");
    expect(result.reason).toBe("family_review_needs_decision");
  });

  it("rejects a mergedNumbers entry with a null/undefined number value (fails loud, not silent miss)", async () => {
    await expect(
      runContinuation({
        subIssues: [{ id: 220, epicId: 217, state: "open", title: "S2", url: "https://example.test/220" }],
        args: { mergedNumbers: [{ number: null }] }
      })
    ).rejects.toThrow(/null \/ undefined \/ non-primitive \/ empty slice id/);
  });

  it("rejects a mergedNumbers/dirty entry whose number value is a nested object (no silent '[object Object]')", async () => {
    await expect(
      runContinuation({
        subIssues: [{ id: 220, epicId: 217, state: "open", title: "S2", url: "https://example.test/220" }],
        args: { mergedNumbers: [{ number: { id: 220 } }] }
      })
    ).rejects.toThrow(/non-primitive \/ empty slice id/);
  });

  it("accepts the handoff's `merged` field as the mergedNumbers alias (whole handoff round-trips as relaunch args)", async () => {
    // Passing the prior handoff object straight back (it carries `merged`, not `mergedNumbers`) must
    // still git-skip already-merged slices.
    const { result, implementedIssues } = await runContinuation({
      subIssues: [
        { id: 220, epicId: 217, state: "open", title: "S2-A", url: "https://example.test/220" },
        { id: 221, epicId: 217, state: "open", title: "S2-B", url: "https://example.test/221" }
      ],
      args: { merged: [{ number: 220, reviewedCommit: "c220" }] }
    });

    expect(result.status).toBe("ready");
    expect(implementedIssues).toEqual([221]); // 220 git-skipped via the `merged` alias
    expect(result.continuation.layers[0]).toMatchObject({ skipped: [220], todo: [221] });
  });

  it("rejects an empty / whitespace-only familyBranch (would reach git as an empty ref)", async () => {
    await expect(
      runContinuation({
        subIssues: [{ id: 220, epicId: 217, state: "open", title: "S2", url: "https://example.test/220" }],
        args: { familyBranch: "   " }
      })
    ).rejects.toThrow(/familyBranch must not be empty/);
  });

  it("rejects a familyBranch carrying a git refspec metacharacter (':' would make fetch write an unintended local ref)", async () => {
    await expect(
      runContinuation({
        subIssues: [{ id: 220, epicId: 217, state: "open", title: "S2", url: "https://example.test/220" }],
        args: { familyBranch: "origin/evil:refs/heads/pwned" }
      })
    ).rejects.toThrow(/git ref\/refspec metacharacter/);
  });

  it("rejects a git-special targetBranch ('@' resolves to HEAD; leading '-' is an option)", async () => {
    await expect(
      runContinuation({
        subIssues: [{ id: 220, epicId: 217, state: "open", title: "S2", url: "https://example.test/220" }],
        args: { targetBranch: "@" }
      })
    ).rejects.toThrow(/git-special value/);
    await expect(
      runContinuation({
        subIssues: [{ id: 220, epicId: 217, state: "open", title: "S2", url: "https://example.test/220" }],
        args: { startupTargetHead: "--upload-pack=evil" }
      })
    ).rejects.toThrow(/git-special value/);
  });

  it("a family reviewer returning a non-array findings field is treated as an unavailable (degraded) leg, not silently empty", async () => {
    // A malformed (non-array findings) report must NOT be coerced to [] findings (which could converge);
    // the leg's guard throws, the leg catch marks it unavailable, and the round degrades (with codex
    // missing) rather than trusting the malformed output.
    const { result } = await runContinuation({
      subIssues: [{ id: 220, epicId: 217, state: "open", title: "S2", url: "https://example.test/220" }],
      args: { mergedNumbers: [220] },
      familyReview: () => ({ codex: { status: "failed", findings: { not: "an array" } }, agy: { status: "passed", findings: [] }, claude: { findings: [] } })
    });

    const round = result.familyReview.rounds?.at(-1) ?? result.rounds?.at(-1);
    expect(round.degradation.missingModels).toContain("codex");
    const codexReviewer = round.reviewers.find((r: any) => r.model === "codex");
    expect(codexReviewer.available).toBe(false);
    expect(codexReviewer.reason).toMatch(/non-array findings field/);
  });

  it("a raw-id prior merged entry surfaces in the cumulative handoff with reviewedCommit:null (contract allows null)", async () => {
    const { result } = await runContinuation({
      subIssues: [
        { id: 220, epicId: 217, state: "open", title: "S2-A", url: "https://example.test/220" },
        { id: 221, epicId: 217, state: "open", title: "S2-B", url: "https://example.test/221" }
      ],
      args: { mergedNumbers: [220] } // raw id -> no commit identity
    });

    expect(result.status).toBe("ready");
    expect(result.handoff.merged).toContainEqual({ number: 220, reviewedCommit: null });
  });
});
