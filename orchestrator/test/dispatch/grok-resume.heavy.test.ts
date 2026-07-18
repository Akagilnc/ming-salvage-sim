import {
  execFile,
  mkdtempSync,
  mkdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
  existsSync,
  tmpdir,
  join,
  BindMountSandboxHandle,
  afterEach,
  describe,
  expect,
  it,
  grokAgent,
  resumeCapableForSlug,
  tempDirs,
  tmp,
  localHandleWithStdin,
  RUN_GROK_RESUME_SMOKE,
} from "./grok-resume.shared.js";

afterEach(() => {
  while (tempDirs.length > 0) {
    rmSync(tempDirs.pop()!, { recursive: true, force: true });
  }
});

describe("#955 grok session storage — sandbox transfer roundtrip (real tar/base64 via local shell)", () => {
  it("captureToHost pulls a sandbox session dir and rewrites cwd paths", async () => {
    const hostRoot = tmp("grok-host-");
    const sandboxFs = tmp("grok-sbx-");
    const sandboxCwd = join(sandboxFs, "workspace");
    const hostCwd = tmp("grok-hostcwd-");
    const sessionId = "019f-transfer-1";
    // Seed the SANDBOX session store (as the in-container grok CLI would).
    const sbxSessions = join(sandboxFs, "home-.grok-sessions");
    const sbxDir = join(sbxSessions, encodeURIComponent(sandboxCwd), sessionId);
    mkdirSync(sbxDir, { recursive: true });
    writeFileSync(
      join(sbxDir, "chat_history.jsonl"),
      `{"cwd":"${sandboxCwd}"}\n`,
    );

    const storage = grokAgent("grok-4.5", {
      sessionStorage: {
        hostSessionsDir: hostRoot,
        sandboxSessionsDir: sbxSessions,
      },
    }).sessionStorage!;
    await storage.captureToHost({
      hostCwd,
      sandboxCwd,
      sessionId,
      handle: localHandleWithStdin(sandboxFs),
    });

    const captured = join(hostRoot, encodeURIComponent(hostCwd), sessionId);
    expect(existsSync(join(captured, "chat_history.jsonl"))).toBe(true);
    const body = readFileSync(join(captured, "chat_history.jsonl"), "utf8");
    expect(body).toContain(hostCwd);
    expect(body).not.toContain(sandboxCwd);
  });

  it("resumeIntoSandbox pushes a host session dir into the sandbox store, paths rewritten", async () => {
    const hostRoot = tmp("grok-host-");
    const sandboxFs = tmp("grok-sbx-");
    const sandboxCwd = join(sandboxFs, "workspace");
    const hostCwd = tmp("grok-hostcwd-");
    const sessionId = "019f-transfer-2";
    const hostDir = join(hostRoot, encodeURIComponent(hostCwd), sessionId);
    mkdirSync(hostDir, { recursive: true });
    writeFileSync(join(hostDir, "chat_history.jsonl"), `{"cwd":"${hostCwd}"}\n`);

    const sbxSessions = join(sandboxFs, "home-.grok-sessions");
    const storage = grokAgent("grok-4.5", {
      sessionStorage: {
        hostSessionsDir: hostRoot,
        sandboxSessionsDir: sbxSessions,
      },
    }).sessionStorage!;
    await storage.resumeIntoSandbox({
      hostCwd,
      sandboxCwd,
      sessionId,
      handle: localHandleWithStdin(sandboxFs),
    });

    const pushed = join(sbxSessions, encodeURIComponent(sandboxCwd), sessionId);
    expect(existsSync(join(pushed, "chat_history.jsonl"))).toBe(true);
    const body = readFileSync(join(pushed, "chat_history.jsonl"), "utf8");
    expect(body).toContain(sandboxCwd);
    expect(body).not.toContain(hostCwd);
  });

  it("resumeIntoSandbox rewrites from the hit bucket cwd when hostCwd bucket misses (cross-worktree)", async () => {
    // Session lives under an OLD cwd bucket only; resume is invoked with a NEW
    // hostCwd (worktree re-feed). Rewrite from must be the bucket that actually
    // holds the file, not the caller's hostCwd (r2-F3: from = path present in file).
    const hostRoot = tmp("grok-host-");
    const sandboxFs = tmp("grok-sbx-");
    const sandboxCwd = join(sandboxFs, "workspace");
    const oldHostCwd = "/old/worktree";
    const newHostCwd = "/new/worktree";
    const sessionId = "019f-cross-bucket-resume";
    const hostDir = join(hostRoot, encodeURIComponent(oldHostCwd), sessionId);
    mkdirSync(hostDir, { recursive: true });
    writeFileSync(
      join(hostDir, "chat_history.jsonl"),
      [
        JSON.stringify({ cwd: oldHostCwd }),
        JSON.stringify({ nested: { path: `${oldHostCwd}/src/main.ts` } }),
      ].join("\n") + "\n",
    );

    const sbxSessions = join(sandboxFs, "home-.grok-sessions");
    const storage = grokAgent("grok-4.5", {
      sessionStorage: {
        hostSessionsDir: hostRoot,
        sandboxSessionsDir: sbxSessions,
      },
    }).sessionStorage!;
    await storage.resumeIntoSandbox({
      hostCwd: newHostCwd,
      sandboxCwd,
      sessionId,
      handle: localHandleWithStdin(sandboxFs),
    });

    const body = readFileSync(
      join(sbxSessions, encodeURIComponent(sandboxCwd), sessionId, "chat_history.jsonl"),
      "utf8",
    );
    expect(body).toContain(sandboxCwd);
    expect(body).toContain(`${sandboxCwd}/src/main.ts`);
    expect(body).not.toContain(oldHostCwd);
    expect(body).not.toContain(newHostCwd);
  });

  it("rewrite does not pollute sibling path prefixes or dialogue mentions", async () => {
    // from=/work/tree must not rewrite /work/tree-2, nor prose that merely
    // mentions the path as a substring of a longer string value.
    const hostRoot = tmp("grok-host-");
    const sandboxFs = tmp("grok-sbx-");
    const sandboxCwd = "/work/tree";
    const siblingCwd = "/work/tree-2";
    const hostCwd = "/host/work";
    const sessionId = "019f-rewrite-bound";
    const sbxSessions = join(sandboxFs, "home-.grok-sessions");
    const sbxDir = join(sbxSessions, encodeURIComponent(sandboxCwd), sessionId);
    mkdirSync(sbxDir, { recursive: true });
    writeFileSync(
      join(sbxDir, "chat_history.jsonl"),
      [
        JSON.stringify({ cwd: sandboxCwd }),
        JSON.stringify({ cwd: siblingCwd }),
        JSON.stringify({
          role: "user",
          text: `please look at ${sandboxCwd} and ${siblingCwd}`,
        }),
        JSON.stringify({ nested: { path: `${sandboxCwd}/src/main.ts` } }),
      ].join("\n") + "\n",
    );

    const storage = grokAgent("grok-4.5", {
      sessionStorage: {
        hostSessionsDir: hostRoot,
        sandboxSessionsDir: sbxSessions,
      },
    }).sessionStorage!;
    await storage.captureToHost({
      hostCwd,
      sandboxCwd,
      sessionId,
      handle: localHandleWithStdin(sandboxFs),
    });

    const body = readFileSync(
      join(hostRoot, encodeURIComponent(hostCwd), sessionId, "chat_history.jsonl"),
      "utf8",
    );
    const lines = body
      .trim()
      .split("\n")
      .map((line) => JSON.parse(line) as Record<string, unknown>);
    expect(lines[0]).toEqual({ cwd: hostCwd });
    expect(lines[1]).toEqual({ cwd: siblingCwd });
    expect(lines[2]).toEqual({
      role: "user",
      text: `please look at ${sandboxCwd} and ${siblingCwd}`,
    });
    expect(lines[3]).toEqual({
      nested: { path: `${hostCwd}/src/main.ts` },
    });
    expect(body).not.toContain(`${hostCwd}-2`);
  });
});

describe("#955 grok session storage — failure paths", () => {

  it("resumeIntoSandbox times out a never-settling sandbox exec with classified error", async () => {
    const hostRoot = tmp("grok-host-");
    const sandboxFs = tmp("grok-sbx-");
    const hostCwd = "/host/cwd";
    const sessionId = "019f-hang-import";
    const hostDir = join(hostRoot, encodeURIComponent(hostCwd), sessionId);
    mkdirSync(hostDir, { recursive: true });
    writeFileSync(join(hostDir, "chat_history.jsonl"), `{"cwd":"${hostCwd}"}\n`);

    const handle: BindMountSandboxHandle = {
      worktreePath: sandboxFs,
      exec: () =>
        new Promise(() => {
          /* never settle — wall clock must fire */
        }),
      copyFileIn: async () => {},
      copyFileOut: async () => {},
      close: async () => {},
    };
    const storage = grokAgent("grok-4.5", {
      sessionStorage: {
        hostSessionsDir: hostRoot,
        sandboxSessionsDir: join(sandboxFs, "sessions"),
      },
    }).sessionStorage!;

    await expect(
      storage.resumeIntoSandbox({
        hostCwd,
        sandboxCwd: "/sbx/cwd",
        sessionId,
        handle,
      }),
    ).rejects.toMatchObject({
      name: "ExternalCallTimeoutError",
      stage: expect.stringMatching(
        new RegExp(
          `grok-session:sandbox-import.*sessionId=${sessionId.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`,
        ),
      ),
    });
  });
});

describe.skipIf(!RUN_GROK_RESUME_SMOKE)(
  "#955 live grok --resume smoke (GROK_RESUME_SMOKE=1)",
  () => {
    it(
      "starts a session, resumes by id, and recalls a unique token",
      async () => {
        const work = tmp("grok-smoke-");
        const token = `TOKEN_SMOKE_955_${Date.now().toString(36)}`;

        const runGrok = (
          prompt: string,
          resumeSession?: string,
        ): Promise<{ stdout: string; exitCode: number }> =>
          new Promise((resolve, reject) => {
            const built = grokAgent("grok-4.5", {
              captureSessions: false,
            }).buildPrintCommand({
              prompt,
              dangerouslySkipPermissions: true,
              resumeSession,
            });
            const child = execFile(
              "bash",
              ["-c", built.command],
              { cwd: work, maxBuffer: 16 * 1024 * 1024, timeout: 120_000 },
              (err, stdout, stderr) => {
                if (err && (err as { killed?: boolean }).killed) {
                  reject(
                    new Error(
                      `grok smoke timed out; stderr=${String(stderr).slice(0, 400)}`,
                    ),
                  );
                  return;
                }
                const code = err
                  ? ((err as { code?: number }).code ?? 1)
                  : 0;
                resolve({
                  stdout: String(stdout),
                  exitCode: typeof code === "number" ? code : 1,
                });
              },
            );
            child.stdin?.write(built.stdin);
            child.stdin?.end();
          });

        const first = await runGrok(
          `Reply with exactly ${token} on one line and nothing else.`,
        );
        expect(first.exitCode).toBe(0);

        let sessionId: string | undefined;
        let firstText = "";
        for (const line of first.stdout.split("\n")) {
          const trimmed = line.trim();
          if (!trimmed.startsWith("{")) continue;
          try {
            const obj = JSON.parse(trimmed) as {
              type?: string;
              data?: string;
              sessionId?: string;
            };
            if (obj.type === "text" && typeof obj.data === "string") {
              firstText += obj.data;
            }
            if (obj.type === "end" && typeof obj.sessionId === "string") {
              sessionId = obj.sessionId;
            }
          } catch {
            // ignore non-JSON
          }
        }
        expect(firstText).toContain(token);
        expect(sessionId).toBeTruthy();

        const second = await runGrok(
          "What unique token did I ask you to reply with earlier? Reply with only that token.",
          sessionId,
        );
        expect(second.exitCode).toBe(0);
        let resumeText = "";
        for (const line of second.stdout.split("\n")) {
          const trimmed = line.trim();
          if (!trimmed.startsWith("{")) continue;
          try {
            const obj = JSON.parse(trimmed) as {
              type?: string;
              data?: string;
            };
            if (obj.type === "text" && typeof obj.data === "string") {
              resumeText += obj.data;
            }
          } catch {
            // ignore
          }
        }
        expect(resumeText).toContain(token);
      },
      180_000,
    );
  },
);
