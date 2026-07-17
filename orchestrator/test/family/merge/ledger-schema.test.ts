/**
 * family-ledger FULL schema + aborted events (ADR 0022 decision 5, #298).
 *
 * #293 recorded the thin `{childIssue, status:"merged"}`. #298 widens the writer
 * to the FULL event (childBranch / childHead / wave / familyHeadBefore /
 * familyHeadAfter) and adds `recordAborted` (a verify/cmr-failure event carrying
 * the family head at the time). The unblock predicate `mergedSet` still reads
 * `status === "merged"` only — so a reconcile補账条 (status:"merged" +
 * event:"reconciled") COUNTS, while an `aborted` event does NOT.
 *
 * Zero-IO: a fake FamilyBackend keeps the ledger in memory (no real git / file).
 */

import { describe, expect, it } from "vitest";
import {
  familyEscalationState,
  isFamilyLedgerEntryShape,
  mergedSet,
  parseFamilyLedgerJsonl,
  recordAborted,
  recordFamilyEscalated,
  recordFamilyEscalationAnswered,
  recordMerged,
} from "../../../src/family/ledger.js";
import type {

  FamilyBackend,
  FamilyLedgerEntry,
  MergeRequest,
} from "../../../src/family/types.js";
import { buildExplicitLandingLiveHooks } from "../../../src/family/landing.js";

class FakeFamilyBackend implements FamilyBackend {
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

  async runFamilyVerify(_req?: unknown): Promise<{ ok: boolean }> {
    return { ok: true };
  }

  readonly appended: FamilyLedgerEntry[] = [];
  async mergeChildIntoFamilyBase(_c: MergeRequest): Promise<{ familyHead: string }> {
    return { familyHead: "head" };
  }
  async resolveMergeConflict(_req?: unknown): Promise<{ familyHead: string }> {
    throw new Error("resolveMergeConflict not used in this test");
  }

  async appendFamilyLedger(entry: FamilyLedgerEntry): Promise<void> {
    this.appended.push(entry);
  }
  async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
    return this.appended;
  }
}

describe("recordMerged — full-schema event (#298)", () => {
  it("writes ALL fields when supplied (childBranch / childHead / wave / heads)", async () => {
    const backend = new FakeFamilyBackend();
    await recordMerged(backend, {
      childIssue: 10,
      childBranch: "feat/child-10",
      childHead: "c10head",
      wave: 0,
      familyHeadBefore: "base0",
      familyHeadAfter: "base1",
    });
    expect(backend.appended).toEqual([
      {
        childIssue: 10,
        status: "merged",
        childBranch: "feat/child-10",
        childHead: "c10head",
        wave: 0,
        familyHeadBefore: "base0",
        familyHeadAfter: "base1",
      },
    ]);
  });

  it("stays back-compatible: a number childIssue still writes the thin entry", async () => {
    // #293-style call (the merger before #295 fills full fields) must still work.
    const backend = new FakeFamilyBackend();
    await recordMerged(backend, 11);
    expect(backend.appended).toEqual([{ childIssue: 11, status: "merged" }]);
  });

  it("omits undefined optional fields (no `childBranch: undefined` noise)", async () => {
    const backend = new FakeFamilyBackend();
    await recordMerged(backend, { childIssue: 12, wave: 1 });
    expect(backend.appended[0]).toEqual({ childIssue: 12, status: "merged", wave: 1 });
    expect("childBranch" in backend.appended[0]!).toBe(false);
  });
});

describe("recordAborted — PHASE-LEVEL verify/cmr failure event (#291 缺口 2)", () => {
  it("writes a phase-level aborted event carrying phase / reason / family head (no childIssue)", async () => {
    const backend = new FakeFamilyBackend();
    await recordAborted(backend, {
      phase: "wave",
      reason: "tsc: TS2345 cross-slice",
      familyHeadAfter: "baseX",
    });
    expect(backend.appended).toMatchObject([
      {
        status: "aborted",
        event: "aborted",
        phase: "wave",
        reason: "tsc: TS2345 cross-slice",
        familyHeadAfter: "baseX",
        stopSummary: {
          reason: "infra_failure",
          repairHint: "inspect this aborted ledger row, repair the barrier, and rerun",
        },
      },
    ]);
    // PHASE-LEVEL: an abort is not a single child's failure → no childIssue.
    expect("childIssue" in backend.appended[0]!).toBe(false);
  });

  it("omits undefined optional fields (reason / familyHeadAfter)", async () => {
    const backend = new FakeFamilyBackend();
    await recordAborted(backend, { phase: "final" });
    expect(backend.appended[0]).toMatchObject({
      status: "aborted",
      event: "aborted",
      phase: "final",
      stopSummary: {
        reason: "infra_failure",
        repairHint: "inspect this aborted ledger row, repair the barrier, and rerun",
      },
    });
    expect("reason" in backend.appended[0]!).toBe(false);
    expect("familyHeadAfter" in backend.appended[0]!).toBe(false);
  });

  it("an aborted event is NOT counted as merged by the unblock predicate", async () => {
    const backend = new FakeFamilyBackend();
    await recordMerged(backend, 10);
    await recordAborted(backend, { phase: "wave", familyHeadAfter: "baseY" });
    const set = mergedSet(await backend.readFamilyLedger());
    expect(set.has(10)).toBe(true);
    expect(set.size).toBe(1); // only the real merge — the aborted phase entry never counts
  });
});

describe("#439 family escalation answer events", () => {
  it("writes decision escalation and answer rows append-only", async () => {
    const backend = new FakeFamilyBackend();
    await recordFamilyEscalated(backend, {
      escalationKind: "decision",
      phase: "final",
      reason: "cmr needs human disposition",
      familyHeadAfter: "baseZ",
    });
    await recordFamilyEscalationAnswered(backend, {
      answer: "continue-same-class",
      source: "human",
      note: "human approved another pass",
    });

    expect(backend.appended).toMatchObject([
      {
        status: "escalated",
        event: "escalated",
        phase: "final",
        reason: "cmr needs human disposition",
        familyHeadAfter: "baseZ",
        escalationKind: "decision",
        stopSummary: {
          reason: "infra_failure",
          repairHint: "inspect this escalation row and repair before rerun",
        },
      },
      {
        status: "escalation_answered",
        event: "escalation_answered",
        phase: "final",
        answer: "continue-same-class",
        source: "human",
        note: "human approved another pass",
      },
    ]);
    expect(familyEscalationState(backend.appended)).toMatchObject({
      answer: {
        event: "escalation_answered",
        answer: "continue-same-class",
        source: "human",
        note: "human approved another pass",
      },
      escalation: { escalationKind: "decision" },
    });
  });

  it("rejects blank answer rows before appending them", async () => {
    const backend = new FakeFamilyBackend();

    await expect(
      recordFamilyEscalationAnswered(backend, {
        answer: "   ",
        source: "human",
      }),
    ).rejects.toThrow("family escalation answer must be a non-empty string");

    expect(backend.appended).toEqual([]);
  });

  it("returns the latest valid answer payload after the latest escalation", () => {
    const entries: FamilyLedgerEntry[] = [
      {
        status: "escalated",
        event: "escalated",
        escalationKind: "decision",
      },
      {
        status: "escalation_answered",
        event: "escalation_answered",
        phase: "final",
        answer: "continue-old",
        source: "human",
      },
      {
        status: "escalation_answered",
        event: "escalation_answered",
        phase: "final",
        answer: "   ",
      },
      {
        status: "escalation_answered",
        event: "escalation_answered",
        phase: "final",
        answer: "continue-latest",
        source: "human",
        note: "latest human answer wins",
      },
    ];

    expect(familyEscalationState(entries)).toEqual({
      escalation: entries[0],
      answer: {
        event: "escalation_answered",
        answer: "continue-latest",
        source: "human",
        note: "latest human answer wins",
      },
    });
  });

  it("rejects malformed family answer rows that do not match the writer shape", () => {
    const entries: FamilyLedgerEntry[] = [
      {
        status: "escalated",
        event: "escalated",
        escalationKind: "decision",
      },
      {
        status: "escalation_answered",
        event: "escalation_answered",
        answer: "continue-without-final-phase",
      },
    ];

    expect(familyEscalationState(entries)).toEqual({
      escalation: entries[0],
    });
  });

  it("does not reopen an older escalation after a terminal shipped marker", () => {
    const entries: FamilyLedgerEntry[] = [
      {
        status: "escalated",
        event: "escalated",
        escalationKind: "decision",
        reason: "old migration pause",
      },
      {
        status: "shipped",
        event: "shipped",
        phase: "final",
        pr: "https://github.com/o/r/pull/1",
        familyHeadAfter: "head-1",
      },
    ];

    expect(familyEscalationState(entries)).toBeUndefined();
  });

  it("failure escalations remain failure even when a later answer row exists", async () => {
    const backend = new FakeFamilyBackend();
    await recordFamilyEscalated(backend, {
      escalationKind: "failure",
      reason: "family base diverged from ledger",
    });
    await recordFamilyEscalationAnswered(backend, {
      answer: "try-anyway",
      source: "human",
    });

    expect(familyEscalationState(backend.appended)).toEqual({
      escalation: backend.appended[0],
    });
    expect(mergedSet(backend.appended).size).toBe(0);
  });

  it("malformed escalation kinds are not reopened by later answer rows", () => {
    const entries: FamilyLedgerEntry[] = [
      {
        status: "escalated",
        event: "escalated",
        escalationKind: "maybe" as unknown as "decision",
      },
      {
        status: "escalation_answered",
        event: "escalation_answered",
        phase: "final",
        answer: "continue",
      },
    ];

    expect(familyEscalationState(entries)).toEqual({
      escalation: entries[0],
    });
  });

  it("malformed escalation rows missing event still pause instead of disappearing", () => {
    const entries = [
      {
        status: "escalated",
        escalationKind: "decision",
      },
      {
        status: "escalation_answered",
        event: "escalation_answered",
        phase: "final",
        answer: "continue",
      },
    ] as unknown as FamilyLedgerEntry[];

    expect(familyEscalationState(entries)).toEqual({
      escalation: entries[0],
    });
  });
});

describe("mergedSet — reconcile補账条 COUNTS (decision 5 / codex R3)", () => {
  it("a status:'merged' + event:'reconciled' entry is in the merged set (no deadlock)", () => {
    const entries: FamilyLedgerEntry[] = [
      { childIssue: 10, status: "merged", event: "reconciled", childHead: "c10" },
      { childIssue: 11, status: "merged" },
      { childIssue: 12, status: "aborted", familyHeadAfter: "b" },
    ];
    const set = mergedSet(entries);
    // reconciled補账条 (10) counts; live merge (11) counts; aborted (12) does not.
    expect(set.has(10)).toBe(true);
    expect(set.has(11)).toBe(true);
    expect(set.has(12)).toBe(false);
  });

  it("ignores malformed merged rows whose childIssue is not a safe integer", () => {
    const entries = [
      { status: "merged", childIssue: null },
      { status: "merged", childIssue: "10" },
      { status: "merged", childIssue: 11 },
    ] as unknown as FamilyLedgerEntry[];

    expect([...mergedSet(entries)].sort()).toEqual([11]);
  });
});

describe("isFamilyLedgerEntryShape — childIssue positive safe integer (#934 online CR-5)", () => {
  it("accepts thin merged rows and phase-level status without childIssue", () => {
    expect(isFamilyLedgerEntryShape({ status: "merged", childIssue: 10 })).toBe(
      true,
    );
    expect(isFamilyLedgerEntryShape({ status: "aborted" })).toBe(true);
  });

  it("rejects non-positive / non-integer / unsafe childIssue when present", () => {
    expect(isFamilyLedgerEntryShape({ status: "merged", childIssue: -1 })).toBe(
      false,
    );
    expect(isFamilyLedgerEntryShape({ status: "merged", childIssue: 0 })).toBe(
      false,
    );
    expect(isFamilyLedgerEntryShape({ status: "merged", childIssue: 1.5 })).toBe(
      false,
    );
    expect(
      isFamilyLedgerEntryShape({
        status: "merged",
        childIssue: Number.MAX_SAFE_INTEGER + 1,
      }),
    ).toBe(false);
    expect(isFamilyLedgerEntryShape({ status: "merged", childIssue: NaN })).toBe(
      false,
    );
  });

  it("parseFamilyLedgerJsonl fail-closes on invalid childIssue lines", () => {
    expect(() =>
      parseFamilyLedgerJsonl('{"status":"merged","childIssue":-1}\n'),
    ).toThrow(/not a valid FamilyLedgerEntry/);
    expect(() =>
      parseFamilyLedgerJsonl('{"status":"merged","childIssue":1.5}\n'),
    ).toThrow(/not a valid FamilyLedgerEntry/);
  });
});
