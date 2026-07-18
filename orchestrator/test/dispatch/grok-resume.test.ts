/**
 * #955 — grokAgent implements the sandcastle resume contract.
 *
 * Sandcastle's capability predicate is interface-based: `provider.sessionStorage`
 * present ⇒ resumeSession and Output.object maxRetries>0 are allowed (the
 * "claudeCode, codex, or pi" in its error text is prose, not the check).
 * The grok CLI natively supports `--resume [<id>]` / `--fork-session`, and
 * stores sessions as one DIRECTORY per session id under
 * `~/.grok/sessions/<encodeURIComponent(cwd)>/<sessionId>/`.
 */
import { execFile } from "node:child_process";
import {
  mkdtempSync,
  mkdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
  existsSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { BindMountSandboxHandle } from "@ai-hero/sandcastle";
import { afterEach, describe, expect, it } from "vitest";
import { grokAgent } from "../../src/grokAgent.js";
import { resumeCapableForSlug } from "../../src/modelRegistry.js";

const tempDirs: string[] = [];
function tmp(prefix: string): string {
  const d = mkdtempSync(join(tmpdir(), prefix));
  tempDirs.push(d);
  return d;
}
afterEach(() => {
  while (tempDirs.length > 0) {
    rmSync(tempDirs.pop()!, { recursive: true, force: true });
  }
});

/**
 * Fake sandbox handle: `exec` runs the command through a real local shell so
 * tar/base64 transfer behaves exactly as in a container — the "sandbox" is
 * just another directory on this machine. Fully typed as BindMountSandboxHandle
 * (no `as never`); unused transfer methods are no-op stubs.
 */
function localHandleWithStdin(worktreePath: string): BindMountSandboxHandle {
  return {
    worktreePath,
    exec: (
      command: string,
      options?: {
        onLine?: (line: string) => void;
        cwd?: string;
        sudo?: boolean;
        stdin?: string;
      },
    ): Promise<{ stdout: string; stderr: string; exitCode: number }> =>
      new Promise((resolve) => {
        const child = execFile(
          "sh",
          ["-c", command],
          { cwd: options?.cwd ?? worktreePath, maxBuffer: 64 * 1024 * 1024 },
          (err, stdout, stderr) => {
            const code = err
              ? ((err as { code?: number }).code ?? 1)
              : 0;
            resolve({
              stdout: String(stdout),
              stderr: String(stderr),
              exitCode: typeof code === "number" ? code : 1,
            });
          },
        );
        if (options?.stdin !== undefined) {
          child.stdin?.write(options.stdin);
        }
        child.stdin?.end();
      }),
    copyFileIn: async () => {},
    copyFileOut: async () => {},
    close: async () => {},
  };
}

describe("#955 buildPrintCommand resume flags", () => {
  const agent = grokAgent("grok-4.5");

  it("appends --resume <id> when resumeSession is set", () => {
    const { command } = agent.buildPrintCommand({
      prompt: "p",
      dangerouslySkipPermissions: true,
      resumeSession: "019f-abc",
    });
    expect(command).toContain("--resume 019f-abc");
    expect(command).not.toContain("--fork-session");
  });

  it("appends --fork-session only alongside resumeSession", () => {
    const { command } = agent.buildPrintCommand({
      prompt: "p",
      dangerouslySkipPermissions: true,
      resumeSession: "019f-abc",
      forkSession: true,
    });
    expect(command).toContain("--resume 019f-abc");
    expect(command).toContain("--fork-session");
  });

  it("omits resume flags on a fresh run (negative)", () => {
    const { command } = agent.buildPrintCommand({
      prompt: "p",
      dangerouslySkipPermissions: true,
    });
    expect(command).not.toContain("--resume");
    expect(command).not.toContain("--fork-session");
  });
});

describe("#955 provider capability surface", () => {
  it("exposes sessionStorage and captures sessions by default", () => {
    const agent = grokAgent("grok-4.5");
    expect(agent.captureSessions).toBe(true);
    expect(agent.sessionStorage).toBeDefined();
    for (const m of [
      "captureToHost",
      "resumeIntoSandbox",
      "readHostSession",
      "existsOnHost",
      "hostSessionFilePath",
      "findByIdOnHost",
    ] as const) {
      expect(typeof agent.sessionStorage?.[m]).toBe("function");
    }
  });

  it("captureSessions:false still opts out", () => {
    expect(grokAgent("grok-4.5", { captureSessions: false }).captureSessions).toBe(
      false,
    );
  });

  it("registry now reports grok as resume-capable (SO maxRetries returns to 2)", () => {
    expect(resumeCapableForSlug("grok-4.5")).toBe(true);
  });
});

describe("#955 grok session storage — host-store semantics", () => {
  const cwd = "/work/tree";
  const sessionId = "019f4753-403b-79e1-b2a4-c9f3931193f0";

  function seedHostSession(root: string): string {
    const dir = join(root, encodeURIComponent(cwd), sessionId);
    mkdirSync(dir, { recursive: true });
    writeFileSync(
      join(dir, "chat_history.jsonl"),
      `{"role":"user","cwd":"${cwd}"}\n`,
    );
    writeFileSync(join(dir, "events.jsonl"), `{"type":"end"}\n`);
    return dir;
  }

  it("existsOnHost / hostSessionFilePath / readHostSession round out the store", async () => {
    const root = tmp("grok-store-");
    seedHostSession(root);
    const storage = grokAgent("grok-4.5", {
      sessionStorage: { hostSessionsDir: root },
    }).sessionStorage!;
    expect(await storage.existsOnHost(cwd, sessionId)).toBe(true);
    expect(await storage.existsOnHost(cwd, "no-such-id")).toBe(false);
    expect(storage.hostSessionFilePath(cwd, sessionId)).toContain(sessionId);
    const jsonl = await storage.readHostSession(cwd, sessionId);
    expect(jsonl).toContain('"role":"user"');
    expect(await storage.readHostSession(cwd, "no-such-id")).toBeUndefined();
  });

  it("findByIdOnHost locates across cwd buckets and reports searchedRoot on miss", async () => {
    const root = tmp("grok-store-");
    seedHostSession(root);
    const storage = grokAgent("grok-4.5", {
      sessionStorage: { hostSessionsDir: root },
    }).sessionStorage!;
    const hit = await storage.findByIdOnHost(sessionId);
    expect(hit.path).toContain(sessionId);
    const miss = await storage.findByIdOnHost("missing-id");
    expect(miss.path).toBeUndefined();
    expect(miss.searchedRoot).toBe(root);
  });
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
  it("captureToHost throws grok-cap with stderr when sandbox exec is non-zero", async () => {
    const hostRoot = tmp("grok-host-");
    const sandboxFs = tmp("grok-sbx-");
    const sessionId = "019f-fail-cap";
    const handle: BindMountSandboxHandle = {
      worktreePath: sandboxFs,
      exec: async () => ({
        stdout: "",
        stderr: "tar: cannot open: No such file or directory",
        exitCode: 2,
      }),
      copyFileIn: async () => {},
      copyFileOut: async () => {},
      close: async () => {},
    };
    const storage = grokAgent("grok-4.5", {
      sessionStorage: {
        hostSessionsDir: hostRoot,
        sandboxSessionsDir: join(sandboxFs, "missing-sessions"),
      },
    }).sessionStorage!;

    await expect(
      storage.captureToHost({
        hostCwd: "/host",
        sandboxCwd: "/sbx",
        sessionId,
        handle,
      }),
    ).rejects.toThrow(/grok-cap[\s\S]*tar: cannot open/);
  });

  it("resumeIntoSandbox throws with searchedRoot when host session is missing", async () => {
    const hostRoot = tmp("grok-host-empty-");
    const sandboxFs = tmp("grok-sbx-");
    const storage = grokAgent("grok-4.5", {
      sessionStorage: {
        hostSessionsDir: hostRoot,
        sandboxSessionsDir: join(sandboxFs, "sessions"),
      },
    }).sessionStorage!;

    await expect(
      storage.resumeIntoSandbox({
        hostCwd: "/host/cwd",
        sandboxCwd: "/sbx/cwd",
        sessionId: "no-such-session-id",
        handle: localHandleWithStdin(sandboxFs),
      }),
    ).rejects.toThrow(
      new RegExp(
        `grok-res: session "no-such-session-id" not found under ${hostRoot.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`,
      ),
    );
  });

  /**
   * #884 / #955 cx-r4-1: sandbox handle.exec is an external wait outside the
   * agent idle clock. Never-settling exec must surface ExternalCallTimeoutError
   * (classifiable transient) with stage + sessionId — not hang the seat forever.
   */
  it("captureToHost times out a never-settling sandbox exec with classified error", async () => {
    const hostRoot = tmp("grok-host-");
    const sandboxFs = tmp("grok-sbx-");
    const sessionId = "019f-hang-export";
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
      storage.captureToHost({
        hostCwd: "/host",
        sandboxCwd: "/sbx",
        sessionId,
        handle,
      }),
    ).rejects.toMatchObject({
      name: "ExternalCallTimeoutError",
      stage: expect.stringMatching(
        new RegExp(
          `grok-session:sandbox-export.*sessionId=${sessionId.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`,
        ),
      ),
    });
  });

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

/**
 * Live smoke: real grok CLI start → sessionId → --resume → context recall.
 * Env-gated (GROK_RESUME_SMOKE=1); CI defaults to skip. Serial + long timeout.
 */
const RUN_GROK_RESUME_SMOKE = process.env.GROK_RESUME_SMOKE === "1";

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
              "sh",
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
