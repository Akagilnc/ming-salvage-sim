import {
  execFileSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
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
  RealFamilyBackend,
  SHIP_FOCUS_FILENAME,
  ShipAuth,
  modelIdForSlug,
  SANDBOX_CODEX_DIR,
  SANDBOX_GH_TOKEN_ENV,
  SANDBOX_GROK_DIR,
  SANDBOX_REPO_ENV,
  SANDBOX_SOUL_ENV,
  soulsMount,
  SPAWNED_WORKER_ENV,
  cmrWorkerSpec,
  familyShipWorkerSpec,
  isReceiptRecoveryFailure,
  RECEIPT_MAX_RETRIES,
  shipReceiptOutput,
  SHIP_RECEIPT_TAG,
  shipStationReceiptSchema,
  shipOutcomeFromResult,
  ShipWorkerOutcome,
  DispatchContext,
  WorkerSpec,
  isRunnerSynthesizedFailureEscalation,
  runScriptedStructuredOutput,
  ScriptedAgent,
  buildExplicitLandingLiveHooks,
  modelOfAgent,
  here,
  realPromptsDir,
  realSoulsDir,
  cleanups,
  mkDir,
  FAMILY_BASE,
  FixturedShipBackend,
  fixtured,
} from "./ship-worker.shared.js";

afterEach(() => {
  vi.unstubAllEnvs();
  while (cleanups.length > 0) {
    const p = cleanups.pop();
    if (p !== undefined) rmSync(p, { recursive: true, force: true });
  }
});

// ═══════════════════ writeShipFocusFile — pins the CONFIGURED PR target base (cmr S336 r5) ═══════════════════

describe("#336 writeShipFocusFile — threads the configured PR target base into the ship worker", () => {
  /** Expose the focus-file seam over a REAL temp git repo (so the exclude path resolves). */
  class FocusShipBackend extends RealFamilyBackend {
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

    public focus(ctx: {
      familyBase: string;
      escalationAnswer?: DispatchContext["escalationAnswer"];
    }): void {
      this.writeShipFocusFile(ctx as never);
    }
  }
  function realRepo(): string {
    const repo = mkDir("ship-focus-repo-");
    execFileSync("git", ["init", "-q"], { cwd: repo });
    return repo;
  }
  function be(over: Partial<{ base: string; repo: string }> = {}): FocusShipBackend {
    return new FocusShipBackend({
      workingRepo: realRepo(),
      familyBase: FAMILY_BASE,
      ledgerDir: mkDir("ship-focus-ledger-"),
      repo: over.repo ?? "Akagilnc/ming-salvage-sim",
      base: over.base ?? "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
    });
  }

  it("pins the configured non-main PR target base in the ship focus", () => {
    // gstack-ship infers the base from the repo default branch (main), so a
    // configured non-main target (an integration branch) would silently regress to a
    // main-targeted PR. The focus file MUST pin the configured base so the worker
    // overrides gstack-ship's inference.
    const backend = be({ base: "integ/291-wave3" });
    backend.focus({ familyBase: FAMILY_BASE });
    const body = readFileSync(join(backend["opts"].workingRepo, SHIP_FOCUS_FILENAME), "utf8");
    expect(body).toContain("integ/291-wave3");
    expect(body).toContain(FAMILY_BASE);
  });

  it("pins a 'develop' configured base + the family base branch + the repo slug", () => {
    const backend = be({ base: "develop", repo: "Akagilnc/ming-salvage-sim" });
    backend.focus({ familyBase: FAMILY_BASE });
    const body = readFileSync(join(backend["opts"].workingRepo, SHIP_FOCUS_FILENAME), "utf8");
    expect(body).toContain("develop");
    expect(body).toContain(FAMILY_BASE);
    expect(body).toContain("Akagilnc/ming-salvage-sim");
  });

  it("git-ignores the focus file (info/exclude) so the ship never commits it", () => {
    const backend = be({ base: "integ/291-wave3" });
    backend.focus({ familyBase: FAMILY_BASE });
    const exclude = readFileSync(join(backend["opts"].workingRepo, ".git", "info", "exclude"), "utf8");
    expect(exclude.split("\n")).toContain(SHIP_FOCUS_FILENAME);
  });

  it("threads a human escalation answer into the ship focus file", () => {
    const backend = be({ base: "integ/291-wave3" });
    backend.focus({
      familyBase: FAMILY_BASE,
      escalationAnswer: {
        event: "escalation_answered",
        answer: "continue-same-class",
        note: "Human approved retrying the family ship gate.",
      },
    });

    const body = readFileSync(join(backend["opts"].workingRepo, SHIP_FOCUS_FILENAME), "utf8");
    expect(body).toContain("Human escalation answer (#439, data-only)");
    expect(body).toContain("continue-same-class");
    expect(body).toContain("Human approved retrying the family ship gate.");
    expect(body).toMatch(/must not override.*GitHub repo.*PR target base.*PR head branch/is);
  });

  it("runShipWorker writes the focus file BEFORE the container runs (so the worker can read it)", async () => {
    // The worker reads .ship-focus.md FIRST (family_ship.md). Prove runShipWorker
    // produces it before the container spins — trap the container call with a
    // sentinel and assert the focus file is ALREADY on disk when it fires (and that
    // the family base was checked out, i.e. the focus write did not displace the
    // existing checkout contract).
    let focusBodyAtRun: string | undefined;
    class SeamBackend extends RealFamilyBackend {
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

      // Stub the only real-I/O dependency runShipWorker has besides the focus write:
      // the git checkout (the temp repo has no `integ/291-wave3` ref) and sc.run.
      protected override sh(): string {
        return "";
      }
      // The worker's OWN claude token + gh auth ARE present (cmr S336 r8 + r10) — this
      // test isolates the focus-write ordering from the auth preflights, so provide
      // BOTH so runShipWorker proceeds past the preflights to the focus write + container.
      protected override mountShipAuth(): ShipAuth {
        return {
          claudeToken: "tok",
          codexAuthDir: "/x/codex",
          grokAuthDir: "/x/grok",
          ghToken: "gho_ok",
          providerAuth: { claude: true, grok: true, agy: true },
        };
      }
      protected override async shipContainerRun(): Promise<never> {
        // Capture the focus-file state at the moment the container would launch.
        focusBodyAtRun = readFileSync(
          join(this["opts"].workingRepo, SHIP_FOCUS_FILENAME),
          "utf8",
        );
        throw new Error("SENTINEL: container reached");
      }
    }
    const b = new SeamBackend({
      workingRepo: realRepo(),
      familyBase: FAMILY_BASE,
      ledgerDir: mkDir("ship-focus-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "integ/291-wave3",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
    });
    await expect(
      (b as unknown as { runShipWorker(s: WorkerSpec, c: DispatchContext): Promise<unknown> }).runShipWorker(
        familyShipWorkerSpec(),
        { familyBase: FAMILY_BASE },
      ),
    ).rejects.toThrow(/SENTINEL/);
    expect(focusBodyAtRun).toBeDefined();
    expect(focusBodyAtRun).toContain("integ/291-wave3");
  });

  it("family ship with billingPool=grok-build launches the grok provider", async () => {
    let providerAtLaunch: string | undefined;
    class ProviderBackend extends RealFamilyBackend {
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

      protected override sh(): string {
        return "";
      }
      protected override mountShipAuth(): ShipAuth {
        return {
          claudeToken: "tok",
          codexAuthDir: "/x/codex",
          grokAuthDir: "/x/grok",
          ghToken: "gho_ok",
          providerAuth: { claude: true, grok: true, agy: true },
        };
      }
      protected override async shipContainerRun(
        spec: WorkerSpec,
        _auth: ShipAuth,
        _outcomeLanding?: { path: string; sandboxPath: string },
        ctx?: Pick<DispatchContext, "billingPool">,
      ): Promise<never> {
        providerAtLaunch = this.agentForSpec(spec, ctx).name;
        throw new Error("SENTINEL: provider captured");
      }
    }
    const b = new ProviderBackend({
      workingRepo: realRepo(),
      familyBase: FAMILY_BASE,
      ledgerDir: mkDir("ship-provider-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
    });

    await expect(
      (b as unknown as { runShipWorker(s: WorkerSpec, c: DispatchContext): Promise<unknown> }).runShipWorker(
        { ...familyShipWorkerSpec(), model: "grok-4.5" },
        { familyBase: FAMILY_BASE, billingPool: "grok-build" },
      ),
    ).rejects.toThrow(/SENTINEL/);
    expect(providerAtLaunch).toBe("grok");
  });

  it("runShipWorker removes the temporary outcome sidecar directory after parsing it", async () => {
    let outcomePathAtRun: string | undefined;
    class SeamBackend extends RealFamilyBackend {
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

      protected override sh(): string {
        return "";
      }
      protected override mountShipAuth(): ShipAuth {
        return { claudeToken: "tok", ghToken: "gho_ok" };
      }
      protected override async shipContainerRun(
        _spec: WorkerSpec,
        _auth: ShipAuth,
        outcomeLanding?: { path: string; sandboxPath: string },
      ): Promise<Awaited<ReturnType<typeof sc.run>>> {
        if (outcomeLanding === undefined) {
          throw new Error("expected an outcome sidecar landing");
        }
        outcomePathAtRun = outcomeLanding.path;
        writeFileSync(
          outcomeLanding.path,
          JSON.stringify({
            status: "pr_opened",
            branch: FAMILY_BASE,
            pr: "https://github.com/Akagilnc/ming-salvage-sim/pull/999",
          }),
          "utf8",
        );
        return {
          branch: FAMILY_BASE,
          stdout: "<ship>{}</ship>",
          commits: [],
          iterations: [],
          // Typed T2 ship completed (SO was attached on this seat).
          output: { station: "ship", status: "completed" },
        } as Awaited<ReturnType<typeof sc.run>>;
      }
    }
    const b = new SeamBackend({
      workingRepo: realRepo(),
      familyBase: FAMILY_BASE,
      ledgerDir: mkDir("ship-outcome-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
    });

    const out = await (
      b as unknown as { runShipWorker(s: WorkerSpec, c: DispatchContext): Promise<ShipWorkerOutcome> }
    ).runShipWorker(familyShipWorkerSpec(), { familyBase: FAMILY_BASE });

    expect(out.kind).toBe("shipped");
    expect(outcomePathAtRun).toBeDefined();
    expect(existsSync(dirname(outcomePathAtRun as string))).toBe(false);
  });

  it("fails family ship when typed decision Output.object is absent", async () => {
    // #899: SO seat without result.output must not fall through to cargo success.
    class MissingTypedShipBackend extends RealFamilyBackend {
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

      protected override sh(): string {
        return "";
      }
      protected override mountShipAuth(): ShipAuth {
        return { claudeToken: "tok", ghToken: "gho_ok" };
      }
      public probeRunShipWorker(
        spec: WorkerSpec,
        ctx: DispatchContext,
      ): Promise<ShipWorkerOutcome> {
        return this.runShipWorker(spec, ctx);
      }
      protected override async shipContainerRun(
        _spec: WorkerSpec,
        _auth: ShipAuth,
        outcomeLanding?: { path: string; sandboxPath: string },
      ): Promise<Awaited<ReturnType<typeof sc.run>>> {
        if (outcomeLanding !== undefined) {
          writeFileSync(
            outcomeLanding.path,
            JSON.stringify({
              status: "pr_opened",
              branch: FAMILY_BASE,
              pr: "https://github.com/Akagilnc/ming-salvage-sim/pull/999",
            }),
            "utf8",
          );
        }
        return {
          branch: FAMILY_BASE,
          stdout: "<ship>{}</ship>",
          commits: [],
          iterations: [],
        } as Awaited<ReturnType<typeof sc.run>>;
      }
    }
    const b = new MissingTypedShipBackend({
      workingRepo: realRepo(),
      familyBase: FAMILY_BASE,
      ledgerDir: mkDir("ship-missing-typed-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
    });

    await expect(
      b.probeRunShipWorker(familyShipWorkerSpec(), { familyBase: FAMILY_BASE }),
    ).rejects.toThrow(/typed traffic signal missing/);
  });

  it("attaches T2 ship envelope Output.object for family ship without cargo-shape re-ask", async () => {
    // #919 D: ship seat uses T2 ship envelope on SHIP_RECEIPT_TAG;
    // PR/URL cargo stays on the opaque sidecar channel (never SO).
    class CaptureShipBackend extends RealFamilyBackend {
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

      public calls: Parameters<typeof sc.run>[0][] = [];
      protected override sh(): string {
        return "";
      }
      protected override mountShipAuth(): ShipAuth {
        return { claudeToken: "tok", ghToken: "gho_ok" };
      }
      /** Typed public probe — no `as unknown as` cast. */
      public probeRunShipWorker(
        spec: WorkerSpec,
        ctx: DispatchContext,
      ): Promise<ShipWorkerOutcome> {
        return this.runShipWorker(spec, ctx);
      }
      protected override async runAgentSandbox(
        options: Parameters<typeof sc.run>[0],
      ): Promise<Awaited<ReturnType<typeof sc.run>>> {
        this.calls.push(options);
        // Typed T2 ship completed traffic. Delivery cargo is sidecar-only.
        return {
          branch: FAMILY_BASE,
          stdout: '<ship>{"station":"ship","status":"completed"}</ship>',
          commits: [],
          iterations: [],
          output: { station: "ship", status: "completed" },
        } as Awaited<ReturnType<typeof sc.run>>;
      }
    }
    const b = new CaptureShipBackend({
      workingRepo: realRepo(),
      familyBase: FAMILY_BASE,
      ledgerDir: mkDir("ship-signal-so-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
    });

    const out = await b.probeRunShipWorker(familyShipWorkerSpec(), {
      familyBase: FAMILY_BASE,
    });

    // T2 completed + empty sidecar cargo → completed (exit is success channel).
    expect(out.kind).toBe("completed");
    expect(b.calls).toHaveLength(1);
    expect(b.calls[0]!.output).toMatchObject({
      tag: SHIP_RECEIPT_TAG,
      maxRetries: RECEIPT_MAX_RETRIES,
    });
    // Not decision-gate dual — ship seat owns the T2 ship tag.
    expect(b.calls[0]!.output).not.toMatchObject({ tag: "decision" });
  });
});

// ─── #919 D: ship production T2 envelope SO four-case matrix ────────────────
// Ship attaches shipStationReceiptSchema on SHIP_RECEIPT_TAG; cargo (status/pr)
// stays opaque sidecar. Four-case crosses production runShipWorker + real sc.run.
// #962: per-run GIT_CONFIG_GLOBAL isolation removes the old sequential need.
describe("#919 ship production T2 envelope SO four-case", () => {
  function shipFourCaseBackend(opts: {
    emissions: ReadonlyArray<{ body: string }>;
    sessionId: string;
    resumable?: boolean;
    name?: string;
    agentOut?: { agent?: ScriptedAgent };
    sandcastleCalls: { n: number };
  }): RealFamilyBackend & {
    probeRunShipWorker(
      spec: WorkerSpec,
      ctx: DispatchContext,
    ): Promise<ShipWorkerOutcome>;
  } {
    class Backend extends RealFamilyBackend {
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

      public probeRunShipWorker(
        spec: WorkerSpec,
        ctx: DispatchContext,
      ): Promise<ShipWorkerOutcome> {
        return this.runShipWorker(spec, ctx);
      }
      protected override sh(): string {
        return "";
      }
      protected override mountShipAuth(): ShipAuth {
        return { claudeToken: "tok", ghToken: "gho_ok" };
      }
      protected override async runAgentSandbox(
        options: Parameters<typeof sc.run>[0],
      ): Promise<Awaited<ReturnType<typeof sc.run>>> {
        opts.sandcastleCalls.n += 1;
        // Production ship seat must bind T2 ship SO + maxRetries.
        expect(options.output).toEqual(
          expect.objectContaining({
            tag: SHIP_RECEIPT_TAG,
            maxRetries: RECEIPT_MAX_RETRIES,
          }),
        );
        const run = await runScriptedStructuredOutput({
          tag: SHIP_RECEIPT_TAG,
          schema: shipStationReceiptSchema(),
          emissions: opts.emissions,
          maxRetries: RECEIPT_MAX_RETRIES,
          sessionId: opts.sessionId,
          resumable: opts.resumable,
          name: opts.name,
          cleanups,
          agentOut: opts.agentOut,
        });
        return run.result;
      }
    }
    return new Backend({
      workingRepo: (() => {
        const repo = mkDir("ship-so-four-case-repo-");
        execFileSync("git", ["init", "-q"], { cwd: repo });
        return repo;
      })(),
      familyBase: FAMILY_BASE,
      ledgerDir: mkDir("ship-so-four-case-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
    });
  }

  it("accepts initial-good T2 ship completed via production ship + real sc.run", async () => {
    // first-good: station:ship status:completed → completed (cargo miss is fine).
    const sandcastleCalls = { n: 0 };
    const agentOut: { agent?: ScriptedAgent } = {};
    const be = shipFourCaseBackend({
      emissions: [
        {
          body: JSON.stringify({ station: "ship", status: "completed" }),
        },
      ],
      sessionId: "prod-ship-t2-initial-good",
      agentOut,
      sandcastleCalls,
    });
    await expect(
      be.probeRunShipWorker(familyShipWorkerSpec(), { familyBase: FAMILY_BASE }),
    ).resolves.toEqual({ kind: "completed" });
    expect(sandcastleCalls.n).toBe(1);
    expect(agentOut.agent?.callCount).toBe(1);
    expect(agentOut.agent?.resumedSessions).toEqual([undefined]);
  });

  it("accepts T2 ship shipped envelope via production ship + real sc.run", async () => {
    const sandcastleCalls = { n: 0 };
    const agentOut: { agent?: ScriptedAgent } = {};
    const be = shipFourCaseBackend({
      emissions: [
        {
          body: JSON.stringify({ station: "ship", status: "shipped" }),
        },
      ],
      sessionId: "prod-ship-t2-shipped",
      agentOut,
      sandcastleCalls,
    });
    await expect(
      be.probeRunShipWorker(familyShipWorkerSpec(), { familyBase: FAMILY_BASE }),
    ).resolves.toEqual({ kind: "shipped" });
    expect(sandcastleCalls.n).toBe(1);
    expect(agentOut.agent?.callCount).toBe(1);
  });

  it("recovers T2 ship escalate bad→good via production ship + real sc.run", async () => {
    const sandcastleCalls = { n: 0 };
    const agentOut: { agent?: ScriptedAgent } = {};
    const good = {
      station: "ship",
      status: "escalate",
      reason: "owner choice",
      diagnosis: "contract fork",
    };
    const be = shipFourCaseBackend({
      emissions: [
        {
          body: JSON.stringify({
            station: "ship",
            status: "escalate",
            reason: "",
            diagnosis: "x",
          }),
        },
        { body: JSON.stringify(good) },
      ],
      sessionId: "prod-ship-t2-recover",
      agentOut,
      sandcastleCalls,
    });
    await expect(
      be.probeRunShipWorker(familyShipWorkerSpec(), { familyBase: FAMILY_BASE }),
    ).resolves.toMatchObject({
      kind: "escalate",
      reason: "owner choice",
      diagnosis: "contract fork",
    });
    expect(sandcastleCalls.n).toBe(1);
    expect(agentOut.agent?.callCount).toBe(2);
    expect(agentOut.agent?.resumedSessions).toEqual([
      undefined,
      "prod-ship-t2-recover",
    ]);
  });

  it("propagates StructuredOutputError when ship T2 envelope maxRetries exhaust", async () => {
    // exhaust SOE → Action non-zero for #598; never invent cargo success.
    const sandcastleCalls = { n: 0 };
    const agentOut: { agent?: ScriptedAgent } = {};
    const be = shipFourCaseBackend({
      emissions: [
        {
          body: JSON.stringify({
            station: "ship",
            status: "escalate",
            reason: "",
            diagnosis: "",
          }),
        },
        {
          body: JSON.stringify({
            station: "ship",
            status: "escalate",
            reason: "",
            diagnosis: "x",
          }),
        },
        {
          body: JSON.stringify({
            station: "ship",
            status: "escalate",
            reason: "x",
            diagnosis: "",
          }),
        },
      ],
      sessionId: "prod-ship-t2-exhausted",
      agentOut,
      sandcastleCalls,
    });
    await expect(
      be.probeRunShipWorker(familyShipWorkerSpec(), { familyBase: FAMILY_BASE }),
    ).rejects.toSatisfy((err: unknown) => {
      // FiberFailure/ExecError wrap is load-dependent; recovery class is the contract.
      expect(isReceiptRecoveryFailure(err)).toBe(true);
      return true;
    });
    // One production sc.run; native same-session resumes are inside it.
    expect(sandcastleCalls.n).toBe(1);
    expect(agentOut.agent?.callCount).toBe(RECEIPT_MAX_RETRIES + 1);
  });

  it("classifies non-resumable ship T2 envelope maxRetries as recovery failure", async () => {
    const sandcastleCalls = { n: 0 };
    const be = shipFourCaseBackend({
      emissions: [
        {
          body: JSON.stringify({ station: "ship", status: "completed" }),
        },
      ],
      sessionId: "prod-ship-t2-nonresumable",
      resumable: false,
      name: "grok",
      sandcastleCalls,
    });
    await expect(
      be.probeRunShipWorker(familyShipWorkerSpec(), { familyBase: FAMILY_BASE }),
    ).rejects.toSatisfy((err: unknown) => {
      expect(err).toBeInstanceOf(Error);
      expect((err as Error).message).toMatch(
        /output\.maxRetries requires an agent provider that supports session resumption/i,
      );
      expect(isReceiptRecoveryFailure(err)).toBe(true);
      return true;
    });
    expect(sandcastleCalls.n).toBe(1);
  });
});
