import {
  execFileSync,
  mkdtempSync,
  rmSync,
  writeFileSync,
  tmpdir,
  join,
  afterEach,
  describe,
  expect,
  it,
  vi,
  runOrchestrator,
  telemetry,
  Backend,
  FindingDisposition,
  IssueMeta,
  PersistentLedgerEntry,
  ResumeState,
  StepOutput,
  StepSpec,
  WorktreeHandle,
  HappyPathBackend,
} from "./happy-path.shared.js";

describe("runOrchestrator — happy path skeleton (ADR 0030)", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
  });

  it("freezes the real runner telemetry range with held SHAs before deferred collection", async () => {
    const repo = mkdtempSync(join(tmpdir(), "runner-786-telemetry-"));
    try {
      execFileSync("git", ["init", "-q"], { cwd: repo });
      execFileSync("git", ["config", "user.email", "runner@example.test"], { cwd: repo });
      execFileSync("git", ["config", "user.name", "Runner Test"], { cwd: repo });
      writeFileSync(join(repo, "fixture.txt"), "before\n");
      execFileSync("git", ["add", "fixture.txt"], { cwd: repo });
      execFileSync("git", ["commit", "-qm", "base"], { cwd: repo });

      class TelemetryRoutingBackend extends HappyPathBackend {
        override readonly worktree: WorktreeHandle = {
          branch: "feat/orchestrator/issue-786",
          base: "main",
          path: repo,
        };

        override async runStep(spec: StepSpec): Promise<StepOutput> {
          if (spec.role === "coder") {
            writeFileSync(join(repo, "fixture.txt"), "after\n");
            execFileSync("git", ["commit", "-am", "coder commit", "-q"], { cwd: repo });
          }
          return await super.runStep(spec);
        }

        resolveTelemetryDir(): string {
          return join(repo, ".ledger-786");
        }
      }

      let releaseCollection!: () => void;
      const collectionGate = new Promise<void>((resolve) => { releaseCollection = resolve; });
      const schedule = vi.spyOn(telemetry, "scheduleCommitTelemetry")
        .mockImplementation(() => collectionGate);
      const backend = new TelemetryRoutingBackend();

      const result = await runOrchestrator({ issueNumber: 786, backend });

      expect(result.status).toBe("completed");
      expect(backend.runStepIds).toContain("S3");
      expect(schedule).toHaveBeenCalledOnce();
      expect(schedule.mock.calls[0]?.[0]).toMatchObject({
        repoPath: repo,
        worker: { stepId: "S2", modelSlug: "gpt-5.6-terra" },
        before: { kind: "held", oid: expect.stringMatching(/^[0-9a-f]{40}$/) },
        after: { kind: "held", oid: expect.stringMatching(/^[0-9a-f]{40}$/) },
      });
      expect(schedule.mock.calls[0]?.[0].before).not.toEqual(
        schedule.mock.calls[0]?.[0].after,
      );
      releaseCollection();
    } finally {
      rmSync(repo, { recursive: true, force: true });
    }
  });

});
