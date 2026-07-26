import {
  describe,
  expect,
  it,
  vi,
  mkdtempSync,
  writeFileSync,
  existsSync,
  readFileSync,
  tmpdir,
  join,
  execFileSync,
  runFamily,
  cmrWorkerSpec,
  familyShipWorkerSpec,
  QuotaWaitForResetError,
  DEFAULT_PARK_THRESHOLD_MS,
  CoderRecError,
  applyRelayBatonToRoute,
  familyRelaySlotsForWall,
  resolveActiveModelRoute,
  ResolvedModelRoute,
  Backend,
  IssueMeta,
  PersistentLedgerEntry,
  StepOutput,
  StepSpec,
  WorktreeHandle,
  FamilyBackend,
  FamilyEpic,
  FamilyLedgerEntry,
  MergeRequest,
  buildExplicitLandingLiveHooks,
  CODER_REC_BODY,
  BROKEN_CODER_REC_BODY,
  makeRepo,
  ChildBackend,
  FakeFamilyBackend,
  epicWith,
  quotaWaitError,
  liveBatonRelayPools,
  allDeadRelayPools,
  stubGrokCmrPreset,
} from "./quota-park.shared.js";

describe("#909 family runner consumes QuotaWait park/relay at verify boundary", () => {

  it("pure apply: family slots rewrite cmr/ship; single-slice S7 still only coder", () => {
    const route = resolveActiveModelRoute();
    const baton = { slug: "gpt-5.6-terra" };
    // N2: S3 requires cmrPass — only the hit pass slot is rewritten.
    const wallSlots = familyRelaySlotsForWall({
      phase: "final",
      wallStep: "S3",
      cmrPass: "completeness",
    });
    expect(wallSlots).toEqual(["cmrCompleteness"]);

    const familyApplied = applyRelayBatonToRoute(route, baton, "S3", {
      slots: wallSlots,
    });
    expect(familyApplied.slots.cmrCompleteness).toBe("gpt-5.6-terra");
    // correctness slot must stay on the route preset (not polluted by completeness wall).
    expect(familyApplied.slots.cmrCorrectness).toBe(route.slots.cmrCorrectness);
    // coder may already be terra on normal — not the proof surface
    expect(familyApplied.slots.ship).toBe(route.slots.ship);

    const shipApplied = applyRelayBatonToRoute(route, baton, "S7", {
      slots: familyRelaySlotsForWall({ phase: "final", wallStep: "S7" }),
    });
    expect(shipApplied.slots.ship).toBe("gpt-5.6-terra");
    expect(shipApplied.slots.cmrCompleteness).toBe(route.slots.cmrCompleteness);

    // Single-slice S7 (no slots opt) still uses coder map — not ship.
    const singleSlice = applyRelayBatonToRoute(route, baton, "S7");
    expect(singleSlice.slots.coder).toBe("gpt-5.6-terra");
    expect(singleSlice.slots.ship).toBe(route.slots.ship);
  });

  it("N2: S3 without cmrPass refuses dual CMR rewrite; correctness pass is single-slot", () => {
    expect(() =>
      familyRelaySlotsForWall({ phase: "final", wallStep: "S3" }),
    ).toThrow(/cmrPass|refusing to rewrite both/i);

    expect(
      familyRelaySlotsForWall({
        phase: "final",
        wallStep: "S3",
        cmrPass: "correctness",
      }),
    ).toEqual(["cmrCorrectness"]);
  });

  it("C1: endgame wall steps map to real consume slots (not S7/ship)", () => {
    expect(
      familyRelaySlotsForWall({ phase: "online_review", wallStep: "S9" }),
    ).toEqual(["verify"]);
    expect(
      familyRelaySlotsForWall({ phase: "online_review", wallStep: "S10" }),
    ).toEqual(["fixer"]);
    expect(
      familyRelaySlotsForWall({ phase: "online_review", wallStep: "S12" }),
    ).toEqual(["landing"]);
    expect(
      familyRelaySlotsForWall({ phase: "online_review", wallStep: "S13" }),
    ).toEqual(["collector"]);
    expect(familyRelaySlotsForWall({ phase: "merge", wallStep: "S1" })).toEqual(
      ["merger"],
    );
    // Phase fallback must not rewrite ship for online-review.
    expect(
      familyRelaySlotsForWall({
        phase: "online_review",
        wallStep: "S0",
      }),
    ).toEqual(["verify"]);
  });

  it("C1 pure: familyWallStepFromQuotaWait keeps S9 (isStepId alone would drop it)", async () => {
    const { familyWallStepFromQuotaWait } = await import(
      "../../../src/family/runner.js"
    );
    const { isStepId } = await import("../../../src/types.js");
    const resetAt = new Date("2026-07-14T14:00:00.000Z");
    const err = quotaWaitError({ resetAt, pool: "grok", step: "S9" });
    // Precondition: SliceStepId guard rejects S9 (the bug root).
    expect(isStepId("S9")).toBe(false);
    expect(familyWallStepFromQuotaWait({ err, phase: "online_review" })).toBe(
      "S9",
    );
    expect(
      familyRelaySlotsForWall({
        phase: "online_review",
        wallStep: familyWallStepFromQuotaWait({ err, phase: "online_review" }),
      }),
    ).toEqual(["verify"]);
    // Default when step missing: online_review → S9 (not S7/ship).
    const errNoStep = quotaWaitError({ resetAt, pool: "grok", step: "S3" });
    // Valid error first, then strip step without audit-trigger cast (#982).
    const bare = new QuotaWaitForResetError({
      disposition: errNoStep.disposition,
      applied: {
        ledgerEntry: { ...errNoStep.applied.ledgerEntry! },
      },
      pool: errNoStep.pool,
    });
    Reflect.deleteProperty(bare.applied.ledgerEntry!, "step");
    expect(
      familyWallStepFromQuotaWait({ err: bare, phase: "online_review" }),
    ).toBe("S9");
  });

  it("C1 pure: correctness_checkpoint bare step → S3 CMR (not S7/ship, not verify-only S9)", async () => {
    // #961 CR R2 + #982 Codex P2: phase default must not fall through to S7/ship.
    // Checkpoint baton must rewrite cmrCorrectness — S9 hard-maps to verify and
    // would leave the quota-limited CMR slot unchanged when step is lost.
    const { familyWallStepFromQuotaWait } = await import(
      "../../../src/family/runner.js"
    );
    const resetAt = new Date("2026-07-14T14:00:00.000Z");
    const errNoStep = quotaWaitError({ resetAt, pool: "grok", step: "S3" });
    const bare = new QuotaWaitForResetError({
      disposition: errNoStep.disposition,
      applied: {
        ledgerEntry: { ...errNoStep.applied.ledgerEntry! },
      },
      pool: errNoStep.pool,
    });
    bare.cmrPass = "correctness";
    Reflect.deleteProperty(bare.applied.ledgerEntry!, "step");
    const wallStep = familyWallStepFromQuotaWait({
      err: bare,
      phase: "correctness_checkpoint",
    });
    expect(wallStep).toBe("S3");
    expect(wallStep).not.toBe("S7");
    expect(wallStep).not.toBe("S9");
    const slots = familyRelaySlotsForWall({
      phase: "correctness_checkpoint",
      wallStep,
      cmrPass: "correctness",
    });
    expect(slots).toEqual(["cmrCorrectness"]);
    expect(slots).not.toContain("ship");
    expect(slots).not.toContain("verify");
    // Defense in depth: legacy S9 stamp under checkpoint phase still CMR.
    expect(
      familyRelaySlotsForWall({
        phase: "correctness_checkpoint",
        wallStep: "S9",
        cmrPass: "correctness",
      }),
    ).toEqual(["cmrCorrectness"]);
  });

});
