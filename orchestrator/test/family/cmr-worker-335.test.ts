/**
 * #335 — the family integrated cmr step is a CONTAINER cmr WORKER that invokes
 * the real `ak-cross-m-review`, replacing the runner-internal 3-CLI 手搓
 * (`DriverFamilyBackend.runCmr`'s direct codex/claude/agy fan-out).
 *
 * The cmr worker = the 2b container's TOP-LEVEL claude; it `Skill`-invokes
 * `ak-cross-m-review` (which itself fans out 1 Agent + 2 CLI legs inside the
 * container — proven in #333), FRESH each round (cross-model independence). The
 * worker returns a `{converged, reason?, successfulLegs, skippedLegs?}` verdict
 * (PRD #330 R2: the family cmr consumer `verifyCmr.ts` is escalate-on-red, NO
 * fix-loop, so no findings array is required). A `red` verdict is
 * `WorkerResult.completed` (a CmrResult payload), NOT `failed`.
 *
 * Tested WITHOUT a real container:
 *   - parseCmrOutcome: the `<cmr>` tag → converged / red / escalate / malformed;
 *   - cmrOutcomeFromResult: the completion-signal gate (an unsignaled run is NOT a
 *     pass — mirrors the merger gate);
 *   - RealFamilyBackend.dispatchWorker(cmr): routes ak-cross-m-review + FRESH +
 *     cmr (write/fixer) soul through the injected `runCmrWorker` seam and wraps the verdict
 *     into a WorkerResult (converged → completed; red → completed; escalate →
 *     escalated; malformed → malformed);
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
import {
  CMR_ROUTE_FILENAME,
  CMR_FOCUS_FILENAME,
  cmrOutcomeFromResult,
  parseCmrOutcome,
  RealFamilyBackend,
  SANDBOX_AGY_DIR,
  type CmrAuth,
  type CmrWorkerOutcome,
} from "../../src/family/realFamilyBackend.js";
import {
  SANDBOX_CODEX_DIR,
  SANDBOX_GH_TOKEN_ENV,
  SANDBOX_REPO_ENV,
  SANDBOX_SOUL_ENV,
  SPAWNED_WORKER_ENV,
} from "../../src/realBackend.js";
import { cmrWorkerSpec, familyShipWorkerSpec } from "../../src/family/dispatchFamilyWorker.js";
import { cmrLegAccountingFailure } from "../../src/modelRoutes.js";
import type { ShipWorkerOutcome } from "../../src/shipOutcome.js";
import type { DispatchContext, WorkerSpec } from "../../src/types.js";

const here = dirname(fileURLToPath(import.meta.url));
const realPromptsDir = join(here, "..", "..", "prompts");
const DEFAULT_CMR_LEGS = ["opus", "gpt-5.5", "agy"] as const;
const FROZEN_NORMAL_CMR_REVIEW_LEGS = [
  { family: "codex", slug: "gpt-5.5" },
  { family: "claude", slug: "opus" },
  { family: "agy", slug: "agy" },
] as const;
const STRONG_LEGS = ["opus", "gpt-5.5"] as const;
const EMPTY_CMR_CLOSURE = {
  claimedFixedFindingIdentityKeys: [],
  priorFindingDispositions: [],
} as const;

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
        ...EMPTY_CMR_CLOSURE,
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
        successfulLegs: ["gpt-5.5"],
        ...EMPTY_CMR_CLOSURE,
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
      expect(o.successfulLegs).toEqual(["gpt-5.5"]);
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

  it("only the LAST <cmr> tag is read (the worker may iterate)", () => {
    const o = parseCmrOutcome(
      `<cmr>{"converged": false}</cmr>\nlater…\n<cmr>${JSON.stringify({
        converged: true,
        successfulLegs: DEFAULT_CMR_LEGS,
        ...EMPTY_CMR_CLOSURE,
      })}</cmr>`,
    );
    expect(o.kind).toBe("verdict");
    if (o.kind === "verdict") expect(o.converged).toBe(true);
  });

  it("no <cmr> tag ⇒ malformed (never silently a pass)", () => {
    const o = parseCmrOutcome("I reviewed everything, looks fine.");
    expect(o.kind).toBe("malformed");
  });

  it("a non-JSON / non-object <cmr> body ⇒ malformed (never a pass)", () => {
    expect(parseCmrOutcome("<cmr>not json</cmr>").kind).toBe("malformed");
    expect(parseCmrOutcome("<cmr>null</cmr>").kind).toBe("malformed");
    expect(parseCmrOutcome("<cmr>true</cmr>").kind).toBe("malformed");
  });

  it("a <cmr> object with no boolean converged and no escalate ⇒ malformed", () => {
    expect(parseCmrOutcome('<cmr>{"foo": 1}</cmr>').kind).toBe("malformed");
  });

  // ── Finding A (integ-cmr int-r1): STRICT shape, mirroring shipOutcome ─────────
  // Integrated CMR pass prompts: "must match one of the shapes above exactly". A mixed /
  // extra-key / garbage payload must NOT coerce into a pass — fail-CLOSED.
  describe("Finding A — strict shape (no extra/mixed keys, non-empty verdict fields)", () => {
    it("a mixed converged+escalate payload ⇒ malformed (not a pass)", () => {
      // A success key carried ALONGSIDE an escalate verdict is off-contract — it
      // must NOT slip through to a converged pass.
      expect(
        parseCmrOutcome(
          '<cmr>{"converged": true, "escalate": {"reason": "r", "diagnosis": "d"}}</cmr>',
        ).kind,
      ).toBe("malformed");
    });

    it("converged:true carrying an EXTRA key ⇒ malformed (strict)", () => {
      expect(
        parseCmrOutcome(
          '<cmr>{"converged": true, "successfulLegs": ["opus"], "junk": 1}</cmr>',
        ).kind,
      ).toBe(
        "malformed",
      );
    });

    it("converged:true may carry explicit prior-finding closure dispositions", () => {
      const o = parseCmrOutcome(
        `<cmr>${JSON.stringify({
          converged: true,
          successfulLegs: DEFAULT_CMR_LEGS,
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
          claimedFixedFindingIdentityKeys: [],
          priorFindingDispositions: [],
        })}</cmr>`,
      );

      expect(o.kind).toBe("verdict");
      if (o.kind === "verdict") {
        expect(o.claimedFixedFindingIdentityKeys).toEqual([]);
        expect(o.priorFindingDispositions).toEqual([]);
      }
    });

    it("converged:true without closure arrays ⇒ malformed (absence is not closure)", () => {
      expect(
        parseCmrOutcome(
          `<cmr>${JSON.stringify({
            converged: true,
            successfulLegs: DEFAULT_CMR_LEGS,
          })}</cmr>`,
        ).kind,
      ).toBe("malformed");
    });

    it("converged:false WITHOUT a reason ⇒ malformed (the contract requires the one-line reason)", () => {
      expect(parseCmrOutcome('<cmr>{"converged": false}</cmr>').kind).toBe("malformed");
    });

    it("converged:false with a BLANK reason ⇒ malformed (non-empty required)", () => {
      expect(
        parseCmrOutcome(
          '<cmr>{"converged": false, "reason": "  ", "successfulLegs": ["opus"]}</cmr>',
        ).kind,
      ).toBe(
        "malformed",
      );
    });

    it("a garbage escalate (blank reason/diagnosis) ⇒ malformed (not a coerced escalate)", () => {
      expect(
        parseCmrOutcome('<cmr>{"escalate": {"reason": "", "diagnosis": ""}}</cmr>').kind,
      ).toBe("malformed");
      expect(parseCmrOutcome('<cmr>{"escalate": {}}</cmr>').kind).toBe("malformed");
    });

    it("converged with a NON-boolean value ⇒ malformed", () => {
      expect(parseCmrOutcome('<cmr>{"converged": "true"}</cmr>').kind).toBe("malformed");
    });

    it("bare converged:true without successfulLegs ⇒ malformed (ADR0032 floor needs leg truth)", () => {
      expect(parseCmrOutcome('<cmr>{"converged": true}</cmr>').kind).toBe("malformed");
    });

    it("omitted skippedLegs is valid only when every default cmr leg succeeded", () => {
      expect(
        parseCmrOutcome(
          `<cmr>${JSON.stringify({
            converged: true,
            successfulLegs: DEFAULT_CMR_LEGS,
            ...EMPTY_CMR_CLOSURE,
          })}</cmr>`,
        ).kind,
      ).toBe("verdict");
      expect(parseCmrOutcome('<cmr>{"converged": true, "successfulLegs": ["opus"]}</cmr>').kind).toBe(
        "malformed",
      );
    });

    it("accounts against the active route's declared cmr legs, not the default route", () => {
      vi.stubEnv("ORCHESTRATOR_ROUTE", "claude-tight");

      const o = parseCmrOutcome(
        `<cmr>${JSON.stringify({
          converged: true,
          successfulLegs: ["gpt-5.5", "agy"],
          ...EMPTY_CMR_CLOSURE,
        })}</cmr>`,
      );

      expect(o).toEqual({
        kind: "verdict",
        converged: true,
        successfulLegs: ["gpt-5.5", "agy"],
        ...EMPTY_CMR_CLOSURE,
      });
    });

    it("rejects successful legs that were not declared by the active route", () => {
      vi.stubEnv("ORCHESTRATOR_ROUTE", "claude-tight");

      expect(
        parseCmrOutcome(
          `<cmr>${JSON.stringify({
            converged: true,
            successfulLegs: ["agy", "opus"],
            ...EMPTY_CMR_CLOSURE,
            skippedLegs: [{ slug: "gpt-5.5", reason: "auth unavailable" }],
          })}</cmr>`,
        ).kind,
      ).toBe("malformed");
    });

    it("rejects skipped legs that were not declared by the active route", () => {
      vi.stubEnv("ORCHESTRATOR_ROUTE", "claude-tight");

      expect(
        parseCmrOutcome(
          `<cmr>${JSON.stringify({
            converged: true,
            successfulLegs: ["gpt-5.5", "agy"],
            ...EMPTY_CMR_CLOSURE,
            skippedLegs: [{ slug: "opus", reason: "auth unavailable" }],
          })}</cmr>`,
        ).kind,
      ).toBe("malformed");
    });

    it("accepts a single surviving default leg only when the other declared legs are skipped", () => {
      const o = parseCmrOutcome(
        `<cmr>${JSON.stringify({
          converged: true,
          successfulLegs: ["opus"],
          ...EMPTY_CMR_CLOSURE,
          skippedLegs: [
            { slug: "gpt-5.5", reason: "auth unavailable" },
            { slug: "agy", reason: "quota exhausted" },
          ],
        })}</cmr>`,
      );
      expect(o.kind).toBe("verdict");
      if (o.kind === "verdict") {
        expect(o.successfulLegs).toEqual(["opus"]);
        expect(o.skippedLegs).toEqual([
          { slug: "gpt-5.5", reason: "auth unavailable" },
          { slug: "agy", reason: "quota exhausted" },
        ]);
      }
    });

    it("a declared leg cannot be both successful and skipped", () => {
      expect(
        parseCmrOutcome(
          `<cmr>${JSON.stringify({
            converged: true,
            successfulLegs: DEFAULT_CMR_LEGS,
            ...EMPTY_CMR_CLOSURE,
            skippedLegs: [{ slug: "agy", reason: "quota exhausted" }],
          })}</cmr>`,
        ).kind,
      ).toBe("malformed");
    });

    it("still accepts the two LEGAL verdict shapes (regression)", () => {
      expect(
        parseCmrOutcome(
          `<cmr>${JSON.stringify({
            converged: true,
            successfulLegs: DEFAULT_CMR_LEGS,
            ...EMPTY_CMR_CLOSURE,
          })}</cmr>`,
        ).kind,
      ).toBe("verdict");
      expect(
        parseCmrOutcome(
          `<cmr>${JSON.stringify({
            converged: false,
            reason: "seam mismatch",
            successfulLegs: ["gpt-5.5"],
            ...EMPTY_CMR_CLOSURE,
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
    "integrated_cmr.md",
    "integrated_cmr_completeness.md",
    "integrated_cmr_correctness.md",
  ]) {
    it(`${promptName} requires closure arrays on converged output`, () => {
      const prompt = readFileSync(join(realPromptsDir, promptName), "utf8");

      expect(prompt).toContain("claimedFixedFindingIdentityKeys");
      expect(prompt).toContain("priorFindingDispositions");
      expect(prompt).toMatch(/empty arrays/i);
    });

    it(`${promptName} not-converged example accounts for every declared leg`, () => {
      const prompt = readFileSync(join(realPromptsDir, promptName), "utf8");
      const examples = [...prompt.matchAll(/<cmr>(\{[^\n]*"converged": false[^\n]*\})<\/cmr>/g)];

      expect(examples.length).toBeGreaterThan(0);
      for (const [, rawJson] of examples) {
        const output = JSON.parse(rawJson) as {
          readonly successfulLegs: readonly string[];
          readonly skippedLegs?: readonly { readonly slug: string; readonly reason: string }[];
        };

        expect(cmrLegAccountingFailure(output)).toBeUndefined();
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

// ═══════════════════════ 2. cmrOutcomeFromResult (signal gate) ═══════════════════════

describe("#335 cmrOutcomeFromResult — completion-signal gate (mirrors the merger gate)", () => {
  const SIGNAL = cmrWorkerSpec().completionSignal;

  it("a signaled converged run ⇒ a verdict outcome", () => {
    const o = cmrOutcomeFromResult({
      completionSignal: SIGNAL,
      stdout: `<cmr>${JSON.stringify({
        converged: true,
        successfulLegs: DEFAULT_CMR_LEGS,
        ...EMPTY_CMR_CLOSURE,
      })}</cmr>`,
    });
    expect(o.kind).toBe("verdict");
    if (o.kind === "verdict") expect(o.converged).toBe(true);
  });

  it("an UNSIGNALED run ⇒ escalate (a complete-but-unsignaled run is NOT a pass)", () => {
    const o = cmrOutcomeFromResult({
      completionSignal: undefined,
      stdout: `<cmr>${JSON.stringify({
        converged: true,
        successfulLegs: DEFAULT_CMR_LEGS,
        ...EMPTY_CMR_CLOSURE,
      })}</cmr>`,
    });
    expect(o.kind).toBe("escalate");
  });

  it("a wrong-signal run ⇒ escalate", () => {
    const o = cmrOutcomeFromResult({
      completionSignal: "SOME_OTHER_SIGNAL",
      stdout: `<cmr>${JSON.stringify({
        converged: true,
        successfulLegs: DEFAULT_CMR_LEGS,
        ...EMPTY_CMR_CLOSURE,
      })}</cmr>`,
    });
    expect(o.kind).toBe("escalate");
  });

  it("accounts worker verdict legs against the frozen worker route, not later process env", () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "normal");
    const result = {
      completionSignal: SIGNAL,
      cmrReviewLegs: FROZEN_NORMAL_CMR_REVIEW_LEGS,
      stdout: `<cmr>${JSON.stringify({
        converged: true,
        successfulLegs: DEFAULT_CMR_LEGS,
        ...EMPTY_CMR_CLOSURE,
      })}</cmr>`,
    };
    vi.stubEnv("ORCHESTRATOR_ROUTE", "claude-tight");

    const o = cmrOutcomeFromResult(result);

    expect(o).toEqual({
      kind: "verdict",
      converged: true,
      successfulLegs: DEFAULT_CMR_LEGS,
      ...EMPTY_CMR_CLOSURE,
    });
  });
});

// ═══════════════════ 3. dispatchWorker(cmr) — routes the skill + wraps verdict ═══════════════════

describe("#335 RealFamilyBackend.dispatchWorker — the cmr worker", () => {
  /** A backend whose container `runCmrWorker` seam is fixtured (no real sc.run). */
  class FixturedCmrBackend extends RealFamilyBackend {
    runCmrCalls: { spec: ReturnType<typeof cmrWorkerSpec>; ctx: DispatchContext }[] = [];
    runShipCalls: { spec: WorkerSpec; ctx: DispatchContext }[] = [];
    outcome: CmrWorkerOutcome = {
      kind: "verdict",
      converged: true,
      successfulLegs: STRONG_LEGS,
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
    // (the pre-#336 version relied on the legacy openFamilyPr `git push` throwing,
    // which is now both stale and host-fragile — cmr S336 r9).
    protected override async runShipWorker(
      spec: WorkerSpec,
      ctx: DispatchContext,
    ): Promise<ShipWorkerOutcome> {
      this.runShipCalls.push({ spec, ctx });
      return { kind: "shipped", branch: ctx.familyBase!, status: "pr_opened", pr: "https://gh/pr/9" };
    }
    protected override verifyFamilyShipPr(): { ok: true; headOid: string } | { ok: false; reason: string } {
      return { ok: true, headOid: "head-1" };
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
      imageName: "ming-orchestrator-coder:latest",
    });
  }

  it("dispatches the cmr pass worker spec to runCmrWorker — ak-cross-m-review + FRESH session + write-capable cmr soul", async () => {
    const be = fixtured();
    await be.dispatchWorker(cmrWorkerSpec(), { familyBase: "feat/330-pure-scheduler" });
    expect(be.runCmrCalls.length).toBe(1);
    const spec = be.runCmrCalls[0]!.spec;
    expect(spec.kind).toBe("cmr");
    expect(spec.skill).toBe("ak-cross-m-review");
    // FRESH session = a new pass-worker session, not a crash/escalate resume.
    expect(spec.session).toBe("fresh");
    // The pass worker can retain context while producing its terminal verdict, under
    // the WRITE-capable `cmr` soul.
    expect(spec.contextRetention).toBe("retain");
    expect(spec.soul).toBe("cmr");
  });

  it("a converged verdict ⇒ WorkerResult.completed with a bare cmr payload", async () => {
    const be = fixtured();
    be.outcome = { kind: "verdict", converged: true, successfulLegs: STRONG_LEGS };
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

  it("an escalate outcome ⇒ WorkerResult.escalated (model-stuck, not a verdict)", async () => {
    const be = fixtured();
    be.outcome = { kind: "escalate", reason: "skill missing", diagnosis: "not on PATH" };
    const res = await be.dispatchWorker(cmrWorkerSpec(), { familyBase: "fb" });
    expect(res.kind).toBe("escalated");
    if (res.kind === "escalated") {
      expect(res.escalation.reason).toContain("skill missing");
    }
  });

  it("a malformed outcome ⇒ WorkerResult.malformed (never silently a pass)", async () => {
    const be = fixtured();
    be.outcome = { kind: "malformed", reason: "no <cmr> tag" };
    const res = await be.dispatchWorker(cmrWorkerSpec(), { familyBase: "fb" });
    expect(res.kind).toBe("malformed");
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
    be.outcome = { kind: "verdict", converged: true, successfulLegs: STRONG_LEGS };
    const res = await be.dispatchWorker(familyShipWorkerSpec(), { familyBase: "fb" });
    expect(res.kind).toBe("completed"); // the fixtured ship outcome, not the cmr path
    expect(be.runShipCalls.length).toBe(1); // reached the ship worker seam
    expect(be.runCmrCalls.length).toBe(0); // the cmr worker seam was NOT touched
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

    // ALL auth absent ⇒ zero mounts, only the soul env — still no throw (the skill
    // runs and will degrade/escalate in-container, never a host crash).
    const none = cfgBackend().config({});
    expect(none.mounts.length).toBe(0);
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
      { family: "codex", slug: "gpt-5.5" },
      { family: "claude", slug: "opus" },
      { family: "agy", slug: "agy" },
    ]);
  });

  it("exports frozen CMR legs from the worker spec, not later route env", () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "normal");
    const spec = cmrWorkerSpec("fresh", "correctness");
    vi.stubEnv("ORCHESTRATOR_ROUTE", "claude-tight");
    const cfg = cfgBackend().config(auth, spec);
    const legs = JSON.parse(cfg.env.ORCHESTRATOR_CMR_REVIEW_LEGS ?? "null") as unknown;

    expect(legs).toEqual([
      { family: "codex", slug: "gpt-5.5" },
      { family: "claude", slug: "opus" },
      { family: "agy", slug: "agy" },
    ]);
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
      claudeToken: undefined,
      ghToken: undefined,
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
        'model = "gpt-5.5"',
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

  it("writes the route file pass from dispatch context, not the prompt filename", () => {
    const repo = realRepo();
    const be = new FocusBackend({
      workingRepo: repo,
      familyBase: "feat/330-pure-scheduler",
      ledgerDir: mkDir("cmr-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
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
      imageName: "img",
      familyBaseStartHead: "abc123",
    });

    be.routeFile("correctness");

    const route = JSON.parse(readFileSync(join(repo, CMR_ROUTE_FILENAME), "utf8")) as unknown;
    expect(route).toEqual({
      pass: "correctness",
      reviewLegs: [
        { family: "codex", slug: "gpt-5.5" },
        { family: "claude", slug: "opus" },
        { family: "agy", slug: "agy" },
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
      imageName: "img",
      familyBaseStartHead: "abc123",
    });

    be.routeFileFromSpec("correctness", spec);

    const route = JSON.parse(readFileSync(join(repo, CMR_ROUTE_FILENAME), "utf8")) as {
      reviewLegs: unknown;
    };
    expect(route.reviewLegs).toEqual([
      { family: "codex", slug: "gpt-5.5" },
      { family: "claude", slug: "opus" },
      { family: "agy", slug: "agy" },
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
      imageName: "img",
      // no familyBaseStartHead
    });
    const res = await be.dispatchWorker(cmrWorkerSpec(), { familyBase: "fb" });
    expect(res.kind).toBe("escalated");
    if (res.kind === "escalated") {
      expect(res.escalation.reason).toMatch(/familyBaseStartHead|cut SHA/i);
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
      imageName: "img",
      familyBaseStartHead: "abc123",
    });
    const outcome = await be.run(cmrWorkerSpec(), { familyBase: "fb" });
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
      imageName: "img",
      familyBaseStartHead: "abc123",
    });
    const res = await be.dispatchWorker(cmrWorkerSpec(), { familyBase: "fb" });
    expect(res.kind).toBe("escalated");
  });
});

function realRepo335(): string {
  const repo = mkDir("cmr-guard-repo-");
  execFileSync("git", ["init", "-q"], { cwd: repo });
  return repo;
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

  it("the early no-claude-auth escalate still removes the codex + agy temp dirs", async () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "normal");
    const codexDir = mkDir("reclaim-codex-");
    const agyDir = mkDir("reclaim-agy-");
    expect(existsSync(codexDir)).toBe(true);
    expect(existsSync(agyDir)).toBe(true);

    const be = new ReclaimBackend(
      {
        workingRepo: realRepo335(),
        familyBase: "fb",
        ledgerDir: mkDir("cmr-ledger-"),
        repo: "Akagilnc/ming-salvage-sim",
        base: "main",
        promptsDir: realPromptsDir,
        imageName: "img",
        familyBaseStartHead: "abc123",
      },
      { codexAuthDir: codexDir, agyDir }, // no claudeToken ⇒ early escalate
    );

    const outcome = await be.run(cmrWorkerSpec(), { familyBase: "fb" });
    expect(outcome.kind).toBe("escalate");
    // The finally reclaimed BOTH per-run dirs even though sc.run never ran.
    expect(existsSync(codexDir)).toBe(false);
    expect(existsSync(agyDir)).toBe(false);
  });

  it("the successful container path removes the temporary outcome sidecar directory", async () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "normal");
    const repo = realRepo335();
    execFileSync("git", ["config", "user.email", "t@t.t"], { cwd: repo });
    execFileSync("git", ["config", "user.name", "t"], { cwd: repo });
    execFileSync("git", ["commit", "--allow-empty", "-q", "-m", "root"], { cwd: repo });
    execFileSync("git", ["checkout", "-b", "fb"], { cwd: repo });
    let outcomePathAtRun: string | undefined;
    class OutcomeCleanupBackend extends RealFamilyBackend {
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
        writeFileSync(
          outcomePathAtRun,
          JSON.stringify({
            escalate: { reason: "review unavailable", diagnosis: "synthetic test verdict" },
          }),
          "utf8",
        );
        return {
          completionSignal: "CMR_STEP_COMPLETE",
          stdout: "<cmr>{}</cmr>",
        } as Awaited<ReturnType<typeof sc.run>>;
      }
    }
    const be = new OutcomeCleanupBackend({
      workingRepo: repo,
      familyBase: "fb",
      ledgerDir: mkDir("cmr-outcome-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      imageName: "img",
      familyBaseStartHead: "abc123",
    });

    const outcome = await be.run(cmrWorkerSpec(), { familyBase: "fb", cmrPass: "completeness" });

    expect(outcome.kind).toBe("escalate");
    expect(outcomePathAtRun).toBeDefined();
    expect(existsSync(dirname(outcomePathAtRun as string))).toBe(false);
  });
});

// ═══════════════════ 5. deleted-fanout regression ═══════════════════

describe("#335 the runner-internal 3-CLI 手搓 is DELETED", () => {
  it("familyDriver no longer exports the 3-leg reviewer fan-out symbols", async () => {
    const mod = await import("../../src/familyDriver.js");
    const m = mod as Record<string, unknown>;
    expect(m.DriverFamilyBackend).toBeUndefined();
    expect(m.reviewerPrompt).toBeUndefined();
    expect(m.parseReviewerVerdict).toBeUndefined();
    expect(m.aggregateCmr).toBeUndefined();
    expect(m.reviewerLegFromOutput).toBeUndefined();
  });
});
