/**
 * #1126 R3 — RealBackend production seam for runner-owned review-panel legs.
 *
 * Axis legs keep scope.judgeStep id (S3/S6) for monitor bookkeeping, but must
 * NOT enter legacyDispatchWorker (judge/open-count SO strips prose → empty
 * papers). Stub outermost runAgentSandbox; enter via dispatchWorker.
 */

import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";

import { afterAll, afterEach, describe, expect, it } from "vitest";

import {
  CODE_REVIEW_SPEC_LEG_PROMPT_FILE,
  CODE_REVIEW_STANDARDS_LEG_PROMPT_FILE,
  reviewPanelLegWorkerSpec,
} from "../../src/family/reviewPanelLegs.js";
import {
  RealBackend,
  SANDBOX_FIX_FINDINGS_PATH_ENV,
  SANDBOX_REVIEW_FIXED_POINT_ENV,
  type AgentSandboxRunOptions,
} from "../../src/realBackend.js";
import type {
  DispatchContext,
  WorkerLandingPayload,
  WorkerSpec,
  WorktreeHandle,
} from "../../src/types.js";
import type * as sc from "@ai-hero/sandcastle";

const here = dirname(fileURLToPath(import.meta.url));
const realPromptsDir = join(here, "..", "..", "prompts");
const realSoulsDir = join(here, "..", "..", "image", "souls");

const SLICE_BASE = "origin/codex/issue-1126-base";
const PANEL_PROSE = "AXIS_PANEL_PROSE_1126: standards findings in prose";

type AgentRunResult = Awaited<ReturnType<typeof sc.run>>;

function agentRunResult(stdout: string): AgentRunResult {
  return {
    branch: "feat/issue-1126",
    stdout,
    commits: [],
    iterations: [{ sessionId: "sess-panel-1126" }],
  } as AgentRunResult;
}

const tempHomes: string[] = [];
const tempWorktrees: string[] = [];

function tempHome(): string {
  const home = mkdtempSync(join(tmpdir(), "rb-panel-1126-"));
  tempHomes.push(home);
  return home;
}

function cleanupDirs(dirs: string[]): void {
  while (dirs.length > 0) {
    const dir = dirs.pop();
    if (dir === undefined) break;
    rmSync(dir, { recursive: true, force: true });
  }
}

afterEach(() => {
  cleanupDirs(tempHomes);
  cleanupDirs(tempWorktrees);
});
afterAll(() => {
  cleanupDirs(tempHomes);
  cleanupDirs(tempWorktrees);
});

class PanelLegProbeBackend extends RealBackend {
  lastAgentOptions?: AgentSandboxRunOptions;
  capturedEnv?: Record<string, string>;
  agentRunReached = false;

  protected override boxConfig(
    ...args: Parameters<RealBackend["boxConfig"]>
  ): ReturnType<RealBackend["boxConfig"]> {
    const cfg = super.boxConfig(...args);
    this.capturedEnv = cfg.env;
    return cfg;
  }

  protected override async runAgentSandbox(
    options: AgentSandboxRunOptions,
  ): Promise<AgentRunResult> {
    this.lastAgentOptions = options;
    this.agentRunReached = true;
    return agentRunResult(PANEL_PROSE);
  }
}

function makeBackend(): PanelLegProbeBackend {
  return new PanelLegProbeBackend({
    sourceRepo: "/tmp/source",
    remote: "https://github.com/owner/name.git",
    runKey: 1126,
    repo: "owner/name",
    imageName: "ming-worker:test",
    promptsDir: realPromptsDir,
    soulsDir: realSoulsDir,
    home: tempHome(),
  });
}

function worktree(): WorktreeHandle {
  const path = mkdtempSync(join(tmpdir(), "wt-panel-1126-"));
  tempWorktrees.push(path);
  return {
    branch: "feat/issue-1126",
    base: SLICE_BASE,
    path,
  };
}

function standardsLeg(): WorkerSpec {
  return reviewPanelLegWorkerSpec(
    { family: "codex", slug: "gpt-5.6-sol", axis: "standards" },
    { kind: "single", judgeStep: "S3" },
  );
}

function dispatchCtx(wt: WorktreeHandle): DispatchContext {
  return { worktree: wt };
}

describe("#1126 RealBackend review-panel raw-prose path", () => {
  it("dispatchWorker: no output schema, rawStdout preserved, fixed point from base, no judge landing", async () => {
    const backend = makeBackend();
    const wt = worktree();
    const spec = standardsLeg();
    expect(spec.id).toBe("S3");
    expect(spec.promptFile).toBe(CODE_REVIEW_STANDARDS_LEG_PROMPT_FILE);

    const landing: WorkerLandingPayload = {
      panelLegTransports: [
        { slug: "bait", exitCode: 0, stdout: "should not mount" },
      ],
      fixPacketBody: "judge bait — panel legs must ignore landing",
    };

    const result = await backend.dispatchWorker(
      spec,
      dispatchCtx(wt),
      landing,
    );

    expect(backend.agentRunReached).toBe(true);
    expect(backend.lastAgentOptions).toBeDefined();
    // Raw-prose path: never attach judge / open-count structured output.
    expect(
      (backend.lastAgentOptions as { output?: unknown }).output,
    ).toBeUndefined();

    expect(result.kind).toBe("completed");
    if (result.kind !== "completed") throw new Error("expected completed");
    expect(result.output).toMatchObject({
      kind: "reviewer",
      rawStdout: PANEL_PROSE,
    });

    expect(backend.capturedEnv?.[SANDBOX_REVIEW_FIXED_POINT_ENV]).toBe(
      SLICE_BASE,
    );
    expect(backend.capturedEnv?.[SANDBOX_FIX_FINDINGS_PATH_ENV]).toBeUndefined();
  });

  it("spec-axis leg also takes the raw-prose path (same mechanism)", async () => {
    const backend = makeBackend();
    const wt = worktree();
    const spec = reviewPanelLegWorkerSpec(
      { family: "codex", slug: "gpt-5.6-sol", axis: "spec" },
      { kind: "single", judgeStep: "S6" },
    );
    expect(spec.id).toBe("S6");
    expect(spec.promptFile).toBe(CODE_REVIEW_SPEC_LEG_PROMPT_FILE);

    const result = await backend.dispatchWorker(spec, dispatchCtx(wt));

    expect(
      (backend.lastAgentOptions as { output?: unknown }).output,
    ).toBeUndefined();
    expect(result.kind).toBe("completed");
    if (result.kind !== "completed") throw new Error("expected completed");
    expect(result.output).toMatchObject({ rawStdout: PANEL_PROSE });
    expect(backend.capturedEnv?.[SANDBOX_REVIEW_FIXED_POINT_ENV]).toBe(
      SLICE_BASE,
    );
  });
});
