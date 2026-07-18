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
          "bash",
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

});

/**
 * Live smoke: real grok CLI start → sessionId → --resume → context recall.
 * Env-gated (GROK_RESUME_SMOKE=1); CI defaults to skip. Serial + long timeout.
 */
const RUN_GROK_RESUME_SMOKE = process.env.GROK_RESUME_SMOKE === "1";
