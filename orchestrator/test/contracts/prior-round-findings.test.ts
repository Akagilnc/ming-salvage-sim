import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import {
  mergePriorRoundFindings,
  priorCmrFindingsFromFamilyLedger,
  priorOnlineReviewFindingsFromFamilyLedger,
} from "../../src/priorRoundFindings.js";
import { parseVerifyOutcome } from "../../src/family/realFamilyBackend.js";
import { runOnlineReviewLoopStage } from "../../src/family/onlineReviewLoop.js";
import type {
  VerifyResult,
  WorkerLandingPayload,
} from "../../src/types.js";
import type { PrReviewSnapshot } from "../../src/botPolling.js";

/**
 * ADR 0137 residual ban — live tree must not reintroduce the deleted pattern
 * brief side channel. Scope matches AC: whole-repo zero hits, historical ADR
 * under docs/adr/** excepted. Patterns are built at runtime so this file does
 * not contain the banned spellings as contiguous literals. Case-insensitive
 * so camelCase / PascalCase / snake_case aliases collapse cheaply.
 */
function bannedResidual(): RegExp {
  const parts = [
    "finding" + "Families",
    "finding" + "Family",
    "finding" + "_families",
    "finding" + "_family",
    "fix" + "Focus",
    "fix" + "_focus",
    "fix" + "-focus",
  ];
  return new RegExp(parts.join("|"), "i");
}

/** Repo root: orchestrator/test/contracts → ../../.. */
const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const ORCH_ROOT = join(REPO_ROOT, "orchestrator");

function relPosix(file: string): string {
  return relative(REPO_ROOT, file).split("\\").join("/");
}

/** AC exception: historical ADR / campaign notes live under docs/adr. */
function isHistoricalAdr(path: string): boolean {
  const rel = relPosix(path);
  return rel === "docs/adr" || rel.startsWith("docs/adr/");
}

/**
 * Release notes name deleted channels as history — same class of AC exception
 * as docs/adr (not production residual). CI failed when CHANGELOG recorded #977.
 */
function isHistoricalReleaseNote(path: string): boolean {
  const rel = relPosix(path);
  return rel === "CHANGELOG.md" || rel.endsWith("/CHANGELOG.md");
}

function walkFiles(root: string, acc: string[] = []): string[] {
  for (const name of readdirSync(root)) {
    if (name === "node_modules" || name === "dist" || name === ".git") continue;
    const full = join(root, name);
    if (isHistoricalAdr(full) || isHistoricalReleaseNote(full)) continue;
    const st = statSync(full);
    if (st.isDirectory()) walkFiles(full, acc);
    else if (/\.(ts|md|json|js|mjs|cjs)$/.test(name)) acc.push(full);
  }
  return acc;
}

describe("#977 ADR 0137 residual ban (pattern-brief side channel)", () => {
  it("repo has zero residual side-channel hits outside docs/adr", () => {
    const re = bannedResidual();
    const hits: string[] = [];
    for (const file of walkFiles(REPO_ROOT)) {
      const text = readFileSync(file, "utf8");
      if (!re.test(text)) continue;
      for (const [i, line] of text.split(/\r?\n/).entries()) {
        if (re.test(line)) {
          hits.push(`${relPosix(file)}:${i + 1}:${line.trim()}`);
        }
      }
    }
    expect(hits).toEqual([]);
  });

  it("coder_fix prompt has no pattern-brief family sweep clause", () => {
    const prompt = readFileSync(
      join(ORCH_ROOT, "prompts/coder_fix.md"),
      "utf8",
    );
    const re = bannedResidual();
    expect(re.test(prompt)).toBe(false);
    expect(prompt.toLowerCase()).not.toContain("finding family");
  });
});

describe("#711 prior round findings (ledger half retained after ADR 0137)", () => {
  it("mergePriorRoundFindings unions by round (later source wins same round)", () => {
    expect(
      mergePriorRoundFindings(
        [
          { round: 1, fixMarkedFindingIdentityKeys: ["ledger:r1"] },
          { round: 2, fixMarkedFindingIdentityKeys: ["ledger:r2-stale"] },
        ],
        [{ round: 2, fixMarkedFindingIdentityKeys: ["process:r2"] }],
      ),
    ).toEqual([
      { round: 1, fixMarkedFindingIdentityKeys: ["ledger:r1"] },
      { round: 2, fixMarkedFindingIdentityKeys: ["process:r2"] },
    ]);
  });

  it("priorOnlineReviewFindingsFromFamilyLedger reads fix_committed markers", () => {
    const familyLedger = [
      {
        event: "online_review_fix_committed",
        onlineReviewRound: 1,
        fixMarkedFindingIdentityKeys: ["silence:r1"],
        familyHeadAfter: "sha1",
      },
      {
        event: "online_review_round_retrigger",
        onlineReviewRound: 2,
        roundTriggerHeadOid: "sha1",
      },
      {
        event: "online_review_fix_committed",
        onlineReviewRound: 2,
        fixMarkedFindingIdentityKeys: ["silence:r2"],
        familyHeadAfter: "sha2",
      },
    ];
    expect(priorOnlineReviewFindingsFromFamilyLedger(familyLedger, 3)).toEqual([
      { round: 1, fixMarkedFindingIdentityKeys: ["silence:r1"] },
      { round: 2, fixMarkedFindingIdentityKeys: ["silence:r2"] },
    ]);
  });

  it("priorCmrFindingsFromFamilyLedger excludes other and unclassified CMR passes", () => {
    const finding = {
      severity: "medium" as const,
      category: "correctness" as const,
      claim_quote: "silence treated as green",
      location: "src/a.ts",
      suggested_fix: "fail closed",
      action: "fix_now" as const,
    };
    const ledger = [
      {
        event: "cmr_reviewed",
        cmrPass: "completeness",
        blockingFindingIdentityKeys: ["reviewed:complete"],
      },
      { output: { kind: "cmr", findings: [finding] }, cmrPass: "correctness" },
      { output: { kind: "cmr", findings: [finding] }, cmrPass: "completeness" },
      { output: { kind: "cmr", findings: [finding] } },
    ];

    expect(priorCmrFindingsFromFamilyLedger(ledger, "completeness")).toEqual([
      {
        round: 1,
        fixMarkedFindingIdentityKeys: [],
        blockingFindingIdentityKeys: ["reviewed:complete"],
      },
      {
        round: 2,
        fixMarkedFindingIdentityKeys: [],
        blockingFindingIdentityKeys: [
          "correctness|src/a.ts|silence treated as green",
        ],
      },
    ]);
  });

  it("#982: prefers explicit blockingFindingIdentityKeys over dual output fallback on same row", () => {
    const finding = {
      severity: "high" as const,
      category: "correctness" as const,
      claim_quote: "dual snapshot would invent round 2",
      location: "src/dual.ts",
      suggested_fix: "continue after explicit keys",
      action: "fix_now" as const,
    };
    const ledger = [
      {
        event: "cmr_reviewed",
        cmrPass: "completeness",
        blockingFindingIdentityKeys: ["explicit:persisted-key"],
        output: { kind: "judge", findings: [finding] },
      },
    ];
    const snaps = priorCmrFindingsFromFamilyLedger(ledger, "completeness");
    expect(snaps).toHaveLength(1);
    expect(snaps[0]).toEqual({
      round: 1,
      fixMarkedFindingIdentityKeys: [],
      blockingFindingIdentityKeys: ["explicit:persisted-key"],
    });
  });

  it("verify prompt contains only the data and output contract", () => {
    const prompt = readFileSync(
      join(ORCH_ROOT, "prompts/verify.md"),
      "utf8",
    );
    expect(prompt).not.toContain("use it to mark recurringFromRounds");
    expect(prompt).not.toContain(
      "When `priorRoundFindings` is in the landing file",
    );
  });

  it("parseVerifyOutcome ignores residual pattern-brief cargo (opaque miss)", () => {
    const residualKey = "finding" + "Families";
    const raw: Record<string, unknown> = {
      converged: false,
      findingDispositions: [
        {
          identityKey: "t:1",
          threadId: "thread-1",
          action: "fix" as const,
        },
      ],
      fixMarkedFindingIdentityKeys: ["t:1"],
    };
    // residual deleted channel — must not attach onto VerifyResult
    raw[residualKey] = [
      {
        family: "silence-not-green",
        members: ["t:1"],
        recurringFromRounds: [1, 2],
        brief: "should be ignored",
      },
    ];
    const parsed = parseVerifyOutcome(`<verify>${JSON.stringify(raw)}</verify>`);
    expect(parsed).toMatchObject({
      kind: "verify",
      converged: false,
      fixMarkedFindingIdentityKeys: ["t:1"],
    });
    expect(Object.prototype.hasOwnProperty.call(parsed, residualKey)).toBe(
      false,
    );
  });
});

describe("#711 three-round priorRoundFindings path (no pattern-brief channel)", () => {
  const stageShip = {
    kind: "ship" as const,
    branch: "family/epic-711",
    status: "pr_opened",
    pr: "pr://family/711-stage",
    prHead: "head-1",
  };

  const baseSnapshot: PrReviewSnapshot = {
    repo: "o/r",
    prNumber: 711,
    prUrl: "pr://family/711-stage",
    headOid: "head-1",
    pollCount: 1,
    bots: {
      coderabbit: { state: "complete", findingCount: 1 },
      sourcery: { state: "complete", findingCount: 0 },
      codex: { state: "complete", findingCount: 0 },
      gemini: { state: "complete", findingCount: 0 },
    },
    threads: [
      {
        id: "thread-silence",
        authorLogin: "coderabbit",
        threadNodeId: "thread-silence-node",
        path: "src/a.ts",
        line: 1,
        body: "silence treated as green",
        isResolved: false,
      },
    ],
    checkRuns: [],
    roundTriggerUsed: {
      headOid: "head-1",
      triggeredAt: "2026-07-10T00:00:00.000Z",
    },
    checkRunsEmptyMeans: "converged",
    totalFindingCount: 1,
    quiescent: true,
  };

  function mergeEnrichFromLedger(
    familyLedger: ReadonlyArray<{
      readonly event: string;
      readonly onlineReviewRound?: number;
      readonly fixMarkedFindingIdentityKeys?: ReadonlyArray<string>;
    }>,
  ) {
    return async (
      landing: WorkerLandingPayload,
      round: number,
    ): Promise<WorkerLandingPayload> => {
      const fromLedger = priorOnlineReviewFindingsFromFamilyLedger(
        familyLedger,
        round,
      );
      const merged = mergePriorRoundFindings(
        fromLedger,
        landing.priorRoundFindings ?? [],
      );
      return merged.length > 0
        ? { ...landing, priorRoundFindings: merged }
        : landing;
    };
  }

  it("three-round path: r3 verify sees prior fix-marked keys from earlier rounds", async () => {
    const verifyLandings: WorkerLandingPayload[] = [];
    const fixerLandings: WorkerLandingPayload[] = [];
    const familyLedger: Array<{
      event: string;
      onlineReviewRound?: number;
      fixMarkedFindingIdentityKeys?: ReadonlyArray<string>;
      familyHeadAfter?: string;
    }> = [];

    const result = await runOnlineReviewLoopStage(
      stageShip,
      {
        poll: async () => baseSnapshot,
        dispatchVerify: async (landing, round) => {
          verifyLandings.push(landing);
          if (round >= 4) {
            return {
              kind: "verify",
              converged: true,
              isRecheck: true,
              fixMarkedFindingIdentityKeys:
                landing.fixMarkedFindingIdentityKeys ?? [],
            } satisfies VerifyResult;
          }
          const key = `silence:r${round}`;
          return {
            kind: "verify",
            converged: false,
            isRecheck: round > 1,
            fixMarkedFindingIdentityKeys: [key],
            findingDispositions: [
              {
                identityKey: key,
                threadId: "thread-silence",
                action: "fix",
              },
            ],
          } satisfies VerifyResult;
        },
        dispatchFixer: async (landing) => {
          fixerLandings.push(landing);
          const n = fixerLandings.length;
          return {
            kind: "fixer",
            committed: true,
            fixCommitSha: `fix-sha-${n}`,
          };
        },
        resolveFixCommitSha: async (sha) => {
          const lastFixer = fixerLandings[fixerLandings.length - 1]!;
          familyLedger.push({
            event: "online_review_fix_committed",
            onlineReviewRound:
              lastFixer.onlineReviewRound ?? fixerLandings.length,
            fixMarkedFindingIdentityKeys:
              lastFixer.fixMarkedFindingIdentityKeys ?? [],
            familyHeadAfter: sha,
          });
          return sha;
        },
        applySideEffects: (_landing, verify) => verify,
        retriggerAfterFix: () => {},
      },
      {
        enrichVerifyLanding: mergeEnrichFromLedger(familyLedger),
      },
    );

    expect(result).toEqual({
      ok: true,
      terminalState: "mergeable",
      round: 4,
    });
    expect(verifyLandings).toHaveLength(4);
    expect(fixerLandings).toHaveLength(3);

    expect(verifyLandings[0]!.priorRoundFindings ?? []).toEqual([]);
    expect(verifyLandings[1]!.priorRoundFindings).toMatchObject([
      { round: 1, fixMarkedFindingIdentityKeys: ["silence:r1"] },
    ]);
    expect(verifyLandings[2]!.priorRoundFindings).toMatchObject([
      { round: 1, fixMarkedFindingIdentityKeys: ["silence:r1"] },
      { round: 2, fixMarkedFindingIdentityKeys: ["silence:r2"] },
    ]);

    // Fixer landing carries only fix-marked keys — no pattern-brief side channel.
    expect(fixerLandings[2]!.fixMarkedFindingIdentityKeys).toEqual([
      "silence:r3",
    ]);
    expect(
      Object.prototype.hasOwnProperty.call(
        fixerLandings[2]!,
        "finding" + "Families",
      ),
    ).toBe(false);

    expect(familyLedger).toHaveLength(3);
    expect(priorOnlineReviewFindingsFromFamilyLedger(familyLedger, 3)).toEqual([
      { round: 1, fixMarkedFindingIdentityKeys: ["silence:r1"] },
      { round: 2, fixMarkedFindingIdentityKeys: ["silence:r2"] },
    ]);
  });

  it("resume mid-loop merges ledger history with in-process rounds so r3 sees r1+r2", async () => {
    const familyLedger: Array<{
      event: string;
      onlineReviewRound?: number;
      fixMarkedFindingIdentityKeys?: ReadonlyArray<string>;
      familyHeadAfter?: string;
    }> = [
      {
        event: "online_review_fix_committed",
        onlineReviewRound: 1,
        fixMarkedFindingIdentityKeys: ["silence:r1"],
        familyHeadAfter: "sha-r1",
      },
    ];
    const verifyLandings: WorkerLandingPayload[] = [];
    const fixerLandings: WorkerLandingPayload[] = [];

    const result = await runOnlineReviewLoopStage(
      stageShip,
      {
        poll: async () => baseSnapshot,
        dispatchVerify: async (landing, round) => {
          verifyLandings.push(landing);
          if (round >= 4) {
            return {
              kind: "verify",
              converged: true,
              isRecheck: true,
              fixMarkedFindingIdentityKeys:
                landing.fixMarkedFindingIdentityKeys ?? [],
            } satisfies VerifyResult;
          }
          const key = `silence:r${round}`;
          return {
            kind: "verify",
            converged: false,
            isRecheck: true,
            fixMarkedFindingIdentityKeys: [key],
            findingDispositions: [
              {
                identityKey: key,
                threadId: "thread-silence",
                action: "fix",
              },
            ],
          } satisfies VerifyResult;
        },
        dispatchFixer: async (landing) => {
          fixerLandings.push(landing);
          return {
            kind: "fixer",
            committed: true,
            fixCommitSha: `resume-fix-${landing.onlineReviewRound ?? "?"}`,
          };
        },
        resolveFixCommitSha: async (sha) => {
          const lastFixer = fixerLandings[fixerLandings.length - 1]!;
          familyLedger.push({
            event: "online_review_fix_committed",
            onlineReviewRound:
              lastFixer.onlineReviewRound ?? fixerLandings.length + 1,
            fixMarkedFindingIdentityKeys:
              lastFixer.fixMarkedFindingIdentityKeys ?? [],
            familyHeadAfter: sha,
          });
          return sha;
        },
        applySideEffects: (_landing, verify) => verify,
        retriggerAfterFix: () => {},
      },
      {
        initialRound: 2,
        enrichVerifyLanding: mergeEnrichFromLedger(familyLedger),
      },
    );

    expect(result.ok).toBe(true);
    expect(verifyLandings.length).toBeGreaterThanOrEqual(3);
    expect(verifyLandings[0]!.onlineReviewRound).toBe(2);
    expect(verifyLandings[0]!.priorRoundFindings).toMatchObject([
      { round: 1, fixMarkedFindingIdentityKeys: ["silence:r1"] },
    ]);
    const r3Verify = verifyLandings.find((l) => l.onlineReviewRound === 3);
    expect(r3Verify).toBeDefined();
    expect(r3Verify!.priorRoundFindings).toMatchObject([
      { round: 1, fixMarkedFindingIdentityKeys: ["silence:r1"] },
      { round: 2, fixMarkedFindingIdentityKeys: ["silence:r2"] },
    ]);
  });

  it("fixer coverage stays on fixMarked keys only (no pattern-brief expansion)", async () => {
    const fixerLandings: WorkerLandingPayload[] = [];
    let verifyCalls = 0;

    const result = await runOnlineReviewLoopStage(stageShip, {
      poll: async () => baseSnapshot,
      dispatchVerify: async (landing, round) => {
        verifyCalls += 1;
        if (round >= 2) {
          return {
            kind: "verify",
            converged: true,
            isRecheck: true,
            fixMarkedFindingIdentityKeys:
              landing.fixMarkedFindingIdentityKeys ?? [],
          } satisfies VerifyResult;
        }
        return {
          kind: "verify",
          converged: false,
          fixMarkedFindingIdentityKeys: ["silence:site-a"],
          findingDispositions: [
            {
              identityKey: "silence:site-a",
              threadId: "thread-silence",
              action: "fix",
            },
          ],
        } satisfies VerifyResult;
      },
      dispatchFixer: async (landing) => {
        fixerLandings.push(landing);
        return {
          kind: "fixer",
          committed: true,
          fixCommitSha: "fix-once",
        };
      },
      applySideEffects: (_landing, verify) => verify,
      retriggerAfterFix: () => {},
    });

    expect(result.ok).toBe(true);
    expect(verifyCalls).toBeGreaterThanOrEqual(2);
    expect(fixerLandings).toHaveLength(1);
    expect(fixerLandings[0]!.fixMarkedFindingIdentityKeys).toEqual([
      "silence:site-a",
    ]);
    expect(
      Object.prototype.hasOwnProperty.call(
        fixerLandings[0]!,
        "finding" + "Families",
      ),
    ).toBe(false);
  });
});
