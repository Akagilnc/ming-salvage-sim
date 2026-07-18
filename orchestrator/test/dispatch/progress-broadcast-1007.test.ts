/**
 * #1007 — active progress broadcast: progress.jsonl + stage issue numbers +
 * status renderer + optional notify hook. Typed signals only; fail-open I/O.
 */
import {
  existsSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  PROGRESS_FILENAME,
  PROGRESS_SCHEMA_VERSION,
  clearProgressBroadcastConfig,
  configureProgressBroadcast,
  countJudgeDispositions,
  countSeverityFromFindings,
  emitJudgeProgress,
  emitParkProgress,
  emitProgressEvent,
  emitStageProgress,
  emitTerminalProgress,
  emitWaveCloseProgress,
  progressPath,
  readProgressEvents,
  renderFamilyStatus,
  renderFamilyStatusFromDir,
  tryAppendProgressEvent,
  type ProgressEvent,
} from "../../src/progressBroadcast.js";
import { logDriverStage } from "../../src/stageLog.js";
import type { Finding, JudgeFindingDisposition } from "../../src/types.js";

const tempDirs: string[] = [];

afterEach(() => {
  clearProgressBroadcastConfig();
  delete process.env.ORCHESTRATOR_NOTIFY_CMD;
  vi.restoreAllMocks();
  for (const dir of tempDirs.splice(0)) {
    rmSync(dir, { recursive: true, force: true });
  }
});

function tempLedger(prefix = "progress-1007-"): string {
  const dir = mkdtempSync(join(tmpdir(), prefix));
  tempDirs.push(dir);
  return dir;
}

function readLines(dir: string): string[] {
  const p = progressPath(dir);
  if (!existsSync(p)) return [];
  return readFileSync(p, "utf8")
    .split("\n")
    .map((l) => l.trim())
    .filter((l) => l.length > 0);
}

const dispositions: readonly JudgeFindingDisposition[] = [
  { identityKey: "a|loc|q1", action: "live" },
  { identityKey: "b|loc|q2", action: "live" },
  {
    identityKey: "c|loc|q3",
    action: "refute",
    reason: "not_established",
    evidence: "code does not match claim",
  },
  {
    identityKey: "d|loc|q4",
    action: "suppress",
    evidence: "owner batch",
    ownerRecordPointer: "owner://batch-1",
  },
];

const findings: readonly Finding[] = [
  {
    severity: "high",
    category: "correctness",
    claim_quote: "q1",
    location: "loc",
    suggested_fix: "fix",
    action: "fix_now",
  },
  {
    severity: "high",
    category: "correctness",
    claim_quote: "q2",
    location: "loc",
    suggested_fix: "fix",
    action: "fix_now",
  },
  {
    severity: "medium",
    category: "correctness",
    claim_quote: "q3",
    location: "loc",
    suggested_fix: "fix",
    action: "fix_now",
  },
];

describe("#1007 disposition / severity pure counters", () => {
  it("maps live→fix_now, refute→refuted, suppress→suppressed", () => {
    expect(countJudgeDispositions(dispositions)).toEqual({
      fix_now: 2,
      refuted: 1,
      suppressed: 1,
    });
  });

  it("counts severity only from typed findings cargo (no invent)", () => {
    expect(countSeverityFromFindings(findings)).toEqual({
      critical: 0,
      high: 2,
      medium: 1,
      low: 0,
      clarity: 0,
    });
    expect(countSeverityFromFindings(undefined)).toBeNull();
    expect(countSeverityFromFindings([])).toEqual({
      critical: 0,
      high: 0,
      medium: 0,
      low: 0,
      clarity: 0,
    });
  });
});

describe("#1007 progress.jsonl append-only schema", () => {
  it("appends schema'd stage / judge / park / wave_close / terminal rows", () => {
    const ledgerDir = tempLedger();
    const log = vi.spyOn(console, "log").mockImplementation(() => {});

    emitStageProgress({
      ledgerDir,
      stage: "dispatch",
      issue: 1007,
      epic: 1000,
      step: "S2",
      detail: "step=S2",
    });
    emitJudgeProgress({
      ledgerDir,
      issue: 1007,
      epic: 1000,
      step: "S3",
      round: 1,
      verdict: "continue",
      findingDispositions: dispositions,
      findings,
      cargoPointer: "ledger://judge/S3",
    });
    emitParkProgress({
      ledgerDir,
      issue: 1007,
      epic: 1000,
      step: "S3",
      gateSummary: "needs owner ruling on scope",
      reason: "decision_gate_park",
    });
    emitWaveCloseProgress({
      ledgerDir,
      epic: 1000,
      issues: [1007, 1008],
      wave: 1,
    });
    emitTerminalProgress({
      ledgerDir,
      epic: 1000,
      issue: 1007,
      status: "parked",
      stopReason: "decision_gate_park",
    });

    const lines = readLines(ledgerDir);
    expect(lines).toHaveLength(5);
    const events = lines.map((l) => JSON.parse(l) as ProgressEvent);
    expect(events.every((e) => e.v === PROGRESS_SCHEMA_VERSION)).toBe(true);
    expect(events.map((e) => e.kind)).toEqual([
      "stage",
      "judge",
      "park",
      "wave_close",
      "terminal",
    ]);

    const judge = events[1]!;
    expect(judge.kind).toBe("judge");
    if (judge.kind === "judge") {
      expect(judge.issue).toBe(1007);
      expect(judge.verdict).toBe("continue");
      expect(judge.dispositions).toEqual({
        fix_now: 2,
        refuted: 1,
        suppressed: 1,
      });
      expect(judge.severity).toEqual({
        critical: 0,
        high: 2,
        medium: 1,
        low: 0,
        clarity: 0,
      });
      expect(judge.cargoPointer).toBe("ledger://judge/S3");
      // Finding bodies never enter the feed.
      expect(JSON.stringify(judge)).not.toMatch(/suggested_fix|claim_quote|q1/);
    }

    // run.log lines include issue numbers on stage.
    const stageLine = log.mock.calls.map((c) => String(c[0])).find((s) =>
      s.includes("[orchestrator:progress]"),
    );
    expect(stageLine).toMatch(/#1007/);
    expect(stageLine).toMatch(/stage/);
  });

  it("tryAppend fails open when parent dir is missing (no throw, no mkdir invent)", () => {
    const orphan = join(tmpdir(), `no-such-parent-${Date.now()}`, "leaf");
    const ok = tryAppendProgressEvent(orphan, {
      v: PROGRESS_SCHEMA_VERSION,
      ts: new Date().toISOString(),
      kind: "stage",
      stage: "dispatch",
      issue: 1,
      detail: "x",
    });
    expect(ok).toBe(false);
  });

  it("emitProgressEvent swallows append failures (fail-open)", () => {
    const ledgerDir = tempLedger();
    // Make ledgerDir a file so mkdir/append fails.
    rmSync(ledgerDir, { recursive: true, force: true });
    writeFileSync(ledgerDir, "not-a-dir");
    expect(() =>
      emitProgressEvent({
        ledgerDir,
        event: {
          v: PROGRESS_SCHEMA_VERSION,
          ts: new Date().toISOString(),
          kind: "stage",
          stage: "dispatch",
          issue: 9,
        },
      }),
    ).not.toThrow();
  });
});

describe("#1007 stage lines carry issue number (#975 debt ④)", () => {
  it("logDriverStage dual-writes progress when configured, with issue id", () => {
    const ledgerDir = tempLedger();
    configureProgressBroadcast({ ledgerDir, epic: 1000 });
    const log = vi.spyOn(console, "log").mockImplementation(() => {});

    logDriverStage("dispatch", "step=S2", { issue: 1007 });

    expect(log.mock.calls.map((c) => String(c[0]))).toEqual(
      expect.arrayContaining([
        expect.stringMatching(
          /\[orchestrator:stage\] dispatch issue #1007 step=S2/,
        ),
      ]),
    );
    const events = readProgressEvents(ledgerDir);
    expect(events).toHaveLength(1);
    expect(events[0]).toMatchObject({
      kind: "stage",
      stage: "dispatch",
      issue: 1007,
      epic: 1000,
    });
  });

  it("logDriverStage without issue still prints stage line (no invent)", () => {
    const log = vi.spyOn(console, "log").mockImplementation(() => {});
    logDriverStage("smoke-k", "route=grok-blitz");
    expect(log.mock.calls[0]?.[0]).toMatch(
      /\[orchestrator:stage\] smoke-k route=grok-blitz/,
    );
  });
});

describe("#1007 status renderer from progress feed + ledger", () => {
  it("renders per-issue station / rounds / latest verdict / dispositions / parks", () => {
    const ledgerDir = tempLedger();
    emitStageProgress({
      ledgerDir,
      stage: "dispatch",
      issue: 1007,
      epic: 1000,
      step: "S2",
    });
    emitJudgeProgress({
      ledgerDir,
      issue: 1007,
      epic: 1000,
      step: "S3",
      round: 1,
      verdict: "continue",
      findingDispositions: dispositions,
      findings,
    });
    emitStageProgress({
      ledgerDir,
      stage: "dispatch",
      issue: 1007,
      epic: 1000,
      step: "S5",
    });
    emitJudgeProgress({
      ledgerDir,
      issue: 1007,
      epic: 1000,
      step: "S6",
      round: 2,
      verdict: "converged",
      findingDispositions: [],
    });
    emitStageProgress({
      ledgerDir,
      stage: "dispatch",
      issue: 1008,
      epic: 1000,
      step: "S2",
    });
    emitParkProgress({
      ledgerDir,
      issue: 1008,
      epic: 1000,
      step: "S2",
      gateSummary: "quota wall on pool grok",
      reason: "decision_gate_park",
    });
    emitWaveCloseProgress({
      ledgerDir,
      epic: 1000,
      issues: [1007],
      wave: 1,
    });
    // family ledger confirms merge (status consumes feed + ledger).
    writeFileSync(
      join(ledgerDir, "family-ledger.jsonl"),
      `${JSON.stringify({
        childIssue: 1007,
        status: "merged",
        event: "merged",
      })}\n`,
    );

    const text = renderFamilyStatusFromDir(ledgerDir);
    expect(text).toMatch(/#1007/);
    expect(text).toMatch(/#1008/);
    // station / rounds / verdict
    expect(text).toMatch(/S6|converged/);
    expect(text).toMatch(/rounds?\s*[:=]?\s*2|round 2/i);
    expect(text).toMatch(/park/i);
    expect(text).toMatch(/quota wall on pool grok/);
    // disposition counts from latest judge (converged → zeros) or prior
    expect(text).toMatch(/merged/i);

    const structured = renderFamilyStatus({
      events: readProgressEvents(ledgerDir),
      familyLedgerPath: join(ledgerDir, "family-ledger.jsonl"),
    });
    const issue1007 = structured.issues.find((i) => i.issue === 1007);
    const issue1008 = structured.issues.find((i) => i.issue === 1008);
    expect(issue1007).toMatchObject({
      issue: 1007,
      latestStep: "S6",
      latestVerdict: "converged",
      judgeRounds: 2,
      merged: true,
      parked: false,
    });
    expect(issue1008).toMatchObject({
      issue: 1008,
      parked: true,
      parkSummary: "quota wall on pool grok",
    });
  });

  it("does not invent status when progress feed is empty", () => {
    const ledgerDir = tempLedger();
    const structured = renderFamilyStatus({
      events: readProgressEvents(ledgerDir),
    });
    expect(structured.issues).toEqual([]);
    expect(renderFamilyStatusFromDir(ledgerDir)).toMatch(/no progress/i);
  });
});

describe("#1007 optional notify hook (default off, fail-open)", () => {
  it("does not invoke notify when env unset", () => {
    const spawn = vi.fn();
    emitParkProgress({
      ledgerDir: tempLedger(),
      issue: 1,
      gateSummary: "x",
      reason: "decision_gate_park",
      notifySpawn: spawn,
    });
    expect(spawn).not.toHaveBeenCalled();
  });

  it("invokes configured notify command on park / terminal (not on stage)", () => {
    process.env.ORCHESTRATOR_NOTIFY_CMD = "true";
    const calls: string[] = [];
    const spawn = (
      command: string,
      _args: readonly string[],
      _opts: {
        readonly env: NodeJS.ProcessEnv;
        readonly detached: boolean;
        readonly stdio: "ignore";
      },
    ) => {
      calls.push(command);
      return { unref() {} };
    };
    const ledgerDir = tempLedger();

    emitStageProgress({
      ledgerDir,
      stage: "dispatch",
      issue: 1,
      step: "S2",
      notifySpawn: spawn,
    });
    expect(calls).toEqual([]);

    emitParkProgress({
      ledgerDir,
      issue: 1,
      gateSummary: "gate",
      reason: "decision_gate_park",
      notifySpawn: spawn,
    });
    expect(calls).toEqual(["true"]);

    emitTerminalProgress({
      ledgerDir,
      status: "failed",
      stopReason: "infra_failure",
      notifySpawn: spawn,
    });
    expect(calls).toEqual(["true", "true"]);
  });

  it("notify spawn failure does not throw", () => {
    process.env.ORCHESTRATOR_NOTIFY_CMD = "true";
    const spawn = vi.fn(() => {
      throw new Error("spawn boom");
    });
    expect(() =>
      emitParkProgress({
        ledgerDir: tempLedger(),
        issue: 1,
        gateSummary: "gate",
        notifySpawn: spawn,
      }),
    ).not.toThrow();
  });
});

describe("#1007 PROGRESS_FILENAME constant", () => {
  it("is progress.jsonl under ledgerDir", () => {
    expect(PROGRESS_FILENAME).toBe("progress.jsonl");
    expect(progressPath("/tmp/ledger")).toBe(join("/tmp/ledger", "progress.jsonl"));
  });
});

// Shared thin single-slice backend for family park real-entry cases (#1007).
async function makeConvergingChildBackend(): Promise<
  import("../../src/types.js").Backend
> {
  type Backend = import("../../src/types.js").Backend;
  type IssueMeta = import("../../src/types.js").IssueMeta;
  type StepOutput = import("../../src/types.js").StepOutput;
  type StepSpec = import("../../src/types.js").StepSpec;
  type WorktreeHandle = import("../../src/types.js").WorktreeHandle;

  class ChildBackend implements Backend {
    async smokeModelRoute(route: Parameters<Backend["smokeModelRoute"]>[0]) {
      const { smokeRouteModels } = await import("../../src/modelRoutes.js");
      return smokeRouteModels(route, async () => ({ cliVersion: "t" }));
    }
    async findResumeState() {
      return undefined;
    }
    async resumeSession(): Promise<StepOutput> {
      return { kind: "coder", committed: true, commitsAdded: 1 };
    }
    async fetchIssueMeta(issueNumber: number): Promise<IssueMeta> {
      return {
        number: issueNumber,
        isReadyForAgent: true,
        hasSubIssues: false,
        isClosed: false,
        openBlockedBy: [],
      };
    }
    async prepareWorktree(
      issueNumber: number,
      base: string,
    ): Promise<WorktreeHandle> {
      return { branch: `feat/child-${issueNumber}`, base, path: `/wt/${issueNumber}` };
    }
    async runStep(spec: StepSpec): Promise<StepOutput> {
      if (spec.role === "coder") {
        return { kind: "coder", committed: true, commitsAdded: 1 };
      }
      return { kind: "judge", status: "converged" };
    }
    async writeLedger(): Promise<void> {}
  }
  return new ChildBackend();
}

function expectParkAndTerminal(
  ledgerDir: string,
  opts: { epic: number; issue?: number },
): void {
  const events = readProgressEvents(ledgerDir);
  expect(
    events.some(
      (e) =>
        e.kind === "park" &&
        e.epic === opts.epic &&
        (opts.issue === undefined || e.issue === opts.issue),
    ),
  ).toBe(true);
  expect(
    events.some(
      (e) =>
        e.kind === "terminal" &&
        e.status === "parked" &&
        e.epic === opts.epic &&
        (opts.issue === undefined || e.issue === opts.issue),
    ),
  ).toBe(true);
}

describe("#1007 real-entry: runOrchestrator stage lines carry issue id", () => {
  it("emits issue-numbered stage + judge + terminal progress rows", async () => {
    const { runOrchestrator } = await import("../../src/runner.js");
    const log = vi.spyOn(console, "log").mockImplementation(() => {});
    const ledgerDir = tempLedger("progress-1007-entry-");
    configureProgressBroadcast({ ledgerDir, epic: 1000 });

    type Backend = import("../../src/types.js").Backend;
    type IssueMeta = import("../../src/types.js").IssueMeta;
    type ResumeState = import("../../src/types.js").ResumeState;
    type StepOutput = import("../../src/types.js").StepOutput;
    type StepSpec = import("../../src/types.js").StepSpec;
    type WorktreeHandle = import("../../src/types.js").WorktreeHandle;

    class ScriptedBackend implements Backend {
      async smokeModelRoute(route: Parameters<Backend["smokeModelRoute"]>[0]) {
        const { smokeRouteModels } = await import("../../src/modelRoutes.js");
        return smokeRouteModels(route, async () => ({ cliVersion: "t" }));
      }
      async findResumeState(): Promise<ResumeState | undefined> {
        return undefined;
      }
      async resumeSession(_spec: StepSpec): Promise<StepOutput> {
        return { kind: "coder", committed: true, commitsAdded: 1 };
      }
      async fetchIssueMeta(issueNumber: number): Promise<IssueMeta> {
        return {
          number: issueNumber,
          isReadyForAgent: true,
          hasSubIssues: false,
          isClosed: false,
          openBlockedBy: [],
        };
      }
      async prepareWorktree(
        issueNumber: number,
      ): Promise<WorktreeHandle> {
        const path = join(ledgerDir, `wt-${issueNumber}`);
        return {
          path,
          branch: `feat/${issueNumber}`,
          base: "main",
        };
      }
      async runStep(spec: StepSpec): Promise<StepOutput> {
        if (spec.role === "coder") {
          return { kind: "coder", committed: true, commitsAdded: 1 };
        }
        // Judge seat: converge immediately.
        return { kind: "judge", status: "converged" };
      }
      async writeLedger(): Promise<void> {
        return;
      }
      async pushBranch(): Promise<void> {
        return;
      }
      async openPullRequest(): Promise<{ url: string }> {
        return { url: "https://example.test/pr/1" };
      }
      async cleanupWorktree(): Promise<void> {
        return;
      }
    }

    const result = await runOrchestrator({
      issueNumber: 1007,
      backend: new ScriptedBackend(),
    });
    expect(result.status === "completed" || result.status === "parked" || result.status === "failed").toBe(
      true,
    );

    const stageLines = log.mock.calls
      .map((c) => String(c[0]))
      .filter((s) => s.includes("[orchestrator:stage]"));
    expect(stageLines.some((s) => /issue #1007/.test(s))).toBe(true);

    const events = readProgressEvents(ledgerDir);
    const stages = events.filter((e) => e.kind === "stage");
    expect(stages.some((e) => e.kind === "stage" && e.issue === 1007)).toBe(
      true,
    );
    // Nit: single-slice real-entry also carries judge + terminal progress rows.
    expect(
      events.some(
        (e) =>
          e.kind === "judge" && e.issue === 1007 && e.verdict === "converged",
      ),
    ).toBe(true);
    expect(
      events.some(
        (e) =>
          e.kind === "terminal" &&
          e.issue === 1007 &&
          (e.status === "completed" ||
            e.status === "parked" ||
            e.status === "failed"),
      ),
    ).toBe(true);
  });
});

describe("#1007 first ship + family early-return park/terminal progress", () => {
  it("recordShipped emits ship progress (first successful ship, not only resume echo)", async () => {
    const { recordShipped } = await import("../../src/family/ledger.js");
    const ledgerDir = tempLedger("progress-1007-ship-");
    configureProgressBroadcast({ ledgerDir, epic: 1007 });

    type FamilyBackend = import("../../src/family/types.js").FamilyBackend;
    type FamilyLedgerEntry = import("../../src/family/types.js").FamilyLedgerEntry;
    const appended: FamilyLedgerEntry[] = [];
    const backend = {
      async appendFamilyLedger(entry: FamilyLedgerEntry): Promise<void> {
        appended.push(entry);
      },
      async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
        return appended;
      },
    } as FamilyBackend;

    await recordShipped(backend, {
      pr: "https://gh.test/pr/1007",
      familyHeadAfter: "ship-head-1",
    });

    const ships = readProgressEvents(ledgerDir).filter((e) => e.kind === "ship");
    expect(ships).toHaveLength(1);
    expect(ships[0]).toMatchObject({
      kind: "ship",
      epic: 1007,
      pr: "https://gh.test/pr/1007",
      familyHead: "ship-head-1",
    });
    expect(appended).toHaveLength(1);
    expect(appended[0]?.status).toBe("shipped");
  });

  it("prior family decision escalation re-entry emits park + terminal progress", async () => {
    const { runFamily } = await import("../../src/family/runner.js");
    const { buildExplicitLandingLiveHooks } = await import(
      "../../src/family/landing.js"
    );
    const ledgerDir = tempLedger("progress-1007-prior-park-");
    configureProgressBroadcast({ ledgerDir, epic: 291 });
    vi.spyOn(console, "log").mockImplementation(() => {});
    vi.spyOn(console, "info").mockImplementation(() => {});

    type FamilyBackend = import("../../src/family/types.js").FamilyBackend;
    type FamilyLedgerEntry = import("../../src/family/types.js").FamilyLedgerEntry;

    const ledger: FamilyLedgerEntry[] = [
      {
        status: "escalated",
        event: "escalated",
        phase: "final",
        reason: "cmr needs human disposition",
        escalationKind: "decision",
        familyHeadAfter: "head-park",
      },
    ];
    const familyBackend = {
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
      },
      async runFamilyVerify() {
        return { ok: true };
      },
      async mergeChildIntoFamilyBase() {
        return { familyHead: "should-not-merge" };
      },
      async appendFamilyLedger(entry: FamilyLedgerEntry) {
        ledger.push(entry);
      },
      async readFamilyLedger() {
        return ledger;
      },
      resolveTelemetryDir() {
        return ledgerDir;
      },
    } as unknown as FamilyBackend;

    const result = await runFamily({
      verifyCmr: async () => ({ ok: true, ran: true }),
      epic: { issue: 291, children: [{ issue: 10, blockedBy: [] }] },
      familyBackend,
      singleSliceBackend: await makeConvergingChildBackend(),
      familyBase: "family/291-base",
    });
    expect(result.status).toBe("parked");
    expectParkAndTerminal(ledgerDir, { epic: 291 });
  });

  it("unanswered child decision park re-entry emits park + terminal progress", async () => {
    const { runFamily } = await import("../../src/family/runner.js");
    const { buildExplicitLandingLiveHooks } = await import(
      "../../src/family/landing.js"
    );
    const ledgerDir = tempLedger("progress-1007-child-park-");
    configureProgressBroadcast({ ledgerDir, epic: 291 });
    vi.spyOn(console, "log").mockImplementation(() => {});
    vi.spyOn(console, "info").mockImplementation(() => {});

    type FamilyBackend = import("../../src/family/types.js").FamilyBackend;
    type FamilyLedgerEntry = import("../../src/family/types.js").FamilyLedgerEntry;

    const ledger: FamilyLedgerEntry[] = [
      {
        status: "child_decision_parked",
        event: "child_decision_parked",
        childIssue: 11,
        reason: "product decision required",
        diagnosis: "unclear optional vs required field",
        escalationKind: "decision",
        sessionId: "child-11-session",
        familyHeadAfter: "head-child-park",
      },
    ];
    const familyBackend = {
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
      },
      async runFamilyVerify() {
        return { ok: true };
      },
      async mergeChildIntoFamilyBase() {
        return { familyHead: "should-not-merge" };
      },
      async appendFamilyLedger(entry: FamilyLedgerEntry) {
        ledger.push(entry);
      },
      async readFamilyLedger() {
        return ledger;
      },
      resolveTelemetryDir() {
        return ledgerDir;
      },
    } as unknown as FamilyBackend;

    const result = await runFamily({
      verifyCmr: async () => ({ ok: true, ran: true }),
      epic: {
        issue: 291,
        children: [
          { issue: 10, blockedBy: [] },
          { issue: 11, blockedBy: [] },
        ],
      },
      familyBackend,
      singleSliceBackend: await makeConvergingChildBackend(),
      familyBase: "family/291-base",
    });
    expect(result.status).toBe("parked");
    expectParkAndTerminal(ledgerDir, { epic: 291, issue: 11 });
  });

  it("landing park re-entry emits park + terminal progress", async () => {
    const { runFamily } = await import("../../src/family/runner.js");
    const ledgerDir = tempLedger("progress-1007-landing-park-");
    configureProgressBroadcast({ ledgerDir, epic: 941 });
    vi.spyOn(console, "log").mockImplementation(() => {});
    vi.spyOn(console, "info").mockImplementation(() => {});

    type FamilyBackend = import("../../src/family/types.js").FamilyBackend;
    type FamilyLedgerEntry = import("../../src/family/types.js").FamilyLedgerEntry;
    type MergeRequest = import("../../src/family/types.js").MergeRequest;
    type WorkerSpec = import("../../src/types.js").WorkerSpec;
    type WorkerResult = import("../../src/types.js").WorkerResult;

    const ledger: FamilyLedgerEntry[] = [
      {
        childIssue: 9411,
        status: "merged",
        familyHeadAfter: "family-base-941",
      },
      {
        status: "review_loop_converged",
        event: "review_loop_converged",
        phase: "final",
        pr: "pr://family/941-landing",
        familyHeadAfter: "family-base-941",
      },
    ];
    let head = "family-base-941";
    const familyBackend = {
      resolveLandingLiveHooks() {
        return {
          fetchState: () => ({
            prNumber: 941,
            prUrl: "pr://family/941-landing",
            state: "OPEN",
            headOid: "family-base-941",
            headRefName: "family/epic-941",
            mergeStateStatus: "BLOCKED",
          }),
          executeMerge: () => {
            throw new Error("must not merge when ruleset blocked");
          },
          pollSnapshot: async () => ({
            repo: "o/r",
            prNumber: 941,
            prUrl: "pr://family/941-landing",
            headOid: "family-base-941",
            pollCount: 1,
            bots: {
              coderabbit: { state: "complete", findingCount: 0 },
              sourcery: { state: "complete", findingCount: 0 },
              codex: { state: "complete", findingCount: 0 },
              gemini: { state: "complete", findingCount: 0 },
            },
            threads: [],
            checkRuns: [
              {
                id: 1,
                name: "ci",
                status: "completed",
                conclusion: "success",
                headSha: "family-base-941",
              },
            ],
            totalFindingCount: 0,
            quiescent: true,
            roundTriggerUsed: {
              headOid: "family-base-941",
              triggeredAt: "1970-01-01T00:00:00.000Z",
            },
            checkRunsEmptyMeans: "pending",
          }),
        };
      },
      async mergeChildIntoFamilyBase(child: MergeRequest) {
        head = `+${child.childIssue}`;
        return { familyHead: head };
      },
      async resolveMergeConflict(): Promise<never> {
        throw new Error("resolveMergeConflict not used in this test");
      },
      async appendFamilyLedger(entry: FamilyLedgerEntry) {
        ledger.push(entry);
      },
      async readFamilyLedger() {
        return ledger;
      },
      async readFamilyHead() {
        return head;
      },
      async runFamilyVerify() {
        return { ok: true };
      },
      async dispatchWorker(spec: WorkerSpec): Promise<WorkerResult> {
        if (spec.kind === "landing") {
          return {
            kind: "completed",
            output: { kind: "landing", released: true },
          };
        }
        throw new Error(`unexpected ${spec.kind}`);
      },
      resolveTelemetryDir() {
        return ledgerDir;
      },
    } as unknown as FamilyBackend;

    const result = await runFamily({
      verifyCmr: async () => ({ ok: true, ran: true }),
      epic: {
        issue: 941,
        children: [{ issue: 9411, blockedBy: [] }],
      },
      familyBackend,
      singleSliceBackend: await makeConvergingChildBackend(),
      familyBase: "family/epic-941",
    });
    expect(result.status).toBe("parked");
    expectParkAndTerminal(ledgerDir, { epic: 941 });
  });

  it("merger decision park emits park + terminal progress", async () => {
    const { runFamily } = await import("../../src/family/runner.js");
    const { buildExplicitLandingLiveHooks } = await import(
      "../../src/family/landing.js"
    );
    const ledgerDir = tempLedger("progress-1007-merger-park-");
    configureProgressBroadcast({ ledgerDir, epic: 291 });
    vi.spyOn(console, "log").mockImplementation(() => {});
    vi.spyOn(console, "info").mockImplementation(() => {});

    type FamilyBackend = import("../../src/family/types.js").FamilyBackend;
    type FamilyEscalation = import("../../src/family/types.js").FamilyEscalation;
    type FamilyLedgerEntry = import("../../src/family/types.js").FamilyLedgerEntry;
    type MergeRequest = import("../../src/family/types.js").MergeRequest;

    const ledger: FamilyLedgerEntry[] = [];
    const familyBackend = {
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
      },
      async runFamilyVerify() {
        return { ok: true };
      },
      async mergeChildIntoFamilyBase(child: MergeRequest) {
        return { familyHead: `conflicted-${child.childIssue}`, conflicted: true as const };
      },
      async resolveMergeConflict(request: MergeRequest) {
        return {
          familyHead: `conflicted-${request.childIssue}`,
          conflicted: true as const,
          escalation: {
            reason: "choose the canonical migration",
            diagnosis: "both branches deliberately changed the same public contract",
            escalationKind: "decision" as const,
            phase: "wave" as const,
          },
        };
      },
      async escalateFamily(escalation: FamilyEscalation): Promise<void> {
        ledger.push({
          status: "escalated",
          event: "escalated",
          escalationKind: escalation.escalationKind ?? "decision",
          phase: escalation.phase ?? "wave",
          reason: escalation.reason,
          ...(escalation.familyHeadAfter !== undefined
            ? { familyHeadAfter: escalation.familyHeadAfter }
            : {}),
          ...(escalation.stopSummary !== undefined
            ? { stopSummary: escalation.stopSummary }
            : {}),
        });
      },
      async appendFamilyLedger(entry: FamilyLedgerEntry) {
        ledger.push(entry);
      },
      async readFamilyLedger() {
        return ledger;
      },
      resolveTelemetryDir() {
        return ledgerDir;
      },
    } as unknown as FamilyBackend;

    const result = await runFamily({
      verifyCmr: async () => ({ ok: true, ran: true }),
      epic: {
        issue: 291,
        children: [
          { issue: 10, blockedBy: [] },
          { issue: 11, blockedBy: [] },
        ],
      },
      familyBackend,
      singleSliceBackend: await makeConvergingChildBackend(),
      familyBase: "family/291-base",
    });
    expect(result.status).toBe("parked");
    expectParkAndTerminal(ledgerDir, { epic: 291, issue: 10 });
  });

  it("finalize() parked (final barrier decision_gate) emits park + terminal progress", async () => {
    const { runFamily } = await import("../../src/family/runner.js");
    const { buildExplicitLandingLiveHooks } = await import(
      "../../src/family/landing.js"
    );
    const ledgerDir = tempLedger("progress-1007-finalize-park-");
    configureProgressBroadcast({ ledgerDir, epic: 291 });
    vi.spyOn(console, "log").mockImplementation(() => {});
    vi.spyOn(console, "info").mockImplementation(() => {});

    type FamilyBackend = import("../../src/family/types.js").FamilyBackend;
    type FamilyLedgerEntry = import("../../src/family/types.js").FamilyLedgerEntry;
    type MergeRequest = import("../../src/family/types.js").MergeRequest;

    const ledger: FamilyLedgerEntry[] = [];
    const familyBackend = {
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
      },
      async runFamilyVerify() {
        return { ok: true };
      },
      async mergeChildIntoFamilyBase(child: MergeRequest) {
        return { familyHead: `h${child.childIssue}` };
      },
      async appendFamilyLedger(entry: FamilyLedgerEntry) {
        ledger.push(entry);
      },
      async readFamilyLedger() {
        return ledger;
      },
      resolveTelemetryDir() {
        return ledgerDir;
      },
    } as unknown as FamilyBackend;

    const result = await runFamily({
      epic: { issue: 291, children: [{ issue: 10, blockedBy: [] }] },
      familyBackend,
      singleSliceBackend: await makeConvergingChildBackend(),
      familyBase: "family/291-base",
      // Final barrier writes decision_gate_park then returns ok:false without
      // failedStatus → finalize() resolves public parked (not early-return park).
      verifyCmr: async (input) => {
        if (input.phase !== "final") return { ok: true, ran: true };
        ledger.push({
          status: "escalated",
          event: "escalated",
          phase: "final",
          escalationKind: "decision",
          reason: "final barrier needs human disposition",
          familyHeadAfter: "h10",
          stopSummary: {
            reason: "decision_gate_park",
            summary: "finalize parked decision gate",
            repairHint: "answer the gate and re-feed",
          },
        });
        return { ok: false, ran: true };
      },
    });
    expect(result.status).toBe("parked");
    expectParkAndTerminal(ledgerDir, { epic: 291 });
  });
});
