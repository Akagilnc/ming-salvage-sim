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
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { promisify } from "node:util";
import { afterEach, describe, expect, it } from "vitest";
import { grokAgent } from "../../src/grokAgent.js";
import { resumeCapableForSlug } from "../../src/modelRegistry.js";

const execFileP = promisify(execFile);

const tempDirs: string[] = [];
function tmp(prefix: string): string {
  const d = mkdtempSync(join(tmpdir(), prefix));
  tempDirs.push(d);
  return d;
}
afterEach(() => {
  while (tempDirs.length > 0) rmSync(tempDirs.pop()!, { recursive: true, force: true });
});

/**
 * Fake sandbox handle: `exec` runs the command through a real local shell so
 * tar/base64 transfer behaves exactly as in a container — the "sandbox" is
 * just another directory on this machine.
 */
function localHandle(worktreePath: string) {
  return {
    worktreePath,
    exec: async (
      command: string,
      options?: { onLine?: (l: string) => void; cwd?: string; sudo?: boolean; stdin?: string },
    ) => {
      try {
        const { stdout, stderr } = await execFileP("bash", ["-c", command], {
          cwd: options?.cwd ?? worktreePath,
          maxBuffer: 64 * 1024 * 1024,
          ...(options?.stdin !== undefined ? {} : {}),
        } as never);
        return { stdout, stderr, exitCode: 0 };
      } catch (err) {
        const e = err as { stdout?: string; stderr?: string; code?: number };
        return { stdout: e.stdout ?? "", stderr: e.stderr ?? "", exitCode: e.code ?? 1 };
      }
    },
  };
}

/** stdin-capable variant (promisify(execFile) cannot pipe stdin). */
function localHandleWithStdin(worktreePath: string) {
  return {
    worktreePath,
    exec: (
      command: string,
      options?: { onLine?: (l: string) => void; cwd?: string; sudo?: boolean; stdin?: string },
    ): Promise<{ stdout: string; stderr: string; exitCode: number }> =>
      new Promise((resolve) => {
        const child = execFile(
          "bash",
          ["-c", command],
          { cwd: options?.cwd ?? worktreePath, maxBuffer: 64 * 1024 * 1024 },
          (err, stdout, stderr) => {
            const code = err ? ((err as { code?: number }).code ?? 1) : 0;
            resolve({ stdout: String(stdout), stderr: String(stderr), exitCode: typeof code === "number" ? code : 1 });
          },
        );
        if (options?.stdin !== undefined) {
          child.stdin?.write(options.stdin);
        }
        child.stdin?.end();
      }),
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
    expect(grokAgent("grok-4.5", { captureSessions: false }).captureSessions).toBe(false);
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
    writeFileSync(join(dir, "chat_history.jsonl"), `{"role":"user","cwd":"${cwd}"}\n`);
    writeFileSync(join(dir, "events.jsonl"), `{"type":"end"}\n`);
    return dir;
  }

  it("existsOnHost / hostSessionFilePath / readHostSession round out the store", async () => {
    const root = tmp("grok-store-");
    seedHostSession(root);
    const storage = grokAgent("grok-4.5", { sessionStorage: { hostSessionsDir: root } })
      .sessionStorage!;
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
    const storage = grokAgent("grok-4.5", { sessionStorage: { hostSessionsDir: root } })
      .sessionStorage!;
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
    writeFileSync(join(sbxDir, "chat_history.jsonl"), `{"cwd":"${sandboxCwd}"}\n`);

    const storage = grokAgent("grok-4.5", {
      sessionStorage: { hostSessionsDir: hostRoot, sandboxSessionsDir: sbxSessions },
    }).sessionStorage!;
    await storage.captureToHost({
      hostCwd,
      sandboxCwd,
      sessionId,
      handle: localHandleWithStdin(sandboxFs) as never,
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
      sessionStorage: { hostSessionsDir: hostRoot, sandboxSessionsDir: sbxSessions },
    }).sessionStorage!;
    await storage.resumeIntoSandbox({
      hostCwd,
      sandboxCwd,
      sessionId,
      handle: localHandleWithStdin(sandboxFs) as never,
    });

    const pushed = join(sbxSessions, encodeURIComponent(sandboxCwd), sessionId);
    expect(existsSync(join(pushed, "chat_history.jsonl"))).toBe(true);
    const body = readFileSync(join(pushed, "chat_history.jsonl"), "utf8");
    expect(body).toContain(sandboxCwd);
    expect(body).not.toContain(hostCwd);
  });
});
