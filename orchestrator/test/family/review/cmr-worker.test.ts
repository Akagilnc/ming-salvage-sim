import {
  execFileSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
  tmpdir,
  dirname,
  join,
  fileURLToPath,
  afterEach,
  describe,
  expect,
  it,
  vi,
  sc,
  RunResult,
  docker,
  CMR_ROUTE_FILENAME,
  CMR_FOCUS_FILENAME,
  cmrOutcomeFromResult,
  parseCmrOutcome,
  RealFamilyBackend,
  SANDBOX_AGY_DIR,
  CmrAuth,
  CmrWorkerOutcome,
  ShipAuth,
  DECISION_GATE_TAG,
  decisionGateSignalSchema,
  isReceiptRecoveryFailure,
  RECEIPT_MAX_RETRIES,
  workerReceiptSchema,
  CODER_RECEIPT_TAG,
  coderStationReceiptSchema,
  MAX_DISPATCH_ATTEMPTS,
  withMechanicalRetry,
  runScriptedStructuredOutput,
  ScriptedAgent,
  SANDBOX_CODEX_DIR,
  SANDBOX_GH_TOKEN_ENV,
  SANDBOX_GROK_DIR,
  SANDBOX_REPO_ENV,
  SPAWNED_WORKER_ENV,
  cmrWorkerSpec,
  familyCoderFixWorkerSpec,
  familyShipWorkerSpec,
  shipOutcomeFromResult,
  isRunnerSynthesizedFailureEscalation,
  DispatchContext,
  WorkerLandingPayload,
  WorkerResult,
  WorkerSpec,
  buildExplicitLandingLiveHooks,
  realPromptsDir,
  realSoulsDir,
  DEFAULT_CMR_LEGS,
  FROZEN_NORMAL_CMR_REVIEW_LEGS,
  STRONG_LEGS,
  EMPTY_CMR_CLOSURE,
  CMR_EVIDENCE_PATHS,
  CMR_EVIDENCE,
  VALID_CMR_VERDICT_FIELDS,
  DERIVED_EMPTY_FINDINGS_COUNT,
  sandboxRunResult,
  typedSandboxRunResult,
  cleanups,
  mkDir,
  makeBackend,
  realRepo335,
  legacyClaudeCmrSpec,
} from "./cmr-worker.shared.js";

afterEach(() => {
  vi.unstubAllEnvs();
  while (cleanups.length > 0) {
    const p = cleanups.pop();
    if (p !== undefined) rmSync(p, { recursive: true, force: true });
  }
});

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

// ═══════════════════════ 2. cmrOutcomeFromResult (structured outcome) ═══════════════════════

describe("#335 cmrOutcomeFromResult — structured outcome parsing", () => {
  it("a clean-exit typed/stdout verdict parses without any STEP_COMPLETE password", () => {
    const o = cmrOutcomeFromResult({
      stdout: `<cmr>${JSON.stringify({
        converged: true,
        successfulLegs: DEFAULT_CMR_LEGS,
        ...VALID_CMR_VERDICT_FIELDS,
      })}</cmr>\nfindings = 0\n`,
    });
    expect(o.kind).toBe("verdict");
    if (o.kind === "verdict") expect(o.converged).toBe(true);
  });

  it("typed Output.object is the fate channel when present (#928 no signal gate)", () => {
    const o = cmrOutcomeFromResult({
      output: {
        converged: true,
        successfulLegs: DEFAULT_CMR_LEGS,
        ...VALID_CMR_VERDICT_FIELDS,
      },
      stdout: "noise without password",
    });
    expect(o.kind).toBe("verdict");
  });

  it("keeps continue traffic typed when the family judge adds soft reason cargo (#1034)", () => {
    const o = cmrOutcomeFromResult({
      output: {
        station: "judge",
        status: "continue",
        findingDispositions: [{ identityKey: "live-1034", action: "live" }],
        fixPacketBody: "repair the live finding",
        reason: "one live completeness finding remains",
        findingsCount: 1,
      },
      stdout: "noise without completion signal",
    });

    expect(o).toMatchObject({
      kind: "judge",
      status: "continue",
      findingDispositions: [{ identityKey: "live-1034", action: "live" }],
      fixPacketBody: "repair the live finding",
    });
  });

  it("rejects converged judge traffic carrying continue-only repair instructions", () => {
    const o = cmrOutcomeFromResult({
      output: {
        station: "judge",
        status: "converged",
        findingDispositions: [{ identityKey: "still-live", action: "live" }],
        fixPacketBody: "repair the still-live finding",
      },
    });

    expect(o).toEqual({
      kind: "verdict",
      successfulLegs: [],
      evidencePaths: [],
    });
  });

  it("accounts worker verdict legs against the frozen worker route, not later process env", () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "normal");
    const result = {
      cmrReviewLegs: FROZEN_NORMAL_CMR_REVIEW_LEGS,
      // #899: findingsCount lives on the typed Output.object receipt only.
      output: {
        converged: true,
        findingsCount: 0,
        successfulLegs: DEFAULT_CMR_LEGS,
        ...VALID_CMR_VERDICT_FIELDS,
      },
      stdout: "findings = 99\n",
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
  resolveLandingLiveHooks(input: {
    prUrl: string;
    convergedHeadOid: string;
    familyBase: string;
  }) {
    return buildExplicitLandingLiveHooks({
      prUrl: input.prUrl,
      headOid: input.convergedHeadOid,
      remoteBranchName: input.familyBase,
    });
  }

    runCmrCalls: { spec: ReturnType<typeof cmrWorkerSpec>; ctx: DispatchContext }[] = [];
    runCoderFixCalls: { spec: WorkerSpec; ctx: DispatchContext }[] = [];
    runShipCalls: { spec: WorkerSpec; ctx: DispatchContext }[] = [];
    // #919 M1/M2 / #930: default Fixtured happy path is live T2 judge green.
    // Residual kind:verdict without open-count is unusable (never silent clean).
    outcome: CmrWorkerOutcome = {
      kind: "judge",
      status: "converged",
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
      return { kind: "shipped", branch: ctx.familyBase!, status: "pr_opened", pr: "https://github.com/test/repo/pull/9" };
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
    expect(spec.skill).toBeUndefined();
    expect(spec.promptFile).toBe("integrated_cmr_correctness.md");
    // FRESH session = a new pass-worker session, not a crash/escalate resume.
    expect(spec.session).toBe("fresh");
    // The pass worker is a clean reviewer boundary; blocking findings return to the
    // runner, which dispatches a separate coder-fix worker.
    expect(spec.contextRetention).toBe("clean");
    // #919 S2: family CMR pass seat identity is verify (kind stays cmr).
    expect(spec.role).toBe("verify");
    expect(spec.maxIter).toBe(1);
    expect(spec.soul).toBe("verify");
  });

  it("rejects malformed decision-gate and open-count receipts at the Sandcastle schema seam", () => {
    // #899 Testing Decisions: recovery/exhaust sequences are SO schema + maxRetries.
    // These safeParse cases are the exact validation Sandcastle runs on each emission.
    const openCount = workerReceiptSchema();
    const decision = decisionGateSignalSchema;
    // First (malformed) emission would force a same-session re-ask.
    expect(openCount.safeParse({ findings: [] }).success).toBe(false);
    expect(openCount.safeParse({ findingsCount: -1 }).success).toBe(false);
    expect(decision.safeParse({ escalate: { reason: "", diagnosis: "" } }).success).toBe(false);
    expect(decision.safeParse({ escalate: { reason: "r" } }).success).toBe(false);
    // Recovered second emission succeeds.
    expect(openCount.safeParse({ findingsCount: 0, findings: [] }).success).toBe(true);
    expect(
      decision.safeParse({
        escalate: { reason: "owner choice", diagnosis: "contract fork" },
      }).success,
    ).toBe(true);
    expect(decision.safeParse({}).success).toBe(true);
  });

  it("rejects malformed decision gates so Sandcastle re-asks the CMR author", () => {
    // #899: empty/missing reason+diagnosis must fail the typed boundary.
    expect(workerReceiptSchema().safeParse({ escalate: {} }).success).toBe(false);
    expect(workerReceiptSchema().safeParse({
      escalate: { reason: "owner decision", diagnosis: "design fork" },
    }).success).toBe(true);
    // Legal findingsCount must not mask a present-but-malformed decision gate.
    expect(workerReceiptSchema().safeParse({
      findingsCount: 2,
      escalate: { reason: "", diagnosis: "x" },
    }).success).toBe(false);
    expect(workerReceiptSchema().safeParse({
      findingsCount: 2,
      escalate: { reason: "owner decision", diagnosis: "design fork" },
    }).success).toBe(true);
    // Near-miss spellings of escalate are opaque cargo — no approximate match.
    expect(workerReceiptSchema().safeParse({
      findingsCount: 0,
      escalte: { reason: "typo", diagnosis: "key" },
    }).success).toBe(true);
    expect(workerReceiptSchema().safeParse({
      findingsCount: 1,
      escalatee: { reason: "near-miss", diagnosis: "not a gate" },
    }).success).toBe(true);
  });

  it("keeps opaque evidence cargo on an otherwise typed CMR verdict", () => {
    // #899: only findingsCount is typed; legs/evidence are cargo passthrough.
    expect(workerReceiptSchema().safeParse({
      findingsCount: 0,
      evidencePaths: ["cmr/review.json"],
    }).success).toBe(true);
    expect(workerReceiptSchema().safeParse({
      findingsCount: 0,
    }).success).toBe(true);
    expect(workerReceiptSchema().safeParse({
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

  it("a converged verdict ⇒ WorkerResult.completed with T2 judge converged (#930)", async () => {
    const be = fixtured();
    // Live seat green is kind:judge status:converged (not residual boolean paper).
    be.outcome = {
      kind: "judge",
      status: "converged",
      successfulLegs: STRONG_LEGS,
      ...CMR_EVIDENCE,
    };
    const res = await be.dispatchWorker(cmrWorkerSpec(), { familyBase: "fb" });
    expect(res.kind).toBe("completed");
    if (res.kind === "completed" && res.output.kind === "judge") {
      expect(res.output.status).toBe("converged");
    } else {
      throw new Error("expected completed judge payload");
    }
  });

  it("a live red judge verdict ⇒ WorkerResult.completed judge continue (NOT failed) (#930)", async () => {
    // Live seat continue is typed kind:judge — residual open-count is not a closer.
    const be = fixtured();
    be.outcome = {
      kind: "judge",
      status: "continue",
      findingDispositions: [{ identityKey: "__open_1", action: "live" as const }],
      // ADR 0138: continue requires authored body (no empty invent at projection).
      fixPacketBody: "live: __open_1 (fixture continue packet)",
      findings: [],
      successfulLegs: STRONG_LEGS,
      ...CMR_EVIDENCE,
    };
    const res = await be.dispatchWorker(cmrWorkerSpec(), { familyBase: "fb" });
    expect(res.kind).toBe("completed");
    if (res.kind === "completed" && res.output.kind === "judge") {
      expect(res.output.status).toBe("continue");
    } else {
      throw new Error("expected completed judge payload");
    }
  });

  it("residual kind:verdict never mints continue — shared unusable paper only (#919 CR S1)", async () => {
    const be = fixtured();
    be.outcome = {
      kind: "verdict",
      converged: false,
      reason: "blocking findings remain",
      findingsCount: 1,
      successfulLegs: STRONG_LEGS,
      ...CMR_EVIDENCE,
    };

    const res = await be.dispatchWorker(cmrWorkerSpec(), { familyBase: "fb" });

    // One shared fail-loud paper (kind:reviewer+findingsCount:0) — never
    // kind:cmr+findingsCount dual and never count-minted judge continue.
    expect(res).toEqual({
      kind: "completed",
      output: {
        kind: "reviewer",
        findingsCount: 0,
        findings: [],
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
    // Outcome unused for ship routing — keep live-green default (no residual paper).
    be.outcome = {
      kind: "judge",
      status: "converged",
      successfulLegs: STRONG_LEGS,
      ...CMR_EVIDENCE,
    };
    const res = await be.dispatchWorker(familyShipWorkerSpec(), { familyBase: "fb" });
    expect(res.kind).toBe("completed"); // the fixtured ship outcome, not the cmr path
    expect(be.runShipCalls.length).toBe(1); // reached the ship worker seam
    expect(be.runCmrCalls.length).toBe(0); // the cmr worker seam was NOT touched
  });
});

// ═══════════════════ 4. cmrSandboxConfig — agy auth runtime-mount + codex + claude ═══════════════════

describe("#1094 cmrSandboxConfig — pure court (judge identity only; no nested-panel armament)", () => {
  /** Expose the protected pure config seam + a canned-auth path. */
  class ConfigBackend extends RealFamilyBackend {
  resolveLandingLiveHooks(input: {
    prUrl: string;
    convergedHeadOid: string;
    familyBase: string;
  }) {
    return buildExplicitLandingLiveHooks({
      prUrl: input.prUrl,
      headOid: input.convergedHeadOid,
      remoteBranchName: input.familyBase,
    });
  }

    public config(
      auth: CmrAuth,
      spec: ReturnType<typeof cmrWorkerSpec> = cmrWorkerSpec(),
    ): {
      imageName: string;
      env: Record<string, string>;
      mounts: ReadonlyArray<{ hostPath: string; sandboxPath: string; readonly?: boolean }>;
    } {
      return this.cmrSandboxConfig(auth, {
        model: spec.model,
        soul: spec.soul,
        host: spec.host,
      });
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
    grokAuthDir: "/tmp/cmr-grok-auth",
  };

  it("injects the judge Claude token + cmr soul + ORCHESTRATOR_REPO (no nested legs)", () => {
    const cfg = cfgBackend().config(auth);
    expect(cfg.env.CLAUDE_CODE_OAUTH_TOKEN).toBe("tok-xyz");
    expect(cfg.env[SANDBOX_REPO_ENV]).toBe("Akagilnc/ming-salvage-sim");
  });

  it("mounts ONLY the judge's own family credential (codex for default gpt-5.6-sol)", () => {
    const cfg = cfgBackend().config(auth);
    expect(cfg.mounts.some((m) => m.sandboxPath === SANDBOX_CODEX_DIR)).toBe(true);
    expect(cfg.mounts.some((m) => m.sandboxPath === SANDBOX_AGY_DIR)).toBe(false);
    expect(cfg.mounts.some((m) => m.sandboxPath === SANDBOX_GROK_DIR)).toBe(false);
  });

  it("opus judge does not mount codex/agy/grok — Claude uses env token only", () => {
    const cfg = cfgBackend().config(auth, {
      ...cmrWorkerSpec(),
      model: "opus",
      host: "claude",
    });
    expect(cfg.mounts.some((m) => m.sandboxPath === SANDBOX_CODEX_DIR)).toBe(false);
    expect(cfg.mounts.some((m) => m.sandboxPath === SANDBOX_AGY_DIR)).toBe(false);
    expect(cfg.mounts.some((m) => m.sandboxPath === SANDBOX_GROK_DIR)).toBe(false);
    expect(cfg.env.CLAUDE_CODE_OAUTH_TOKEN).toBe("tok-xyz");
  });

  it("does NOT export ORCHESTRATOR_CMR_REVIEW_LEGS or CMR_CODEX_* nested-panel env", () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "normal");
    const cfg = cfgBackend().config(auth);
    expect(cfg.env.ORCHESTRATOR_CMR_REVIEW_LEGS).toBeUndefined();
    expect(cfg.env.CMR_CODEX_MODEL).toBeUndefined();
    expect(cfg.env.CMR_CODEX_EFFORT).toBeUndefined();
  });

  it("exports the gh token as GH_TOKEN so the in-container completeness gate can `gh issue view`", () => {
    const cfg = cfgBackend().config({
      claudeToken: "tok-xyz",
      ghToken: "gho_cmr",
    });
    expect(cfg.env[SANDBOX_GH_TOKEN_ENV]).toBe("gho_cmr");
  });

  it("omits GH_TOKEN when no gh token is present", () => {
    const cfg = cfgBackend().config(auth);
    expect(cfg.env[SANDBOX_GH_TOKEN_ENV]).toBeUndefined();
  });

  it("souls + home env mounts remain without credential mounts", () => {
    const none = cfgBackend().config({});
    expect(none.mounts.length).toBe(2);
    expect(none.mounts.some((m) => m.sandboxPath === "/home/agent/.orchestrator/souls")).toBe(true);
    expect(none.mounts.some((m) => m.sandboxPath === "/home/agent/.claude/CLAUDE.md")).toBe(true);
  });

  it("marks the cmr container as an orchestrator-spawned, non-interactive session", () => {
    const cfg = cfgBackend().config(auth);
    expect(cfg.env.OPENCLAW_SESSION).toBe("1");
    expect(cfg.env.OPENCLAW_SESSION).toBe(SPAWNED_WORKER_ENV.OPENCLAW_SESSION);
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
  resolveLandingLiveHooks(input: {
    prUrl: string;
    convergedHeadOid: string;
    familyBase: string;
  }) {
    return buildExplicitLandingLiveHooks({
      prUrl: input.prUrl,
      headOid: input.convergedHeadOid,
      remoteBranchName: input.familyBase,
    });
  }

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
      providerAuth: { claude: false, grok: false, agy: false },
    });
  });

  it("threads the host gh token (readGhToken) into ghToken — the completeness gate's `gh issue view` authority", () => {
    // A separate backend whose readGhToken yields a present token: mountCmrAuth must
    // wire it onto CmrAuth.ghToken (cmrSandboxConfig then exports it as GH_TOKEN).
    class GhAuthBackend extends RealFamilyBackend {
  resolveLandingLiveHooks(input: {
    prUrl: string;
    convergedHeadOid: string;
    familyBase: string;
  }) {
    return buildExplicitLandingLiveHooks({
      prUrl: input.prUrl,
      headOid: input.convergedHeadOid,
      remoteBranchName: input.familyBase,
    });
  }

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
  resolveLandingLiveHooks(input: {
    prUrl: string;
    convergedHeadOid: string;
    familyBase: string;
  }) {
    return buildExplicitLandingLiveHooks({
      prUrl: input.prUrl,
      headOid: input.convergedHeadOid,
      remoteBranchName: input.familyBase,
    });
  }

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
