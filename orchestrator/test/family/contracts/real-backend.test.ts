import {
  execFileSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  symlinkSync,
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
  discoverSubprojects,
  cmrOutcomeFromResult,
  mergerOutcomeFromResult,
  MergerAuth,
  parseCmrOutcome,
  REFERENCED_FAMILY_PROMPT_FILES,
  RealFamilyBackend,
  RealFamilyBackendOptions,
  familyEscalationState,
  MAX_DISPATCH_ATTEMPTS,
  SANDBOX_SKILLS_DIR,
  soulsMount,
  ConflictResolveRequest,
  FamilyVerifyRequest,
  IntegratedCmrRequest,
  IntegratedCmrResult,
  DEFAULT_IMAGE_TAG,
  resolveImageTag,
  PROVISION_SUBPROCESS_TIMEOUT_MS,
  WorkerSpec,
  telemetry,
  buildExplicitLandingLiveHooks,
  here,
  realPromptsDir,
  realSoulsDir,
  git,
  makeRepo,
  commitFile,
  tempState,
  trackTempDir,
  trackRepo,
  opts,
  FakeSeamsBackend,
} from "./real-backend.shared.js";

afterEach(() => {
  for (const r of tempState.repos) rmSync(r, { recursive: true, force: true });
  for (const d of tempState.ledgerDirs) rmSync(d, { recursive: true, force: true });
  tempState.repos = [];
  tempState.ledgerDirs = [];
});

// ═══════════════════════════════ 3. ReconcileGit ════════════════════════════

describe("RealFamilyBackend ReconcileGit predicates (#291 real git)", () => {

  it("runFamilyVerify runs the project's npm typecheck+test from verifyCwd, NOT the clone root (online R2 Codex P1 / #5)", async () => {
    // The clone is the FULL repo; a project's package.json/scripts live under a
    // subdir (e.g. `<clone>/orchestrator`). The verify commands must run from
    // `verifyCwd`, and (#5) be the PROJECT'S OWN npm scripts, not a hardcoded npx.
    const calls: Array<{ file: string; args: string[]; cwd?: string }> = [];
    class SpyBackend extends RealFamilyBackend {
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

      protected override sh(file: string, args: string[], cwd?: string): string {
        calls.push({ file, args, cwd });
        return "";
      }
      protected override packageScripts(_cwd: string): readonly string[] {
        return ["typecheck", "test"]; // orchestrator's scripts
      }
      protected override isNodeProject(_cwd: string): boolean {
        return true;
      }
      async runVerifyForTest(): Promise<void> {
        await this.runVerifyCommands({ phase: "final", familyBase: "family/293-base" });
      }
      public waitForStamps(): Promise<void> { return this.waitForVerificationStamps(); }
    }
    const backend = new SpyBackend(opts("/clone/root", { verifyCwd: "/clone/root/orchestrator" }));
    await backend.runVerifyForTest();
    await backend.waitForStamps();
    // Unconditional install first (by construction), then project's scripts.
    // (installDeps chooses "ci" or "install" based on whether lockfile exists at the cwd path.)
    expect(calls[0].file).toBe("npm");
    expect(["ci", "install"]).toContain(calls[0].args[0]);
    expect(calls[0].cwd).toBe("/clone/root/orchestrator");
    expect(calls.slice(1).map((c) => `${c.file} ${c.args.join(" ")}`)).toEqual([
      "npm run typecheck",
      "npm test",
    ]);
    expect(calls.slice(1).every((c) => c.cwd === "/clone/root/orchestrator")).toBe(true);
  });

  it("never appends telemetry reporters or compiler flags to the project's declared verify commands (#786)", async () => {
    const calls: Array<{ file: string; args: string[]; cwd?: string }> = [];
    class SpyBackend extends RealFamilyBackend {
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

      protected override sh(file: string, args: string[], cwd?: string): string {
        calls.push({ file, args, cwd });
        return "";
      }
      protected override packageScripts(_cwd: string): readonly string[] {
        return ["typecheck", "test"];
      }
      protected override isNodeProject(_cwd: string): boolean {
        return true;
      }
      async runVerifyForTest(): Promise<void> {
        await this.runVerifyCommands({ phase: "final", familyBase: "family/293-base" });
      }
      public waitForStamps(): Promise<void> { return this.waitForVerificationStamps(); }
    }

    const backend = new SpyBackend(opts("/clone/root", { verifyCwd: "/clone/root/orchestrator" }));
    await backend.runVerifyForTest();
    await backend.waitForStamps();
    expect(calls.slice(1).map((c) => `${c.file} ${c.args.join(" ")}`)).toEqual([
      "npm run typecheck",
      "npm test",
    ]);
  });

  it("#3 + #372 P2: ALWAYS runs installDeps (unconditional, by construction) even when node_modules EXISTS and manifest changed after a wave", async () => {
    // #372 P2: runVerifyCommands must not condition install on depsInstalled presence.
    // Freshness by construction: later waves in family can change package.json / package-lock.json
    // inside the (shared) family clone; verify must still run install (npm ci idempotent) on
    // the (now potentially stale) node_modules. We simulate "node_modules exists + manifest changed"
    // by creating a temp Node project dir with node_modules present, then updating the lock manifest
    // (post-"wave" mutation), and asserting install is STILL invoked before scripts.
    // No mtime/manifest compare is re-introduced (per direction).
    const calls: Array<{ file: string; args: string[]; cwd?: string }> = [];
    const proj = trackTempDir("verify-uncond-install-");
    const pkg = join(proj, "package.json");
    const lock = join(proj, "package-lock.json");
    const nm = join(proj, "node_modules");
    writeFileSync(pkg, JSON.stringify({ name: "test-proj", version: "0.0.0" }));
    writeFileSync(lock, JSON.stringify({ name: "test-proj", version: "0.0.0", lockfileVersion: 3 }));
    mkdirSync(nm, { recursive: true });
    // Simulate a later wave mutating the manifest (new lock content after node_modules was laid).
    writeFileSync(lock, JSON.stringify({ name: "test-proj", version: "0.0.1", lockfileVersion: 3, "updated-by-wave": true }));

    class SpyBackend extends RealFamilyBackend {
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

      protected override sh(file: string, args: string[], cwd?: string): string {
        calls.push({ file, args, cwd });
        return "";
      }
      protected override packageScripts(_cwd: string): readonly string[] {
        return ["typecheck", "test"];
      }
      protected override isNodeProject(_cwd: string): boolean {
        return true;
      }
      async runVerifyForTest(): Promise<void> {
        await this.runVerifyCommands({ phase: "final", familyBase: "family/293-base" });
      }
      public waitForStamps(): Promise<void> { return this.waitForVerificationStamps(); }
    }
    // Note: pass verifyCwd=proj so run reaches install+scripts (isNode true by override).
    // We do NOT override depsInstalled (it no longer exists).
    const backend = new SpyBackend(opts("/clone/root", { verifyCwd: proj }));
    await backend.runVerifyForTest();
    await backend.waitForStamps();
    // Install MUST run (first) even though node_modules existed + manifest mutated post-wave.
    expect(calls[0].file).toBe("npm");
    expect(["ci", "install"]).toContain(calls[0].args[0]);
    expect(calls[0].cwd).toBe(proj);
    // Then the project's verify scripts, still in cwd.
    expect(calls.slice(1).map((c) => `${c.file} ${c.args.join(" ")}`)).toEqual([
      "npm run typecheck",
      "npm test",
    ]);
    expect(calls.slice(1).every((c) => c.cwd === proj)).toBe(true);
  });

  it("#5/R1-T3: runs web's OWN scripts — `npm run build` (its tsc check) then `npm test` (jsdom), never raw npx", async () => {
    // #5: web/'s test = `vitest run --environment jsdom`; a hardcoded `npx vitest run`
    // dropped `--environment jsdom` → `document is not defined`. R1 T3 (codex): web/
    // has NO `typecheck` script — its TS check lives in `build` (`tsc -b && vite build`).
    // So type-check must fall back to `npm run build`, NOT be silently skipped (else a
    // web change with TS errors passes verify as long as Vitest does).
    const calls: Array<{ file: string; args: string[]; cwd?: string }> = [];
    class SpyBackend extends RealFamilyBackend {
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

      protected override sh(file: string, args: string[], cwd?: string): string {
        calls.push({ file, args, cwd });
        return "";
      }
      protected override packageScripts(_cwd: string): readonly string[] {
        return ["dev", "build", "test", "preview"]; // web's scripts — NO `typecheck`
      }
      protected override isNodeProject(_cwd: string): boolean {
        return true;
      }
      async runVerifyForTest(): Promise<void> {
        await this.runVerifyCommands({ phase: "final", familyBase: "family/293-base" });
      }
      public waitForStamps(): Promise<void> { return this.waitForVerificationStamps(); }
    }
    const backend = new SpyBackend(opts("/clone/root", { verifyCwd: "/clone/root/web" }));
    await backend.runVerifyForTest();
    await backend.waitForStamps();
    // Unconditional install first (even if node_modules "existed"), then web's scripts.
    expect(calls[0].file).toBe("npm");
    expect(["ci", "install"]).toContain(calls[0].args[0]);
    expect(calls[0].cwd).toBe("/clone/root/web");
    expect(calls.slice(1).map((c) => `${c.file} ${c.args.join(" ")}`)).toEqual([
      "npm run build",
      "npm test",
    ]);
    expect(calls.some((c) => c.file === "npx")).toBe(false);
    expect(calls.slice(1).every((c) => c.cwd === "/clone/root/web")).toBe(true);
  });

  it("R1-T2: a diff touching NO Node subproject (cwd undefined) → verify is a no-op, never npm in the clone root", async () => {
    // codex R1 T2: `inferVerifyCwd` returns undefined for a docs/content/root-only
    // diff. The old `?? workingRepo` fallback ran `npm install` + scripts in the clone
    // ROOT (no package.json) → verify_failed for valid non-code changes. Now: skip.
    const calls: Array<{ file: string; args: string[]; cwd?: string }> = [];
    class SpyBackend extends RealFamilyBackend {
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

      protected override sh(file: string, args: string[], cwd?: string): string {
        calls.push({ file, args, cwd });
        return "";
      }
      runVerifyForTest(): void {
        this.runVerifyCommands({ phase: "final", familyBase: "family/293-base" });
      }
    }
    // No verifyCwd, and resolveVerifyCwd returns undefined (non-Node diff).
    new SpyBackend(opts("/clone/root", { resolveVerifyCwd: () => undefined })).runVerifyForTest();
    expect(calls).toEqual([]); // nothing installed, nothing run
  });

  it("ID-011: package.json probe operational error (ELOOP) fails closed — never soft-skip as non-Node", async () => {
    // existsSync returns false on ELOOP; the old isNodeProject then treated the
    // project as non-Node and legally skipped verify. Probe must throw instead.
    const root = trackTempDir("verify-eloop-");
    const loopPath = join(root, "package.json");
    symlinkSync(loopPath, loopPath);
    class SpyBackend extends RealFamilyBackend {
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
        throw new Error("verify commands must not run after probe failure");
      }
      async runVerifyForTest(): Promise<void> {
        await this.runVerifyCommands({ phase: "final", familyBase: "family/293-base" });
      }
    }
    const backend = new SpyBackend(
      opts(root, { resolveVerifyCwd: () => undefined }),
    );
    await expect(backend.runVerifyForTest()).rejects.toThrow(
      /package\.json probe failed|ELOOP|too many levels/i,
    );
  });

  it("R3: a SINGLE-project repo (package.json at the clone ROOT) falls back to workingRepo verify", async () => {
    // gemini R3: dropping the `?? workingRepo` fallback made single-project tempState.repos
    // (package.json at root, no subproject) skip verify entirely. Restore the
    // fallback — but ONLY when the root IS a Node project (multi-project non-Node
    // root still skips, R1 T2).
    const calls: Array<{ file: string; args: string[]; cwd?: string }> = [];
    class SpyBackend extends RealFamilyBackend {
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

      protected override sh(file: string, args: string[], cwd?: string): string {
        calls.push({ file, args, cwd });
        return "";
      }
      protected override isNodeProject(_cwd: string): boolean {
        return true; // the clone root has a package.json (single-project repo)
      }
      protected override packageScripts(_cwd: string): readonly string[] {
        return ["test"];
      }
      async runVerifyForTest(): Promise<void> {
        await this.runVerifyCommands({ phase: "final", familyBase: "family/293-base" });
      }
      public waitForStamps(): Promise<void> { return this.waitForVerificationStamps(); }
    }
    // No verifyCwd; resolver undefined (no subproject) → root is Node → verify at root.
    const backend = new SpyBackend(opts("/clone/root", { resolveVerifyCwd: () => undefined }));
    await backend.runVerifyForTest();
    await backend.waitForStamps();
    // Unconditional: install first, then test.
    expect(calls[0].file).toBe("npm");
    expect(["ci", "install"]).toContain(calls[0].args[0]);
    expect(calls[0].cwd).toBe("/clone/root");
    expect(calls.slice(1).map((c) => `${c.file} ${c.args.join(" ")}`)).toEqual(["npm test"]);
    expect(calls.slice(1).every((c) => c.cwd === "/clone/root")).toBe(true);
  });

  it("R1-T3: an EXPLICIT verifyCwd that is NOT a Node project FAILS CLOSED (throws), never silent-passes", async () => {
    // codex R1 T3: a docs/content/root-only diff (inferred-undefined) legitimately
    // skips, but an EXPLICITLY-set verifyCwd pointing at a non-Node dir is a caller
    // misconfig — it must NOT be treated like "nothing to verify" and green-light an
    // un-verified merge. (An inference-FAILURE fails closed via familyDiffFiles, which
    // no longer swallows git errors.)
    class SpyBackend extends RealFamilyBackend {
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
      protected override isNodeProject(_cwd: string): boolean {
        return false; // explicit cwd has no package.json
      }
      async runVerifyForTest(): Promise<void> {
        await this.runVerifyCommands({ phase: "final", familyBase: "family/293-base" });
      }
    }
    await expect(
      new SpyBackend(opts("/clone/root", { verifyCwd: "/clone/root/not-node" })).runVerifyForTest(),
    ).rejects.toThrow(/not a Node project/i);
  });

  it("#939 ID-011: package.json parse operational error fails closed — never empty-command success", async () => {
    // Production packageScripts used to catch read/parse errors and return [] →
    // zero-command pseudo-success. Malformed manifest must fail verify.
    const proj = trackTempDir("verify-op-err-");
    writeFileSync(join(proj, "package.json"), "{not-valid-json");
    const npmCalls: string[] = [];
    class SpyBackend extends RealFamilyBackend {
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

      protected override sh(file: string, args: string[]): string {
        if (file === "npm") npmCalls.push(args.join(" "));
        return "";
      }
      protected override async installDeps(): Promise<void> {
        throw new Error("installDeps must not run after package.json operational error");
      }
    }
    const result = await new SpyBackend(
      opts("/clone/root", { verifyCwd: proj }),
    ).runFamilyVerify({ phase: "final", familyBase: "family/293-base" });
    expect(result.ok).toBe(false);
    expect(result.errorPackage?.reason).toMatch(/parse package\.json|failed to parse/i);
    expect(npmCalls).toEqual([]);
  });

  it("#939 ID-011: successful empty scripts is legal skip (no install, no npm, ok:true)", async () => {
    // Only a successful read that confirms no typecheck/build/test scripts may skip.
    const proj = trackTempDir("verify-empty-scripts-");
    writeFileSync(
      join(proj, "package.json"),
      JSON.stringify({ name: "empty-scripts", version: "0.0.0", scripts: { dev: "echo hi" } }),
    );
    const npmCalls: string[] = [];
    class SpyBackend extends RealFamilyBackend {
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

      protected override sh(file: string, args: string[]): string {
        if (file === "npm") npmCalls.push(args.join(" "));
        return "";
      }
      protected override async installDeps(): Promise<void> {
        throw new Error("installDeps must not run on legal empty command set");
      }
    }
    await expect(
      new SpyBackend(opts("/clone/root", { verifyCwd: proj })).runFamilyVerify({
        phase: "final",
        familyBase: "family/293-base",
      }),
    ).resolves.toEqual({ ok: true });
    expect(npmCalls).toEqual([]);
  });

  it("#939 ID-011 negative: unreadable package.json (missing after Node check) fails closed", async () => {
    // isNodeProject can be true while a subsequent read fails (race / override).
    // That is operational error, not legal empty.
    class SpyBackend extends RealFamilyBackend {
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
      protected override isNodeProject(): boolean {
        return true;
      }
      protected override async installDeps(): Promise<void> {
        throw new Error("installDeps must not run after package.json read failure");
      }
    }
    const missing = join(trackTempDir("verify-missing-pkg-"), "no-such-dir");
    const result = await new SpyBackend(
      opts("/clone/root", { verifyCwd: missing }),
    ).runFamilyVerify({ phase: "wave", familyBase: "family/293-base" });
    expect(result.ok).toBe(false);
    expect(result.errorPackage?.reason).toMatch(/failed to read package\.json/i);
  });

  it("#939 ID-011: invalid scripts shape fails closed (not Object.keys empty skip)", async () => {
    const proj = trackTempDir("verify-scripts-shape-");
    writeFileSync(
      join(proj, "package.json"),
      JSON.stringify({ name: "bad", version: "0.0.0", scripts: ["test"] }),
    );
    class SpyBackend extends RealFamilyBackend {
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
      protected override async installDeps(): Promise<void> {
        throw new Error("installDeps must not run after scripts shape error");
      }
    }
    const result = await new SpyBackend(opts("/clone/root", { verifyCwd: proj })).runFamilyVerify({
      phase: "final",
      familyBase: "family/293-base",
    });
    expect(result.ok).toBe(false);
    expect(result.errorPackage?.reason).toMatch(/scripts.*must be an object/i);
  });

});

// ════════ 3b. construction-time prompt validation (gap g, same-type C-3) ═══════
//
// RealBackend (single slice) validates promptsDir at construction (C-3): every
// REFERENCED_PROMPT_FILES entry, derived from the worker specs, must exist or the
// constructor throws — a missing prompt surfaces THERE, not deep in the first
// sandbox.run(). RealFamilyBackend lazily resolves its family prompts
// (integrated CMR pass prompts / family_ship.md / merger_resolve_conflict.md) at dispatch
// time, so a missing one would only blow up at run time. These tests pin the
// SAME construction-time net at the family layer.
describe("RealFamilyBackend construction-time prompt validation (gap g, same-type C-3)", () => {
  /** A promptsDir holding exactly the named family prompt files. */
  function promptsDirWith(files: string[]): string {
    const dir = mkdtempSync(join(tmpdir(), "rfb-prompts-"));
    tempState.ledgerDirs.push(dir); // reuse the afterEach cleanup list
    for (const f of files) {
      execFileSync("bash", ["-c", `printf '%s' 'x' > '${join(dir, f)}'`]);
    }
    return dir;
  }

  it("family inventory covers every prompt dispatched by the family workflow", () => {
    expect(new Set(REFERENCED_FAMILY_PROMPT_FILES)).toEqual(
      new Set([
        "integrated_cmr_completeness.md",
        "integrated_cmr_correctness.md",
        "cmr_panel_leg.md",
        "wave_verify_judge.md",
        "coder_fix.md",
        "family_ship.md",
        "merger_resolve_conflict.md",
        "collector.md",
        "verify.md",
        "fixer.md",
        "landing.md",
      ]),
    );
  });

  it("construction throws when the family prompt inventory is incomplete", () => {
    // #1068 regression net: a promptsDir holding every inventory entry EXCEPT
    // wave_verify_judge.md must fail closed at construction, not fail open and
    // surface only at the first red-wave triage dispatch.
    const dir = promptsDirWith(
      REFERENCED_FAMILY_PROMPT_FILES.filter((f) => f !== "wave_verify_judge.md"),
    );
    expect(() => new RealFamilyBackend(opts("/clone/root", { promptsDir: dir }))).toThrow(
      /wave_verify_judge\.md/,
    );
  });

  it("construction throws when collector.md is missing from promptsDir (#1145)", () => {
    // Collector is family-dispatched (S13); missing prompt must fail at
    // construction, not after ship on the first Collector dispatch.
    const dir = promptsDirWith(
      REFERENCED_FAMILY_PROMPT_FILES.filter((f) => f !== "collector.md"),
    );
    expect(() => new RealFamilyBackend(opts("/clone/root", { promptsDir: dir }))).toThrow(
      /collector\.md/,
    );
  });

});

describe("RealFamilyBackend resolveMergeConflict (#291 sc.run merger seam)", () => {

  it("a sparse merger T2 escalate fails the Action instead of inventing a park", () => {
    // #899 / #919 CR T2: empty escalate on the thin merger envelope fails closed.
    expect(() =>
      mergerOutcomeFromResult({
        output: { station: "merger", status: "escalate" },
        stdout: "",
      }),
    ).toThrow(/illegal merger station receipt/);
  });

});

// #919 CR N1: parseMergerOutcome dual DELETED. Resolve cargo + T2 escalate
// live only on mergerOutcomeFromResult / decodeMergerEnvelope.
describe("merger resolve cargo (#291 pure, T2-only)", () => {
  it("parses a resolved stdout cargo tag (no typed envelope)", () => {
    expect(
      mergerOutcomeFromResult({
        stdout:
          'blah\n<merger>{"resolved": true, "tradeoffs": ""}</merger>\nMERGER_STEP_COMPLETE',
      }),
    ).toEqual({ resolved: true });
  });
  it("stdout escalate is cargo-stripped, not a fate bell (T2 owns escalate)", () => {
    // #919 CR N1: nested escalate on stdout never parks — fate is T2 envelope.
    const out = mergerOutcomeFromResult({
      stdout:
        '<merger>{"resolved": false, "escalate": {"reason": "ambiguous", "diagnosis": "needs decision"}}</merger>',
    });
    expect(out.resolved).toBe(false);
    expect(out.escalation).toBeUndefined();
  });
  it("no tag → not resolved", () => {
    expect(mergerOutcomeFromResult({ stdout: "nothing here" }).resolved).toBe(
      false,
    );
  });
  it("takes the LAST tag when the agent iterated", () => {
    const out = mergerOutcomeFromResult({
      stdout:
        '<merger>{"resolved": false, "escalate": {"reason": "first"}}</merger>' +
        '<merger>{"resolved": true}</merger>',
    });
    expect(out).toEqual({ resolved: true });
  });
  it("a non-object JSON payload (null / true / number) is unresolved, NOT a crash", () => {
    expect(
      mergerOutcomeFromResult({ stdout: "<merger>null</merger>" }),
    ).toEqual({
      resolved: false,
      reason: "merger agent <merger> tag was not a JSON object",
    });
    expect(
      mergerOutcomeFromResult({ stdout: "<merger>true</merger>" }).resolved,
    ).toBe(false);
    expect(
      mergerOutcomeFromResult({ stdout: "<merger>42</merger>" }).resolved,
    ).toBe(false);
    expect(
      mergerOutcomeFromResult({ stdout: "<merger>[]</merger>" }),
    ).toEqual({
      resolved: false,
      reason: "merger agent <merger> tag was not a JSON object",
    });
  });

  describe("Finding A — strict resolve cargo shape", () => {
    it("resolved:true carrying escalate is stripped → still resolves when cargo is clean", () => {
      // escalate key is stripped before strict resolve schema; pure resolve remains.
      const out = mergerOutcomeFromResult({
        stdout:
          '<merger>{"resolved": true, "escalate": {"reason": "r", "diagnosis": "d"}}</merger>',
      });
      expect(out).toEqual({ resolved: true });
    });

    it("resolved:true carrying an unknown EXTRA key ⇒ NOT resolved (strict)", () => {
      expect(
        mergerOutcomeFromResult({
          stdout: '<merger>{"resolved": true, "junk": 1}</merger>',
        }).resolved,
      ).toBe(false);
    });

    it("resolved as a NON-boolean ⇒ NOT resolved", () => {
      expect(
        mergerOutcomeFromResult({
          stdout: '<merger>{"resolved": "true"}</merger>',
        }).resolved,
      ).toBe(false);
    });

    it("still accepts the LEGAL success shapes (regression: with/without tradeoffs)", () => {
      expect(
        mergerOutcomeFromResult({
          stdout: '<merger>{"resolved": true}</merger>',
        }),
      ).toEqual({ resolved: true });
      expect(
        mergerOutcomeFromResult({
          stdout:
            '<merger>{"resolved": true, "tradeoffs": "picked left"}</merger>',
        }),
      ).toEqual({ resolved: true });
    });

    it("T2 merger escalate parks decision (sole fate channel)", () => {
      const out = mergerOutcomeFromResult({
        output: {
          station: "merger",
          status: "escalate",
          reason: "ambiguous",
          diagnosis: "needs decision",
        },
        stdout: "",
      });
      expect(out.resolved).toBe(false);
      expect(out.reason).toContain("ambiguous");
      expect(out.escalation?.diagnosis).toContain("needs decision");
    });
  });
});

// #596 F2: family-side decode seam test (raw through parse*Outcome)
// #919 CR N1: cargo parsers no longer ring classifyDecisionGate bells.
describe("#596 F2: family-side real decode (parseVerifyOutcome etc) for review-loop kinds (raw, not fake)", () => {

  // import here via the file's re-export or direct (the test file imports some parses)
  // we will require the module symbols via the existing pattern; use dynamic to avoid top-edit
  it("feeds RAW valid verify tag through real parseVerifyOutcome (family seam)", async () => {
    const mod = await import("../../../src/family/realFamilyBackend.js");
    const raw = `<verify>{"status": "converged"}</verify>`;
    const out = mod.parseVerifyOutcome(raw);
    expect(out).toEqual({ kind: "verify", status: "converged" });
  });

  it("feeds RAW valid-but-false verify through real parse (AC2: false flag passes shape)", async () => {
    const mod = await import("../../../src/family/realFamilyBackend.js");
    const out = mod.parseVerifyOutcome(`<verify>{"status": "continue"}</verify>`);
    expect(out).toEqual({ kind: "verify", status: "continue" });
  });

  it("unreadable verify bytes remain cargo instead of becoming a process failure", async () => {
    const mod = await import("../../../src/family/realFamilyBackend.js");
    expect(mod.parseVerifyOutcome("no tag here").kind).toBe("cargo");
    expect(mod.parseVerifyOutcome("<verify>notjson</verify>").kind).toBe("cargo");
    expect(mod.parseVerifyOutcome(`<verify>{"converged": 1}</verify>`).kind).toBe("cargo");
  });

  it("feeds RAW valid fixer through real parseFixerOutcome (family-side kind)", async () => {
    const mod = await import("../../../src/family/realFamilyBackend.js");
    const sha = "a".repeat(40);
    const out = mod.parseFixerOutcome(
      `<fixer>{"committed": true, "fixCommitSha": "${sha}"}</fixer>`,
    );
    expect(out).toEqual({ kind: "fixer", committed: true, fixCommitSha: sha });
  });

  it("falls back to readable stdout buttons when the sidecar cargo is unreadable", async () => {
    const mod = await import("../../../src/family/realFamilyBackend.js");
    const dir = trackTempDir("review-loop-outcome-fallback-");
    const outcomePath = join(dir, "outcome.json");
    writeFileSync(outcomePath, "{not json", "utf8");
    const sha = "a".repeat(40);

    expect(mod.parseVerifyOutcome('<verify>{"status": "converged"}</verify>', outcomePath))
      .toEqual({ kind: "verify", status: "converged" });
    expect(
      mod.parseFixerOutcome(
        `<fixer>{"committed": true, "fixCommitSha": "${sha}"}</fixer>`,
        outcomePath,
      ),
    ).toEqual({ kind: "fixer", committed: true, fixCommitSha: sha });
    expect(
      mod.parseCleanupOutcome('<cleanup>{"terminal": true, "ok": true}</cleanup>', outcomePath),
    ).toEqual({ kind: "cleanup", terminal: true, ok: true });
    expect(
      mod.parseLandingOutcome('<landing>{"released": true}</landing>', outcomePath),
    ).toEqual({ kind: "landing", released: true });
  });

  it("prefers readable sidecar cargo over a stdout decision bell (no bell-shop)", async () => {
    // #899 H2: cargo source selection is not a gate court. Prefer sidecar when
    // present; do not shop stdout because it carries escalate. Fate is typed SO.
    const mod = await import("../../../src/family/realFamilyBackend.js");
    const dir = trackTempDir("review-loop-outcome-bell-");
    const outcomePath = join(dir, "outcome.json");
    writeFileSync(outcomePath, JSON.stringify({ status: "converged" }), "utf8");

    expect(mod.parseVerifyOutcome(
      '<verify>{"bad": 1, "escalate": {"reason": "owner choice", "diagnosis": "review fork"}}</verify>',
      outcomePath,
    )).toEqual({ kind: "verify", status: "converged" });
  });

  class FamilyCoderDecodeHarness extends RealFamilyBackend {
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

    public classify(
      result: {
        output?: unknown;
        stdout: string;
        iterations?: ReadonlyArray<{ readonly sessionId?: string }>;
      },
      outcomePath: string,
    ) {
      return this.familyCoderResultFromRun(
        {
          stdout: result.stdout,
          commits: [],
          iterations: [...(result.iterations ?? [])],
          ...(result.output !== undefined ? { output: result.output } : {}),
        },
        {
          id: "S5",
          kind: "coder",
          role: "coder",
          host: "claude",
          session: "fresh",
          contextRetention: "clean",
          promptFile: "x.md",
          maxIter: 1,
          model: "sonnet",
          soul: "coder",
          toolchain: [],
        },
        outcomePath,
      );
    }
  }

  function familyCoderDecodeHarness(dir: string): FamilyCoderDecodeHarness {
    return new FamilyCoderDecodeHarness({
      workingRepo: dir,
      familyBase: "fb",
      ledgerDir: dir,
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
      familyBaseStartHead: "abc",
    });
  }

  it("does not let family coder-fix cargo escalate after a T2 completed receipt", async () => {
    // #899 / #919 M1: opaque sidecar cargo must not reintroduce escalate after
    // a validated T2 completed station receipt (fourth routing channel ban).
    const dir = trackTempDir(`family-coder-spoof-escalate-`);
    const outcomePath = join(dir, "outcome.json");
    writeFileSync(
      outcomePath,
      JSON.stringify({
        committed: true,
        commitsAdded: 1,
        escalate: { reason: "sidecar spoof", diagnosis: "must not win" },
      }),
      "utf8",
    );
    const be = familyCoderDecodeHarness(dir);
    const out = be.classify(
      {
        output: { station: "familyCoderFix", status: "completed" },
        stdout: "",
      },
      outcomePath,
    );
    expect(out.kind).toBe("completed");
    if (out.kind === "completed") {
      expect(out.output).toEqual({
        kind: "coder",
        committed: true,
        commitsAdded: 1,
      });
      expect("escalate" in out.output).toBe(false);
      expect(out.output).not.toHaveProperty("refusedFindingIdentityKeys");
    }
  });

  it("preserves family coder-fix commit cargo when the T2 receipt escalates", async () => {
    // #899 / #919 M1: T2 escalate is fate; committed/commitsAdded stay real cargo.
    const dir = trackTempDir(`family-coder-bell-cargo-`);
    const outcomePath = join(dir, "outcome.json");
    writeFileSync(
      outcomePath,
      JSON.stringify({ committed: true, commitsAdded: 3 }),
      "utf8",
    );
    const be = familyCoderDecodeHarness(dir);
    const out = be.classify(
      {
        output: {
          station: "familyCoderFix",
          status: "escalate",
          reason: "design fork",
          diagnosis: "owner must choose the contract",
        },
        stdout: "",
      },
      outcomePath,
    );
    expect(out.kind).toBe("completed");
    if (out.kind === "completed") {
      expect(out.output).toEqual({
        kind: "coder",
        committed: true,
        commitsAdded: 3,
        escalate: {
          reason: "design fork",
          diagnosis: "owner must choose the contract",
        },
      });
    }
  });

  it("#919 M1: RealFamilyBackend T2 refuse preserves envelope keys + cargo refuseRecords", () => {
    // Production decode path (familyCoderResultFromRun) must emit refuse traffic
    // isomorphic with single-slice projectCoderStationReceipt — not fake-only.
    const dir = trackTempDir(`family-coder-refuse-`);
    const outcomePath = join(dir, "outcome.json");
    const refuseKey = "correctness|src/a.ts:1|claim";
    const refuseRecord = {
      identityKey: refuseKey,
      finding: "claim",
      acceptanceCriterion: "AC-1",
      conflictReason: "unconstitutional",
    };
    writeFileSync(
      outcomePath,
      JSON.stringify({
        committed: true,
        commitsAdded: 1,
        // Hostile cargo: different key set must not win over envelope traffic.
        refusedFindingIdentityKeys: ["wrong|cargo|key"],
        refuseRecords: [refuseRecord],
      }),
      "utf8",
    );
    const be = familyCoderDecodeHarness(dir);
    const out = be.classify(
      {
        output: {
          station: "familyCoderFix",
          status: "refused",
          refusedFindingIdentityKeys: [refuseKey],
        },
        stdout: "",
      },
      outcomePath,
    );
    expect(out.kind).toBe("completed");
    if (out.kind === "completed") {
      expect(out.output).toEqual({
        kind: "coder",
        committed: true,
        commitsAdded: 1,
        refusedFindingIdentityKeys: [refuseKey],
        refuseRecords: [refuseRecord],
      });
    }
  });

  it("#919 M1 negative: completed T2 receipt cannot smuggle refuse keys from cargo", () => {
    const dir = trackTempDir(`family-coder-no-smuggle-refuse-`);
    const outcomePath = join(dir, "outcome.json");
    writeFileSync(
      outcomePath,
      JSON.stringify({
        committed: true,
        commitsAdded: 1,
        refusedFindingIdentityKeys: ["smuggled|from|cargo"],
        refuseRecords: [
          {
            identityKey: "smuggled|from|cargo",
            finding: "x",
            acceptanceCriterion: "AC",
            conflictReason: "not_established",
          },
        ],
      }),
      "utf8",
    );
    const be = familyCoderDecodeHarness(dir);
    const out = be.classify(
      {
        output: { station: "familyCoderFix", status: "completed" },
        stdout: "",
      },
      outcomePath,
    );
    expect(out.kind).toBe("completed");
    if (out.kind === "completed") {
      expect(out.output).toEqual({
        kind: "coder",
        committed: true,
        commitsAdded: 1,
      });
      expect(out.output).not.toHaveProperty("refusedFindingIdentityKeys");
      expect(out.output).not.toHaveProperty("refuseRecords");
    }
  });

  it("#919 M1 negative: empty/illegal typed envelope fails closed (no fake refuse ring)", () => {
    const dir = trackTempDir(`family-coder-illegal-`);
    const outcomePath = join(dir, "outcome.json");
    writeFileSync(
      outcomePath,
      JSON.stringify({ committed: true, commitsAdded: 1 }),
      "utf8",
    );
    const be = familyCoderDecodeHarness(dir);
    // Empty no-gate `{}` is not a legal T2 receipt (same as single-slice).
    expect(() => be.classify({ output: {}, stdout: "" }, outcomePath)).toThrow(
      /illegal coder station receipt/i,
    );
    // status:refused without keys is illegal — cannot open a refuse re-open.
    expect(() =>
      be.classify(
        {
          output: { station: "familyCoderFix", status: "refused" },
          stdout: "",
        },
        outcomePath,
      ),
    ).toThrow(/illegal coder station receipt|refusedFindingIdentityKeys/i);
  });

  it("keeps fixer completion even when fixCommitSha cargo is absent", async () => {
    const mod = await import("../../../src/family/realFamilyBackend.js");
    const out = mod.parseFixerOutcome(`<fixer>{"committed": true}</fixer>`);
    expect(out).toEqual({ kind: "fixer", committed: true });
  });

  it("RAW extra keys on verify remain cargo", async () => {
    const mod = await import("../../../src/family/realFamilyBackend.js");
    const out = mod.parseVerifyOutcome(`<verify>{"status": "converged", "extra": "nope"}</verify>`);
    expect(out.kind).toBe("verify");
  });

  it("RAW extra keys on fixer remain cargo", async () => {
    const mod = await import("../../../src/family/realFamilyBackend.js");
    const out = mod.parseFixerOutcome(
      `<fixer>{"committed": false, "foo": 1, "bar": {}, "notes": "opaque"}</fixer>`,
    );
    // #1145: after minimal object/committed check, preserve all fields with
    // canonical kind:"fixer" — typed envelope retains sole fate authority.
    expect(out).toEqual({
      kind: "fixer",
      committed: false,
      foo: 1,
      bar: {},
      notes: "opaque",
    });
  });

  it("RAW extra keys on cleanup remain cargo", async () => {
    const mod = await import("../../../src/family/realFamilyBackend.js");
    const out = mod.parseCleanupOutcome(
      `<cleanup>{"terminal": true, "ok": true, "unexpected": true}</cleanup>`,
    );
    expect(out).toEqual({ kind: "cleanup", terminal: true, ok: true });
  });

  it("drops side-effect plan fields from verify host typing; keeps opaque audit-only (#1145)", async () => {
    const mod = await import("../../../src/family/realFamilyBackend.js");
    // #1145: threadReplies / threadsToResolve / deferredIssueUrls are no longer
    // host-typed plan cargo — decoder ignores them whether well-formed or not.
    expect(
      mod.parseVerifyOutcome(
        `<verify>${JSON.stringify({
          status: "converged",
          threadReplies: [{ threadId: "t1", body: "fixed" }],
          threadsToResolve: ["t1"],
          deferredIssueUrls: ["https://github.com/o/r/issues/1"],
        })}</verify>`,
      ),
    ).toEqual({
      kind: "verify",
      status: "converged",
    });
    expect(
      mod.parseVerifyOutcome(
        `<verify>{"status": "converged", "threadReplies": "chatty"}</verify>`,
      ),
    ).toEqual({ kind: "verify", status: "converged" });
    expect(
      mod.parseCleanupOutcome(
        `<cleanup>{"terminal": true, "ok": true, "issuesClosed": ["chatty"]}</cleanup>`,
      ),
    ).toEqual({ kind: "cleanup", terminal: true, ok: true });
  });

  it("RAW extra keys on landing remain cargo", async () => {
    const mod = await import("../../../src/family/realFamilyBackend.js");
    const out = mod.parseLandingOutcome(`<landing>{"released": true, "x": 9}</landing>`);
    // Pin released (CR-11); unknown extra keys are dropped, not cargo shape.
    expect(out).toEqual({ kind: "landing", released: true });
  });

  // === pinning the canonical family last-complete-block semantics ===
  it("conversational prefix mentioning the tag before the real block → still decodes the real block", async () => {
    const mod = await import("../../../src/family/realFamilyBackend.js");
    // prose mention of <verify> (as in real model chatter) must not poison extraction
    const raw =
      '我会把最终结果放在 <verify> 里。\n' +
      '<verify>{"status": "converged"}</verify>\n' +
      'done';
    const out = mod.parseVerifyOutcome(raw);
    expect(out).toEqual({ kind: "verify", status: "converged" });
  });

  it("multiple complete tag blocks → the family parser takes the last one", async () => {
    const fam = await import("../../../src/family/realFamilyBackend.js");
    const raw =
      '<verify>{"status": "continue"}</verify>\n' +
      'chatter between\n' +
      '<verify>{"status": "converged"}</verify>';
    const outFam = fam.parseVerifyOutcome(raw);
    expect(outFam).toEqual({ kind: "verify", status: "converged" });
  });

  it("unclosed trailing tag mention after a complete block → last complete wins (actual observed behavior)", async () => {
    const mod = await import("../../../src/family/realFamilyBackend.js");
    // trailing open-mention with no close must be ignored; we take the prior complete
    const raw =
      '<verify>{"status": "continue"}</verify>\n' +
      'later mention without close: see <verify> for details';
    const out = mod.parseVerifyOutcome(raw);
    expect(out).toEqual({ kind: "verify", status: "continue" });
  });
});

describe("parseCmrOutcome accepted suppression contract", () => {
  it("normalizes a missing stdout before reading a valid cmr sidecar", () => {
    const dir = trackTempDir("cmr-outcome-missing-stdout-");
    const outcomePath = join(dir, "outcome.json");
    writeFileSync(
      outcomePath,
      JSON.stringify({
        converged: true,
        successfulLegs: ["gpt-5.6-sol"],
        claimedFixedFindingIdentityKeys: [],
        priorFindingDispositions: [],
        evidencePaths: ["cmr/review.json"],
      }) + "\n",
      "utf8",
    );

    const outcome = cmrOutcomeFromResult({
      stdout: undefined,
      outcomePath,
    });

    expect(outcome).toMatchObject({
      kind: "verdict",
      converged: true,
    });
    expect(outcome).not.toHaveProperty("findingsCount");
  });

  it("preserves cmr verdict and findingsCount after trimming CRLF stdout", () => {
    // #899: open-count is the typed receipt's findingsCount field only.
    const receipt = {
      converged: false,
      reason: "two findings remain",
      findingsCount: 2,
      successfulLegs: ["gpt-5.6-sol"],
      claimedFixedFindingIdentityKeys: [],
      priorFindingDispositions: [],
      evidencePaths: ["cmr/review.json"],
    };
    const outcome = cmrOutcomeFromResult({
      output: receipt,
      stdout: "\r\n  <cmr>" + JSON.stringify(receipt) + "</cmr>\r\n  ",
    });

    expect(outcome).toMatchObject({
      kind: "verdict",
      converged: false,
      reason: "two findings remain",
      findingsCount: 2,
    });
  });

  it("prefers a runner-owned outcome sidecar over malformed cmr stdout", () => {
    const dir = trackTempDir("cmr-outcome-");
    const outcomePath = join(dir, "outcome.json");
    writeFileSync(
      outcomePath,
      JSON.stringify({
        converged: true,
        successfulLegs: ["gpt-5.6-sol"],
        skippedLegs: [
          { slug: "opus", reason: "not configured for this test" },
          { slug: "agy", reason: "not configured for this test" },
        ],
        claimedFixedFindingIdentityKeys: [],
        priorFindingDispositions: [],
        evidencePaths: ["cmr/review.json"],
      }) + "\n",
      "utf8",
    );

    const outcome = cmrOutcomeFromResult({
      stdout: "<cmr>not json</cmr>\nfindings = 0\nCMR_STEP_COMPLETE",
      outcomePath,
      cmrReviewLegs: [
        { slug: "opus" },
        { slug: "gpt-5.6-sol" },
        { slug: "agy" },
      ],
    });

    expect(outcome).toMatchObject({
      kind: "verdict",
      converged: true,
      successfulLegs: ["gpt-5.6-sol"],
    });
  });

  it("treats a guarded cmr sidecar as completion on clean exit without a password string", () => {
    const dir = trackTempDir("cmr-outcome-sidecar-complete-");
    const outcomePath = join(dir, "outcome.json");
    writeFileSync(
      outcomePath,
      JSON.stringify({
        converged: false,
        reason: "same-module budget summary label mismatch remains",
        successfulLegs: ["opus", "gpt-5.6-sol"],
        skippedLegs: [{ slug: "agy", reason: "no active conversation" }],
        claimedFixedFindingIdentityKeys: [],
        priorFindingDispositions: [],
        findings: [
          {
            severity: "low",
            category: "correctness",
            claim_quote: '"中央军饷", "太仓亏空", "宗室禄米", "官俸", "工部",',
            location: "ming_sim/db.py:3985",
            suggested_fix: "Use 百官俸禄 as the matched budget item name.",
            // #604 slice 4 (ADR 0062): route kinds were removed; a fix_now finding
            // carries no disposition. (Was `disposition:{kind:"same_module"}`.)
            action: "fix_now",
          },
        ],
        evidencePaths: ["cmr/step6-correctness/review-summary.json"],
      }) + "\n",
      "utf8",
    );

    const outcome = cmrOutcomeFromResult({
      stdout:
        "CMR correctness gate completed through the outcome guard.\n" +
        "findings = 1\n" +
        "Reached max iterations (1).\n",
      outcomePath,
      cmrReviewLegs: [
        { slug: "opus" },
        { slug: "gpt-5.6-sol" },
        { slug: "agy" },
      ],
    });

    expect(outcome).toMatchObject({
      kind: "verdict",
      converged: false,
      reason: "same-module budget summary label mismatch remains",
      findings: [expect.objectContaining({ location: "ming_sim/db.py:3985" })],
    });
  });

  it("parses cmr sidecar payloads directly when free-form text contains a cmr tag delimiter", () => {
    // #899: decision bells enter fate only via typed Output.object; sidecar is
    // cargo. Typed escalate still works when free-form text quotes </cmr>.
    const outcome = cmrOutcomeFromResult({
      stdout: "<cmr>not json</cmr>\nCMR_STEP_COMPLETE",
      output: {
        escalate: {
          reason: "review unavailable",
          diagnosis: "diagnosis quoted the literal </cmr> delimiter",
        },
      },
    });

    expect(outcome).toEqual({
      kind: "escalate",
      reason: "review unavailable",
      diagnosis: "diagnosis quoted the literal </cmr> delimiter",
    });
  });

  it("falls back to CMR stdout cargo when the sidecar is unreadable", () => {
    const dir = trackTempDir("cmr-outcome-bad-");
    const outcomePath = join(dir, "outcome.json");
    writeFileSync(outcomePath, "{not json", "utf8");

    const outcome = cmrOutcomeFromResult({
      stdout:
        '<cmr>{"converged": true, "successfulLegs": ["gpt-5.6-sol"], "claimedFixedFindingIdentityKeys": [], "priorFindingDispositions": [], "evidencePaths": ["cmr/review.json"]}</cmr>',
      outcomePath,
      cmrReviewLegs: [{ slug: "gpt-5.6-sol" }],
    });

    expect(outcome).toMatchObject({ kind: "verdict", converged: true });
    expect(outcome).not.toHaveProperty("findingsCount");
  });

  it("falls back to stdout when the cmr outcome sidecar is blank", () => {
    const dir = trackTempDir("cmr-outcome-blank-");
    const outcomePath = join(dir, "outcome.json");
    writeFileSync(outcomePath, "   \n", "utf8");

    const outcome = cmrOutcomeFromResult({
      stdout:
        '<cmr>{"converged": true, "successfulLegs": ["gpt-5.6-sol"], "skippedLegs": [{"slug": "opus", "reason": "not configured for this test"}, {"slug": "agy", "reason": "not configured for this test"}], "claimedFixedFindingIdentityKeys": [], "priorFindingDispositions": [], "evidencePaths": ["cmr/review.json"]}</cmr>\nfindings = 0\n',
      outcomePath,
      cmrReviewLegs: [
        { slug: "opus" },
        { slug: "gpt-5.6-sol" },
        { slug: "agy" },
      ],
    });

    expect(outcome).toMatchObject({
      kind: "verdict",
      converged: true,
      successfulLegs: ["gpt-5.6-sol"],
    });
  });

  it("falls back to signaled cmr stdout only when no outcome sidecar path exists", () => {
    const outcome = cmrOutcomeFromResult({
      stdout:
        '<cmr>{"converged": true, "successfulLegs": ["gpt-5.6-sol"], "skippedLegs": [{"slug": "opus", "reason": "not configured for this test"}, {"slug": "agy", "reason": "not configured for this test"}], "claimedFixedFindingIdentityKeys": [], "priorFindingDispositions": [], "evidencePaths": ["cmr/review.json"]}</cmr>\nfindings = 0\n',
      cmrReviewLegs: [
        { slug: "opus" },
        { slug: "gpt-5.6-sol" },
        { slug: "agy" },
      ],
    });

    expect(outcome).toMatchObject({
      kind: "verdict",
      converged: true,
      successfulLegs: ["gpt-5.6-sol"],
    });
  });

  it("keeps completion telemetry out of unreadable-sidecar cargo fallback", () => {
    const dir = trackTempDir("cmr-outcome-bad-unsignaled-");
    const outcomePath = join(dir, "outcome.json");
    writeFileSync(outcomePath, "{not json", "utf8");

    const outcome = cmrOutcomeFromResult({
      stdout:
        '<cmr>{"converged": true, "successfulLegs": ["gpt-5.6-sol"], "claimedFixedFindingIdentityKeys": [], "priorFindingDispositions": [], "evidencePaths": ["cmr/review.json"]}</cmr>',
      outcomePath,
      cmrReviewLegs: [{ slug: "gpt-5.6-sol" }],
    });

    expect(outcome).toMatchObject({ kind: "verdict", converged: true });
    expect(outcome).not.toHaveProperty("findingsCount");
  });

  it("derives redundant accepted_suppressed finding fields from the finding payload", () => {
    const outcome = parseCmrOutcome(`<cmr>${JSON.stringify({
      converged: false,
      reason: "accepted suppression remains",
      successfulLegs: ["gpt-5.6-sol"],
      skippedLegs: [
        { slug: "opus", reason: "not part of this parser unit" },
        { slug: "agy", reason: "not part of this parser unit" },
      ],
      claimedFixedFindingIdentityKeys: [],
      priorFindingDispositions: [],
      evidencePaths: ["cmr/review.json"],
      findings: [
        {
          severity: "medium",
          category: "correctness",
          claim_quote: "Known accepted gap",
          location: "orchestrator/src/family/verifyCmr.ts:42",
          suggested_fix: "keep the bounded suppression",
          action: "wont_fix",
          disposition: {
            kind: "accepted_suppressed",
            source: "#445 owner answer",
            scope: "orchestrator family CMR",
            reason: "Owner accepted this bounded risk.",
            boundedReopen: "reopen if the same scope regresses",
          },
        },
      ],
    })}</cmr>\nCMR_STEP_COMPLETE`);

    expect(outcome).toMatchObject({
      converged: false,
      findings: [
        expect.objectContaining({
          disposition_reason: "Owner accepted this bounded risk.",
          disposition: expect.objectContaining({
            kind: "accepted_suppressed",
            findingIdentity:
              "correctness|orchestrator/src/family/verifycmr.ts:42|known accepted gap",
          }),
        }),
      ],
    });
  });

  it("normalizes accepted_suppressed findings with canonical disposition reason first", () => {
    const outcome = parseCmrOutcome(`<cmr>${JSON.stringify({
      converged: false,
      reason: "accepted suppression remains",
      successfulLegs: ["gpt-5.6-sol"],
      skippedLegs: [
        { slug: "opus", reason: "not part of this parser unit" },
        { slug: "agy", reason: "not part of this parser unit" },
      ],
      claimedFixedFindingIdentityKeys: [],
      priorFindingDispositions: [],
      evidencePaths: ["cmr/review.json"],
      findings: [
        {
          severity: "medium",
          category: "correctness",
          claim_quote: "Known accepted gap",
          location: "orchestrator/src/family/verifyCmr.ts:42",
          suggested_fix: "keep the bounded suppression",
          action: "wont_fix",
          disposition_reason: "legacy fallback should not win",
          disposition: {
            kind: "accepted_suppressed",
            source: "#445 owner answer",
            scope: "orchestrator family CMR",
            reason: "Owner accepted this bounded risk.",
            boundedReopen: "reopen if the same scope regresses",
          },
        },
      ],
    })}</cmr>\nCMR_STEP_COMPLETE`);

    expect(outcome.kind).toBe("verdict");
    expect(outcome.kind === "verdict" ? outcome.findings?.[0]?.disposition_reason : undefined).toBe(
      "Owner accepted this bounded risk.",
    );
  });

  it("#875: converged verdict omitting claim/disposition prose fields still parses (no closure shape court)", () => {
    // Pre-#875 / residual court: cmrClosureSchema required
    // claimedFixedFindingIdentityKeys + priorFindingDispositions arrays; omitting
    // them made the whole verdict malformed before three-channel routing.
    // Post-#875: those fields are optional worker prose.
    const outcome = parseCmrOutcome(`<cmr>${JSON.stringify({
      converged: true,
      successfulLegs: ["gpt-5.6-sol"],
      skippedLegs: [
        { slug: "opus", reason: "not part of this parser unit" },
        { slug: "agy", reason: "not part of this parser unit" },
      ],
      evidencePaths: ["cmr/review.json"],
    })}</cmr>\nCMR_STEP_COMPLETE`);

    expect(outcome.kind).toBe("verdict");
    if (outcome.kind === "verdict") {
      expect(outcome.converged).toBe(true);
      expect(outcome.successfulLegs).toEqual(["gpt-5.6-sol"]);
      expect(outcome.claimedFixedFindingIdentityKeys).toBeUndefined();
      expect(outcome.priorFindingDispositions).toBeUndefined();
    }
  });

  it("#875: incomplete accepted_suppressed prior disposition prose still parses as a verdict (not malformed death)", () => {
    // Pre-#875: parse-time superRefine killed incomplete accepted_suppressed
    // prior dispositions as malformed before verifyCmr could three-channel route.
    // Post-#875: prior dispositions are worker prose at parse; finding.disposition
    // governance (cmrDispositionEvidenceSchema) stays strict.
    const outcome = parseCmrOutcome(`<cmr>${JSON.stringify({
      converged: true,
      successfulLegs: ["gpt-5.6-sol"],
      skippedLegs: [
        { slug: "opus", reason: "not part of this parser unit" },
        { slug: "agy", reason: "not part of this parser unit" },
      ],
      claimedFixedFindingIdentityKeys: ["correctness|src/x.ts:1|accepted"],
      evidencePaths: ["cmr/review.json"],
      priorFindingDispositions: [
        {
          identityKey: "correctness|src/x.ts:1|accepted",
          status: "accepted_suppressed",
          // deliberately incomplete — missing reason/source/scope/boundedReopen
        },
      ],
    })}</cmr>\nCMR_STEP_COMPLETE`);

    expect(outcome.kind).toBe("verdict");
    if (outcome.kind === "verdict") {
      expect(outcome.converged).toBe(true);
      expect(outcome.priorFindingDispositions).toEqual([
        {
          identityKey: "correctness|src/x.ts:1|accepted",
          status: "accepted_suppressed",
        },
      ]);
    }
  });

  it("#875 kill-axis: chatty/non-array leg lists still parse; empty successfulLegs land as verdict prose", () => {
    // r11 high: successfulLegs/skippedLegs z.array courts shape-killed before floor.
    const outcome = parseCmrOutcome(`<cmr>${JSON.stringify({
      converged: true,
      successfulLegs: "not-an-array",
      skippedLegs: [
        { slug: "agy", reason: "quota" },
        { slug: "opus", note: "chatty incomplete skip — drop" },
        "bare-string-skip",
      ],
      evidencePaths: ["cmr/review.json"],
    })}</cmr>\nCMR_STEP_COMPLETE`);

    expect(outcome.kind).toBe("verdict");
    if (outcome.kind === "verdict") {
      expect(outcome.successfulLegs).toEqual([]);
      expect(outcome.skippedLegs).toEqual([
        { slug: "agy", reason: "quota" },
      ]);
    }
  });

  it("#875 kill-axis: non-array claim/disposition top-level values still parse as a verdict", () => {
    // codex high r10: z.array(...) still shape-killed object/string/null before
    // soft-parse. Accept unknown top-level shape; discard unusable prose.
    const outcome = parseCmrOutcome(`<cmr>${JSON.stringify({
      converged: true,
      successfulLegs: ["gpt-5.6-sol"],
      skippedLegs: [
        { slug: "opus", reason: "not part of this parser unit" },
        { slug: "agy", reason: "not part of this parser unit" },
      ],
      evidencePaths: ["cmr/review.json"],
      claimedFixedFindingIdentityKeys: { note: "reviewer freeform" },
      priorFindingDispositions: "chatty prose not an array",
    })}</cmr>\nCMR_STEP_COMPLETE`);

    expect(outcome.kind).toBe("verdict");
    if (outcome.kind === "verdict") {
      expect(outcome.converged).toBe(true);
      expect(outcome.claimedFixedFindingIdentityKeys).toEqual([]);
      expect(outcome.priorFindingDispositions).toEqual([]);
    }
  });

  it("#875 kill-axis: chatty prior dispositions (unknown status / extra keys) do not malformed the whole verdict", () => {
    // Pre-kill-axis residual: one disposition with unknown status or extra prose
    // key failed cmrFindingDispositionSchema → entire <cmr> malformed → rewrite
    // → durable abort. Post: soft-drop unparseable entries; well-formed neighbors
    // still land; envelope survives as a verdict.
    const outcome = parseCmrOutcome(`<cmr>${JSON.stringify({
      converged: true,
      successfulLegs: ["gpt-5.6-sol"],
      skippedLegs: [
        { slug: "opus", reason: "not part of this parser unit" },
        { slug: "agy", reason: "not part of this parser unit" },
      ],
      evidencePaths: ["cmr/review.json"],
      priorFindingDispositions: [
        {
          identityKey: "correctness|src/x.ts:1|chatty",
          status: "probably-closed-ish",
          note: "reviewer freeform prose",
        },
        {
          identityKey: "correctness|src/x.ts:2|ok",
          status: "verified-closed",
        },
        {
          identityKey: "correctness|src/x.ts:3|extra",
          status: "still-active",
          extraProse: "more chatter",
        },
      ],
    })}</cmr>\nCMR_STEP_COMPLETE`);

    expect(outcome.kind).toBe("verdict");
    if (outcome.kind === "verdict") {
      expect(outcome.converged).toBe(true);
      expect(outcome.priorFindingDispositions).toEqual([
        {
          identityKey: "correctness|src/x.ts:2|ok",
          status: "verified-closed",
        },
      ]);
    }
  });

  it("drops missing evidence-path cargo without rejecting a converged field", () => {
    const outcome = parseCmrOutcome(`<cmr>${JSON.stringify({
      converged: true,
      successfulLegs: ["gpt-5.6-sol"],
      skippedLegs: [
        { slug: "opus", reason: "not part of this parser unit" },
        { slug: "agy", reason: "not part of this parser unit" },
      ],
      claimedFixedFindingIdentityKeys: [],
      priorFindingDispositions: [],
    })}</cmr>\nCMR_STEP_COMPLETE`);

    expect(outcome).toMatchObject({
      kind: "verdict",
      converged: true,
      evidencePaths: [],
    });
  });

  it("keeps not-converged cargo when evidence paths are absent", () => {
    const outcome = parseCmrOutcome(`<cmr>${JSON.stringify({
      converged: false,
      reason: "blocking findings remain",
      successfulLegs: ["gpt-5.6-sol"],
      skippedLegs: [
        { slug: "opus", reason: "not part of this parser unit" },
        { slug: "agy", reason: "not part of this parser unit" },
      ],
      claimedFixedFindingIdentityKeys: [],
      priorFindingDispositions: [],
      findings: [
        {
          severity: "medium",
          category: "correctness",
          claim_quote: "missing evidence paths should not be accepted",
          location: "orchestrator/src/family/realFamilyBackend.ts",
          suggested_fix: "include review artifact evidence paths",
          action: "fix_now",
        },
      ],
    })}</cmr>\nCMR_STEP_COMPLETE`);

    expect(outcome).toMatchObject({
      kind: "verdict",
      converged: false,
      reason: "blocking findings remain",
      evidencePaths: [],
    });
  });

  it("strips legacy disposition aliases even when status is already present", () => {
    const outcome = parseCmrOutcome(`<cmr>${JSON.stringify({
      converged: true,
      successfulLegs: ["gpt-5.6-sol"],
      skippedLegs: [
        { slug: "opus", reason: "not part of this parser unit" },
        { slug: "agy", reason: "not part of this parser unit" },
      ],
      claimedFixedFindingIdentityKeys: ["correctness|src/x.ts:1|accepted"],
      evidencePaths: ["cmr/review.json"],
      priorFindingDispositions: [
        {
          identityKey: "correctness|src/x.ts:1|accepted",
          status: "verified-closed",
          disposition: "accepted_suppressed",
        },
      ],
    })}</cmr>\nCMR_STEP_COMPLETE`);

    expect(outcome).toMatchObject({
      converged: true,
      priorFindingDispositions: [
        {
          identityKey: "correctness|src/x.ts:1|accepted",
          status: "verified-closed",
        },
      ],
    });
  });
});

describe("mergerOutcomeFromResult (#291 structured telemetry parser, pure)", () => {
  it("prefers a runner-owned outcome sidecar over malformed merger stdout", () => {
    const dir = trackTempDir("merger-outcome-");
    const outcomePath = join(dir, "outcome.json");
    writeFileSync(
      outcomePath,
      JSON.stringify({ resolved: true, tradeoffs: "preserved both sides" }) + "\n",
      "utf8",
    );

    expect(
      mergerOutcomeFromResult({
        stdout: "<merger>not json</merger>\nMERGER_STEP_COMPLETE",
        outcomePath,
      }),
    ).toEqual({ resolved: true });
  });

  it("parses merger sidecar payloads directly when free-form text contains a merger tag delimiter", () => {
    const dir = trackTempDir("merger-outcome-delimiter-");
    const outcomePath = join(dir, "outcome.json");
    writeFileSync(
      outcomePath,
      JSON.stringify({
        resolved: true,
        tradeoffs: "resolution notes quoted the literal </merger> delimiter",
      }) + "\n",
      "utf8",
    );

    expect(
      mergerOutcomeFromResult({
        stdout: "<merger>not json</merger>\nMERGER_STEP_COMPLETE",
        outcomePath,
      }),
    ).toEqual({ resolved: true });
  });

  it("treats a non-empty malformed merger sidecar as a protocol failure", () => {
    const dir = trackTempDir("merger-outcome-bad-");
    const outcomePath = join(dir, "outcome.json");
    writeFileSync(outcomePath, "{not json", "utf8");

    const outcome = mergerOutcomeFromResult({
      stdout: '<merger>{"resolved": true}</merger>',
      outcomePath,
    });

    expect(outcome).toMatchObject({
      resolved: false,
      reason: expect.stringContaining("sidecar protocol failure"),
    });
  });

  it("falls back to stdout when the merger outcome sidecar is blank", () => {
    const dir = trackTempDir("merger-outcome-blank-");
    const outcomePath = join(dir, "outcome.json");
    writeFileSync(outcomePath, "   \n", "utf8");

    const outcome = mergerOutcomeFromResult({
      stdout: '<merger>{"resolved": true}</merger>',
      outcomePath,
    });

    expect(outcome).toEqual({ resolved: true });
  });

  it("falls back to signaled merger stdout only when no outcome sidecar path exists", () => {
    expect(
      mergerOutcomeFromResult({
        stdout: '<merger>{"resolved": true}</merger>',
      }),
    ).toEqual({ resolved: true });
  });

  it("a signaled run resolves from stdout cargo (resolved)", () => {
    expect(
      mergerOutcomeFromResult({
        stdout: '<merger>{"resolved": true}</merger>',
      }),
    ).toEqual({ resolved: true });
  });
  it("keeps a valid merger result available for git-truth adjudication from typed envelope alone", () => {
    // #928: completion is exit + legal sidecar / typed envelope. The caller
    // must still verify the merge commit and conflict state before recording
    // a landed merge.
    const out = mergerOutcomeFromResult({
      stdout: '<merger>{"resolved": true}</merger>',
    });
    expect(out).toEqual({ resolved: true });
  });
  it("typed merger envelope alone is enough for resolved (no password required)", () => {
    expect(
      mergerOutcomeFromResult({
        stdout: '<merger>{"resolved": true}</merger>',
      }).resolved,
    ).toBe(true);
  });

  it("T2 merger completed enriches resolve cargo; escalate parks decision", () => {
    // #919 CR T2: production typed channel is station:merger completed|escalate.
    const dir = trackTempDir("merger-t2-completed-");
    const outcomePath = join(dir, "outcome.json");
    writeFileSync(
      outcomePath,
      JSON.stringify({ resolved: true, tradeoffs: "kept both" }) + "\n",
      "utf8",
    );
    expect(
      mergerOutcomeFromResult({
        output: { station: "merger", status: "completed" },
        outcomePath,
        stdout: "",
      }),
    ).toEqual({ resolved: true });

    expect(
      mergerOutcomeFromResult({
        output: {
          station: "merger",
          status: "escalate",
          reason: "product fork",
          diagnosis: "need owner",
        },
        stdout: "",
      }),
    ).toMatchObject({
      resolved: false,
      reason: "product fork",
      escalation: {
        reason: "product fork",
        diagnosis: "need owner",
        escalationKind: "decision",
      },
    });

    // Legacy decision-gate dual is fail-closed after T2.
    expect(() =>
      mergerOutcomeFromResult({
        output: { escalate: { reason: "legacy", diagnosis: "dual" } },
        stdout: "",
      }),
    ).toThrow(/illegal merger station receipt/);
  });

});

// ═══════════════════════════ 5. runFamilyVerify ═════════════════════════════

describe("RealFamilyBackend runFamilyVerify (#291 tsc + vitest)", () => {
  it("gives declared npm build/test verification the provision-class subprocess budget", async () => {
    const commands: Array<{
      file: string;
      args: string[];
      timeoutMs: number | undefined;
    }> = [];
    class LongVerifyBackend extends RealFamilyBackend {
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

      protected override sh(
        file: string,
        args: string[],
        _cwd?: string,
        timeoutMs?: number,
      ): string {
        commands.push({ file, args, timeoutMs });
        return "";
      }
      protected override async installDeps(_cwd: string): Promise<void> {}
      protected override isNodeProject(_cwd: string): boolean { return true; }
      protected override packageScripts(_cwd: string): readonly string[] {
        return ["build", "test"];
      }
      public waitForStamps(): Promise<void> { return this.waitForVerificationStamps(); }
    }
    const backend = new LongVerifyBackend(
      opts("/clone/root", { verifyCwd: "/clone/root/web" }),
    );

    await expect(backend.runFamilyVerify({
      phase: "final",
      familyBase: "family/293-base",
    })).resolves.toEqual({ ok: true });
    await backend.waitForStamps();

    expect(commands.filter((command) => command.file === "npm")).toEqual([
      {
        file: "npm",
        args: ["run", "build"],
        timeoutMs: PROVISION_SUBPROCESS_TIMEOUT_MS,
      },
      {
        file: "npm",
        args: ["test"],
        timeoutMs: PROVISION_SUBPROCESS_TIMEOUT_MS,
      },
    ]);
  });

  it("records unknown counts without rewriting the project's typecheck or wave-unit commands", async () => {
    const commands: Array<{ file: string; args: string[] }> = [];
    class ObservedVerifyBackend extends RealFamilyBackend {
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

      protected override sh(file: string, args: string[], _cwd?: string): string {
        commands.push({ file, args });
        if (args.includes("test")) {
          return JSON.stringify({ numTotalTests: 507 });
        }
        return "";
      }
      protected override async installDeps(_cwd: string): Promise<void> {}
      protected override isNodeProject(_cwd: string): boolean { return true; }
      protected override packageScripts(_cwd: string): readonly string[] {
        return ["typecheck", "test"];
      }
      public waitForStamps(): Promise<void> { return this.waitForVerificationStamps(); }
    }
    const options = opts("/clone/root", { verifyCwd: "/clone/root/orchestrator" });
    const backend = new ObservedVerifyBackend(options);

    await expect(backend.runFamilyVerify({
      phase: "wave",
      familyBase: "family/293-base",
      runId: "run-786",
      issue: 786,
    })).resolves.toEqual({ ok: true });
    await backend.waitForStamps();

    const rows = telemetry.readTelemetryRecords(options.ledgerDir).filter(
      (record): record is telemetry.TelemetryVerificationRecord =>
        record.phase === "verification",
    );
    expect(rows).toMatchObject([
      { runId: "run-786", issue: 786, verification: "typecheck", passed: true, count: null },
      { runId: "run-786", issue: 786, verification: "unit", passed: true, count: null },
    ]);
    expect(rows.every((row) => typeof row.duration_ms === "number")).toBe(true);
    expect(commands).toContainEqual({
      file: "npm",
      args: ["run", "typecheck"],
    });
    expect(commands).toContainEqual({ file: "npm", args: ["test"] });
  });

  it("keeps later verification stamps flowing after one unexpected stamp failure", async () => {
    class ObservedVerifyBackend extends RealFamilyBackend {
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

      protected override sh(): string { return ""; }
      protected override async installDeps(_cwd: string): Promise<void> {}
      protected override isNodeProject(_cwd: string): boolean { return true; }
      protected override packageScripts(_cwd: string): readonly string[] {
        return ["typecheck", "test"];
      }
      public waitForStamps(): Promise<void> { return this.waitForVerificationStamps(); }
    }
    const options = opts("/clone/root", { verifyCwd: "/clone/root/orchestrator" });
    vi.spyOn(telemetry, "recordVerificationStamp").mockImplementationOnce(async () => {
      throw new Error("unexpected verification telemetry failure");
    });
    const backend = new ObservedVerifyBackend(options);

    await expect(backend.runFamilyVerify({
      phase: "wave",
      familyBase: "family/293-base",
    })).resolves.toEqual({ ok: true });
    await expect(backend.waitForStamps()).resolves.toBeUndefined();

    expect(telemetry.recordVerificationStamp).toHaveBeenCalledTimes(2);
    expect(telemetry.readTelemetryRecords(options.ledgerDir)).toContainEqual(expect.objectContaining({
      phase: "verification",
      verification: "unit",
      passed: true,
    }));
  });

  it("keeps a failed typecheck count unknown instead of parsing its diagnostic prose", async () => {
    class FailedTypecheckBackend extends RealFamilyBackend {
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

      protected override sh(file: string, args: string[], _cwd?: string): string {
        if (file === "npm" && args.includes("typecheck")) {
          const error = new Error("Command failed: npm run typecheck") as Error & {
            stderr?: string;
          };
          error.stderr = [
            "src/one.ts(1,1): error TS2322: first",
            "src/two.ts(2,2): error TS2345: second",
          ].join("\n");
          throw error;
        }
        return "";
      }
      protected override async installDeps(_cwd: string): Promise<void> {}
      protected override isNodeProject(_cwd: string): boolean { return true; }
      protected override packageScripts(_cwd: string): readonly string[] {
        return ["typecheck", "test"];
      }
      public waitForStamps(): Promise<void> { return this.waitForVerificationStamps(); }
    }
    const options = opts("/clone/root", { verifyCwd: "/clone/root/orchestrator" });
    const backend = new FailedTypecheckBackend(options);

    await expect(backend.runFamilyVerify({
      phase: "wave",
      familyBase: "family/293-base",
      runId: "run-786",
      issue: 786,
    })).resolves.toMatchObject({ ok: false });
    await backend.waitForStamps();

    expect(telemetry.readTelemetryRecords(options.ledgerDir)).toContainEqual(expect.objectContaining({
      phase: "verification",
      verification: "typecheck",
      passed: false,
      count: null,
    }));
  });

  it("records a failed final observation and preserves the verification verdict", async () => {
    class FailedObservedVerifyBackend extends RealFamilyBackend {
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

      protected override sh(file: string, args: string[], _cwd?: string): string {
        if (file === "npm" && args[0] === "test") throw new Error("plain test output");
        return "";
      }
      protected override async installDeps(_cwd: string): Promise<void> {}
      protected override isNodeProject(_cwd: string): boolean { return true; }
      protected override packageScripts(_cwd: string): readonly string[] {
        return ["typecheck", "test"];
      }
      public waitForStamps(): Promise<void> { return this.waitForVerificationStamps(); }
    }
    const options = opts("/clone/root", { verifyCwd: "/clone/root/orchestrator" });
    const backend = new FailedObservedVerifyBackend(options);

    await expect(backend.runFamilyVerify({
      phase: "final",
      familyBase: "family/293-base",
      runId: "run-786",
      issue: 786,
    })).resolves.toMatchObject({ ok: false });
    await backend.waitForStamps();

    const rows = telemetry.readTelemetryRecords(options.ledgerDir).filter(
      (record): record is telemetry.TelemetryVerificationRecord =>
        record.phase === "verification",
    );
    expect(rows.map((row) => [row.verification, row.passed])).toEqual([
      ["typecheck", true],
      ["full", false],
    ]);
  });

});

describe("resolveImageTag / DEFAULT_IMAGE_TAG pin (#372 R2)", () => {
  it("provides identical tag for build and dispatch (single source of truth)", () => {
    // Small assertion: launcher + driver read the same resolver/default.
    // Ensures when IMAGE_TAG=... is set, dispatch uses it (not a different default).
    expect(resolveImageTag(undefined)).toBe(DEFAULT_IMAGE_TAG);
    expect(resolveImageTag("")).toBe(DEFAULT_IMAGE_TAG);
    expect(resolveImageTag("ming-orchestrator-coder:latest")).toBe("ming-orchestrator-coder:latest");
    expect(resolveImageTag("custom:tag-xyz")).toBe("custom:tag-xyz");
    // The default is the one build.sh also defaults to.
    expect(DEFAULT_IMAGE_TAG).toBe("ming-orchestrator-coder:latest");
  });
});

/**
 * #909/#937 — family sandbox shares single-slice silence contract (ID-007):
 * Sandcastle idle rethrows without quota probe/park. Explicit 429 is separate.
 */
describe("#909 RealFamilyBackend runAgentSandbox quota/idle parity", () => {
  function idleTimeoutError(): Error {
    return Object.assign(
      new Error(
        "Agent idle for 600 seconds — no output received. Consider increasing the idle timeout with --idle-timeout.",
      ),
      { name: "AgentIdleTimeoutError", _tag: "AgentIdleTimeoutError" },
    );
  }

  class FamilyIdleBackend extends RealFamilyBackend {
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

    public sandcastleReached = false;

    protected override async invokeSandcastleRun(
      options: Parameters<typeof sc.run>[0],
    ): Promise<never> {
      this.sandcastleReached = true;
      void options;
      throw idleTimeoutError();
    }

    public exposeRunAgentSandbox(
      options: import("../../../src/realBackend.js").AgentSandboxRunOptions,
    ) {
      return this.runAgentSandbox(options);
    }

    public exposeShipContainerRun(spec: WorkerSpec) {
      return this.shipContainerRun(spec, {
        claudeToken: "tok",
        codexAuthDir: undefined,
        grokAuthDir: undefined,
        ghToken: "gh",
      });
    }
  }

  function makeFamilyIdleBackend(): FamilyIdleBackend {
    return new FamilyIdleBackend(opts(trackRepo()));
  }

  it("family + single-slice delete idle→quota machinery (#937 ID-007)", () => {
    const familySrc = readFileSync(
      join(here, "..", "..", "..", "src", "family", "realFamilyBackend.ts"),
      "utf8",
    );
    const realSrc = readFileSync(
      join(here, "..", "..", "..", "src", "realBackend.ts"),
      "utf8",
    );
    const probeSrc = readFileSync(
      join(here, "..", "..", "..", "src", "quotaProbe.ts"),
      "utf8",
    );
    expect(familySrc).not.toMatch(/resolveIdleAfterQuotaProbe/);
    expect(realSrc).not.toMatch(/resolveIdleAfterQuotaProbe/);
    expect(familySrc).not.toMatch(/withIdleQuotaProbeDisposition/);
    expect(realSrc).not.toMatch(/withIdleQuotaProbeDisposition/);
    expect(probeSrc).not.toMatch(/function handleIdleThreshold/);
    expect(probeSrc).not.toMatch(/function withIdleQuotaProbeDisposition/);
    expect(probeSrc).not.toMatch(/function resolveSandboxIdleAfterQuotaProbe/);
    expect(familySrc).toMatch(/protected async runAgentSandbox/);
    expect(realSrc).toMatch(/protected async runAgentSandbox/);
  });
});

describe("#939 discoverSubprojects directory op-errors", () => {
  it("readdir operational failure throws (never degrades to [])", () => {
    const missing = join(trackTempDir("disc-missing-"), "no-such");
    // #934 CR: single canonical token `failed to readdir subprojects`.
    expect(() => discoverSubprojects(missing)).toThrow(/failed to readdir subprojects/i);
  });

  it("successful empty top-level (no child package.json) returns []", () => {
    const empty = trackTempDir("disc-empty-");
    expect(discoverSubprojects(empty)).toEqual([]);
  });
});
