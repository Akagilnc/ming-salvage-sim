import {
  execFile,
  copyFileSync,
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
  BindMountSandboxHandle,
  sc,
  afterEach,
  describe,
  expect,
  it,
  agentForSlug,
  tempDirs,
  tmp,
  localHandle,
  CODEX_SLUGS,
  STORAGE_METHODS,
} from "./codex-native-capture-957.shared.js";

afterEach(() => {
  while (tempDirs.length > 0) {
    rmSync(tempDirs.pop()!, { recursive: true, force: true });
  }
});

describe("#957 codex native session capture (reverses #883 bandaid)", () => {
  it("every codex-provider agent captures sessions by default", () => {
    for (const slug of CODEX_SLUGS) {
      const agent = agentForSlug(slug);
      expect(agent.name).toBe("codex");
      expect(agent.captureSessions).toBe(true);
    }
  });

  it("claude legs keep capture (unchanged)", () => {
    expect(agentForSlug("opus").captureSessions).toBe(true);
  });

  it("sandcastle-native sessionStorage is present on codex agents", () => {
    const agent = agentForSlug("gpt-5.6-sol");
    expect(agent.sessionStorage).toBeDefined();
    for (const m of STORAGE_METHODS) {
      expect(typeof agent.sessionStorage?.[m]).toBe("function");
    }
  });
});

describe("#957 codex provider command has no --ephemeral", () => {
  it("fresh print command never includes --ephemeral", () => {
    const { command } = agentForSlug("gpt-5.6-sol").buildPrintCommand({
      prompt: "implement the slice",
      dangerouslySkipPermissions: true,
    });
    expect(command).toMatch(/^codex exec\b/);
    expect(command).not.toContain("--ephemeral");
    // Negative: host CMR / bare-ping patterns must not leak into the provider.
    expect(command).not.toMatch(/--ephemeral\b/);
  });

  it("resume print command uses native `codex exec resume` without --ephemeral", () => {
    const sessionId = "019f-codex-resume-fixture";
    const { command } = agentForSlug("gpt-5.6-sol").buildPrintCommand({
      prompt: "continue from parked answer",
      dangerouslySkipPermissions: true,
      resumeSession: sessionId,
    });
    expect(command).toContain("codex exec resume");
    expect(command).toContain(sessionId);
    expect(command).not.toContain("--ephemeral");
    // Fresh `codex exec` base must not be used when resuming.
    expect(command).not.toMatch(/^codex exec --/);
  });

  it("fork resume uses native `codex exec fork` without --ephemeral", () => {
    const sessionId = "019f-codex-fork-fixture";
    const { command } = agentForSlug("gpt-5.6-terra").buildPrintCommand({
      prompt: "fork for SO re-ask",
      dangerouslySkipPermissions: true,
      resumeSession: sessionId,
      forkSession: true,
    });
    expect(command).toContain("codex exec fork");
    expect(command).toContain(sessionId);
    expect(command).not.toContain("--ephemeral");
  });
});

describe("#957 structured-output same-session retry is native (#934)", () => {
  it("does not invent a second homemade codex session-transfer module", () => {
    // #957 scope = restore Sandcastle native capture; no host session-dir
    // migration / second retry protocol (contrast grokAgent's own storage,
    // which is out of scope and already landed under #955).
    const srcDir = join(dirname(fileURLToPath(import.meta.url)), "../../src");
    const names = readdirSync(srcDir);
    expect(names.some((n) => /codex.*session/i.test(n))).toBe(false);
    expect(names.some((n) => /session.*codex/i.test(n))).toBe(false);
  });
});

describe("#957 no #960 Runner existence gate revived", () => {
  it("registry factory is pure agent construction — no existsOnHost pre-check export", async () => {
    const registry = await import("../../src/modelRegistry.js");
    // #960 folded: Runner must not gate resume on container-side existence.
    // This package only exports capability + agent construction for codex.
    expect(
      Object.keys(registry).some((k) =>
        /exist|sessionGate|sessionPresence|preflightSession/i.test(k),
      ),
    ).toBe(false);
    // Still constructs a capturable, resume-capable agent.
    const agent = registry.agentForSlug("gpt-5.6-sol");
    expect(agent.captureSessions).toBe(true);
    expect(registry.resumeCapableForSlug("gpt-5.6-sol")).toBe(true);
  });
});
