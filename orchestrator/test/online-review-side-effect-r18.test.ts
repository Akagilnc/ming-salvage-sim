/**
 * #600 r18 — single-slice verify side-effect in-band terminal (isolated ESM mock).
 */
import { afterEach, describe, expect, it, vi } from "vitest";

const ghCalls: string[] = [];
const POLL_TS = "2026-07-08T12:00:00.000Z";
const BOT_SIGNAL_TS = "2026-07-08T12:00:01.000Z";

function ghFixture(file: string, args: string[]): string {
  ghCalls.push(`${file} ${args.join(" ")}`);
  const cmd = args.join(" ");
  if (
    cmd.includes("pulls/42") &&
    cmd.includes("repos/o/r/pulls/42") &&
    !cmd.includes("comments") &&
    !cmd.includes("reviews")
  ) {
    return JSON.stringify({
      head: { sha: "headsha1" },
      html_url: "https://github.com/o/r/pull/42",
    });
  }
  if (cmd.includes("issues/42/comments") || cmd.includes("pulls/42/comments")) {
    return JSON.stringify([
      {
        user: { login: "coderabbitai[bot]" },
        body: "Summary: coderabbit completed review with no blocking findings",
        created_at: BOT_SIGNAL_TS,
      },
      {
        user: { login: "sourcery-ai[bot]" },
        body: "Sourcery review complete — no issues found on this change",
        created_at: BOT_SIGNAL_TS,
      },
      {
        user: { login: "gemini-code-assist[bot]" },
        body: "Gemini review complete — no actionable findings on this pull request",
        created_at: BOT_SIGNAL_TS,
      },
    ]);
  }
  if (cmd.includes("check-runs")) {
    return JSON.stringify({
      check_runs: [
        {
          id: 1,
          name: "ci",
          head_sha: "headsha1",
          status: "completed",
          conclusion: "success",
        },
      ],
    });
  }
  if (cmd.includes("repos/o/r/issues/42/reactions")) {
    return "[]";
  }
  if (
    (cmd.includes("pulls/comments/") || cmd.includes("issues/comments/")) &&
    cmd.includes("/reactions")
  ) {
    return "[]";
  }
  if (cmd.includes("pulls/42/reviews")) {
    return JSON.stringify([
      {
        user: { login: "chatgpt-codex-connector[bot]" },
        state: "COMMENTED",
        submitted_at: BOT_SIGNAL_TS,
        body: "Codex review complete",
      },
    ]);
  }
  if (cmd.includes("graphql") && cmd.includes("reviewThreads")) {
    return JSON.stringify({
      data: {
        repository: {
          pullRequest: {
            reviewThreads: {
              pageInfo: { endCursor: "cursor-single-page", hasNextPage: false },
              nodes: [],
            },
          },
        },
      },
    });
  }
  return "[]";
}

vi.mock("node:child_process", async (importOriginal) => {
  const actual = await importOriginal<typeof import("node:child_process")>();
  return {
    ...actual,
    execFileSync: vi.fn((file: string, args: string[], options?: object) => {
      if (file === "gh") {
        return ghFixture(file, args);
      }
      return actual.execFileSync(
        file,
        args as Parameters<typeof actual.execFileSync>[1],
        options as Parameters<typeof actual.execFileSync>[2],
      );
    }),
  };
});

import type {
  Backend,
  IssueMeta,
  IssueSnapshot,
  StepOutput,
  WorkerResult,
  WorkerSpec,
  WorktreeHandle,
} from "../src/types.js";
import { runOrchestrator } from "../src/runner.js";
import { skeletonReviewLoopWorkerResult } from "../src/reviewLoopOutcome.js";

describe("#600 r18 single-slice verify side-effect in-band", () => {
  const livePr = "https://github.com/o/r/pull/42";
  const worktree: WorktreeHandle = {
    branch: "feat/600-side-effect-fail",
    base: "main",
    path: "/resident/worktrees/issue-600-side-effect",
  };

  class SideEffectFailBackend implements Backend {
    async findResumeState(): Promise<undefined> {
      return undefined;
    }
    async cleanResidue(): Promise<void> {}
    async fetchIssueMeta(issueNumber: number): Promise<IssueMeta> {
      return {
        number: issueNumber,
        isReadyForAgent: true,
        hasSubIssues: false,
        openBlockedBy: [],
      };
    }
    async fetchIssueSnapshot(issueNumber: number): Promise<IssueSnapshot> {
      return {
        number: issueNumber,
        body: "b",
        comments: [],
        agentBrief: "",
      };
    }
    async prepareWorktree(): Promise<WorktreeHandle> {
      return worktree;
    }
    async writeSnapshot(): Promise<void> {}
    async writeLedger(): Promise<void> {}
    async runStep(): Promise<StepOutput> {
      throw new Error("runStep should not be called");
    }
    async push(): Promise<void> {}
    async dispatchWorker(spec: WorkerSpec): Promise<WorkerResult> {
      if (spec.kind === "coder") {
        return {
          kind: "completed",
          output: { kind: "coder", committed: true, commitsAdded: 1 },
        };
      }
      if (spec.kind === "reviewer") {
        return { kind: "completed", output: { kind: "reviewer", findings: [] } };
      }
      if (spec.kind === "verify") {
        return {
          kind: "completed",
          output: {
            kind: "verify",
            converged: true,
            isRecheck: true,
            threadsToResolve: ["PRRT_kwDOExampleThread"],
          },
        };
      }
      const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
      if (skeleton !== undefined) {
        return skeleton;
      }
      return {
        kind: "completed",
        output: {
          kind: "ship",
          branch: worktree.branch,
          status: "pr_opened",
          pr: livePr,
          prHead: "headsha1",
        },
      };
    }
  }

  afterEach(() => {
    ghCalls.length = 0;
    vi.useRealTimers();
  });

  it("pin: S9 side-effect failure errorTerminates with verify side-effect stopSummary", async () => {
    const prev = process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
    delete process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
    vi.useFakeTimers();
    vi.setSystemTime(new Date(POLL_TS));
    try {
      const result = await runOrchestrator({
        issueNumber: 600,
        backend: new SideEffectFailBackend(),
      });
      expect(result.status).toBe("error");
      expect(result.stopSummary?.reason).toBe("infra_failure");
      expect(result.stopSummary?.summary).toContain("side effects failed");
      expect(result.stopSummary?.summary).toContain("fixingCommitSha");
      expect(ghCalls.some((c) => c.startsWith("gh "))).toBe(true);
    } finally {
      if (prev === undefined) {
        delete process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
      } else {
        process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = prev;
      }
    }
  });
});