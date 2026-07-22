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
  emitBeatProgress,
  emitExitProgress,
  emitJudgeProgress,
  emitParkProgress,
  emitProgressEvent,
  emitStageProgress,
  emitTerminalProgress,
  emitWaveCloseProgress,
  getProgressBroadcastConfig,
  progressPath,
  readProgressEvents,
  renderFamilyStatus,
  renderFamilyStatusFromDir,
  tryAppendProgressEvent,
  type ProgressEvent,
} from "../../src/progressBroadcast.js";
import { logDriverStage } from "../../src/stageLog.js";
import type { Finding, JudgeFindingDisposition } from "../../src/types.js";
import { judgeEscalate } from "../helpers/judge-fixtures.js";
import { s8 } from "../helpers/resume-fixtures.js";

const tempDirs: string[] = [];

afterEach(() => {
  clearProgressBroadcastConfig();
  delete process.env.ORCHESTRATOR_NOTIFY_CMD;
  vi.unstubAllEnvs();
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

  it("#1076: failed terminal row + log line carry gateSummary/stopReason verbatim", () => {
    const ledgerDir = tempLedger();
    const log = vi.spyOn(console, "log").mockImplementation(() => {});

    emitTerminalProgress({
      ledgerDir,
      epic: 1000,
      issue: 1007,
      status: "failed",
      stopReason: "infra_failure",
      gateSummary: "real substr: runtime exploded at finalize",
    });

    const events = readProgressEvents(ledgerDir);
    const terminal = events.find((e) => e.kind === "terminal");
    expect(terminal).toBeDefined();
    if (terminal && terminal.kind === "terminal") {
      expect(terminal.status).toBe("failed");
      expect(terminal.stopReason).toBe("infra_failure");
      expect(terminal.gateSummary).toBe(
        "real substr: runtime exploded at finalize",
      );
    }

    const line = log.mock.calls
      .map((c) => String(c[0]))
      .find((s) => s.includes("[orchestrator:progress]"));
    expect(line).toMatch(/status=failed/);
    expect(line).toMatch(/stop=infra_failure/);
    expect(line).toMatch(/real substr: runtime exploded at finalize/);
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
    // station / rounds / verdict + stage 站位
    expect(text).toMatch(/S6|converged/);
    expect(text).toMatch(/stage=dispatch/);
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

  it("#1086 AC3: family-status aggregates beat rotation without worker logs", () => {
    // Value-night / morning report surface: renderFamilyStatus + FromDir.
    // Emits real progress API events (not pre-seeded snapshot rows).
    const ledgerDir = tempLedger();
    emitBeatProgress({
      ledgerDir,
      issue: 1086,
      epic: 1080,
      role: "builder",
      step: "S2",
      rotation: 1,
      beatKind: "plan",
    });
    let snap = renderFamilyStatus({
      events: readProgressEvents(ledgerDir),
    });
    expect(snap.issues.find((i) => i.issue === 1086)).toMatchObject({
      latestBeatRole: "builder",
      latestBeatKind: "plan",
      latestRotation: 1,
    });

    emitBeatProgress({
      ledgerDir,
      issue: 1086,
      epic: 1080,
      role: "judge",
      step: "S3",
      rotation: 2,
      verdict: "continue",
    });
    snap = renderFamilyStatus({
      events: readProgressEvents(ledgerDir),
    });
    expect(snap.issues.find((i) => i.issue === 1086)).toMatchObject({
      latestBeatRole: "judge",
      latestBeatKind: null,
      latestRotation: 2,
      latestVerdict: "continue",
    });

    emitBeatProgress({
      ledgerDir,
      issue: 1086,
      epic: 1080,
      role: "builder",
      step: "S2",
      rotation: 3,
      beatKind: "construct",
    });
    emitBeatProgress({
      ledgerDir,
      issue: 1086,
      epic: 1080,
      role: "judge",
      step: "S3",
      rotation: 4,
      verdict: "converged",
    });
    snap = renderFamilyStatus({
      events: readProgressEvents(ledgerDir),
    });
    expect(snap.issues.find((i) => i.issue === 1086)).toMatchObject({
      latestBeatRole: "judge",
      latestRotation: 4,
      latestVerdict: "converged",
    });

    const text = renderFamilyStatusFromDir(ledgerDir);
    expect(text).toMatch(/rotation=judge@4/);
  });

  it("#1017 R4: merge events without numeric issue do not poison snapshot", () => {
    // readProgressEvents only checks v+kind; malformed merge.issue must not
    // create Map keys / merged flags via ensure / Set.add.
    const structured = renderFamilyStatus({
      events: [
        {
          v: PROGRESS_SCHEMA_VERSION,
          ts: "2026-01-01T00:00:00.000Z",
          kind: "merge",
          // cast: disk feed can carry non-number after loose parse
          issue: "not-a-number" as unknown as number,
        },
        {
          v: PROGRESS_SCHEMA_VERSION,
          ts: "2026-01-01T00:00:01.000Z",
          kind: "merge",
          // missing issue entirely
        } as ProgressEvent,
        {
          v: PROGRESS_SCHEMA_VERSION,
          ts: "2026-01-01T00:00:02.000Z",
          kind: "merge",
          issue: 10071,
        },
      ],
    });
    expect(structured.issues.map((i) => i.issue)).toEqual([10071]);
    expect(structured.issues[0]).toMatchObject({
      issue: 10071,
      merged: true,
    });
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

  it("emitExitProgress parked notifies once (park carries notify; terminal silent)", () => {
    process.env.ORCHESTRATOR_NOTIFY_CMD = "true";
    const spawn = vi.fn(() => ({ unref() {} }));
    const ledgerDir = tempLedger();
    emitExitProgress({
      ledgerDir,
      epic: 1007,
      issue: 1007,
      status: "parked",
      stopReason: "decision_gate_park",
      gateSummary: "needs owner ruling",
      notifySpawn: spawn,
    });
    expect(spawn).toHaveBeenCalledTimes(1);
    const events = readProgressEvents(ledgerDir);
    expect(events.map((e) => e.kind)).toEqual(["park", "terminal"]);
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
    // Worktree parent; standalone rebinds progress to sibling `.ledger-N` (#1017).
    const workParent = tempLedger("progress-1007-entry-");
    const stateDir = join(workParent, ".ledger-1007");

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
        const path = join(workParent, `wt-${issueNumber}`);
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

    const events = readProgressEvents(stateDir);
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

  it("judge escalate emits kind:judge verdict=escalate + park/terminal (AC1)", async () => {
    const { runOrchestrator } = await import("../../src/runner.js");
    const log = vi.spyOn(console, "log").mockImplementation(() => {});
    vi.spyOn(console, "info").mockImplementation(() => {});
    const workParent = tempLedger("progress-1007-judge-esc-");
    const stateDir = join(workParent, ".ledger-1007");

    type Backend = import("../../src/types.js").Backend;
    type IssueMeta = import("../../src/types.js").IssueMeta;
    type ResumeState = import("../../src/types.js").ResumeState;
    type StepOutput = import("../../src/types.js").StepOutput;
    type StepSpec = import("../../src/types.js").StepSpec;
    type WorktreeHandle = import("../../src/types.js").WorktreeHandle;

    class EscalateJudgeBackend implements Backend {
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
      async prepareWorktree(issueNumber: number): Promise<WorktreeHandle> {
        return {
          path: join(workParent, `wt-${issueNumber}`),
          branch: `feat/${issueNumber}`,
          base: "main",
        };
      }
      async runStep(spec: StepSpec): Promise<StepOutput> {
        if (spec.role === "coder") {
          return { kind: "coder", committed: true, commitsAdded: 1 };
        }
        return judgeEscalate("needs owner ruling", "scope boundary unclear");
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
      backend: new EscalateJudgeBackend(),
    });
    expect(result.status).toBe("parked");
    void log;

    const events = readProgressEvents(stateDir);
    expect(
      events.some(
        (e) =>
          e.kind === "judge" &&
          e.issue === 1007 &&
          e.verdict === "escalate",
      ),
    ).toBe(true);
    // Standalone feed has no epic; pin park+terminal rows on issue alone.
    expect(
      events.some((e) => e.kind === "park" && e.issue === 1007),
    ).toBe(true);
    expect(
      events.some(
        (e) =>
          e.kind === "terminal" &&
          e.status === "parked" &&
          e.issue === 1007,
      ),
    ).toBe(true);
  });

  it("resident durable completed replay emits terminal progress", async () => {
    const { runOrchestrator } = await import("../../src/runner.js");
    vi.spyOn(console, "log").mockImplementation(() => {});
    vi.spyOn(console, "info").mockImplementation(() => {});
    const ledgerDir = tempLedger("progress-1007-replay-");

    type Backend = import("../../src/types.js").Backend;
    type ResumeState = import("../../src/types.js").ResumeState;
    type StepOutput = import("../../src/types.js").StepOutput;
    type StepSpec = import("../../src/types.js").StepSpec;

    class TerminalResidentBackend implements Backend {
      async smokeModelRoute(): Promise<never> {
        throw new Error("durable completed replay must not smoke");
      }
      async findResumeState(): Promise<ResumeState> {
        return {
          worktree: {
            branch: "feat/1007",
            base: "main",
            path: join(ledgerDir, "wt-1007"),
          },
          stateDir: ledgerDir,
          ledger: [s8("completed")],
        };
      }
      async resumeSession(_spec: StepSpec): Promise<StepOutput> {
        throw new Error("durable completed replay must not resume session");
      }
      async fetchIssueMeta(): Promise<never> {
        throw new Error("durable completed replay must not fetch meta");
      }
      async prepareWorktree(): Promise<never> {
        throw new Error("durable completed replay must not re-cut");
      }
      async runStep(): Promise<never> {
        throw new Error("durable completed replay must not dispatch");
      }
      async writeLedger(): Promise<void> {
        return;
      }
    }

    const result = await runOrchestrator({
      issueNumber: 1007,
      backend: new TerminalResidentBackend(),
    });
    expect(result.status).toBe("completed");
    const events = readProgressEvents(ledgerDir);
    expect(
      events.some(
        (e) =>
          e.kind === "terminal" &&
          e.status === "completed" &&
          e.issue === 1007 &&
          e.stopReason === "already_done",
      ),
    ).toBe(true);
  });
});

describe("#1017 P2: standalone rebinds progress ledger; family child inherits", () => {
  it("after family config, standalone run writes progress to its own stateDir not the old family ledger", async () => {
    const { runOrchestrator } = await import("../../src/runner.js");
    vi.spyOn(console, "log").mockImplementation(() => {});
    vi.spyOn(console, "info").mockImplementation(() => {});

    const familyLedger = tempLedger("progress-1017-fam-");
    const workParent = tempLedger("progress-1017-standalone-");
    // Simulate prior same-process family driver binding.
    configureProgressBroadcast({ ledgerDir: familyLedger, epic: 1000 });

    type Backend = import("../../src/types.js").Backend;
    type IssueMeta = import("../../src/types.js").IssueMeta;
    type ResumeState = import("../../src/types.js").ResumeState;
    type StepOutput = import("../../src/types.js").StepOutput;
    type StepSpec = import("../../src/types.js").StepSpec;
    type WorktreeHandle = import("../../src/types.js").WorktreeHandle;

    class StandaloneBackend implements Backend {
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
      async prepareWorktree(issueNumber: number): Promise<WorktreeHandle> {
        return {
          path: join(workParent, `wt-${issueNumber}`),
          branch: `feat/${issueNumber}`,
          base: "main",
        };
      }
      async runStep(spec: StepSpec): Promise<StepOutput> {
        if (spec.role === "coder") {
          return { kind: "coder", committed: true, commitsAdded: 1 };
        }
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
      issueNumber: 1017,
      backend: new StandaloneBackend(),
    });
    expect(
      result.status === "completed" ||
        result.status === "parked" ||
        result.status === "failed",
    ).toBe(true);

    const standaloneStateDir = join(workParent, ".ledger-1017");
    expect(readLines(familyLedger)).toHaveLength(0);
    const events = readProgressEvents(standaloneStateDir);
    expect(events.some((e) => e.kind === "stage" && e.issue === 1017)).toBe(
      true,
    );
    expect(getProgressBroadcastConfig().ledgerDir).toBe(standaloneStateDir);
    expect(getProgressBroadcastConfig().epic).toBeUndefined();
  });

  it("family child keeps already-configured family ledgerDir (does not rebind to child stateDir)", async () => {
    const { runOrchestrator } = await import("../../src/runner.js");
    vi.spyOn(console, "log").mockImplementation(() => {});
    vi.spyOn(console, "info").mockImplementation(() => {});

    const familyLedger = tempLedger("progress-1017-inherit-");
    const workParent = tempLedger("progress-1017-child-wt-");
    configureProgressBroadcast({ ledgerDir: familyLedger, epic: 1000 });

    type Backend = import("../../src/types.js").Backend;
    type IssueMeta = import("../../src/types.js").IssueMeta;
    type ResumeState = import("../../src/types.js").ResumeState;
    type StepOutput = import("../../src/types.js").StepOutput;
    type StepSpec = import("../../src/types.js").StepSpec;
    type WorktreeHandle = import("../../src/types.js").WorktreeHandle;

    class FamilyChildBackend implements Backend {
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
      async prepareWorktree(issueNumber: number): Promise<WorktreeHandle> {
        return {
          path: join(workParent, `wt-${issueNumber}`),
          branch: `feat/${issueNumber}`,
          base: "main",
        };
      }
      async runStep(spec: StepSpec): Promise<StepOutput> {
        if (spec.role === "coder") {
          return { kind: "coder", committed: true, commitsAdded: 1 };
        }
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
      issueNumber: 1017,
      backend: new FamilyChildBackend(),
      family: {
        parentIssue: 1000,
        familyBase: "family/1000",
        mergedBlockers: [],
      },
    });
    expect(
      result.status === "completed" ||
        result.status === "parked" ||
        result.status === "failed",
    ).toBe(true);

    const childStateDir = join(workParent, ".ledger-1017");
    expect(existsSync(progressPath(childStateDir))).toBe(false);
    const events = readProgressEvents(familyLedger);
    expect(events.some((e) => e.kind === "stage" && e.issue === 1017)).toBe(
      true,
    );
    expect(getProgressBroadcastConfig().ledgerDir).toBe(familyLedger);
    expect(getProgressBroadcastConfig().epic).toBe(1000);
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
      pr: "https://github.com/test/repo/pull/1007",
      familyHeadAfter: "ship-head-1",
    });

    const ships = readProgressEvents(ledgerDir).filter((e) => e.kind === "ship");
    expect(ships).toHaveLength(1);
    expect(ships[0]).toMatchObject({
      kind: "ship",
      epic: 1007,
      pr: "https://github.com/test/repo/pull/1007",
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
        pr: "https://github.com/test/repo/pull/941",
        familyHeadAfter: "family-base-941",
      },
    ];
    let head = "family-base-941";
    const familyBackend = {
      resolveLandingLiveHooks() {
        return {
          fetchState: () => ({
            prNumber: 941,
            prUrl: "https://github.com/test/repo/pull/941",
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
            prUrl: "https://github.com/test/repo/pull/941",
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

describe("#1007 CR R3: shared exit helpers + familyDriver early parks dual-write", () => {
  it("parkQuotaWaitForReset emits park + terminal progress (P1)", async () => {
    const { parkQuotaWaitForReset } = await import(
      "../../src/quotaParkRelay.js"
    );
    const { QuotaWaitForResetError } = await import("../../src/quotaProbe.js");
    const ledgerDir = tempLedger("progress-1007-quota-");
    configureProgressBroadcast({ ledgerDir, epic: 1007 });
    vi.spyOn(console, "log").mockImplementation(() => {});

    const resetAt = new Date("2026-07-08T16:10:00.000Z");
    const err = new QuotaWaitForResetError({
      disposition: {
        kind: "wait_for_reset",
        pool: "zai",
        resetAt,
        reason: "quota limited (429); wait for reset",
      },
      applied: {
        ledgerEntry: {
          event: "quota_wait_for_reset",
          pool: "zai",
          reason: "quota limited (429); wait for reset",
          step: "S2",
          ts: "2026-07-08T12:00:00.000Z",
          resetAt: resetAt.toISOString(),
        },
      },
      pool: "zai",
    });
    const ledger: import("../../src/types.js").LedgerEntry[] = [];
    const result = await parkQuotaWaitForReset({
      step: "S2",
      err,
      ledger,
      // undefined stateDir → no durable write; still must dual-write progress.
      stateDir: undefined,
      sessionId: "sess-quota-1007",
      backend: {} as import("../../src/types.js").Backend,
      resolveBranchHEAD: async () => "abc",
      hashPrompt: async () => "hash",
      // #1007 R5: single-slice park must attribute progress to the ticket.
      issue: 1007,
    });
    expect(result.status).toBe("parked");
    expectParkAndTerminal(ledgerDir, { epic: 1007, issue: 1007 });
    const parks = readProgressEvents(ledgerDir).filter((e) => e.kind === "park");
    expect(parks).toHaveLength(1);
    expect(parks[0]).toMatchObject({
      kind: "park",
      step: "S2",
      issue: 1007,
      reason: "provider_degraded",
    });
  });

  it("escalateTermination decision park (GitHub auth) emits park + terminal (P1/P4)", async () => {
    const { runOrchestrator } = await import("../../src/runner.js");
    // Pre-worktree standalone: no stateDir yet — progress is log-only until
    // bind (#1017 clears any prior process feed at standalone entry).
    const log = vi.spyOn(console, "log").mockImplementation(() => {});
    vi.spyOn(console, "info").mockImplementation(() => {});
    vi.spyOn(console, "error").mockImplementation(() => {});

    type Backend = import("../../src/types.js").Backend;
    class AuthFailBackend implements Backend {
      async smokeModelRoute(route: Parameters<Backend["smokeModelRoute"]>[0]) {
        const { smokeRouteModels } = await import("../../src/modelRoutes.js");
        return smokeRouteModels(route, async () => ({ cliVersion: "t" }));
      }
      async findResumeState() {
        return undefined;
      }
      async resumeSession(): Promise<never> {
        throw new Error("unreachable");
      }
      async fetchIssueMeta(): Promise<never> {
        throw Object.assign(new Error("HTTP 401: To re-authenticate, please run: gh auth login"), {
          status: 401,
        });
      }
      async prepareWorktree(): Promise<never> {
        throw new Error("unreachable");
      }
      async runStep(): Promise<never> {
        throw new Error("unreachable");
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
      backend: new AuthFailBackend(),
    });
    expect(result.status).toBe("parked");
    const progressLines = log.mock.calls.map((c) => String(c[0]));
    expect(
      progressLines.some(
        (s) =>
          s.includes("[orchestrator:progress]") &&
          s.includes("park") &&
          s.includes("issue #1007"),
      ),
    ).toBe(true);
    expect(
      progressLines.some(
        (s) =>
          s.includes("[orchestrator:progress]") &&
          s.includes("terminal") &&
          s.includes("status=parked") &&
          s.includes("issue #1007"),
      ),
    ).toBe(true);
  });

  it("errorTermination (metadata throw) emits terminal progress (P3)", async () => {
    const { runOrchestrator } = await import("../../src/runner.js");
    const log = vi.spyOn(console, "log").mockImplementation(() => {});
    vi.spyOn(console, "info").mockImplementation(() => {});
    vi.spyOn(console, "error").mockImplementation(() => {});

    type Backend = import("../../src/types.js").Backend;
    class MetaFailBackend implements Backend {
      async smokeModelRoute(route: Parameters<Backend["smokeModelRoute"]>[0]) {
        const { smokeRouteModels } = await import("../../src/modelRoutes.js");
        return smokeRouteModels(route, async () => ({ cliVersion: "t" }));
      }
      async findResumeState() {
        return undefined;
      }
      async resumeSession(): Promise<never> {
        throw new Error("unreachable");
      }
      async fetchIssueMeta(): Promise<never> {
        throw new Error("gh issue view exploded");
      }
      async prepareWorktree(): Promise<never> {
        throw new Error("unreachable");
      }
      async runStep(): Promise<never> {
        throw new Error("unreachable");
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
      backend: new MetaFailBackend(),
    });
    expect(result.status).toBe("failed");
    const progressLines = log.mock.calls.map((c) => String(c[0]));
    expect(
      progressLines.some(
        (s) =>
          s.includes("[orchestrator:progress]") &&
          s.includes("terminal") &&
          s.includes("status=failed") &&
          s.includes("issue #1007"),
      ),
    ).toBe(true);
  });

  it("familyDriver route preflight fail emits terminal progress (P2)", async () => {
    const { runFamilyDriver } = await import("../../src/familyDriver.js");
    const ledgerDir = tempLedger("progress-1007-fd-route-");
    vi.stubEnv("ORCHESTRATOR_ROUTE", "definitely-not-a-route-preset");
    vi.spyOn(console, "log").mockImplementation(() => {});
    vi.spyOn(console, "info").mockImplementation(() => {});

    const result = await runFamilyDriver({
      epicIssue: 1007,
      sourceRepo: "/tmp/no-such-source",
      repo: "Akagilnc/ming-salvage-sim",
      familyBase: "family/1007-base",
      base: "main",
      promptsDir: "/tmp/prompts",
      familyPromptsDir: "/tmp/family-prompts",
      soulsDir: "/tmp/souls",
      ledgerDir,
      imageName: "img",
      sh: () => {
        throw new Error("should not read GitHub after route admission stop");
      },
      realBackendFactory: () => {
        throw new Error("should not clone after route admission stop");
      },
    });
    expect(result.status).toBe("failed");
    const events = readProgressEvents(ledgerDir);
    expect(
      events.some(
        (e) =>
          e.kind === "terminal" &&
          e.status === "failed" &&
          e.epic === 1007,
      ),
    ).toBe(true);
  });

  it("familyDriver root blocked_by park emits park + terminal (P2)", async () => {
    const { runFamilyDriver } = await import("../../src/familyDriver.js");
    const ledgerDir = tempLedger("progress-1007-fd-block-");
    vi.stubEnv("ORCHESTRATOR_ROUTE", "normal");
    vi.spyOn(console, "log").mockImplementation(() => {});
    vi.spyOn(console, "info").mockImplementation(() => {});
    vi.spyOn(console, "warn").mockImplementation(() => {});

    const sh = (_file: string, args: string[]): string => {
      const joined = args.join(" ");
      if (joined.includes("sub_issues")) {
        return JSON.stringify([
          {
            number: 1008,
            state: "OPEN",
            labels: [{ name: "ready-for-agent" }],
          },
        ]);
      }
      // Root epic blocked by open upstream #999 → FamilyRootBlockerError park.
      if (joined.includes(`issues/1007/dependencies/blocked_by`)) {
        return JSON.stringify([{ number: 999, state: "OPEN" }]);
      }
      if (joined.includes("dependencies/blocked_by")) return "[]";
      if (joined.includes("issue view")) {
        return JSON.stringify({
          number: Number(args[2]),
          body: "Coder-Rec: terra@med",
          author: { login: "Akagilnc" },
        });
      }
      throw new Error(`unexpected metadata call: ${joined}`);
    };

    const result = await runFamilyDriver({
      epicIssue: 1007,
      sourceRepo: "/tmp/source",
      repo: "Akagilnc/ming-salvage-sim",
      familyBase: "family/1007-base",
      base: "main",
      promptsDir: "/tmp/prompts",
      familyPromptsDir: "/tmp/prompts",
      soulsDir: "/tmp/souls",
      ledgerDir,
      imageName: "img",
      sh,
      realBackendFactory: () => {
        throw new Error("blocked_by park must not create worksite");
      },
    });
    expect(result.status).toBe("parked");
    expectParkAndTerminal(ledgerDir, { epic: 1007 });
  });

  it("familyDriver GitHub auth park emits park + terminal (P2)", async () => {
    const { runFamilyDriver } = await import("../../src/familyDriver.js");
    const ledgerDir = tempLedger("progress-1007-fd-auth-");
    vi.stubEnv("ORCHESTRATOR_ROUTE", "normal");
    vi.spyOn(console, "log").mockImplementation(() => {});
    vi.spyOn(console, "info").mockImplementation(() => {});

    const result = await runFamilyDriver({
      epicIssue: 1007,
      sourceRepo: "/tmp/source",
      repo: "Akagilnc/ming-salvage-sim",
      familyBase: "family/1007-base",
      base: "main",
      promptsDir: "/tmp/prompts",
      familyPromptsDir: "/tmp/prompts",
      soulsDir: "/tmp/souls",
      ledgerDir,
      imageName: "img",
      sh: () => {
        throw Object.assign(
          new Error("HTTP 401: To re-authenticate, please run: gh auth login"),
          { status: 401 },
        );
      },
      realBackendFactory: () => {
        throw new Error("auth park must not create worksite");
      },
    });
    expect(result.status).toBe("parked");
    expectParkAndTerminal(ledgerDir, { epic: 1007 });
  });

  it("family reconcile fail-closed emits terminal progress (P3)", async () => {
    const { runFamily } = await import("../../src/family/runner.js");
    const { buildExplicitLandingLiveHooks } = await import(
      "../../src/family/landing.js"
    );
    const ledgerDir = tempLedger("progress-1007-reconcile-");
    configureProgressBroadcast({ ledgerDir, epic: 291 });
    vi.spyOn(console, "log").mockImplementation(() => {});
    vi.spyOn(console, "info").mockImplementation(() => {});

    type FamilyBackend = import("../../src/family/types.js").FamilyBackend;
    type FamilyLedgerEntry = import("../../src/family/types.js").FamilyLedgerEntry;

    const ledger: FamilyLedgerEntry[] = [
      {
        childIssue: 10,
        status: "merged",
        familyHeadAfter: "ledger-head",
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

    // Live family-base HEAD diverged from ledger末条 → reconcile fail-closed.
    const result = await runFamily({
      verifyCmr: async () => ({ ok: true, ran: true }),
      epic: { issue: 291, children: [{ issue: 10, blockedBy: [] }] },
      familyBackend,
      singleSliceBackend: await makeConvergingChildBackend(),
      familyBase: "family/291-base",
      reconcileGit: {
        liveFamilyHead: async () => "divergent-live-head",
        familyBaseStartHead: async () => "start-head",
        childHeadExists: async () => ({ exists: false }),
        isAncestor: async () => false,
      },
    });
    expect(result.status).toBe("failed");
    const events = readProgressEvents(ledgerDir);
    expect(
      events.some(
        (e) =>
          e.kind === "terminal" &&
          e.status === "failed" &&
          e.epic === 291,
      ),
    ).toBe(true);
  });

  it("family already-converged completed early return emits terminal progress", async () => {
    const { runFamily } = await import("../../src/family/runner.js");
    const { buildExplicitLandingLiveHooks } = await import(
      "../../src/family/landing.js"
    );
    const ledgerDir = tempLedger("progress-1007-converged-");
    configureProgressBroadcast({ ledgerDir, epic: 291 });
    vi.spyOn(console, "log").mockImplementation(() => {});
    vi.spyOn(console, "info").mockImplementation(() => {});

    type FamilyBackend = import("../../src/family/types.js").FamilyBackend;
    type FamilyLedgerEntry = import("../../src/family/types.js").FamilyLedgerEntry;

    const ledger: FamilyLedgerEntry[] = [
      {
        childIssue: 10,
        status: "merged",
        familyHeadAfter: "family-base-0",
      },
      {
        status: "review_loop_converged",
        event: "review_loop_converged",
        phase: "final",
        pr: "https://github.com/test/repo/pull/291",
        familyHeadAfter: "family-base-0",
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
      async readFamilyHead() {
        return "family-base-0";
      },
      resolveTelemetryDir() {
        return ledgerDir;
      },
      async dispatchWorker(spec: { kind: string }) {
        if (spec.kind === "landing") {
          return {
            kind: "completed" as const,
            output: { kind: "landing" as const, released: true },
          };
        }
        throw new Error(`unexpected ${spec.kind} on already-converged resume`);
      },
    } as unknown as FamilyBackend;

    const result = await runFamily({
      verifyCmr: async () => ({ ok: true, ran: true }),
      epic: { issue: 291, children: [{ issue: 10, blockedBy: [] }] },
      familyBackend,
      singleSliceBackend: await makeConvergingChildBackend(),
      familyBase: "family/291-base",
    });
    expect(result.status).toBe("completed");
    expect(result.stopSummary?.reason).toBe("already_done");
    const events = readProgressEvents(ledgerDir);
    expect(
      events.some(
        (e) =>
          e.kind === "terminal" &&
          e.status === "completed" &&
          e.epic === 291 &&
          e.stopReason === "already_done",
      ),
    ).toBe(true);
  });

  it("familyDriver durable terminal replay emits terminal progress", async () => {
    const { runFamilyDriver } = await import("../../src/familyDriver.js");
    const { FAMILY_LEDGER_FILENAME } = await import(
      "../../src/family/realFamilyBackend.js"
    );
    const ledgerDir = tempLedger("progress-1007-fd-replay-");
    vi.spyOn(console, "log").mockImplementation(() => {});
    vi.spyOn(console, "info").mockImplementation(() => {});

    writeFileSync(
      join(ledgerDir, FAMILY_LEDGER_FILENAME),
      `${JSON.stringify({
        status: "post_merge_cleanup",
        event: "post_merge_cleanup",
        phase: "final",
        familyHeadAfter: "abc123",
        cleanupOutput: {
          kind: "cleanup",
          terminal: true,
          ok: true,
          issuesClosed: [1008],
          skippedReasons: [],
        },
      })}\n`,
    );

    const result = await runFamilyDriver({
      epicIssue: 1007,
      sourceRepo: "/tmp/source",
      repo: "Akagilnc/ming-salvage-sim",
      familyBase: "family/1007-base",
      base: "main",
      promptsDir: "/tmp/prompts",
      familyPromptsDir: "/tmp/prompts",
      soulsDir: "/tmp/souls",
      ledgerDir,
      imageName: "img",
      sh: () => {
        throw new Error("durable terminal replay must not call GitHub");
      },
      realBackendFactory: () => {
        throw new Error("durable terminal replay must not create worksite");
      },
    });
    expect(result.status).toBe("completed");
    const events = readProgressEvents(ledgerDir);
    expect(
      events.some(
        (e) =>
          e.kind === "terminal" &&
          e.status === "completed" &&
          e.epic === 1007 &&
          e.stopReason === "already_done",
      ),
    ).toBe(true);
  });

  it("stopForCoderRecTightRoutePolicy emits terminal progress (nit pin)", async () => {
    const { runOrchestrator } = await import("../../src/runner.js");
    // S0 Coder-Rec tight stop is pre-worktree — log dual-write only (#1017).
    vi.stubEnv("ORCHESTRATOR_ROUTE", "codex-tight");
    const log = vi.spyOn(console, "log").mockImplementation(() => {});
    vi.spyOn(console, "info").mockImplementation(() => {});
    vi.spyOn(console, "error").mockImplementation(() => {});

    type Backend = import("../../src/types.js").Backend;
    type IssueMeta = import("../../src/types.js").IssueMeta;
    type StepOutput = import("../../src/types.js").StepOutput;
    type StepSpec = import("../../src/types.js").StepSpec;
    type WorktreeHandle = import("../../src/types.js").WorktreeHandle;

    class TightCoderRecBackend implements Backend {
      async smokeModelRoute(route: Parameters<Backend["smokeModelRoute"]>[0]) {
        const { smokeRouteModels } = await import("../../src/modelRoutes.js");
        return smokeRouteModels(route, async () => ({ cliVersion: "t" }));
      }
      async findResumeState() {
        return undefined;
      }
      async resumeSession(spec: StepSpec): Promise<StepOutput> {
        return this.runStep(spec);
      }
      async fetchIssueMeta(issueNumber: number): Promise<IssueMeta> {
        return {
          number: issueNumber,
          isReadyForAgent: true,
          hasSubIssues: false,
          isClosed: false,
          openBlockedBy: [],
          body: "Coder-Rec: terra@med\n",
        };
      }
      async prepareWorktree(issueNumber: number): Promise<WorktreeHandle> {
        return {
          path: join(tmpdir(), `wt-${issueNumber}`),
          branch: `feat/${issueNumber}`,
          base: "main",
        };
      }
      async runStep(spec: StepSpec): Promise<StepOutput> {
        if (spec.role === "coder") {
          return { kind: "coder", committed: true, commitsAdded: 1 };
        }
        return { kind: "judge", status: "converged" };
      }
      async writeLedger(): Promise<void> {
        return;
      }
    }

    const result = await runOrchestrator({
      issueNumber: 1007,
      backend: new TightCoderRecBackend(),
    });
    expect(result.status).toBe("failed");
    const progressLines = log.mock.calls.map((c) => String(c[0]));
    expect(
      progressLines.some(
        (s) =>
          s.includes("[orchestrator:progress]") &&
          s.includes("terminal") &&
          s.includes("status=failed") &&
          s.includes("issue #1007"),
      ),
    ).toBe(true);
  });
});

describe("#1007 CR R5: family quota single emit + CMR judge progress", () => {
  it("family quota park dual-writes park+terminal once (no double notify)", async () => {
    const { runFamily } = await import("../../src/family/runner.js");
    const { buildExplicitLandingLiveHooks } = await import(
      "../../src/family/landing.js"
    );
    const { QuotaWaitForResetError } = await import("../../src/quotaProbe.js");
    const ledgerDir = tempLedger("progress-1007-fam-quota-");
    configureProgressBroadcast({ ledgerDir, epic: 909 });
    vi.spyOn(console, "log").mockImplementation(() => {});
    vi.spyOn(console, "info").mockImplementation(() => {});

    type FamilyBackend = import("../../src/family/types.js").FamilyBackend;
    type FamilyLedgerEntry = import("../../src/family/types.js").FamilyLedgerEntry;

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
      async mergeChildIntoFamilyBase(child: { childIssue: number }) {
        return { familyHead: `+${child.childIssue}` };
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

    const now = new Date("2026-07-14T12:00:00.000Z");
    const resetAt = new Date(now.getTime() + 10 * 60 * 1000);
    const err = new QuotaWaitForResetError({
      disposition: {
        kind: "wait_for_reset",
        pool: "zai",
        resetAt,
        reason: "quota limited (429); wait for reset",
      },
      applied: {
        ledgerEntry: {
          event: "quota_wait_for_reset",
          pool: "zai",
          resetAt: resetAt.toISOString(),
          reason: "quota limited (429); wait for reset",
          step: "S3",
          workerPid: 0,
          ts: "2026-07-14T12:00:00.000Z",
        },
      },
      pool: "zai",
    });
    // Force park via parkOrRelayQuotaWall (true double-emit class) not slot refuse.
    err.cmrPass = "completeness";

    const result = await runFamily({
      epic: { issue: 909, children: [{ issue: 10, blockedBy: [] }] },
      familyBackend,
      singleSliceBackend: await makeConvergingChildBackend(),
      familyBase: "family/909-base",
      now: () => now,
      verifyCmr: async (input) => {
        if (input.phase === "wave") throw err;
        return { ok: true, ran: true };
      },
    });

    expect(result.status).toBe("parked");
    const events = readProgressEvents(ledgerDir);
    const parks = events.filter((e) => e.kind === "park");
    const terminals = events.filter(
      (e) => e.kind === "terminal" && e.status === "parked",
    );
    // R5 must: helper + buildParkResult must not both dual-write
    // (double park/terminal rows ⇒ double notify class).
    expect(parks).toHaveLength(1);
    expect(terminals).toHaveLength(1);
    expect(parks[0]).toMatchObject({ epic: 909 });
  });

  it("family CMR typed judge land emits kind:judge via runVerifyCmr", async () => {
    const { runVerifyCmr } = await import("../../src/family/verifyCmr.js");
    const { buildExplicitLandingLiveHooks } = await import(
      "../../src/family/landing.js"
    );
    const { skeletonReviewLoopWorkerResult } = await import(
      "../../src/reviewLoopOutcome.js"
    );
    const { completeCmrPanelLegWorker } = await import(
      "../helpers/cmr-panel-leg-dispatch.js"
    );
    const ledgerDir = tempLedger("progress-1007-fam-cmr-judge-");
    configureProgressBroadcast({ ledgerDir, epic: 909 });
    vi.spyOn(console, "log").mockImplementation(() => {});
    vi.spyOn(console, "info").mockImplementation(() => {});

    type FamilyBackend = import("../../src/family/types.js").FamilyBackend;
    type FamilyLedgerEntry = import("../../src/family/types.js").FamilyLedgerEntry;
    type WorkerSpec = import("../../src/types.js").WorkerSpec;
    type DispatchContext = import("../../src/types.js").DispatchContext;

    const ledger: FamilyLedgerEntry[] = [];
    let head = "head-1";
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
        return { familyHead: head };
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
      async dispatchWorker(spec: WorkerSpec, ctx: DispatchContext) {
        const panelLeg = completeCmrPanelLegWorker(spec);
        if (panelLeg !== undefined) return panelLeg;
        if (spec.kind === "cmr") {
          return {
            kind: "completed" as const,
            output: {
              kind: "judge" as const,
              status: "converged" as const,
              findingDispositions: dispositions,
              findings,
            },
            sessionId: `judge-${ctx.cmrPass ?? "x"}`,
          };
        }
        if (spec.kind === "ship") {
          return {
            kind: "completed" as const,
            output: {
              kind: "ship" as const,
              branch: ctx.familyBase ?? "family/909-base",
              status: "pr_opened" as const,
              pr: "https://github.com/test/repo/pull/909",
              prHead: head,
            },
          };
        }
        // #600/#603 online-review tail after ship (verify / fixer / landing / cleanup).
        const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
        if (skeleton !== undefined) return skeleton;
        throw new Error(`unexpected worker ${spec.kind}`);
      },
      resolveTelemetryDir() {
        return ledgerDir;
      },
    } as unknown as FamilyBackend;

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/909-base",
      familyBackend,
      familyIssue: 909,
      familyHeadAfter: head,
    });
    expect(result.ok).toBe(true);

    const judges = readProgressEvents(ledgerDir).filter((e) => e.kind === "judge");
    // Completeness + correctness both land typed judge progress.
    expect(judges.length).toBeGreaterThanOrEqual(2);
    expect(
      judges.some(
        (e) =>
          e.kind === "judge" &&
          e.step === "cmr:completeness" &&
          e.verdict === "converged" &&
          e.epic === 909 &&
          e.issue === 909,
      ),
    ).toBe(true);
    expect(
      judges.some(
        (e) =>
          e.kind === "judge" &&
          e.step === "cmr:correctness" &&
          e.verdict === "converged",
      ),
    ).toBe(true);
    // Typed dispositions/severity only — no prose cargo in the feed row.
    const completeness = judges.find(
      (e) => e.kind === "judge" && e.step === "cmr:completeness",
    );
    expect(completeness).toMatchObject({
      dispositions: {
        fix_now: 2,
        refuted: 1,
        suppressed: 1,
      },
    });
  });
});
