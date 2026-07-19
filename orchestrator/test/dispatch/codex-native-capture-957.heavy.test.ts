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

describe("#957 Sandcastle-native capture → resume same context", () => {
  it("sc.codex sessionStorage captureToHost then resumeIntoSandbox keeps dialogue context", async () => {
    // Real Sandcastle codex provider surface (not a string pin of captureSessions).
    // Seeds a sandbox rollout JSONL, captures to host, clears sandbox, resumes
    // back — proves same session id + dialogue marker survive the native path.
    const hostSessions = tmp("957-codex-host-");
    const sandboxFs = tmp("957-codex-sbx-");
    const sandboxCwd = join(sandboxFs, "workspace");
    const hostCwd = tmp("957-codex-hostcwd-");
    const sandboxSessions = join(sandboxFs, "home-.codex-sessions");
    const sessionId = "019f-codex-native-957";
    const dialogueMarker = "DIALOGUE_CONTEXT_MARKER_957_SAME_SESSION";
    const relativeRollout = join(
      "2026",
      "07",
      "17",
      `rollout-2026-07-17T00-00-00-${sessionId}.jsonl`,
    );
    const sandboxRollout = join(sandboxSessions, relativeRollout);
    mkdirSync(dirname(sandboxRollout), { recursive: true });
    const sandboxJsonl = [
      JSON.stringify({
        type: "session_meta",
        payload: { cwd: sandboxCwd, id: sessionId },
      }),
      JSON.stringify({
        type: "response_item",
        cwd: sandboxCwd,
        text: dialogueMarker,
      }),
      "",
    ].join("\n");
    writeFileSync(sandboxRollout, sandboxJsonl);

    // Direct Sandcastle factory (same surface agentForSlug uses for codex rows).
    const agent = sc.codex("gpt-5.6-sol", {
      sessionStorage: {
        hostSessionsDir: hostSessions,
        sandboxSessionsDir: sandboxSessions,
      },
    });
    expect(agent.captureSessions).toBe(true);
    expect(agent.sessionStorage).toBeDefined();
    const storage = agent.sessionStorage!;
    const handle = localHandle(sandboxFs);

    await storage.captureToHost({
      hostCwd,
      sandboxCwd,
      sessionId,
      handle,
    });

    expect(await storage.existsOnHost(hostCwd, sessionId)).toBe(true);
    const hostBody = await storage.readHostSession(hostCwd, sessionId);
    expect(hostBody).toBeDefined();
    expect(hostBody!).toContain(dialogueMarker);
    expect(hostBody!).toContain(hostCwd);
    expect(hostBody!).not.toContain(sandboxCwd);
    // Relative layout preserved under host sessions root (native path).
    expect(existsSync(join(hostSessions, relativeRollout))).toBe(true);

    // Resume into a fresh sandbox tree — same session id + context.
    const resumeSbx = tmp("957-codex-resume-sbx-");
    const resumeSessions = join(resumeSbx, "home-.codex-sessions");
    const resumeCwd = join(resumeSbx, "workspace");
    mkdirSync(resumeSessions, { recursive: true });
    const resumeAgent = sc.codex("gpt-5.6-sol", {
      sessionStorage: {
        hostSessionsDir: hostSessions,
        sandboxSessionsDir: resumeSessions,
      },
    });
    await resumeAgent.sessionStorage!.resumeIntoSandbox({
      hostCwd,
      sandboxCwd: resumeCwd,
      sessionId,
      handle: localHandle(resumeSbx),
    });

    const resumedPath = join(resumeSessions, relativeRollout);
    expect(existsSync(resumedPath)).toBe(true);
    const resumedBody = readFileSync(resumedPath, "utf8");
    expect(resumedBody).toContain(dialogueMarker);
    expect(resumedBody).toContain(resumeCwd);
    expect(resumedBody).not.toContain(hostCwd);

    // Resume CLI still targets the same session id (native `codex exec resume`).
    const { command } = agentForSlug("gpt-5.6-sol").buildPrintCommand({
      prompt: "continue the captured dialogue",
      dangerouslySkipPermissions: true,
      resumeSession: sessionId,
    });
    expect(command).toContain("codex exec resume");
    expect(command).toContain(sessionId);
    expect(command).not.toContain("--ephemeral");
  });
});
