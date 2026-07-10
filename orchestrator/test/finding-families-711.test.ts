import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";

import { legacyDispatchWorker } from "../src/dispatchWorker.js";
import {
  FIX_FOCUS_LANDING_FILE,
  formatFixFocusMarkdown,
  priorOnlineReviewFindingsFromLedger,
  sanitizeFindingFamilies,
} from "../src/findingFamilies.js";
import { parseVerifyOutcome } from "../src/family/realFamilyBackend.js";
import { verifyOutputSchema } from "../src/realBackend.js";
import { isValidVerifyResult } from "../src/reviewLoopOutcome.js";
import type { Backend, StepOutput, VerifyResult, WorkerLandingPayload } from "../src/types.js";
import { fixerWorkerSpec } from "../src/dispatchWorker.js";

describe("#711 findingFamilies contract", () => {
  it("sanitizeFindingFamilies drops malformed entries but keeps valid ones", () => {
    const families = sanitizeFindingFamilies([
      {
        family: "silence-not-green",
        members: ["t:1"],
        recurringFromRounds: [1, 2],
        brief: "Silence must not count as green across call sites.",
      },
      { family: "", members: ["x"], recurringFromRounds: [1], brief: "bad" },
      "not-an-object",
    ]);
    expect(families).toEqual([
      {
        family: "silence-not-green",
        members: ["t:1"],
        recurringFromRounds: [1, 2],
        brief: "Silence must not count as green across call sites.",
      },
    ]);
  });

  it("malformed top-level findingFamilies degrades to undefined (not a gate)", () => {
    expect(sanitizeFindingFamilies("oops")).toBeUndefined();
    expect(sanitizeFindingFamilies({ family: "x" })).toBeUndefined();
  });

  it("verify schema accepts findingFamilies and parseVerifyOutcome preserves sanitized families", () => {
    const raw = {
      converged: false,
      findingDispositions: [
        {
          identityKey: "t:1",
          threadId: "thread-1",
          action: "fix" as const,
        },
      ],
      fixMarkedFindingIdentityKeys: ["t:1"],
      findingFamilies: [
        {
          family: "silence-not-green",
          members: ["t:1"],
          recurringFromRounds: [1, 2],
          brief: "Fix the class, not one call site.",
        },
        { bad: true },
      ],
    };
    const shape = verifyOutputSchema.parse(raw);
    expect(shape.findingFamilies).toEqual(raw.findingFamilies);
    const stdout = `<verify>${JSON.stringify(raw)}</verify>`;
    const parsed = parseVerifyOutcome(stdout);
    expect(parsed).toMatchObject({
      kind: "verify",
      converged: false,
      findingFamilies: [
        {
          family: "silence-not-green",
          members: ["t:1"],
          recurringFromRounds: [1, 2],
          brief: "Fix the class, not one call site.",
        },
      ],
    });
    expect(isValidVerifyResult(parsed as VerifyResult)).toBe(true);
  });

  it("verify output stays valid when findingFamilies is entirely malformed", () => {
    const raw = {
      converged: false,
      findingDispositions: [
        {
          identityKey: "t:1",
          threadId: "thread-1",
          action: "fix" as const,
        },
      ],
      fixMarkedFindingIdentityKeys: ["t:1"],
      findingFamilies: "not-an-array",
    };
    verifyOutputSchema.parse(raw);
    const parsed = parseVerifyOutcome(`<verify>${JSON.stringify(raw)}</verify>`);
    expect(parsed).toMatchObject({ kind: "verify", converged: false });
    expect((parsed as VerifyResult).findingFamilies).toBeUndefined();
    expect(isValidVerifyResult(parsed as VerifyResult)).toBe(true);
  });
});

describe("#711 prior round findings + fix-focus forwarding", () => {
  const worktrees: string[] = [];
  afterEach(() => {
    for (const dir of worktrees.splice(0)) {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("priorOnlineReviewFindingsFromLedger collects rounds before the current one", () => {
    const ledger = [
      {
        step: "S9",
        output: {
          kind: "verify",
          converged: false,
          fixMarkedFindingIdentityKeys: ["t:1"],
        } satisfies VerifyResult,
      },
      { step: "S10", output: { kind: "fixer", committed: true, fixCommitSha: "abc" } },
      {
        step: "S9",
        output: {
          kind: "verify",
          converged: false,
          fixMarkedFindingIdentityKeys: ["t:2"],
        } satisfies VerifyResult,
      },
    ];
    expect(priorOnlineReviewFindingsFromLedger(ledger, 3)).toEqual([
      { round: 1, fixMarkedFindingIdentityKeys: ["t:1"] },
      { round: 2, fixMarkedFindingIdentityKeys: ["t:2"] },
    ]);
  });

  it("formatFixFocusMarkdown includes recurring round markers for fixer", () => {
    const md = formatFixFocusMarkdown([
      {
        family: "silence-not-green",
        members: ["t:1", "t:2"],
        recurringFromRounds: [1, 2],
        brief: "Silence must not count as green.",
      },
    ]);
    expect(md).toContain("Recurring from rounds: 1, 2");
    expect(md).toContain("silence-not-green");
  });

  it("r3 fixer dispatch writes .fix-focus.md with recurring markers (runner pure IO)", async () => {
    const worktree = mkdtempSync(join(tmpdir(), "fix-focus-711-"));
    const stateDir = mkdtempSync(join(tmpdir(), "fix-focus-state-711-"));
    worktrees.push(worktree, stateDir);
    const landingPayload: WorkerLandingPayload = {
      onlineReviewSnapshot: {
        prUrl: "https://github.com/o/r/pull/42",
        headOid: "abc",
        totalFindingCount: 1,
        quiescent: false,
        bots: {
          coderabbit: { state: "complete", findingCount: 1 },
          sourcery: { state: "complete", findingCount: 0 },
          codex: { state: "complete", findingCount: 0 },
          gemini: { state: "complete", findingCount: 0 },
        },
        droppedBots: [],
        threads: [],
        checkRuns: [],
      },
      onlineReviewRound: 3,
      fixMarkedFindingIdentityKeys: ["t:3"],
      findingFamilies: [
        {
          family: "silence-not-green",
          members: ["t:3"],
          recurringFromRounds: [1, 2],
          brief: "Same class recurred — sweep all silence-as-green sites.",
        },
      ],
    };
    const spec = fixerWorkerSpec();
    // A defined dispatchWorker skips the offline skeleton short-circuit so the
    // legacy path reaches landing + fix-focus writes (same pattern as #600 r17).
    const legacyBackend = {
      dispatchWorker: async () => ({
        kind: "completed" as const,
        output: {
          kind: "fixer",
          committed: true,
          fixCommitSha: "deadbeef",
        },
      }),
      async runStep(): Promise<StepOutput> {
        return {
          kind: "fixer",
          committed: true,
          fixCommitSha: "deadbeef",
        };
      },
    } as unknown as Backend;
    await legacyDispatchWorker(
      legacyBackend,
      spec,
      {
        worktree: { branch: "feat/x", base: "main", path: worktree },
        stateDir,
        repo: "o/r",
        prUrl: "https://github.com/o/r/pull/42",
        onlineReviewRound: 3,
      },
      landingPayload,
    );
    const fixFocusPath = join(stateDir, "fix-focus.md");
    const fixFocus = readFileSync(fixFocusPath, "utf8");
    expect(fixFocus).toContain("Recurring from rounds: 1, 2");
    expect(fixFocus).toContain("silence-not-green");
    expect(fixFocus).toContain("sweep all silence-as-green sites");
  });
});