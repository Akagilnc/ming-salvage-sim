/**
 * #335 — the family integrated cmr step is a CONTAINER cmr WORKER that invokes
 * the real `ak-cross-m-review`, replacing the runner-internal 3-CLI 手搓
 * (`DriverFamilyBackend.runCmr`'s direct codex/claude/agy fan-out).
 *
 * The cmr worker = the 2b container's TOP-LEVEL claude; it `Skill`-invokes
 * `ak-cross-m-review` (which itself fans out 1 Agent + 2 CLI legs inside the
 * container — proven in #333), FRESH each round (cross-model independence). The
 * worker returns a `{converged, reason?, findings?, successfulLegs, skippedLegs?}`
 * verdict (PRD #330 R2: a `red` review outcome is still
 * `WorkerResult.completed`, and `verifyCmr.ts` decides whether to abort or dispatch
 * a separate coder-fix worker). A `red` verdict is NOT `failed`.
 *
 * Tested WITHOUT a real container:
 *   - parseCmrOutcome: the `<cmr>` tag → converged / red / escalate / sparse cargo;
 *   - cmrOutcomeFromResult: sidecar/structured outcome parsing; completion signals
 *     remain compatibility telemetry, not a verdict gate;
 *   - RealFamilyBackend.dispatchWorker(cmr): routes ak-cross-m-review + FRESH +
 *     clean cmr reviewer soul through the injected `runCmrWorker` seam and wraps the verdict
 *     into a WorkerResult (converged → completed; red → completed; escalate →
 *     escalated; sparse cargo remains completed cargo);
 *   - cmrSandboxConfig: wires the agy auth runtime-mount (writable dir) + codex
 *     auth + the claude token (the #333 gotcha: agy needs its file token mounted,
 *     else the cmr leg degrades to codex-only);
 *   - the deleted-fanout regression: the 手搓 symbols no longer exist on the
 *     familyDriver module.
 */

import { execFileSync } from "node:child_process";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it, vi } from "vitest";

import * as sc from "@ai-hero/sandcastle";
import type { RunResult } from "@ai-hero/sandcastle";
import { docker } from "@ai-hero/sandcastle/sandboxes/docker";
import {
  CMR_ROUTE_FILENAME,
  CMR_FOCUS_FILENAME,
  cmrOutcomeFromResult,
  parseCmrOutcome,
  RealFamilyBackend,
  SANDBOX_AGY_DIR,
  type CmrAuth,
  type CmrWorkerOutcome,
  type ShipAuth,
} from "../../../src/family/realFamilyBackend.js";
import {
  isReceiptRecoveryFailure,
  RECEIPT_MAX_RETRIES,
  workerReceiptSchema,
} from "../../../src/receiptRecovery.js";
import {
  SANDBOX_CODEX_DIR,
  SANDBOX_GH_TOKEN_ENV,
  SANDBOX_GROK_DIR,
  SANDBOX_OPENCODE_AUTH_FILE,
  SANDBOX_REPO_ENV,
  SANDBOX_SOUL_ENV,
  SPAWNED_WORKER_ENV,
} from "../../../src/realBackend.js";
import {
  cmrWorkerSpec,
  familyCoderFixWorkerSpec,
  familyShipWorkerSpec,
} from "../../../src/family/dispatchFamilyWorker.js";
import { shipOutcomeFromResult } from "../../../src/shipOutcome.js";
import { isRunnerSynthesizedFailureEscalation } from "../../../src/runnerEscalation.js";
import type {
  DispatchContext,
  WorkerLandingPayload,
  WorkerResult,
  WorkerSpec,
} from "../../../src/types.js";

const here = dirname(fileURLToPath(import.meta.url));
const realPromptsDir = join(here, "..", "..", "..", "prompts");
const realSoulsDir = join(here, "..", "..", "..", "image", "souls");
const DEFAULT_CMR_LEGS = ["opus", "gpt-5.6-sol", "agy"] as const;
const FROZEN_NORMAL_CMR_REVIEW_LEGS = [
  { family: "codex", slug: "gpt-5.6-sol" },
  { family: "claude", slug: "opus" },
  { family: "agy", slug: "agy" },
] as const;
const STRONG_LEGS = ["opus", "gpt-5.6-sol"] as const;
const EMPTY_CMR_CLOSURE = {
  claimedFixedFindingIdentityKeys: [],
  priorFindingDispositions: [],
} as const;
const CMR_EVIDENCE_PATHS = ["cmr/review-summary.json"] as const;
const CMR_EVIDENCE = {
  evidencePaths: CMR_EVIDENCE_PATHS,
} as const;
const VALID_CMR_VERDICT_FIELDS = {
  ...EMPTY_CMR_CLOSURE,
  ...CMR_EVIDENCE,
} as const;
/** Expected on successful parse/verdict output (derived; not a wire field). */
const DERIVED_EMPTY_FINDINGS_COUNT = { findingsCount: 0 } as const;

/** A Sandcastle result fixture with the public result shape, not a partial cast. */
function sandboxRunResult({
  branch = "fb",
  completionSignal,
  stdout = "",
  commits = [],
  sessionId,
}: {
  readonly branch?: string;
  readonly completionSignal?: string;
  readonly stdout?: string;
  readonly commits?: ReadonlyArray<{ readonly sha: string }>;
  readonly sessionId?: string;
} = {}): RunResult {
  return {
    branch,
    completionSignal,
    stdout,
    commits: [...commits],
    iterations: sessionId === undefined ? [] : [{ sessionId }],
  };
}

function typedSandboxRunResult<T>(
  output: T,
  fields: Parameters<typeof sandboxRunResult>[0] = {},
): RunResult & { readonly output: T } {
  return { ...sandboxRunResult(fields), output };
}

/**
 * Models Sandcastle's native typed-output transport at the public sandbox seam:
 * one initial submission, then up to `maxRetries` resumes of that exact agent
 * session after schema failures.  The backend must make only this one call;
 * Sandcastle owns the re-ask loop rather than the runner replaying a reviewer.
 */
function fakeNativeReceiptReask<T>(
  output: { readonly maxRetries?: number },
  receipts: readonly unknown[],
  schema: { safeParse(value: unknown): { success: boolean } },
  sessionId: string,
): {
  readonly attempts: ReadonlyArray<{ readonly sessionId: string; readonly receipt: unknown }>;
  readonly resumes: ReadonlyArray<{ readonly sessionId: string; readonly feedback: string }>;
  readonly result?: T;
} {
  const attempts: Array<{ readonly sessionId: string; readonly receipt: unknown }> = [];
  const resumes: Array<{ readonly sessionId: string; readonly feedback: string }> = [];
  const maxRetries = output.maxRetries ?? 0;
  for (const [index, receipt] of receipts.entries()) {
    attempts.push({ sessionId, receipt });
    if (schema.safeParse(receipt).success) return { attempts, resumes, result: receipt as T };
    if (index === maxRetries) break;
    resumes.push({
      sessionId,
      feedback: "The typed CMR receipt was malformed; re-emit only a valid <cmr> receipt.",
    });
  }
  return { attempts, resumes };
}

const cleanups: string[] = [];
afterEach(() => {
  vi.unstubAllEnvs();
  while (cleanups.length > 0) {
    const p = cleanups.pop();
    if (p !== undefined) rmSync(p, { recursive: true, force: true });
  }
});
function mkDir(prefix: string): string {
  const d = mkdtempSync(join(tmpdir(), prefix));
  cleanups.push(d);
  return d;
}

function makeBackend(over?: {
  home?: string;
  ledgerDir?: string;
}): RealFamilyBackend {
  return new RealFamilyBackend({
    workingRepo: mkDir("cmr-repo-"),
    familyBase: "feat/330-pure-scheduler",
    ledgerDir: over?.ledgerDir ?? mkDir("cmr-ledger-"),
    repo: "Akagilnc/ming-salvage-sim",
    base: "main",
    promptsDir: realPromptsDir,
    soulsDir: realSoulsDir,
    imageName: "ming-orchestrator-coder:latest",
    home: over?.home,
  });
}

// ═══════════════════════ 1. parseCmrOutcome (pure tag parse) ═══════════════════════

describe("#335 parseCmrOutcome — the <cmr> verdict tag", () => {
  it("converged:true ⇒ a converged outcome", () => {
    const o = parseCmrOutcome(
      `noise\n<cmr>${JSON.stringify({
        converged: true,
        successfulLegs: DEFAULT_CMR_LEGS,
        ...VALID_CMR_VERDICT_FIELDS,
      })}</cmr>\n`,
    );
    expect(o.kind).toBe("verdict");
    if (o.kind === "verdict") {
      expect(o.converged).toBe(true);
      expect(o.successfulLegs).toEqual(DEFAULT_CMR_LEGS);
    }
  });

  it("converged:false + reason ⇒ a red outcome carrying the reason", () => {
    const o = parseCmrOutcome(
      `<cmr>${JSON.stringify({
        converged: false,
        reason: "cross-slice field-name mismatch",
        successfulLegs: ["gpt-5.6-sol"],
        ...VALID_CMR_VERDICT_FIELDS,
        skippedLegs: [
          { slug: "opus", reason: "auth unavailable" },
          { slug: "agy", reason: "quota exhausted" },
        ],
      })}</cmr>`,
    );
    expect(o.kind).toBe("verdict");
    if (o.kind === "verdict") {
      expect(o.converged).toBe(false);
      expect(o.reason).toBe("cross-slice field-name mismatch");
      expect(o.successfulLegs).toEqual(["gpt-5.6-sol"]);
    }
  });

  it("an escalate object ⇒ an escalate outcome (the worker is model-stuck)", () => {
    const o = parseCmrOutcome(
      '<cmr>{"escalate": {"reason": "skill missing", "diagnosis": "ak-cross-m-review not on PATH"}}</cmr>',
    );
    expect(o.kind).toBe("escalate");
    if (o.kind === "escalate") {
      expect(o.reason).toContain("skill missing");
      expect(o.diagnosis).toContain("not on PATH");
    }
  });

  it("rings the CMR decision bell before judging the rest of the reviewer receipt", () => {
    const o = parseCmrOutcome(
      '<cmr>{"converged": "garbage", "extra": [1,2,3], "escalate": {"reason": "design fork", "diagnosis": "owner choice required"}}</cmr>',
    );
    expect(o).toMatchObject({
      kind: "escalate",
      reason: "design fork",
      diagnosis: "owner choice required",
    });
  });

  it("only the LAST <cmr> tag is read (the worker may iterate)", () => {
    const o = parseCmrOutcome(
      `<cmr>{"converged": false}</cmr>\nlater…\n<cmr>${JSON.stringify({
        converged: true,
        successfulLegs: DEFAULT_CMR_LEGS,
        ...VALID_CMR_VERDICT_FIELDS,
      })}</cmr>`,
    );
    expect(o.kind).toBe("verdict");
    if (o.kind === "verdict") expect(o.converged).toBe(true);
  });

  it("no <cmr> tag ⇒ sparse cargo with no self-declared count", () => {
    const o = parseCmrOutcome("I reviewed everything, looks fine.");
    expect(o).toMatchObject({ kind: "verdict", successfulLegs: [], evidencePaths: [] });
    expect(o).not.toHaveProperty("converged");
  });

  it("a non-JSON / non-object <cmr> body only reduces cargo richness", () => {
    expect(parseCmrOutcome("<cmr>not json</cmr>").kind).toBe("verdict");
    expect(parseCmrOutcome("<cmr>null</cmr>").kind).toBe("verdict");
    expect(parseCmrOutcome("<cmr>true</cmr>").kind).toBe("verdict");
  });

  it("a <cmr> object with no boolean converged remains sparse cargo", () => {
    expect(parseCmrOutcome('<cmr>{"foo": 1}</cmr>').kind).toBe("verdict");
  });

  describe("ADR 0131 — decision bell independent; remaining fields are cargo", () => {
    it("a mixed converged+escalate payload rings the decision bell first", () => {
      // A success key carried ALONGSIDE an escalate verdict is off-contract — it
      // must NOT slip through to a converged pass.
      expect(
        parseCmrOutcome(
          '<cmr>{"converged": true, "escalate": {"reason": "r", "diagnosis": "d"}}</cmr>',
        ).kind,
      ).toBe("escalate");
    });

    it("converged:true tolerates unknown cargo keys", () => {
      expect(
        parseCmrOutcome(
          `<cmr>${JSON.stringify({
            converged: true,
            successfulLegs: DEFAULT_CMR_LEGS,
            ...VALID_CMR_VERDICT_FIELDS,
            junk: 1,
          })}</cmr>`,
        ).kind,
      ).toBe(
        "verdict",
      );
    });

    it("converged:true may carry explicit prior-finding closure dispositions", () => {
      const o = parseCmrOutcome(
        `<cmr>${JSON.stringify({
          converged: true,
          successfulLegs: DEFAULT_CMR_LEGS,
          ...CMR_EVIDENCE,
          claimedFixedFindingIdentityKeys: ["correctness|src/x.ts:1|closed"],
          priorFindingDispositions: [
            {
              identityKey: "correctness|src/x.ts:1|closed",
              status: "verified-closed",
            },
          ],
        })}</cmr>`,
      );

      expect(o.kind).toBe("verdict");
      if (o.kind === "verdict") {
        expect(o.claimedFixedFindingIdentityKeys).toEqual([
          "correctness|src/x.ts:1|closed",
        ]);
        expect(o.priorFindingDispositions).toEqual([
          {
            identityKey: "correctness|src/x.ts:1|closed",
            status: "verified-closed",
          },
        ]);
      }
    });

    it("normalizes the known priorFindingDispositions[].disposition alias to status", () => {
      const o = parseCmrOutcome(
        `<cmr>${JSON.stringify({
          converged: true,
          successfulLegs: DEFAULT_CMR_LEGS,
          ...CMR_EVIDENCE,
          claimedFixedFindingIdentityKeys: [
            "correctness|src/family/verifyCmr.ts:1|closed",
          ],
          priorFindingDispositions: [
            {
              identityKey: "correctness|src/family/verifyCmr.ts:1|closed",
              disposition: "verified-closed",
            },
          ],
        })}</cmr>`,
      );

      expect(o.kind).toBe("verdict");
      if (o.kind === "verdict") {
        expect(o.priorFindingDispositions).toEqual([
          {
            identityKey: "correctness|src/family/verifyCmr.ts:1|closed",
            status: "verified-closed",
          },
        ]);
      }
    });

    it("normalizes mixed priorFindingDispositions status plus legacy disposition", () => {
      const o = parseCmrOutcome(
        `<cmr>${JSON.stringify({
          converged: true,
          successfulLegs: DEFAULT_CMR_LEGS,
          ...CMR_EVIDENCE,
          claimedFixedFindingIdentityKeys: [
            "correctness|src/family/verifyCmr.ts:1|closed",
          ],
          priorFindingDispositions: [
            {
              identityKey: "correctness|src/family/verifyCmr.ts:1|closed",
              status: "verified-closed",
              disposition: "verified-closed",
            },
          ],
        })}</cmr>`,
      );

      expect(o.kind).toBe("verdict");
      if (o.kind === "verdict") {
        expect(o.priorFindingDispositions).toEqual([
          {
            identityKey: "correctness|src/family/verifyCmr.ts:1|closed",
            status: "verified-closed",
          },
        ]);
      }
    });

    it("converged:true requires explicit empty closure arrays when no claimed-fixed findings occurred", () => {
      const o = parseCmrOutcome(
        `<cmr>${JSON.stringify({
          converged: true,
          successfulLegs: DEFAULT_CMR_LEGS,
          ...VALID_CMR_VERDICT_FIELDS,
        })}</cmr>`,
      );

      expect(o.kind).toBe("verdict");
      if (o.kind === "verdict") {
        expect(o.claimedFixedFindingIdentityKeys).toEqual([]);
        expect(o.priorFindingDispositions).toEqual([]);
      }
    });

    it("does not let finding content override the reviewer-declared verdict channel", () => {
      const o = parseCmrOutcome(
        `<cmr>${JSON.stringify({
          converged: true,
          successfulLegs: DEFAULT_CMR_LEGS,
          ...VALID_CMR_VERDICT_FIELDS,
          findings: [
            {
              severity: "medium",
              category: "correctness",
              claim_quote: "green CMR cannot carry unresolved fix_now blockers",
              location: "orchestrator/src/family/verifyCmr.ts",
              suggested_fix: "emit converged false while the blocker remains",
              action: "fix_now",
            },
          ],
        })}</cmr>`,
      );

      expect(o.kind).toBe("verdict");
    });

    it("converged:true without closure arrays remains readable cargo", () => {
      expect(
        parseCmrOutcome(
          `<cmr>${JSON.stringify({
            converged: true,
            successfulLegs: DEFAULT_CMR_LEGS,
          })}</cmr>`,
        ).kind,
      ).toBe("verdict");
    });

    it("converged:false without a reason remains readable cargo", () => {
      expect(parseCmrOutcome('<cmr>{"converged": false}</cmr>').kind).toBe("verdict");
    });

    it("a blank optional reason is dropped without rejecting the receipt", () => {
      expect(
        parseCmrOutcome(
          `<cmr>${JSON.stringify({
            converged: false,
            reason: "  ",
            successfulLegs: DEFAULT_CMR_LEGS,
            ...VALID_CMR_VERDICT_FIELDS,
          })}</cmr>`,
        ).kind,
      ).toBe(
        "verdict",
      );
    });

    it("an incomplete escalate block fails the Action instead of inventing a park", () => {
      // #899: present-but-malformed escalate fails closed for #598 (typed seats
      // re-ask first via schema; cargo parsers must not swallow empty bells).
      expect(() =>
        parseCmrOutcome('<cmr>{"escalate": {"reason": "", "diagnosis": ""}}</cmr>'),
      ).toThrow(/malformed decision gate/);
      expect(() => parseCmrOutcome('<cmr>{"escalate": {}}</cmr>')).toThrow(
        /malformed decision gate/,
      );
    });

    it("a non-boolean converged cargo field is dropped", () => {
      expect(parseCmrOutcome('<cmr>{"converged": "true"}</cmr>').kind).toBe("verdict");
    });

    it("bare converged:true does not require sibling cargo", () => {
      expect(parseCmrOutcome('<cmr>{"converged": true}</cmr>').kind).toBe("verdict");
    });

    it("leg lists stay optional cargo", () => {
      expect(
        parseCmrOutcome(
          `<cmr>${JSON.stringify({
            converged: true,
            successfulLegs: DEFAULT_CMR_LEGS,
            ...VALID_CMR_VERDICT_FIELDS,
          })}</cmr>`,
        ).kind,
      ).toBe("verdict");
      expect(parseCmrOutcome('<cmr>{"converged": true, "successfulLegs": ["opus"]}</cmr>').kind).toBe(
        "verdict",
      );
    });

    it("accounts against the active route's declared cmr legs, not the default route", () => {
      vi.stubEnv("ORCHESTRATOR_ROUTE", "claude-tight");

      const o = parseCmrOutcome(
        `<cmr>${JSON.stringify({
          converged: true,
          successfulLegs: ["gpt-5.6-sol", "agy"],
          ...VALID_CMR_VERDICT_FIELDS,
        })}</cmr>`,
      );

      expect(o).toEqual({
        kind: "verdict",
        converged: true,
        successfulLegs: ["gpt-5.6-sol", "agy"],
        ...EMPTY_CMR_CLOSURE,
        ...CMR_EVIDENCE,
      });
    });

    it("#875: undeclared successful legs parse as a normal verdict (parse-time accounting court demolished)", () => {
      vi.stubEnv("ORCHESTRATOR_ROUTE", "claude-tight");

      const o = parseCmrOutcome(
        `<cmr>${JSON.stringify({
          converged: true,
          successfulLegs: ["agy", "opus"],
          ...VALID_CMR_VERDICT_FIELDS,
          skippedLegs: [{ slug: "gpt-5.6-sol", reason: "auth unavailable" }],
        })}</cmr>`,
      );
      expect(o.kind).toBe("verdict");
      if (o.kind === "verdict") {
        expect(o.successfulLegs).toEqual(["agy", "opus"]);
      }
    });

    it("#875: undeclared skipped legs parse as a normal verdict (parse-time accounting court demolished)", () => {
      vi.stubEnv("ORCHESTRATOR_ROUTE", "claude-tight");

      const o = parseCmrOutcome(
        `<cmr>${JSON.stringify({
          converged: true,
          successfulLegs: ["gpt-5.6-sol", "agy"],
          ...VALID_CMR_VERDICT_FIELDS,
          skippedLegs: [{ slug: "opus", reason: "auth unavailable" }],
        })}</cmr>`,
      );
      expect(o.kind).toBe("verdict");
      if (o.kind === "verdict") {
        expect(o.skippedLegs).toEqual([
          { slug: "opus", reason: "auth unavailable" },
        ]);
      }
    });

    it("accepts a single surviving default leg only when the other declared legs are skipped", () => {
      const o = parseCmrOutcome(
        `<cmr>${JSON.stringify({
          converged: true,
          successfulLegs: ["opus"],
          ...VALID_CMR_VERDICT_FIELDS,
          skippedLegs: [
            { slug: "gpt-5.6-sol", reason: "auth unavailable" },
            { slug: "agy", reason: "quota exhausted" },
          ],
        })}</cmr>`,
      );
      expect(o.kind).toBe("verdict");
      if (o.kind === "verdict") {
        expect(o.successfulLegs).toEqual(["opus"]);
        expect(o.skippedLegs).toEqual([
          { slug: "gpt-5.6-sol", reason: "auth unavailable" },
          { slug: "agy", reason: "quota exhausted" },
        ]);
      }
    });

    it("#875: a leg listed as both successful and skipped still parses as a verdict (accounting court demolished)", () => {
      const o = parseCmrOutcome(
        `<cmr>${JSON.stringify({
          converged: true,
          successfulLegs: DEFAULT_CMR_LEGS,
          ...VALID_CMR_VERDICT_FIELDS,
          skippedLegs: [{ slug: "agy", reason: "quota exhausted" }],
        })}</cmr>`,
      );
      expect(o.kind).toBe("verdict");
      if (o.kind === "verdict") {
        expect(o.successfulLegs).toEqual([...DEFAULT_CMR_LEGS]);
        expect(o.skippedLegs).toEqual([
          { slug: "agy", reason: "quota exhausted" },
        ]);
      }
    });

    it("still accepts the two LEGAL verdict shapes (regression)", () => {
      expect(
        parseCmrOutcome(
          `<cmr>${JSON.stringify({
            converged: true,
            successfulLegs: DEFAULT_CMR_LEGS,
            ...VALID_CMR_VERDICT_FIELDS,
          })}</cmr>`,
        ).kind,
      ).toBe("verdict");
      expect(
        parseCmrOutcome(
          `<cmr>${JSON.stringify({
            converged: false,
            reason: "seam mismatch",
            successfulLegs: ["gpt-5.6-sol"],
            ...VALID_CMR_VERDICT_FIELDS,
            skippedLegs: [
              { slug: "opus", reason: "auth unavailable" },
              { slug: "agy", reason: "quota exhausted" },
            ],
          })}</cmr>`,
        ).kind,
      ).toBe("verdict");
    });
  });
});

describe("integrated CMR pass prompt closure contract", () => {
  for (const promptName of [
    "integrated_cmr_completeness.md",
    "integrated_cmr_correctness.md",
  ]) {
    it(`${promptName} makes missing review-leg coverage the worker's positive verdict duty`, () => {
      const prompt = readFileSync(join(realPromptsDir, promptName), "utf8");

      expect(prompt).toMatch(
        /review-leg coverage is missing[\s\S]*decision gate[\s\S]*findings\s*=\s*x[\s\S]*x\s*>=\s*1/i,
      );
    });

    it(`${promptName} requires closure arrays on converged output`, () => {
      const prompt = readFileSync(join(realPromptsDir, promptName), "utf8");

      expect(prompt).toContain("claimedFixedFindingIdentityKeys");
      expect(prompt).toContain("priorFindingDispositions");
      expect(prompt).toMatch(/empty arrays/i);
    });

  }

  for (const promptName of [
    "integrated_cmr_completeness.md",
    "integrated_cmr_correctness.md",
  ]) {
    it(`${promptName} routes same-module still-red examples into the runner coder-fix path`, () => {
      const prompt = readFileSync(join(realPromptsDir, promptName), "utf8");
      const examples = [...prompt.matchAll(/<cmr>(\{[^\n]*"converged": false[^\n]*\})<\/cmr>/g)];

      expect(examples.length).toBeGreaterThan(0);
      for (const [, rawJson] of examples) {
        const output = JSON.parse(rawJson) as {
          readonly findings?: readonly {
            readonly action: string;
            readonly disposition?: { readonly kind?: string };
          }[];
        };
        for (const finding of output.findings ?? []) {
          if (finding.disposition?.kind === "same_module") {
            expect(finding.action).toBe("fix_now");
          }
        }
      }
    });
  }

  it("integrated completeness prompt keeps undeveloped targets out of issue-body YAML", () => {
    const prompt = readFileSync(
      join(realPromptsDir, "integrated_cmr_completeness.md"),
      "utf8",
    );

    expect(prompt).toContain("module_scope");
    expect(prompt).toContain("runner-supplied metadata");
    expect(prompt).toContain("not issue-body prose or extra YAML");
    expect(prompt).toContain("Do not infer");
  });
});

// ═══════════════════════ 2. cmrOutcomeFromResult (structured outcome) ═══════════════════════

describe("#335 cmrOutcomeFromResult — structured outcome parsing", () => {
  const SIGNAL = cmrWorkerSpec().completionSignal;

  it("a signaled converged run ⇒ a verdict outcome", () => {
    const o = cmrOutcomeFromResult({
      completionSignal: SIGNAL,
      stdout: `<cmr>${JSON.stringify({
        converged: true,
        successfulLegs: DEFAULT_CMR_LEGS,
        ...VALID_CMR_VERDICT_FIELDS,
      })}</cmr>\nfindings = 0\n`,
    });
    expect(o.kind).toBe("verdict");
    if (o.kind === "verdict") expect(o.converged).toBe(true);
  });

  it("an UNSIGNALED run still parses the structured verdict (signal is telemetry)", () => {
    const o = cmrOutcomeFromResult({
      completionSignal: undefined,
      stdout: `<cmr>${JSON.stringify({
        converged: true,
        successfulLegs: DEFAULT_CMR_LEGS,
        ...VALID_CMR_VERDICT_FIELDS,
      })}</cmr>\nfindings = 0\n`,
    });
    expect(o.kind).toBe("verdict");
  });

  it("a wrong signal does not override the structured verdict", () => {
    const o = cmrOutcomeFromResult({
      completionSignal: "SOME_OTHER_SIGNAL",
      stdout: `<cmr>${JSON.stringify({
        converged: true,
        successfulLegs: DEFAULT_CMR_LEGS,
        ...VALID_CMR_VERDICT_FIELDS,
      })}</cmr>\nfindings = 0\n`,
    });
    expect(o.kind).toBe("verdict");
  });

  it("accounts worker verdict legs against the frozen worker route, not later process env", () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "normal");
    const result = {
      completionSignal: SIGNAL,
      cmrReviewLegs: FROZEN_NORMAL_CMR_REVIEW_LEGS,
      // #899: findingsCount lives on the receipt payload, not a stdout sentinel.
      stdout: `<cmr>${JSON.stringify({
        converged: true,
        findingsCount: 0,
        successfulLegs: DEFAULT_CMR_LEGS,
        ...VALID_CMR_VERDICT_FIELDS,
      })}</cmr>\n`,
    };
    vi.stubEnv("ORCHESTRATOR_ROUTE", "claude-tight");

    const o = cmrOutcomeFromResult(result);

    expect(o).toEqual({
      kind: "verdict",
      converged: true,
      findingsCount: 0,
      successfulLegs: DEFAULT_CMR_LEGS,
      ...VALID_CMR_VERDICT_FIELDS,
    });
  });
});

// ═══════════════════ 3. dispatchWorker(cmr) — routes the skill + wraps verdict ═══════════════════

describe("#335 RealFamilyBackend.dispatchWorker — the cmr worker", () => {
  /** A backend whose container `runCmrWorker` seam is fixtured (no real sc.run). */
  class FixturedCmrBackend extends RealFamilyBackend {
    runCmrCalls: { spec: ReturnType<typeof cmrWorkerSpec>; ctx: DispatchContext }[] = [];
    runCoderFixCalls: { spec: WorkerSpec; ctx: DispatchContext }[] = [];
    runShipCalls: { spec: WorkerSpec; ctx: DispatchContext }[] = [];
    outcome: CmrWorkerOutcome = {
      kind: "verdict",
      converged: true,
      successfulLegs: STRONG_LEGS,
      ...CMR_EVIDENCE,
    };
    protected override async runCmrWorker(
      spec: ReturnType<typeof cmrWorkerSpec>,
      ctx: DispatchContext,
    ): Promise<CmrWorkerOutcome> {
      this.runCmrCalls.push({ spec, ctx });
      return this.outcome;
    }
    // #336: a ship spec routes to the ship worker seam (NOT the cmr seam). Fixture it
    // so this test asserts the routing without a real container / host claude token
    // (the pre-#336 version relied on a host-side `git push` throwing,
    // which is now both stale and host-fragile — cmr S336 r9).
    protected override async runShipWorker(
      spec: WorkerSpec,
      ctx: DispatchContext,
    ): Promise<ReturnType<typeof shipOutcomeFromResult>> {
      this.runShipCalls.push({ spec, ctx });
      return { kind: "shipped", branch: ctx.familyBase!, status: "pr_opened", pr: "https://gh/pr/9" };
    }
    protected override async runFamilyCoderFixWorker(
      spec: WorkerSpec,
      ctx: DispatchContext,
    ): Promise<WorkerResult> {
      this.runCoderFixCalls.push({ spec, ctx });
      return {
        kind: "completed",
        output: { kind: "coder", committed: true, commitsAdded: 1 },
      };
    }
  }

  function fixtured(): FixturedCmrBackend {
    return new FixturedCmrBackend({
      workingRepo: mkDir("cmr-repo-"),
      familyBase: "feat/330-pure-scheduler",
      ledgerDir: mkDir("cmr-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "ming-orchestrator-coder:latest",
    });
  }

  it("dispatches the cmr pass worker spec to runCmrWorker — ak-cross-m-review + FRESH clean reviewer cmr soul", async () => {
    const be = fixtured();
    await be.dispatchWorker(cmrWorkerSpec(), { familyBase: "feat/330-pure-scheduler" });
    expect(be.runCmrCalls.length).toBe(1);
    const spec = be.runCmrCalls[0]!.spec;
    expect(spec.kind).toBe("cmr");
    expect(spec.skill).toBe("ak-cross-m-review");
    // FRESH session = a new pass-worker session, not a crash/escalate resume.
    expect(spec.session).toBe("fresh");
    // The pass worker is a clean reviewer boundary; blocking findings return to the
    // runner, which dispatches a separate coder-fix worker.
    expect(spec.contextRetention).toBe("clean");
    expect(spec.role).toBe("reviewer");
    expect(spec.maxIter).toBe(1);
    expect(spec.soul).toBe("cmr");
  });

  it("lets Sandcastle validate the CMR receipt with its native retry budget", async () => {
    const repo = realRepo335();
    execFileSync("git", ["config", "user.email", "t@t.t"], { cwd: repo });
    execFileSync("git", ["config", "user.name", "t"], { cwd: repo });
    execFileSync("git", ["commit", "--allow-empty", "-q", "-m", "root"], { cwd: repo });
    execFileSync("git", ["checkout", "-q", "-b", "fb"], { cwd: repo });
    const runs: Parameters<typeof sc.run>[0][] = [];
    class Backend extends RealFamilyBackend {
      public run(spec: ReturnType<typeof cmrWorkerSpec>, ctx: DispatchContext) { return this.runCmrWorker(spec, ctx); }
      protected override mountCmrAuth(): CmrAuth { return { claudeToken: "tok" }; }
      protected override async runAgentSandbox(options: Parameters<typeof sc.run>[0]): Promise<Awaited<ReturnType<typeof sc.run>>> {
        runs.push(options);
        return { completionSignal: "CMR_STEP_COMPLETE", stdout: `<cmr>${JSON.stringify({ converged: true, successfulLegs: DEFAULT_CMR_LEGS, ...VALID_CMR_VERDICT_FIELDS })}</cmr>` } as Awaited<ReturnType<typeof sc.run>>;
      }
    }
    const be = new Backend({ workingRepo: repo, familyBase: "fb", ledgerDir: mkDir("cmr-receipt-ledger-"), repo: "Akagilnc/ming-salvage-sim", base: "main", promptsDir: realPromptsDir, soulsDir: realSoulsDir, imageName: "img", familyBaseStartHead: "abc123" });
    await be.run(cmrWorkerSpec(), { familyBase: "fb", cmrPass: "completeness" });
    expect(runs[0]).toMatchObject({
      output: expect.objectContaining({ tag: "cmr", maxRetries: 2 }),
    });
  });

  it("falls back when Sandcastle reports its actual non-resumable maxRetries error", () => {
    expect(isReceiptRecoveryFailure(new Error(
      'output.maxRetries requires an agent provider that supports session resumption. The "grok" provider does not. Use claudeCode, codex, or pi, or set maxRetries to 0.',
    ))).toBe(true);
  });

  it("propagates StructuredOutputError when native CMR receipt retries are exhausted", async () => {
    // #899: exhaust exits non-zero for #598; never preserve bad cargo as success.
    const repo = realRepo335();
    execFileSync("git", ["config", "user.email", "t@t.t"], { cwd: repo });
    execFileSync("git", ["config", "user.name", "t"], { cwd: repo });
    execFileSync("git", ["commit", "--allow-empty", "-q", "-m", "root"], { cwd: repo });
    execFileSync("git", ["checkout", "-q", "-b", "fb"], { cwd: repo });
    let nativeReask:
      | ReturnType<typeof fakeNativeReceiptReask>
      | undefined;
    let sandcastleCalls = 0;
    const exhausted = new sc.StructuredOutputError("bad output", {
      tag: "cmr",
      rawMatched: JSON.stringify({
        converged: false,
        reason: "review finding survives malformed receipt",
        findingsCount: 1,
        successfulLegs: [...DEFAULT_CMR_LEGS],
        ...VALID_CMR_VERDICT_FIELDS,
        findings: [{
          severity: "high",
          category: "correctness",
          claim_quote: "reviewer cargo survives",
          location: "orchestrator/src/family/realFamilyBackend.ts:1606",
          suggested_fix: "preserve the landing cargo",
          action: "fix_now",
        }],
      }),
      commits: [], branch: "fb", sessionId: "sess-cmr-exhausted",
    });
    class Backend extends RealFamilyBackend {
      public run(spec: ReturnType<typeof cmrWorkerSpec>, ctx: DispatchContext) { return this.runCmrWorker(spec, ctx); }
      protected override mountCmrAuth(): CmrAuth { return { claudeToken: "tok" }; }
      protected override async runAgentSandbox(
        options: Parameters<typeof sc.run>[0],
      ): Promise<Awaited<ReturnType<typeof sc.run>>> {
        sandcastleCalls += 1;
        expect(options.output).toEqual(expect.objectContaining({
          tag: "cmr",
          maxRetries: RECEIPT_MAX_RETRIES,
        }));
        // Fake Sandcastle consumes the initial receipt plus two same-session
        // resumes before reporting the framework's normal exhaustion error.
        nativeReask = fakeNativeReceiptReask(
          options.output!,
          [{ converged: true }, { converged: true }, { converged: true }],
          workerReceiptSchema("cmr"),
          "sess-cmr-exhausted",
        );
        expect(nativeReask.result).toBeUndefined();
        throw exhausted;
      }
    }
    const be = new Backend({ workingRepo: repo, familyBase: "fb", ledgerDir: mkDir("cmr-receipt-exhausted-ledger-"), repo: "Akagilnc/ming-salvage-sim", base: "main", promptsDir: realPromptsDir, soulsDir: realSoulsDir, imageName: "img", familyBaseStartHead: "abc123" });

    await expect(be.run(cmrWorkerSpec(), { familyBase: "fb", cmrPass: "completeness" })).rejects.toBe(exhausted);
    expect(sandcastleCalls).toBe(1);
    expect(nativeReask?.attempts).toHaveLength(RECEIPT_MAX_RETRIES + 1);
    expect(nativeReask?.attempts).toEqual([
      { sessionId: "sess-cmr-exhausted", receipt: { converged: true } },
      { sessionId: "sess-cmr-exhausted", receipt: { converged: true } },
      { sessionId: "sess-cmr-exhausted", receipt: { converged: true } },
    ]);
    expect(nativeReask?.resumes).toEqual([
      { sessionId: "sess-cmr-exhausted", feedback: expect.any(String) },
      { sessionId: "sess-cmr-exhausted", feedback: expect.any(String) },
    ]);
  });

  it("delegates a malformed CMR receipt's bad-to-good retry sequence to Sandcastle", async () => {
    const repo = realRepo335();
    execFileSync("git", ["config", "user.email", "t@t.t"], { cwd: repo });
    execFileSync("git", ["config", "user.name", "t"], { cwd: repo });
    execFileSync("git", ["commit", "--allow-empty", "-q", "-m", "root"], { cwd: repo });
    execFileSync("git", ["checkout", "-q", "-b", "fb"], { cwd: repo });
    let nativeReask:
      | ReturnType<typeof fakeNativeReceiptReask<typeof completeVerdict>>
      | undefined;
    let sandcastleCalls = 0;
    const completeVerdict = {
      converged: true,
      findingsCount: 0,
      successfulLegs: [...DEFAULT_CMR_LEGS],
      ...VALID_CMR_VERDICT_FIELDS,
    };
    class Backend extends RealFamilyBackend {
      public run(spec: ReturnType<typeof cmrWorkerSpec>, ctx: DispatchContext) { return this.runCmrWorker(spec, ctx); }
      protected override mountCmrAuth(): CmrAuth { return { claudeToken: "tok" }; }
      protected override async runAgentSandbox(
        options: Parameters<typeof sc.run>[0],
      ): Promise<Awaited<ReturnType<typeof sc.run>>> {
        sandcastleCalls += 1;
        // Fake Sandcastle: its retry loop owns the retries. The runner gets one
        // call and supplies only the typed-output policy.
        expect(options.output).toEqual(expect.objectContaining({ tag: "cmr", maxRetries: 2 }));
        nativeReask = fakeNativeReceiptReask<typeof completeVerdict>(
          options.output!,
          [{ ...completeVerdict, findingsCount: undefined }, completeVerdict],
          workerReceiptSchema("cmr"),
          "same-cmr-reviewer-session",
        );
        if (nativeReask.result === undefined) throw new Error("fake Sandcastle should recover the second receipt");
        return typedSandboxRunResult(nativeReask.result, { sessionId: "same-cmr-reviewer-session" });
      }
    }
    const be = new Backend({ workingRepo: repo, familyBase: "fb", ledgerDir: mkDir("cmr-native-retry-ledger-"), repo: "Akagilnc/ming-salvage-sim", base: "main", promptsDir: realPromptsDir, soulsDir: realSoulsDir, imageName: "img", familyBaseStartHead: "abc123" });

    await expect(be.run(cmrWorkerSpec(), { familyBase: "fb", cmrPass: "completeness" })).resolves.toMatchObject({
      kind: "verdict",
      converged: true,
      findingsCount: 0,
    });
    expect(nativeReask?.attempts).toEqual([
      { sessionId: "same-cmr-reviewer-session", receipt: { ...completeVerdict, findingsCount: undefined } },
      { sessionId: "same-cmr-reviewer-session", receipt: completeVerdict },
    ]);
    expect(nativeReask?.resumes).toEqual([
      { sessionId: "same-cmr-reviewer-session", feedback: expect.any(String) },
    ]);
    expect(sandcastleCalls).toBe(1);
    expect(nativeReask?.attempts).toHaveLength(2);
  });

  it("rejects malformed decision gates so Sandcastle re-asks the CMR author", () => {
    // #899: empty/missing reason+diagnosis must fail the typed boundary.
    expect(workerReceiptSchema("cmr").safeParse({ escalate: {} }).success).toBe(false);
    expect(workerReceiptSchema("cmr").safeParse({
      escalate: { reason: "owner decision", diagnosis: "design fork" },
    }).success).toBe(true);
    // Legal findingsCount must not mask a present-but-malformed decision gate.
    expect(workerReceiptSchema("cmr").safeParse({
      findingsCount: 2,
      escalate: { reason: "", diagnosis: "x" },
    }).success).toBe(false);
    expect(workerReceiptSchema("cmr").safeParse({
      findingsCount: 2,
      escalate: { reason: "owner decision", diagnosis: "design fork" },
    }).success).toBe(true);
  });

  it("keeps approved finding-family cargo on an otherwise typed CMR verdict", () => {
    // #899: only findingsCount is typed; legs/evidence/families are cargo passthrough.
    expect(workerReceiptSchema("cmr").safeParse({
      findingsCount: 0,
      findingFamilies: [{ identityKeys: ["correctness|x|y"] }],
    }).success).toBe(true);
    expect(workerReceiptSchema("cmr").safeParse({
      findingsCount: 0,
    }).success).toBe(true);
    expect(workerReceiptSchema("cmr").safeParse({
      converged: true,
      successfulLegs: [...DEFAULT_CMR_LEGS],
    }).success).toBe(false);
  });

  it("does not let sidecar bells override a schema-validated typed verdict", () => {
    // #899: decision gates and open-count come only from Output.object; sidecar
    // cargo (including malformed escalate) must not enter the human loop.
    const dir = mkdtempSync(join(tmpdir(), "cmr-recovered-bell-"));
    const outcomePath = join(dir, ".orchestrator-outcome.json");
    writeFileSync(outcomePath, JSON.stringify({
      escalate: { reason: "sidecar spoof", diagnosis: "must not win" },
    }));

    expect(cmrOutcomeFromResult({
      output: {
        converged: true,
        findingsCount: 0,
        successfulLegs: [...DEFAULT_CMR_LEGS],
        claimedFixedFindingIdentityKeys: [],
        priorFindingDispositions: [],
        evidencePaths: ["cmr/review-summary.json"],
      },
      outcomePath,
    })).toMatchObject({ kind: "verdict", findingsCount: 0, converged: true });
  });

  it("dispatches the family coder-fix spec to runFamilyCoderFixWorker — /tdd + retained coder context", async () => {
    const be = fixtured();
    await be.dispatchWorker(familyCoderFixWorkerSpec(), {
      familyBase: "feat/330-pure-scheduler",
      familyIssue: 533,
      blockingFindingIdentityKeys: ["cmr-key-1"],
    });
    expect(be.runCoderFixCalls.length).toBe(1);
    const { spec, ctx } = be.runCoderFixCalls[0]!;
    expect(spec.kind).toBe("coder");
    expect(spec.skill).toBe("/tdd");
    expect(spec.promptFile).toBe("coder_fix.md");
    expect(spec.session).toBe("fresh");
    expect(spec.contextRetention).toBe("retain");
    expect(ctx.familyIssue).toBe(533);
    expect(ctx.blockingFindingIdentityKeys).toEqual(["cmr-key-1"]);
  });

  it("cleans up family coder-fix findings if outcome landing fails", async () => {
    const repo = realRepo335();

    class FailingOutcomeLandingBackend extends RealFamilyBackend {
      protected override mountShipAuth(): ShipAuth {
        return { claudeToken: "tok" };
      }

      protected override prepareFamilyCoderOutcomeLanding(): {
        path: string;
        sandboxPath: string;
      } {
        throw new Error("outcome landing failed");
      }

      protected override sh(file: string, args: string[], cwd?: string): string {
        if (file === "git" && args[0] === "checkout") return "";
        if (file === "git" && args[0] === "rev-parse" && args[1] === "HEAD") {
          return "family-head-before-coder-fix";
        }
        return super.sh(file, args, cwd);
      }
    }

    const be = new FailingOutcomeLandingBackend({
      workingRepo: repo,
      familyBase: "fb",
      ledgerDir: mkDir("family-coder-landing-fail-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
    });

    await expect(
      be.dispatchWorker(familyCoderFixWorkerSpec(), {
        familyBase: "fb",
        blockingFindingIdentityKeys: ["cmr-key-1"],
      }),
    ).rejects.toThrow("outcome landing failed");
    expect(existsSync(join(repo, ".orchestrator-fix-findings.json"))).toBe(false);
  });

  it.each([
    [
      "malformed reviewer",
      {
        reviewerSessionId: "cmr-reviewer-malformed",
        sidecarPath: "/ledger/cmr-malformed.json",
        statement: "the previous reviewer raw artifacts are here",
      },
    ],
    [
      "reviewer-declared positive count with empty findings",
      {
        reviewerSessionId: "cmr-reviewer-empty-findings",
        stdoutPath: "/ledger/cmr-empty-findings.log",
        statement: "the previous reviewer raw artifacts are here",
      },
    ],
  ] as const)(
    "transports raw reviewer artifacts into family coder-fix findings for %s",
    (_label, rawReviewerArtifacts) => {
      const repo = realRepo335();

      class FixFindingsBackend extends RealFamilyBackend {
        public writeFixFindings(
          ctx: DispatchContext,
          landing: WorkerLandingPayload,
        ): { path: string; sandboxPath: string } {
          return this.writeFamilyFixFindingsFile(ctx, landing);
        }
      }

      const be = new FixFindingsBackend({
        workingRepo: repo,
        familyBase: "fb",
        ledgerDir: mkDir("family-coder-raw-artifacts-ledger-"),
        repo: "Akagilnc/ming-salvage-sim",
        base: "main",
        promptsDir: realPromptsDir,
        soulsDir: realSoulsDir,
        imageName: "img",
      });

      const landing = be.writeFixFindings(
        { familyBase: "fb", blockingFindingIdentityKeys: [] },
        { blockingFindings: [], rawReviewerArtifacts },
      );

      expect(JSON.parse(readFileSync(landing.path, "utf8"))).toEqual({
        blockingFindings: [],
        rawReviewerArtifacts,
        blockingFindingIdentityKeys: [],
      });
    },
  );

  it("a converged verdict ⇒ WorkerResult.completed with a bare cmr payload", async () => {
    const be = fixtured();
    be.outcome = {
      kind: "verdict",
      converged: true,
      successfulLegs: STRONG_LEGS,
      ...CMR_EVIDENCE,
    };
    const res = await be.dispatchWorker(cmrWorkerSpec(), { familyBase: "fb" });
    expect(res.kind).toBe("completed");
    if (res.kind === "completed" && res.output.kind === "cmr") {
      expect(res.output.converged).toBe(true);
      expect(res.output.successfulLegs).toEqual(STRONG_LEGS);
    } else {
      throw new Error("expected completed cmr payload");
    }
  });

  it("a red verdict ⇒ WorkerResult.completed (NOT failed), carrying the reason", async () => {
    const be = fixtured();
    be.outcome = {
      kind: "verdict",
      converged: false,
      reason: "seam mismatch",
      successfulLegs: STRONG_LEGS,
      ...CMR_EVIDENCE,
    };
    const res = await be.dispatchWorker(cmrWorkerSpec(), { familyBase: "fb" });
    expect(res.kind).toBe("completed");
    if (res.kind === "completed" && res.output.kind === "cmr") {
      expect(res.output.converged).toBe(false);
      expect(res.output.reason).toBe("seam mismatch");
      expect(res.output.successfulLegs).toEqual(STRONG_LEGS);
    } else {
      throw new Error("expected completed cmr payload");
    }
  });

  it("preserves evidencePaths on the runner-facing cmr output", async () => {
    const be = fixtured();
    be.outcome = {
      kind: "verdict",
      converged: false,
      reason: "blocking findings remain",
      successfulLegs: STRONG_LEGS,
      ...CMR_EVIDENCE,
    };

    const res = await be.dispatchWorker(cmrWorkerSpec(), { familyBase: "fb" });

    expect(res).toEqual({
      kind: "completed",
      output: {
        kind: "cmr",
        converged: false,
        reason: "blocking findings remain",
        successfulLegs: STRONG_LEGS,
        ...CMR_EVIDENCE,
      },
    });
  });

  it("an escalate outcome ⇒ WorkerResult.escalated (model-stuck, not a verdict)", async () => {
    const be = fixtured();
    be.outcome = { kind: "escalate", reason: "skill missing", diagnosis: "not on PATH" };
    const res = await be.dispatchWorker(cmrWorkerSpec(), { familyBase: "fb" });
    expect(res.kind).toBe("escalated");
    if (res.kind === "escalated") {
      expect(res.escalation.reason).toContain("skill missing");
    }
  });

  it("forwards llmResolvedChildren on the DispatchContext to the cmr worker", async () => {
    const be = fixtured();
    await be.dispatchWorker(cmrWorkerSpec(), {
      familyBase: "fb",
      llmResolvedChildren: [42, 43],
    });
    expect(be.runCmrCalls[0]!.ctx.llmResolvedChildren).toEqual([42, 43]);
  });

  it("a family worker without familyBase throws (the worker reviews the base diff)", async () => {
    const be = fixtured();
    await expect(be.dispatchWorker(cmrWorkerSpec(), {})).rejects.toThrow(/familyBase/);
  });

  it("the ship worker is NOT handled by the cmr path — routed to the ship worker seam (#336)", async () => {
    // This slice (#335) owns cmr only. A ship spec routes to the ship worker seam
    // (dispatchShipWorker → runShipWorker, #336), NOT through runCmrWorker. (The full
    // ship contract — gstack-ship routing, pr_opened narrowing, branch identity — is
    // covered by ship-worker-336.test.ts; here we only assert the cmr seam is untouched.)
    const be = fixtured();
    be.outcome = {
      kind: "verdict",
      converged: true,
      successfulLegs: STRONG_LEGS,
      ...CMR_EVIDENCE,
    };
    const res = await be.dispatchWorker(familyShipWorkerSpec(), { familyBase: "fb" });
    expect(res.kind).toBe("completed"); // the fixtured ship outcome, not the cmr path
    expect(be.runShipCalls.length).toBe(1); // reached the ship worker seam
    expect(be.runCmrCalls.length).toBe(0); // the cmr worker seam was NOT touched
  });
});

describe("#850 review r5 — production CMR dispatch applies OpenCode auth", () => {
  class AuthDispatchBackend extends RealFamilyBackend {
    config?: {
      env: Record<string, string>;
      mounts: ReadonlyArray<{ hostPath: string; sandboxPath: string; readonly?: boolean }>;
    };
    outcomePath?: string;

    constructor(private readonly auth: CmrAuth, workingRepo: string) {
      super({
        workingRepo,
        familyBase: "fb",
        ledgerDir: mkDir("cmr-auth-ledger-"),
        repo: "Akagilnc/ming-salvage-sim",
        base: "main",
        promptsDir: realPromptsDir,
        soulsDir: realSoulsDir,
        imageName: "img",
        familyBaseStartHead: "abc123",
      });
    }

    protected override mountCmrAuth(): CmrAuth {
      return this.auth;
    }

    protected override cmrSandbox(
      auth: CmrAuth,
      reviewLegs: NonNullable<WorkerSpec["cmrReviewLegs"]>,
      outcomeLanding?: { path: string; sandboxPath: string },
      ctx?: Pick<DispatchContext, "billingPool">,
    ): sc.SandboxProvider {
      this.config = this.cmrSandboxConfig(auth, reviewLegs, outcomeLanding, ctx);
      return docker(this.config);
    }

    protected override prepareCmrOutcomeLanding(
      ctx: DispatchContext,
    ): { path: string; sandboxPath: string } {
      const landing = super.prepareCmrOutcomeLanding(ctx);
      this.outcomePath = landing.path;
      return landing;
    }

    protected override async runAgentSandbox(
      _options: Parameters<typeof sc.run>[0],
    ): Promise<Awaited<ReturnType<typeof sc.run>>> {
      if (this.outcomePath === undefined) throw new Error("missing outcome path");
      writeFileSync(this.outcomePath, JSON.stringify({
        converged: true,
        successfulLegs: DEFAULT_CMR_LEGS,
        ...CMR_EVIDENCE,
      }));
      return { stdout: "", commits: [], iterations: [] } as unknown as Awaited<ReturnType<typeof sc.run>>;
    }
  }

  function authFile(contents: Record<string, unknown>): string {
    const dir = mkDir("cmr-opencode-auth-");
    const path = join(dir, "auth.json");
    writeFileSync(path, JSON.stringify(contents));
    return path;
  }

  async function dispatch(pool: DispatchContext["billingPool"], contents: Record<string, unknown>) {
    const repo = realRepo335();
    execFileSync("git", ["config", "user.email", "t@t.t"], { cwd: repo });
    execFileSync("git", ["config", "user.name", "t"], { cwd: repo });
    execFileSync("git", ["commit", "--allow-empty", "-q", "-m", "root"], { cwd: repo });
    execFileSync("git", ["checkout", "-b", "fb"], { cwd: repo });
    const path = authFile(contents);
    const backend = new AuthDispatchBackend({ opencodeAuthFile: path }, repo);
    await backend.dispatchWorker(cmrWorkerSpec(), { familyBase: "fb", billingPool: pool });
    return { backend, path };
  }

  it("production CMR dispatch carries uniform GLM_KEY + readonly auth mount", async () => {
    vi.stubEnv("GLM_KEY", "glm-secret");
    const { backend, path } = await dispatch("zai", {
      "opencode-go": { type: "api", key: "secret" },
    });
    expect(backend.config?.env.GLM_KEY).toBe("glm-secret");
    expect(backend.config?.mounts).toContainEqual({
      hostPath: path,
      sandboxPath: SANDBOX_OPENCODE_AUTH_FILE,
      readonly: true,
    });
  });

  it("non-zai production dispatch receives the same credentials", async () => {
    vi.stubEnv("GLM_KEY", "glm-secret");
    const { backend, path } = await dispatch(undefined, {
      "grok-4.5": { type: "api", key: "secret" },
    });
    expect(backend.config?.env.GLM_KEY).toBe("glm-secret");
    expect(backend.config?.mounts).toContainEqual({
      hostPath: path,
      sandboxPath: SANDBOX_OPENCODE_AUTH_FILE,
      readonly: true,
    });
  });

  it("codex-pool production CMR dispatch receives the same credentials without metadata inspection", async () => {
    vi.stubEnv("GLM_KEY", "glm-secret");
    const { backend } = await dispatch("codex-5h", {
      "opencode-go": { type: "oauth", refresh: "secret" },
    });
    expect(backend.config?.env.GLM_KEY).toBe("glm-secret");
    expect(backend.config?.mounts).toContainEqual(
      expect.objectContaining({ sandboxPath: SANDBOX_OPENCODE_AUTH_FILE, readonly: true }),
    );
  });
});

// ═══════════════════ 4. cmrSandboxConfig — agy auth runtime-mount + codex + claude ═══════════════════

describe("#335 cmrSandboxConfig — wires the agy auth runtime-mount (writable dir)", () => {
  /** Expose the protected pure config seam + a canned-auth path. */
  class ConfigBackend extends RealFamilyBackend {
    public config(
      auth: CmrAuth,
      spec: ReturnType<typeof cmrWorkerSpec> = cmrWorkerSpec(),
    ): {
      imageName: string;
      env: Record<string, string>;
      mounts: ReadonlyArray<{ hostPath: string; sandboxPath: string; readonly?: boolean }>;
    } {
      return this.cmrSandboxConfig(auth, spec.cmrReviewLegs!);
    }
  }

  function cfgBackend(): ConfigBackend {
    return new ConfigBackend({
      workingRepo: mkDir("cmr-repo-"),
      familyBase: "feat/330-pure-scheduler",
      ledgerDir: mkDir("cmr-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "ming-orchestrator-coder:latest",
    });
  }

  const auth = {
    codexAuthDir: "/tmp/cmr-codex-auth",
    agyDir: "/tmp/cmr-agy",
    claudeToken: "tok-xyz",
  };

  it("mounts the agy writable dir onto the antigravity token path (the #333 gotcha)", () => {
    const cfg = cfgBackend().config(auth);
    const agyMount = cfg.mounts.find((m) => m.sandboxPath === SANDBOX_AGY_DIR);
    expect(agyMount).toBeDefined();
    expect(agyMount!.hostPath).toBe("/tmp/cmr-agy");
    // The agy leg WRITES into its config dir → it must NOT be read-only.
    expect(agyMount!.readonly).not.toBe(true);
  });

  it("still mounts codex auth + injects the claude token + cmr soul (all three legs)", () => {
    const cfg = cfgBackend().config(auth);
    expect(cfg.mounts.some((m) => m.sandboxPath === SANDBOX_CODEX_DIR)).toBe(true);
    expect(cfg.env.CLAUDE_CODE_OAUTH_TOKEN).toBe("tok-xyz");
    expect(cfg.env[SANDBOX_SOUL_ENV]).toBe("cmr");
    // ORCHESTRATOR_REPO so the cmr worker's `gh issue view` / `gh issue create
    // --repo "$ORCHESTRATOR_REPO"` target the right repo in a clone-from-local run
    // (codex #384).
    expect(cfg.env[SANDBOX_REPO_ENV]).toBe("Akagilnc/ming-salvage-sim");
  });

  it("mounts isolated grok auth when the CMR route can dispatch grok", () => {
    const cfg = cfgBackend().config({ ...auth, grokAuthDir: "/tmp/cmr-grok-auth" });
    expect(cfg.mounts).toContainEqual({
      hostPath: "/tmp/cmr-grok-auth",
      sandboxPath: SANDBOX_GROK_DIR,
    });
  });

  it("exports the gh token as GH_TOKEN so the in-container completeness gate can `gh issue view` the live issue body as authority (mirrors the ship worker)", () => {
    // The completeness gate grounds against the live issue body via `gh issue view`;
    // without GH_TOKEN that fails and the audit degrades to commit-titles/test-files.
    const cfg = cfgBackend().config({
      codexAuthDir: "/tmp/cmr-codex-auth",
      agyDir: "/tmp/cmr-agy",
      claudeToken: "tok-xyz",
      ghToken: "gho_cmr",
    });
    expect(cfg.env[SANDBOX_GH_TOKEN_ENV]).toBe("gho_cmr");
  });

  it("omits GH_TOKEN when no gh token is present (NOT a hard blocker for cmr — the gate degrades but still runs)", () => {
    // Unlike ship (which fail-closes on missing gh because it must `gh pr create`),
    // the cmr worker injects gh only when present and still runs without it.
    const cfg = cfgBackend().config(auth);
    expect(cfg.env[SANDBOX_GH_TOKEN_ENV]).toBeUndefined();
  });

  it("the antigravity token path is the host-mirrored gemini path (#333 contract)", () => {
    expect(SANDBOX_AGY_DIR).toBe("/home/agent/.gemini/antigravity-cli");
  });

  it("a leg whose auth is ABSENT degrades — no mount/env, never a crash (codex cmr R1)", () => {
    // agy token absent ⇒ no agy mount, but the rest still mount (the 降级链).
    const noAgy = cfgBackend().config({
      codexAuthDir: "/tmp/cmr-codex-auth",
      claudeToken: "tok",
    });
    expect(noAgy.mounts.some((m) => m.sandboxPath === SANDBOX_AGY_DIR)).toBe(false);
    expect(noAgy.mounts.some((m) => m.sandboxPath === SANDBOX_CODEX_DIR)).toBe(true);
    expect(noAgy.env.CLAUDE_CODE_OAUTH_TOKEN).toBe("tok");

    // claude token absent ⇒ no env var (the Claude Agent leg degrades).
    const noClaude = cfgBackend().config({ codexAuthDir: "/tmp/c", agyDir: "/tmp/a" });
    expect(noClaude.env.CLAUDE_CODE_OAUTH_TOKEN).toBeUndefined();
    expect(noClaude.env[SANDBOX_SOUL_ENV]).toBe("cmr");

    // ALL auth absent ⇒ souls mount is still present (souls always mounted #372),
    // no other mounts, only the soul env — still no throw (the skill runs and will
    // degrade/escalate in-container, never a host crash).
    const none = cfgBackend().config({});
    expect(none.mounts.length).toBe(1);
    expect(none.mounts.some((m) => m.sandboxPath === "/home/agent/.orchestrator/souls")).toBe(true);
    expect(none.env[SANDBOX_SOUL_ENV]).toBe("cmr");
  });

  it("marks the cmr container as an orchestrator-spawned, non-interactive session", () => {
    const cfg = cfgBackend().config(auth);
    expect(cfg.env.OPENCLAW_SESSION).toBe("1");
    expect(cfg.env.OPENCLAW_SESSION).toBe(SPAWNED_WORKER_ENV.OPENCLAW_SESSION);
  });

  it("exports the route-selected CMR leg collection to the worker", () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "normal");
    const cfg = cfgBackend().config(auth);
    const legs = JSON.parse(cfg.env.ORCHESTRATOR_CMR_REVIEW_LEGS ?? "null") as unknown;

    expect(legs).toEqual([
      { family: "codex", slug: "gpt-5.6-sol" },
      { family: "claude", slug: "opus" },
      { family: "agy", slug: "agy", optional: true },
    ]);
  });

  it("exports frozen CMR legs from the worker spec, not later route env", () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "normal");
    const spec = cmrWorkerSpec("fresh", "correctness");
    vi.stubEnv("ORCHESTRATOR_ROUTE", "claude-tight");
    const cfg = cfgBackend().config(auth, spec);
    const legs = JSON.parse(cfg.env.ORCHESTRATOR_CMR_REVIEW_LEGS ?? "null") as unknown;

    expect(legs).toEqual([
      { family: "codex", slug: "gpt-5.6-sol" },
      { family: "claude", slug: "opus" },
      { family: "agy", slug: "agy", optional: true },
    ]);
  });

  // #768: baked skill `codex-review.sh` reads CMR_CODEX_MODEL (default gpt-5.5).
  // Route labels alone are soft — sandbox must pin the executable model from the
  // frozen cmrReview codex leg so leg execution ≡ route label.
  it("#768 pins CMR_CODEX_MODEL from the route's cmrReview codex leg (sol)", () => {
    const solLegs = [
      { family: "codex", slug: "gpt-5.6-sol" },
      { family: "claude", slug: "opus" },
      { family: "agy", slug: "agy" },
    ] as const;
    const spec = {
      ...cmrWorkerSpec("fresh", "correctness"),
      cmrReviewLegs: solLegs,
    };
    const cfg = cfgBackend().config(auth, spec);
    expect(cfg.env.CMR_CODEX_MODEL).toBe("gpt-5.6-sol");
  });

  it("#768 omits CMR_CODEX_MODEL when the frozen legs have no codex review leg", () => {
    const noCodex = {
      ...cmrWorkerSpec("fresh", "correctness"),
      cmrReviewLegs: [
        { family: "claude", slug: "opus" },
        { family: "agy", slug: "agy" },
      ],
    };
    const cfg = cfgBackend().config(auth, noCodex);
    expect(cfg.env.CMR_CODEX_MODEL).toBeUndefined();
  });

  it("#768 drift guard: cmrSandboxConfig source must assign CMR_CODEX_MODEL from the review legs", () => {
    // Behavioral pin above goes green only while injection works; this source
    // guard REDS if the env key is deleted or replaced with a hardcoded slug.
    const source = readFileSync(
      join(here, "..", "..", "..", "src", "family", "realFamilyBackend.ts"),
      "utf8",
    );
    const fnStart = source.indexOf("protected cmrSandboxConfig(");
    expect(fnStart).toBeGreaterThanOrEqual(0);
    // Extract the ENTIRE method via brace matching — no arbitrary char window
    // (a fixed slice can spuriously miss the assignment if the function grows).
    // Signature shape: cmrSandboxConfig(...): { returnType } { body }
    let i = source.indexOf("(", fnStart);
    let depth = 0;
    for (; i < source.length; i++) {
      if (source[i] === "(") depth++;
      else if (source[i] === ")") {
        depth--;
        if (depth === 0) {
          i++;
          break;
        }
      }
    }
    while (i < source.length && /\s/.test(source[i]!)) i++;
    if (source[i] === ":") {
      // Skip return-type annotation; the next `{` at nest 0 after type content
      // is the function body opener.
      i++;
      let nest = 0;
      let started = false;
      while (i < source.length) {
        const c = source[i]!;
        if (c === "{" && nest === 0 && started) break;
        if (c === "{" || c === "(" || c === "[") {
          nest++;
          started = true;
          i++;
        } else if (c === "}" || c === ")" || c === "]") {
          nest--;
          i++;
        } else if (/\s/.test(c)) {
          i++;
        } else {
          started = true;
          i++;
        }
      }
    } else {
      while (i < source.length && source[i] !== "{") i++;
    }
    const bodyOpen = i;
    expect(source[bodyOpen]).toBe("{");
    depth = 0;
    let fnEnd = -1;
    for (i = bodyOpen; i < source.length; i++) {
      if (source[i] === "{") depth++;
      else if (source[i] === "}") {
        depth--;
        if (depth === 0) {
          fnEnd = i + 1;
          break;
        }
      }
    }
    expect(fnEnd).toBeGreaterThan(fnStart);
    const fnBody = source.slice(fnStart, fnEnd);
    // Must match the real assignment/derivation line, not a comment mention alone.
    expect(fnBody).toMatch(/env\.CMR_CODEX_MODEL\s*=\s*codexReviewLeg\.slug/);
  });
});

// ═══════════════════ 4b. mountCmrAuth — best-effort per leg (codex cmr R1) ═══════════════════

describe("#335 mountCmrAuth — a missing host credential degrades, never throws", () => {
  /**
   * Expose the protected auth-mount seam, with $HOME pointed at an EMPTY dir.
   * `readGhToken` is stubbed to undefined so the empty-$HOME case is deterministic:
   * the real `gh auth token` reads the HOST OS keyring (not $HOME), so it would
   * otherwise leak the host's gh token into a "no creds" assertion.
   */
  class AuthBackend extends RealFamilyBackend {
    public auth(): CmrAuth {
      return this.mountCmrAuth();
    }
    protected override readGhToken(): string | undefined {
      return undefined;
    }
  }

  it("an empty $HOME (no codex/agy/claude creds) ⇒ all-undefined auth, no throw", () => {
    const emptyHome = mkDir("cmr-empty-home-");
    const be = new AuthBackend({
      workingRepo: mkDir("cmr-repo-"),
      familyBase: "feat/330-pure-scheduler",
      ledgerDir: mkDir("cmr-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "ming-orchestrator-coder:latest",
      home: emptyHome,
    });
    let auth: CmrAuth | undefined;
    expect(() => {
      auth = be.auth();
    }).not.toThrow();
    expect(auth).toEqual({
      codexAuthDir: undefined,
      agyDir: undefined,
      grokAuthDir: undefined,
      claudeToken: undefined,
      ghToken: undefined,
      providerAuth: { claude: false, grok: false },
    });
  });

  it("threads the host gh token (readGhToken) into ghToken — the completeness gate's `gh issue view` authority", () => {
    // A separate backend whose readGhToken yields a present token: mountCmrAuth must
    // wire it onto CmrAuth.ghToken (cmrSandboxConfig then exports it as GH_TOKEN).
    class GhAuthBackend extends RealFamilyBackend {
      public auth(): CmrAuth {
        return this.mountCmrAuth();
      }
      protected override readGhToken(): string | undefined {
        return "gho_host";
      }
    }
    const be = new GhAuthBackend({
      workingRepo: mkDir("cmr-repo-"),
      familyBase: "feat/330-pure-scheduler",
      ledgerDir: mkDir("cmr-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "ming-orchestrator-coder:latest",
      home: mkDir("cmr-gh-home-"),
    });
    expect(be.auth().ghToken).toBe("gho_host");
  });

  it("a missing codex/agy source reclaims the mkdtemp dir — no leak on degrade (online review r2, gemini)", () => {
    // The degrade path leaks pre-fix: mountCmrAuth's mkdtempSync creates the per-run
    // codex/agy dir, THEN copyFileSync throws ENOENT because the source cred is
    // absent (the expected degradation, e.g. agy quota-out). codexAuthDir/agyDir
    // stay undefined, so the caller's finally cleanup never sees the dir — it leaks
    // under ~/.sc-orchestrator. The catch must rmSync the temp dir it created.
    const emptyHome = mkDir("cmr-degrade-home-");
    const be = new AuthBackend({
      workingRepo: mkDir("cmr-repo-"),
      familyBase: "feat/330-pure-scheduler",
      ledgerDir: mkDir("cmr-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "ming-orchestrator-coder:latest",
      home: emptyHome,
    });
    const auth = be.auth();
    expect(auth.codexAuthDir).toBeUndefined();
    expect(auth.agyDir).toBeUndefined();
    // The mkdtemp dirs created before the copy threw were reclaimed: no residue.
    const root = join(emptyHome, ".sc-orchestrator");
    const residue = existsSync(root) ? readdirSync(root) : [];
    expect(
      residue.filter((n) => n.startsWith("cmr-codex-auth-") || n.startsWith("cmr-agy-")),
    ).toEqual([]);
  });
});

// ═══════════════════ 4b-bis. mountCmrAuth — container codex config is minimal, NOT host copy ═══════════════════

describe("#378 mountCmrAuth — writes a minimal danger-full-access config, never copies the host config.toml", () => {
  class AuthBackend extends RealFamilyBackend {
    public auth(): CmrAuth {
      return this.mountCmrAuth();
    }
    protected override readGhToken(): string | undefined {
      return undefined;
    }
  }

  /**
   * A populated host $HOME with BOTH codex creds AND a host config.toml carrying
   * host-personal keys (the real bug source: `sandbox_mode = "workspace-write"`
   * makes the in-container codex try to self-sandbox → nested bwrap fails → cmr
   * legs degrade to static-only).
   */
  function hostHomeWithCodexConfig(): string {
    const home = mkDir("cmr-host-home-");
    const codexDir = join(home, ".codex");
    mkdirSync(codexDir, { recursive: true });
    writeFileSync(join(codexDir, "auth.json"), '{"OPENAI_API_KEY":"sk-host"}');
    writeFileSync(
      join(codexDir, "config.toml"),
      [
        'model = "gpt-5.6-sol"',
        'sandbox_mode = "workspace-write"',
        'notify = ["/Users/host/notify.app"]',
        '[plugins."github@openai-curated"]',
        "enabled = true",
        "",
      ].join("\n"),
    );
    return home;
  }

  it("copies auth.json but WRITES a minimal config.toml (danger-full-access, never the host copy)", () => {
    const be = new AuthBackend({
      workingRepo: mkDir("cmr-repo-"),
      familyBase: "feat/330-pure-scheduler",
      ledgerDir: mkDir("cmr-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "ming-orchestrator-coder:latest",
      home: hostHomeWithCodexConfig(),
    });
    const auth = be.auth();
    expect(auth.codexAuthDir).toBeTruthy();
    const dir = auth.codexAuthDir as string;

    // Credentials still mirrored.
    expect(readFileSync(join(dir, "auth.json"), "utf8")).toContain("sk-host");

    // A config.toml was written, and it is the minimal container one.
    const config = readFileSync(join(dir, "config.toml"), "utf8");
    expect(config).toContain('sandbox_mode = "danger-full-access"');

    // The host config.toml was NOT copied verbatim: host-only keys + the
    // self-sandbox `workspace-write` mode are absent.
    expect(config).not.toContain("workspace-write");
    expect(config).not.toContain("notify");
    expect(config).not.toContain("plugins");
  });
});

// ═══════════════════ 4c. writeCmrFocusFile — exact scope + focus (codex cmr R1 F2/F3) ═══════════════════

describe("#335 writeCmrFocusFile — threads the exact diff scope + machine-resolved focus", () => {
  /** Expose the focus-file seam over a REAL temp git repo (so the exclude path resolves). */
  class FocusBackend extends RealFamilyBackend {
    public focus(ctx: {
      familyBase: string;
      llmResolvedChildren?: readonly number[];
      escalationAnswer?: DispatchContext["escalationAnswer"];
    }): void {
      this.writeCmrFocusFile(ctx as never);
    }
    public routeFile(pass: "completeness" | "correctness" | undefined): void {
      const spec = cmrWorkerSpec("fresh", pass ?? "correctness");
      this.writeCmrRouteFile(pass, spec.cmrReviewLegs!);
    }
    public routeFileFromNull(): void {
      const spec = cmrWorkerSpec("fresh", "correctness");
      this.writeCmrRouteFile(null as never, spec.cmrReviewLegs!);
    }
    public routeFileFromSpec(
      pass: "completeness" | "correctness",
      spec: ReturnType<typeof cmrWorkerSpec>,
    ): void {
      this.writeCmrRouteFile(pass, spec.cmrReviewLegs!);
    }
    public onlineLanding(
      ctx: DispatchContext,
      landing: NonNullable<Parameters<FocusBackend["writeFamilyOnlineReviewLandingFile"]>[1]>,
    ): string {
      return this.writeFamilyOnlineReviewLandingFile(ctx, landing).path;
    }
  }

  function realRepo(): string {
    const repo = mkDir("cmr-focus-repo-");
    execFileSync("git", ["init", "-q"], { cwd: repo });
    return repo;
  }

  it("pins the cut-SHA scope command + names the machine-resolved children", () => {
    const repo = realRepo();
    const be = new FocusBackend({
      workingRepo: repo,
      familyBase: "feat/330-pure-scheduler",
      ledgerDir: mkDir("cmr-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
      familyBaseStartHead: "abc123",
    });
    be.focus({ familyBase: "feat/330-pure-scheduler", llmResolvedChildren: [42, 43] });
    const body = readFileSync(join(repo, CMR_FOCUS_FILENAME), "utf8");
    // F3: the exact scope diff is on the recorded cut SHA, NOT main...HEAD.
    expect(body).toContain("git diff abc123...feat/330-pure-scheduler");
    // F2: the machine-resolved children are named.
    expect(body).toContain("#42");
    expect(body).toContain("#43");
    // It is git-ignored (info/exclude), so the review never accidentally commits it.
    const exclude = readFileSync(join(repo, ".git", "info", "exclude"), "utf8");
    expect(exclude.split("\n")).toContain(CMR_FOCUS_FILENAME);
  });

  it("serializes an answered gate into the real online-review landing", () => {
    const repo = realRepo();
    const be = new FocusBackend({
      workingRepo: repo,
      familyBase: "feat/330-pure-scheduler",
      ledgerDir: mkDir("cmr-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
      familyBaseStartHead: "abc123",
    });
    const path = be.onlineLanding(
      {
        familyBase: "feat/330-pure-scheduler",
        escalationAnswer: {
          event: "escalation_answered",
          answer: "defer this finding",
          source: "human",
        },
      },
      {
        onlineReviewSnapshot: { kind: "offline", findings: [] } as never,
      },
    );
    const payload = JSON.parse(readFileSync(path, "utf8")) as Record<string, unknown>;
    expect(payload.escalationAnswer).toEqual({
      event: "escalation_answered",
      answer: "defer this finding",
      source: "human",
    });
  });

  it("writes the route file pass from dispatch context, not the prompt filename", () => {
    const repo = realRepo();
    const be = new FocusBackend({
      workingRepo: repo,
      familyBase: "feat/330-pure-scheduler",
      ledgerDir: mkDir("cmr-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
      familyBaseStartHead: "abc123",
    });
    be.routeFile("correctness");
    const body = JSON.parse(readFileSync(join(repo, CMR_ROUTE_FILENAME), "utf8")) as {
      pass: string;
    };
    expect(body.pass).toBe("correctness");
  });

  it("no recorded cut SHA ⇒ FAIL-CLOSED throw, never a stale-base fallback scope (codex R3)", () => {
    // The focus file pins the EXACT cut-SHA review-scope diff (prompt contract:
    // do NOT guess main...HEAD). Emitting a
    // `main...familyBase` fallback when no cut SHA was recorded would silently
    // disable that load-bearing scope — the same fail-open the reconcile
    // `familyBaseStartHead()` predicate refuses (realFamilyBackend.ts:887-895). So
    // a missing cut SHA must THROW (the gate converts it to not-passed / escalate),
    // never write a stale-base diff command.
    const repo = realRepo();
    const be = new FocusBackend({
      workingRepo: repo,
      familyBase: "fb",
      ledgerDir: mkDir("cmr-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
      // no familyBaseStartHead
    });
    expect(() => be.focus({ familyBase: "fb" })).toThrow(/familyBaseStartHead|cut SHA/i);
    // And it did NOT write a stale-base fallback file.
    expect(() => readFileSync(join(repo, CMR_FOCUS_FILENAME), "utf8")).toThrow();
  });

  it("keeps prior finding state out of the transient focus file", () => {
    // The focus file is pass-scoped runtime input. It pins ONLY the review scope +
    // the machine-resolved-child focus; pass/closure accounting travels via the
    // worker verdict and durable ledger, never a "prior round's findings" prompt
    // block in this file.
    const repo = realRepo();
    const be = new FocusBackend({
      workingRepo: repo,
      familyBase: "feat/330-pure-scheduler",
      ledgerDir: mkDir("cmr-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
      familyBaseStartHead: "abc123",
    });
    be.focus({ familyBase: "feat/330-pure-scheduler", llmResolvedChildren: [42] });
    const body = readFileSync(join(repo, CMR_FOCUS_FILENAME), "utf8");
    // The full review-scope diff + the machine-resolved focus are present...
    expect(body).toContain("git diff abc123...feat/330-pure-scheduler");
    expect(body).toContain("#42");
    // ...but NO prior-findings block (the worker remembers within its own session).
    expect(body).not.toMatch(/Prior round's findings/i);
    expect(body).not.toMatch(/confirm-resolved/i);
  });

  it("writes the route-selected CMR review legs beside the focus file", () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "normal");
    const repo = realRepo();
    const be = new FocusBackend({
      workingRepo: repo,
      familyBase: "feat/330-pure-scheduler",
      ledgerDir: mkDir("cmr-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
      familyBaseStartHead: "abc123",
    });

    be.routeFile("correctness");

    const route = JSON.parse(readFileSync(join(repo, CMR_ROUTE_FILENAME), "utf8")) as unknown;
    expect(route).toEqual({
      pass: "correctness",
      reviewLegs: [
        { family: "codex", slug: "gpt-5.6-sol" },
        { family: "claude", slug: "opus" },
        { family: "agy", slug: "agy", optional: true },
      ],
    });
    const exclude = readFileSync(join(repo, ".git", "info", "exclude"), "utf8");
    expect(exclude.split("\n")).toContain(CMR_ROUTE_FILENAME);
  });

  it("freezes CMR review legs from the worker spec, not later route env", () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "normal");
    const spec = cmrWorkerSpec("fresh", "correctness");
    vi.stubEnv("ORCHESTRATOR_ROUTE", "claude-tight");
    const repo = realRepo();
    const be = new FocusBackend({
      workingRepo: repo,
      familyBase: "feat/330-pure-scheduler",
      ledgerDir: mkDir("cmr-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
      familyBaseStartHead: "abc123",
    });

    be.routeFileFromSpec("correctness", spec);

    const route = JSON.parse(readFileSync(join(repo, CMR_ROUTE_FILENAME), "utf8")) as {
      reviewLegs: unknown;
    };
    expect(route.reviewLegs).toEqual([
      { family: "codex", slug: "gpt-5.6-sol" },
      { family: "claude", slug: "opus" },
      { family: "agy", slug: "agy", optional: true },
    ]);
  });

  it("treats null CMR route context as a legacy route-file write instead of crashing", () => {
    const repo = realRepo();
    const be = new FocusBackend({
      workingRepo: repo,
      familyBase: "feat/330-pure-scheduler",
      ledgerDir: mkDir("cmr-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
      familyBaseStartHead: "abc123",
    });

    expect(() => be.routeFileFromNull()).not.toThrow();
    const route = JSON.parse(readFileSync(join(repo, CMR_ROUTE_FILENAME), "utf8")) as {
      pass: string;
      reviewLegs: unknown;
    };
    expect(route.pass).toBe("legacy");
    expect(route.reviewLegs).toEqual(cmrWorkerSpec("fresh", "correctness").cmrReviewLegs);
  });

  it("threads a human escalation answer into the CMR focus file", () => {
    const repo = realRepo();
    const be = new FocusBackend({
      workingRepo: repo,
      familyBase: "feat/330-pure-scheduler",
      ledgerDir: mkDir("cmr-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
      familyBaseStartHead: "abc123",
    });

    be.focus({
      familyBase: "feat/330-pure-scheduler",
      escalationAnswer: {
        event: "escalation_answered",
        answer: "continue-same-class",
        note: "Human says continue the same-class CMR fix loop.",
      },
    });

    const body = readFileSync(join(repo, CMR_FOCUS_FILENAME), "utf8");
    expect(body).toContain("Human escalation answer");
    expect(body).toContain("continue-same-class");
    expect(body).toContain("Human says continue the same-class CMR fix loop.");
  });
});

// ═══════════════════ 4d. runCmrWorker fail-closed on a missing cut SHA (codex R3) ═══════════════════

describe("#335 runCmrWorker — fail-closed when no cut SHA was recorded", () => {
  /** Exposes runCmrWorker and traps sc.run so we can prove it is NEVER reached. */
  class GuardBackend extends RealFamilyBackend {
    scRunReached = false;
    public run(spec: ReturnType<typeof cmrWorkerSpec>, ctx: DispatchContext) {
      return this.runCmrWorker(spec, ctx);
    }
    protected override writeCmrFocusFile(): void {
      // If the guard is correct this is never reached; flag it if it is.
      this.scRunReached = true;
      throw new Error("writeCmrFocusFile should not run when fail-closed");
    }
  }

  it("a cmr worker with NO familyBaseStartHead ⇒ escalate, never spins the container", async () => {
    const repo = realRepo335();
    const be = new GuardBackend({
      workingRepo: repo,
      familyBase: "fb",
      ledgerDir: mkDir("cmr-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
      // no familyBaseStartHead
    });
    const outcome = await be.run(cmrWorkerSpec(), { familyBase: "fb" });
    expect(outcome.kind).toBe("escalate");
    if (outcome.kind === "escalate") {
      expect(outcome.reason).toMatch(/familyBaseStartHead|cut SHA/i);
    }
    // The fail-closed guard returns BEFORE any container / focus-file work.
    expect(be.scRunReached).toBe(false);
  });

  it("dispatchWorker routes that fail-closed escalate to a not-passed WorkerResult", async () => {
    const repo = realRepo335();
    const be = new GuardBackend({
      workingRepo: repo,
      familyBase: "fb",
      ledgerDir: mkDir("cmr-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
      // no familyBaseStartHead
    });
    const res = await be.dispatchWorker(cmrWorkerSpec(), { familyBase: "fb" });
    expect(res.kind).toBe("escalated");
    if (res.kind === "escalated") {
      expect(res.escalation.reason).toMatch(/familyBaseStartHead|cut SHA/i);
      expect(isRunnerSynthesizedFailureEscalation(res.escalation)).toBe(true);
    }
  });
});

// ═══════ 4e. runCmrWorker fail-closed on a missing Claude WORKER auth (codex R4) ═══════

describe("#335 runCmrWorker — fail-closed when the top-level Claude worker has no auth", () => {
  /**
   * The CMR worker is the container's TOP-LEVEL claude (`agent: sc.claudeCode`), so
   * the Claude OAuth token is not a mere reviewer leg — it is the worker's OWN auth.
   * A missing token means the worker cannot start and never emits a `<cmr>` verdict;
   * letting it through would crash out of `sc.run` (NOT a structured escalate),
   * bypassing verifyCmr's escalate routing. So `runCmrWorker` must escalate BEFORE
   * spinning the container when `mountCmrAuth().claudeToken` is absent.
   */
  class NoClaudeAuthBackend extends RealFamilyBackend {
    scRunReached = false;
    public run(spec: ReturnType<typeof cmrWorkerSpec>, ctx: DispatchContext) {
      return this.runCmrWorker(spec, ctx);
    }
    // The cut SHA IS recorded (we isolate the Claude-auth guard from the R3 guard).
    protected override mountCmrAuth(): CmrAuth {
      // codex/agy present, claude token ABSENT (the worker's own auth missing).
      return { codexAuthDir: "/x/codex", agyDir: "/x/agy" };
    }
    protected override writeCmrFocusFile(): void {
      this.scRunReached = true;
      throw new Error("writeCmrFocusFile should not run when the worker has no auth");
    }
  }

  it("no Claude worker token ⇒ escalate, never spins the container", async () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "normal");
    const repo = realRepo335();
    const be = new NoClaudeAuthBackend({
      workingRepo: repo,
      familyBase: "fb",
      ledgerDir: mkDir("cmr-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
      familyBaseStartHead: "abc123",
    });
    const outcome = await be.run(legacyClaudeCmrSpec(), { familyBase: "fb" });
    expect(outcome.kind).toBe("escalate");
    if (outcome.kind === "escalate") {
      expect(outcome.reason).toMatch(/claude|token|auth/i);
    }
    expect(be.scRunReached).toBe(false);
  });

  it("dispatchWorker routes the no-auth escalate to a not-passed WorkerResult", async () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "normal");
    const repo = realRepo335();
    const be = new NoClaudeAuthBackend({
      workingRepo: repo,
      familyBase: "fb",
      ledgerDir: mkDir("cmr-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
      familyBaseStartHead: "abc123",
    });
    const res = await be.dispatchWorker(legacyClaudeCmrSpec(), { familyBase: "fb" });
    expect(res.kind).toBe("escalated");
    if (res.kind === "escalated") {
      expect(isRunnerSynthesizedFailureEscalation(res.escalation)).toBe(true);
    }
  });
});

function realRepo335(): string {
  const repo = mkDir("cmr-guard-repo-");
  execFileSync("git", ["init", "-q"], { cwd: repo });
  return repo;
}

// The live CMR worker is now Codex. Keep this direct legacy spec only to cover
// the conditional Claude-auth guard for replayed historical worker records.
function legacyClaudeCmrSpec(): ReturnType<typeof cmrWorkerSpec> {
  return { ...cmrWorkerSpec(), model: "opus" };
}

// ═══════ 4f. runCmrWorker reclaims its per-run temp auth dirs (online review r1) ═══════

describe("#335 runCmrWorker — reclaims the per-run temp auth dirs (no leak)", () => {
  /**
   * `mountCmrAuth` creates per-run codex/agy temp dirs that are only needed for the
   * lifetime of the mounted container run. They must be reclaimed on EVERY exit —
   * including the early claude-token escalate (which never reaches sc.run). 3 bots
   * flagged the leak; the try/finally in runCmrWorker is the fix.
   */
  class ReclaimBackend extends RealFamilyBackend {
    constructor(opts: ConstructorParameters<typeof RealFamilyBackend>[0], private readonly dirs: CmrAuth) {
      super(opts);
    }
    public run(spec: ReturnType<typeof cmrWorkerSpec>, ctx: DispatchContext) {
      return this.runCmrWorker(spec, ctx);
    }
    // Real on-disk dirs but NO claude token ⇒ the early escalate fires; the finally
    // must still reclaim the two dirs.
    protected override mountCmrAuth(): CmrAuth {
      return this.dirs;
    }
  }

  it("the early no-claude-auth escalate removes codex, agy, and grok temp dirs", async () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "normal");
    const codexDir = mkDir("reclaim-codex-");
    const agyDir = mkDir("reclaim-agy-");
    const grokDir = mkDir("reclaim-grok-");
    expect(existsSync(codexDir)).toBe(true);
    expect(existsSync(agyDir)).toBe(true);
    expect(existsSync(grokDir)).toBe(true);

    const be = new ReclaimBackend(
      {
        workingRepo: realRepo335(),
        familyBase: "fb",
        ledgerDir: mkDir("cmr-ledger-"),
        repo: "Akagilnc/ming-salvage-sim",
        base: "main",
        promptsDir: realPromptsDir,
        soulsDir: realSoulsDir,
        imageName: "img",
        familyBaseStartHead: "abc123",
      },
      { codexAuthDir: codexDir, agyDir, grokAuthDir: grokDir }, // no claudeToken ⇒ early escalate
    );

    const outcome = await be.run(legacyClaudeCmrSpec(), { familyBase: "fb" });
    expect(outcome.kind).toBe("escalate");
    // The finally reclaimed BOTH per-run dirs even though sc.run never ran.
    expect(existsSync(codexDir)).toBe(false);
    expect(existsSync(agyDir)).toBe(false);
    expect(existsSync(grokDir)).toBe(false);
  });

  it("uses Sandcastle's typed CMR receipt when the sidecar cargo is malformed, then removes it", async () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "normal");
    const repo = realRepo335();
    execFileSync("git", ["config", "user.email", "t@t.t"], { cwd: repo });
    execFileSync("git", ["config", "user.name", "t"], { cwd: repo });
    execFileSync("git", ["commit", "--allow-empty", "-q", "-m", "root"], { cwd: repo });
    execFileSync("git", ["checkout", "-b", "fb"], { cwd: repo });
    let outcomePathAtRun: string | undefined;
    class OutcomeCleanupBackend extends RealFamilyBackend {
      public calls = 0;
      public run(spec: ReturnType<typeof cmrWorkerSpec>, ctx: DispatchContext) {
        return this.runCmrWorker(spec, ctx);
      }
      protected override mountCmrAuth(): CmrAuth {
        return { claudeToken: "tok" };
      }
      protected override prepareCmrOutcomeLanding(
        ctx: DispatchContext,
      ): { path: string; sandboxPath: string } {
        const landing = super.prepareCmrOutcomeLanding(ctx);
        outcomePathAtRun = landing.path;
        return landing;
      }
      protected override async runAgentSandbox(
        options: Parameters<typeof sc.run>[0],
      ): Promise<Awaited<ReturnType<typeof sc.run>>> {
        this.calls += 1;
        expect(options.output).toEqual(expect.objectContaining({ tag: "cmr", maxRetries: 2 }));
        if (outcomePathAtRun === undefined) throw new Error("missing outcome sidecar path");
        writeFileSync(
          outcomePathAtRun,
          JSON.stringify({ converged: "not-a-verdict" }),
          "utf8",
        );
        return typedSandboxRunResult({
          converged: true,
          findingsCount: 0,
          successfulLegs: DEFAULT_CMR_LEGS,
          ...VALID_CMR_VERDICT_FIELDS,
        }, {
          completionSignal: "CMR_STEP_COMPLETE",
          stdout: "compatibility tag intentionally absent",
        });
      }
    }
    const be = new OutcomeCleanupBackend({
      workingRepo: repo,
      familyBase: "fb",
      ledgerDir: mkDir("cmr-outcome-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
      familyBaseStartHead: "abc123",
    });

    const outcome = await be.run(cmrWorkerSpec(), { familyBase: "fb", cmrPass: "completeness" });

    expect(outcome).toMatchObject({
      kind: "verdict",
      findingsCount: 0,
      successfulLegs: DEFAULT_CMR_LEGS,
    });
    expect(be.calls).toBe(1);
    expect(outcomePathAtRun).toBeDefined();
    expect(existsSync(dirname(outcomePathAtRun as string))).toBe(false);
  });

  it("does not attach Output.object for family coder so opaque cargo never SO-retries", async () => {
    // #899 / ADR 0131 R9: family coder cargo stays fully opaque — no Output.object.
    // Malformed/absent committed cargo does not force a structured-output re-ask.
    const repo = realRepo335();
    execFileSync("git", ["config", "user.email", "t@t.t"], { cwd: repo });
    execFileSync("git", ["config", "user.name", "t"], { cwd: repo });
    execFileSync("git", ["commit", "--allow-empty", "-q", "-m", "root"], { cwd: repo });
    execFileSync("git", ["checkout", "-b", "fb"], { cwd: repo });
    let outcomePathAtRun: string | undefined;

    class FamilyCoderReceiptBackend extends RealFamilyBackend {
      public calls: Parameters<typeof sc.run>[0][] = [];
      public run(spec: ReturnType<typeof familyCoderFixWorkerSpec>, ctx: DispatchContext) {
        return this.runFamilyCoderFixWorker(spec, ctx);
      }
      protected override mountShipAuth(): ShipAuth { return { claudeToken: "tok" }; }
      protected override prepareFamilyCoderOutcomeLanding(): { path: string; sandboxPath: string } {
        const landing = super.prepareFamilyCoderOutcomeLanding();
        outcomePathAtRun = landing.path;
        return landing;
      }
      protected override async runAgentSandbox(
        options: Parameters<typeof sc.run>[0],
      ): Promise<Awaited<ReturnType<typeof sc.run>>> {
        this.calls.push(options);
        if (outcomePathAtRun === undefined) throw new Error("missing outcome sidecar path");
        writeFileSync(outcomePathAtRun, JSON.stringify({ committed: "not-a-boolean" }), "utf8");
        return {
          branch: "fb",
          completionSignal: "CODER_STEP_COMPLETE",
          stdout: "family coder finished with opaque sidecar cargo",
          commits: [],
          iterations: [{ sessionId: "family-coder-malformed" }],
        } as Awaited<ReturnType<typeof sc.run>>;
      }
    }

    const be = new FamilyCoderReceiptBackend({
      workingRepo: repo,
      familyBase: "fb",
      ledgerDir: mkDir("family-coder-receipt-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
      familyBaseStartHead: "abc123",
    });

    await expect(be.run(familyCoderFixWorkerSpec(), { familyBase: "fb" })).resolves.toMatchObject({
      kind: "completed",
      output: { kind: "coder", committed: false, commitsAdded: 0 },
    });
    expect(be.calls).toHaveLength(1);
    expect(be.calls[0]!.output).toBeUndefined();
    expect(be.calls[0]!.resumeSession).toBeUndefined();
  });

  it("keeps a single family coder invocation when sidecar cargo is absent", async () => {
    const repo = realRepo335();
    execFileSync("git", ["config", "user.email", "t@t.t"], { cwd: repo });
    execFileSync("git", ["config", "user.name", "t"], { cwd: repo });
    execFileSync("git", ["commit", "--allow-empty", "-q", "-m", "root"], { cwd: repo });
    execFileSync("git", ["checkout", "-b", "fb"], { cwd: repo });
    class NoSessionBackend extends RealFamilyBackend {
      public calls = 0;
      public run(spec: ReturnType<typeof familyCoderFixWorkerSpec>, ctx: DispatchContext) {
        return this.runFamilyCoderFixWorker(spec, ctx);
      }
      protected override mountShipAuth(): ShipAuth { return { claudeToken: "tok" }; }
      protected override async runAgentSandbox(): Promise<Awaited<ReturnType<typeof sc.run>>> {
        this.calls += 1;
        return sandboxRunResult();
      }
    }
    const be = new NoSessionBackend({ workingRepo: repo, familyBase: "fb", ledgerDir: mkDir("family-coder-no-session-ledger-"), repo: "Akagilnc/ming-salvage-sim", base: "main", promptsDir: realPromptsDir, soulsDir: realSoulsDir, imageName: "img", familyBaseStartHead: "abc123" });

    await expect(be.run(familyCoderFixWorkerSpec(), { familyBase: "fb" })).resolves.toMatchObject({
      kind: "completed", output: { kind: "coder", committed: false, commitsAdded: 0 },
    });
    expect(be.calls).toBe(1);
  });

  it("a prepared but blank CMR outcome sidecar falls back to legacy stdout", async () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "normal");
    const repo = realRepo335();
    execFileSync("git", ["config", "user.email", "t@t.t"], { cwd: repo });
    execFileSync("git", ["config", "user.name", "t"], { cwd: repo });
    execFileSync("git", ["commit", "--allow-empty", "-q", "-m", "root"], { cwd: repo });
    execFileSync("git", ["checkout", "-b", "fb"], { cwd: repo });
    let outcomePathAtRun: string | undefined;

    class BlankSidecarBackend extends RealFamilyBackend {
      public run(spec: ReturnType<typeof cmrWorkerSpec>, ctx: DispatchContext) {
        return this.runCmrWorker(spec, ctx);
      }
      protected override mountCmrAuth(): CmrAuth {
        return { claudeToken: "tok" };
      }
      protected override prepareCmrOutcomeLanding(
        ctx: DispatchContext,
      ): { path: string; sandboxPath: string } {
        const landing = super.prepareCmrOutcomeLanding(ctx);
        outcomePathAtRun = landing.path;
        return landing;
      }
      protected override async runAgentSandbox(
        _options: Parameters<typeof sc.run>[0],
      ): Promise<Awaited<ReturnType<typeof sc.run>>> {
        if (outcomePathAtRun === undefined) throw new Error("missing outcome sidecar path");
        expect(readFileSync(outcomePathAtRun, "utf8")).toBe("");
        return {
          completionSignal: "CMR_STEP_COMPLETE",
          stdout: `<cmr>${JSON.stringify({
            converged: true,
            successfulLegs: DEFAULT_CMR_LEGS,
            ...VALID_CMR_VERDICT_FIELDS,
          })}</cmr>\nfindings = 0\nCMR_STEP_COMPLETE`,
        } as Awaited<ReturnType<typeof sc.run>>;
      }
    }

    const be = new BlankSidecarBackend({
      workingRepo: repo,
      familyBase: "fb",
      ledgerDir: mkDir("cmr-blank-sidecar-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
      familyBaseStartHead: "abc123",
    });

    const outcome = await be.run(cmrWorkerSpec(), { familyBase: "fb", cmrPass: "completeness" });

    expect(outcome).toMatchObject({
      kind: "verdict",
      converged: true,
      successfulLegs: DEFAULT_CMR_LEGS,
    });
  });
});

// ═══════════════════ 5. deleted-fanout regression ═══════════════════

describe("#335 the runner-internal 3-CLI 手搓 is DELETED", () => {
  it("familyDriver no longer exports the 3-leg reviewer fan-out symbols", async () => {
    const mod = await import("../../../src/familyDriver.js");
    const m = mod as Record<string, unknown>;
    expect(m.DriverFamilyBackend).toBeUndefined();
    expect(m.reviewerPrompt).toBeUndefined();
    expect(m.parseReviewerVerdict).toBeUndefined();
    expect(m.aggregateCmr).toBeUndefined();
    expect(m.reviewerLegFromOutput).toBeUndefined();
  });
});
