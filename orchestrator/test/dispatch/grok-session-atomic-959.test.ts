/**
 * #959 — captureToHost must land via same-volume temp + integrity + atomic
 * rename swap. Mid-transfer failure must not poison an existing host session;
 * concurrent same-slug captures must never leave a mixed directory.
 */
import { execFile } from "node:child_process";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { BindMountSandboxHandle } from "@ai-hero/sandcastle";
import { afterEach, describe, expect, it, vi } from "vitest";

/** When true, host tar-extract succeeds then throws (mid-transfer inject). */
let failAfterHostExtract = false;

vi.mock("../../src/externalCall.js", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../src/externalCall.js")>();
  return {
    ...actual,
    execFileAsyncWithTimeout: async (
      file: string,
      args: readonly string[],
      opts: Parameters<typeof actual.execFileAsyncWithTimeout>[2],
    ) => {
      const result = await actual.execFileAsyncWithTimeout(file, args, opts);
      if (failAfterHostExtract && opts.stage === "grok-session:tar-extract") {
        throw new Error("injected mid-transfer failure after extract");
      }
      return result;
    },
  };
});

// Import after vi.mock so captureToHost's dynamic import of externalCall sees the mock.
const {
  makeGrokSessionStorage,
  grokSessionAtomicReplaceTestInject,
} = await import("../../src/grokSessionStorage.js");

const tempDirs: string[] = [];
function tmp(prefix: string): string {
  const d = mkdtempSync(join(tmpdir(), prefix));
  tempDirs.push(d);
  return d;
}
afterEach(() => {
  failAfterHostExtract = false;
  grokSessionAtomicReplaceTestInject.reset();
  while (tempDirs.length > 0) {
    rmSync(tempDirs.pop()!, { recursive: true, force: true });
  }
});

/** Leftover `.<sessionId>.old-*` backups under a cwd bucket (Standards S1). */
function oldBackupNames(bucketDir: string, sessionId: string): string[] {
  if (!existsSync(bucketDir)) return [];
  return readdirSync(bucketDir).filter(
    (n) => n.startsWith(`.${sessionId}.old-`) || n.includes(`.old-`),
  );
}
/** Local-shell sandbox handle — same pattern as grok-resume.test.ts. */
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
            const code = err ? ((err as { code?: number }).code ?? 1) : 0;
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

function seedSandboxSession(
  sandboxFs: string,
  sbxSessions: string,
  sandboxCwd: string,
  sessionId: string,
  files: Record<string, string>,
): void {
  const dir = join(sbxSessions, encodeURIComponent(sandboxCwd), sessionId);
  mkdirSync(dir, { recursive: true });
  for (const [name, body] of Object.entries(files)) {
    writeFileSync(join(dir, name), body);
  }
}

function seedHostSession(
  hostRoot: string,
  hostCwd: string,
  sessionId: string,
  files: Record<string, string>,
): string {
  const dir = join(hostRoot, encodeURIComponent(hostCwd), sessionId);
  mkdirSync(dir, { recursive: true });
  for (const [name, body] of Object.entries(files)) {
    writeFileSync(join(dir, name), body);
  }
  return dir;
}

describe("#959 captureToHost atomic temp+swap", () => {
  it("happy path: capture rewrites paths and lands a complete host session", async () => {
    const hostRoot = tmp("grok-959-host-");
    const sandboxFs = tmp("grok-959-sbx-");
    const sandboxCwd = join(sandboxFs, "workspace");
    const hostCwd = tmp("grok-959-hostcwd-");
    const sessionId = "019f-959-happy";
    const sbxSessions = join(sandboxFs, "home-.grok-sessions");
    seedSandboxSession(sandboxFs, sbxSessions, sandboxCwd, sessionId, {
      "chat_history.jsonl": `{"cwd":"${sandboxCwd}","mark":"happy"}\n`,
      "events.jsonl": `{"type":"end","mark":"happy"}\n`,
    });

    const storage = makeGrokSessionStorage({
      hostSessionsDir: hostRoot,
      sandboxSessionsDir: sbxSessions,
    });
    await storage.captureToHost({
      hostCwd,
      sandboxCwd,
      sessionId,
      handle: localHandleWithStdin(sandboxFs),
    });

    const captured = join(hostRoot, encodeURIComponent(hostCwd), sessionId);
    const history = readFileSync(join(captured, "chat_history.jsonl"), "utf8");
    const events = readFileSync(join(captured, "events.jsonl"), "utf8");
    expect(history).toContain(hostCwd);
    expect(history).toContain('"mark":"happy"');
    expect(history).not.toContain(sandboxCwd);
    expect(events).toContain('"mark":"happy"');
    // No leftover staging dirs under the cwd bucket.
    const bucket = join(hostRoot, encodeURIComponent(hostCwd));
    const leftovers = readdirSync(bucket).filter((n) => n.startsWith(".grok-cap-"));
    expect(leftovers).toEqual([]);
  });

  it("mid-transfer failure preserves existing host session for resume (no half-write)", async () => {
    const hostRoot = tmp("grok-959-host-");
    const sandboxFs = tmp("grok-959-sbx-");
    const sandboxCwd = join(sandboxFs, "workspace");
    const hostCwd = tmp("grok-959-hostcwd-midfail-");
    const sessionId = "019f-959-midfail";
    const oldHistory = `{"cwd":"${hostCwd}","mark":"OLD_SESSION_V1"}\n`;
    const oldEvents = `{"type":"end","mark":"OLD_SESSION_V1"}\n`;
    seedHostSession(hostRoot, hostCwd, sessionId, {
      "chat_history.jsonl": oldHistory,
      "events.jsonl": oldEvents,
    });

    // Real sandbox export of a complete NEW session. Host tar-extract is forced
    // to fail immediately after a successful unpack — non-atomic capture would
    // already have overwritten the live host dir; atomic staging keeps OLD.
    const sbxSessions = join(sandboxFs, "home-.grok-sessions");
    seedSandboxSession(sandboxFs, sbxSessions, sandboxCwd, sessionId, {
      "chat_history.jsonl": `{"cwd":"${sandboxCwd}","mark":"NEW_SESSION_V2"}\n`,
      "events.jsonl": `{"type":"end","mark":"NEW_SESSION_V2"}\n`,
    });

    failAfterHostExtract = true;
    const storage = makeGrokSessionStorage({
      hostSessionsDir: hostRoot,
      sandboxSessionsDir: sbxSessions,
    });

    await expect(
      storage.captureToHost({
        hostCwd,
        sandboxCwd,
        sessionId,
        handle: localHandleWithStdin(sandboxFs),
      }),
    ).rejects.toThrow(/injected mid-transfer failure after extract/);

    const hostDir = join(hostRoot, encodeURIComponent(hostCwd), sessionId);
    expect(readFileSync(join(hostDir, "chat_history.jsonl"), "utf8")).toBe(oldHistory);
    expect(readFileSync(join(hostDir, "events.jsonl"), "utf8")).toBe(oldEvents);
    expect(readFileSync(join(hostDir, "chat_history.jsonl"), "utf8")).not.toContain(
      "NEW_SESSION_V2",
    );

    // Resume path still sees the intact old session (readHostSession + exists).
    expect(await storage.existsOnHost(hostCwd, sessionId)).toBe(true);
    expect(await storage.readHostSession(hostCwd, sessionId)).toBe(oldHistory);

    // Push into a local "sandbox" to prove resume still works end-to-end.
    failAfterHostExtract = false;
    const resumeFs = tmp("grok-959-resume-");
    const resumeSbxSessions = join(resumeFs, "sessions");
    const resumeStorage = makeGrokSessionStorage({
      hostSessionsDir: hostRoot,
      sandboxSessionsDir: resumeSbxSessions,
    });
    await resumeStorage.resumeIntoSandbox({
      hostCwd,
      sandboxCwd: join(resumeFs, "workspace"),
      sessionId,
      handle: localHandleWithStdin(resumeFs),
    });
    const resumed = readFileSync(
      join(
        resumeSbxSessions,
        encodeURIComponent(join(resumeFs, "workspace")),
        sessionId,
        "chat_history.jsonl",
      ),
      "utf8",
    );
    expect(resumed).toContain("OLD_SESSION_V1");
    expect(resumed).not.toContain("NEW_SESSION_V2");
  });

  it("swap-segment place failure after displace restores old complete session (resumeable)", async () => {
    // Spec S1: failure during the rename swap (after live is displaced to
    // .old-*, before/while placing staging) must restore the prior complete
    // tree — existing failure tests only inject pre-swap (extract/integrity).
    const hostRoot = tmp("grok-959-host-");
    const sandboxFs = tmp("grok-959-sbx-");
    const sandboxCwd = join(sandboxFs, "workspace");
    const hostCwd = tmp("grok-959-hostcwd-swapfail-");
    const sessionId = "019f-959-swapfail";
    const oldHistory = `{"cwd":"${hostCwd}","mark":"OLD_PRE_SWAP"}\n`;
    const oldEvents = `{"type":"end","mark":"OLD_PRE_SWAP"}\n`;
    seedHostSession(hostRoot, hostCwd, sessionId, {
      "chat_history.jsonl": oldHistory,
      "events.jsonl": oldEvents,
    });

    const sbxSessions = join(sandboxFs, "home-.grok-sessions");
    seedSandboxSession(sandboxFs, sbxSessions, sandboxCwd, sessionId, {
      "chat_history.jsonl": `{"cwd":"${sandboxCwd}","mark":"NEW_SHOULD_NOT_LAND"}\n`,
      "events.jsonl": `{"type":"end","mark":"NEW_SHOULD_NOT_LAND"}\n`,
    });

    grokSessionAtomicReplaceTestInject.failPlaceAfterDisplace = true;
    const storage = makeGrokSessionStorage({
      hostSessionsDir: hostRoot,
      sandboxSessionsDir: sbxSessions,
    });

    await expect(
      storage.captureToHost({
        hostCwd,
        sandboxCwd,
        sessionId,
        handle: localHandleWithStdin(sandboxFs),
      }),
    ).rejects.toThrow(/injected place failure after displace/);

    const hostDir = join(hostRoot, encodeURIComponent(hostCwd), sessionId);
    expect(readFileSync(join(hostDir, "chat_history.jsonl"), "utf8")).toBe(
      oldHistory,
    );
    expect(readFileSync(join(hostDir, "events.jsonl"), "utf8")).toBe(oldEvents);
    expect(readFileSync(join(hostDir, "chat_history.jsonl"), "utf8")).not.toContain(
      "NEW_SHOULD_NOT_LAND",
    );

    // Restore path used rename(backup→target); no orphan .old-* left behind.
    const bucket = join(hostRoot, encodeURIComponent(hostCwd));
    expect(oldBackupNames(bucket, sessionId)).toEqual([]);

    expect(await storage.existsOnHost(hostCwd, sessionId)).toBe(true);
    expect(await storage.readHostSession(hostCwd, sessionId)).toBe(oldHistory);

    // End-to-end resume still sees the restored complete old version.
    const resumeFs = tmp("grok-959-swap-resume-");
    const resumeSbxSessions = join(resumeFs, "sessions");
    const resumeStorage = makeGrokSessionStorage({
      hostSessionsDir: hostRoot,
      sandboxSessionsDir: resumeSbxSessions,
    });
    await resumeStorage.resumeIntoSandbox({
      hostCwd,
      sandboxCwd: join(resumeFs, "workspace"),
      sessionId,
      handle: localHandleWithStdin(resumeFs),
    });
    const resumed = readFileSync(
      join(
        resumeSbxSessions,
        encodeURIComponent(join(resumeFs, "workspace")),
        sessionId,
        "chat_history.jsonl",
      ),
      "utf8",
    );
    expect(resumed).toContain("OLD_PRE_SWAP");
    expect(resumed).not.toContain("NEW_SHOULD_NOT_LAND");
  });

  it("swap place fail with concurrent winner leaves winner intact and cleans our .old backup", async () => {
    // Standards S1: when place fails but live was recreated by a concurrent
    // winner, do not restore our stale backup over them — and drop the orphan.
    const hostRoot = tmp("grok-959-host-");
    const sandboxFs = tmp("grok-959-sbx-");
    const sandboxCwd = join(sandboxFs, "workspace");
    const hostCwd = tmp("grok-959-hostcwd-orphan-");
    const sessionId = "019f-959-orphan";
    seedHostSession(hostRoot, hostCwd, sessionId, {
      "chat_history.jsonl": `{"cwd":"${hostCwd}","mark":"OLD_DISPLACED"}\n`,
      "events.jsonl": `{"type":"end","mark":"OLD_DISPLACED"}\n`,
    });

    const sbxSessions = join(sandboxFs, "home-.grok-sessions");
    seedSandboxSession(sandboxFs, sbxSessions, sandboxCwd, sessionId, {
      "chat_history.jsonl": `{"cwd":"${sandboxCwd}","mark":"LOSER_STAGING"}\n`,
      "events.jsonl": `{"type":"end","mark":"LOSER_STAGING"}\n`,
    });

    const winnerHistory = `{"cwd":"${hostCwd}","mark":"CONCURRENT_WINNER"}\n`;
    const winnerEvents = `{"type":"end","mark":"CONCURRENT_WINNER"}\n`;
    // After our displace, plant a complete concurrent winner at the live path
    // so place fails (ENOTEMPTY) and restore must be suppressed.
    grokSessionAtomicReplaceTestInject.afterDisplace = async ({ targetDir }) => {
      mkdirSync(targetDir, { recursive: true });
      writeFileSync(join(targetDir, "chat_history.jsonl"), winnerHistory);
      writeFileSync(join(targetDir, "events.jsonl"), winnerEvents);
    };

    const storage = makeGrokSessionStorage({
      hostSessionsDir: hostRoot,
      sandboxSessionsDir: sbxSessions,
    });

    await expect(
      storage.captureToHost({
        hostCwd,
        sandboxCwd,
        sessionId,
        handle: localHandleWithStdin(sandboxFs),
      }),
    ).rejects.toThrow();

    const hostDir = join(hostRoot, encodeURIComponent(hostCwd), sessionId);
    expect(readFileSync(join(hostDir, "chat_history.jsonl"), "utf8")).toBe(
      winnerHistory,
    );
    expect(readFileSync(join(hostDir, "events.jsonl"), "utf8")).toBe(
      winnerEvents,
    );
    expect(readFileSync(join(hostDir, "chat_history.jsonl"), "utf8")).not.toContain(
      "LOSER_STAGING",
    );
    expect(readFileSync(join(hostDir, "chat_history.jsonl"), "utf8")).not.toContain(
      "OLD_DISPLACED",
    );

    // Our displaced backup must not linger as an orphan.
    const bucket = join(hostRoot, encodeURIComponent(hostCwd));
    expect(oldBackupNames(bucket, sessionId)).toEqual([]);

    // Winner is a complete single version — resumeable.
    expect(await storage.readHostSession(hostCwd, sessionId)).toBe(winnerHistory);
  });

  it("CR-9: staged symlink is rejected and leaves existing host session untouched", async () => {
    const hostRoot = tmp("grok-959-host-");
    const sandboxFs = tmp("grok-959-sbx-");
    const sandboxCwd = join(sandboxFs, "workspace");
    const hostCwd = tmp("grok-959-hostcwd-");
    const sessionId = "019f-959-symlink";
    const oldHistory = `{"cwd":"${hostCwd}","mark":"KEEP_SYMLINK"}\n`;
    seedHostSession(hostRoot, hostCwd, sessionId, {
      "chat_history.jsonl": oldHistory,
    });

    // Sandbox tree with a symlink that would escape if followed on the host.
    const sbxSessions = join(sandboxFs, "home-.grok-sessions");
    const outside = tmp("grok-959-outside-");
    writeFileSync(join(outside, "secret.txt"), "secret-payload\n");
    const dir = join(sbxSessions, encodeURIComponent(sandboxCwd), sessionId);
    mkdirSync(dir, { recursive: true });
    writeFileSync(
      join(dir, "chat_history.jsonl"),
      `{"cwd":"${sandboxCwd}","mark":"evil"}\n`,
    );
    symlinkSync(join(outside, "secret.txt"), join(dir, "events.jsonl"));

    const storage = makeGrokSessionStorage({
      hostSessionsDir: hostRoot,
      sandboxSessionsDir: sbxSessions,
    });

    await expect(
      storage.captureToHost({
        hostCwd,
        sandboxCwd,
        sessionId,
        handle: localHandleWithStdin(sandboxFs),
      }),
    ).rejects.toThrow(/unsupported session entry|symlink|integrity/i);

    expect(
      readFileSync(
        join(hostRoot, encodeURIComponent(hostCwd), sessionId, "chat_history.jsonl"),
        "utf8",
      ),
    ).toBe(oldHistory);
  });

  it("integrity failure after unpack leaves existing host session untouched", async () => {
    const hostRoot = tmp("grok-959-host-");
    const sandboxFs = tmp("grok-959-sbx-");
    const sandboxCwd = join(sandboxFs, "workspace");
    const hostCwd = tmp("grok-959-hostcwd-");
    const sessionId = "019f-959-integrity";
    const oldHistory = `{"cwd":"${hostCwd}","mark":"KEEP_ME"}\n`;
    seedHostSession(hostRoot, hostCwd, sessionId, {
      "chat_history.jsonl": oldHistory,
      "events.jsonl": `{"type":"end","mark":"KEEP_ME"}\n`,
    });

    // Valid tar structure, but chat_history.jsonl is not parseable JSONL.
    const sbxSessions = join(sandboxFs, "home-.grok-sessions");
    seedSandboxSession(sandboxFs, sbxSessions, sandboxCwd, sessionId, {
      "chat_history.jsonl": "this is not json\n",
      "events.jsonl": `{"type":"end"}\n`,
    });

    const storage = makeGrokSessionStorage({
      hostSessionsDir: hostRoot,
      sandboxSessionsDir: sbxSessions,
    });

    await expect(
      storage.captureToHost({
        hostCwd,
        sandboxCwd,
        sessionId,
        handle: localHandleWithStdin(sandboxFs),
      }),
    ).rejects.toThrow(/grok-cap|integrity|JSONL|parse/i);

    expect(
      readFileSync(
        join(hostRoot, encodeURIComponent(hostCwd), sessionId, "chat_history.jsonl"),
        "utf8",
      ),
    ).toBe(oldHistory);
  });

  it("failed first capture does not leave a half-written host session dir", async () => {
    const hostRoot = tmp("grok-959-host-");
    const sandboxFs = tmp("grok-959-sbx-");
    const hostCwd = "/host/work-959-nofirst";
    const sessionId = "019f-959-nofirst";

    const handle: BindMountSandboxHandle = {
      worktreePath: sandboxFs,
      exec: async () => ({
        stdout: Buffer.from("not-a-tar").toString("base64"),
        stderr: "",
        exitCode: 0,
      }),
      copyFileIn: async () => {},
      copyFileOut: async () => {},
      close: async () => {},
    };

    const storage = makeGrokSessionStorage({
      hostSessionsDir: hostRoot,
      sandboxSessionsDir: join(sandboxFs, "sessions"),
    });

    await expect(
      storage.captureToHost({
        hostCwd,
        sandboxCwd: "/sbx",
        sessionId,
        handle,
      }),
    ).rejects.toThrow();

    const hostDir = join(hostRoot, encodeURIComponent(hostCwd), sessionId);
    expect(existsSync(hostDir)).toBe(false);
    expect(await storage.existsOnHost(hostCwd, sessionId)).toBe(false);
  });

  it("concurrent same-slug captures leave one complete version (no mix)", async () => {
    const hostRoot = tmp("grok-959-host-");
    const hostCwd = "/host/work-959-race";
    const sessionId = "019f-959-race";

    const makeSide = (mark: string) => {
      const sandboxFs = tmp(`grok-959-sbx-${mark}-`);
      const sandboxCwd = join(sandboxFs, "workspace");
      const sbxSessions = join(sandboxFs, "home-.grok-sessions");
      seedSandboxSession(sandboxFs, sbxSessions, sandboxCwd, sessionId, {
        "chat_history.jsonl": `{"cwd":"${sandboxCwd}","mark":"${mark}"}\n`,
        "events.jsonl": `{"type":"end","mark":"${mark}"}\n`,
        "state.json": JSON.stringify({ mark }),
      });
      const storage = makeGrokSessionStorage({
        hostSessionsDir: hostRoot,
        sandboxSessionsDir: sbxSessions,
      });
      return storage.captureToHost({
        hostCwd,
        sandboxCwd,
        sessionId,
        handle: localHandleWithStdin(sandboxFs),
      });
    };

    // Both may succeed (last writer wins) or one may lose the swap race and
    // reject — either is fine so long as the live dir is wholly A or wholly B.
    const results = await Promise.allSettled([
      makeSide("VERSION_A"),
      makeSide("VERSION_B"),
    ]);
    const fulfilled = results.filter((r) => r.status === "fulfilled");
    expect(fulfilled.length).toBeGreaterThanOrEqual(1);

    const hostDir = join(hostRoot, encodeURIComponent(hostCwd), sessionId);
    expect(existsSync(join(hostDir, "chat_history.jsonl"))).toBe(true);
    expect(existsSync(join(hostDir, "events.jsonl"))).toBe(true);
    expect(existsSync(join(hostDir, "state.json"))).toBe(true);

    const history = readFileSync(join(hostDir, "chat_history.jsonl"), "utf8");
    const events = readFileSync(join(hostDir, "events.jsonl"), "utf8");
    const state = readFileSync(join(hostDir, "state.json"), "utf8");

    const isA =
      history.includes("VERSION_A") &&
      events.includes("VERSION_A") &&
      state.includes("VERSION_A");
    const isB =
      history.includes("VERSION_B") &&
      events.includes("VERSION_B") &&
      state.includes("VERSION_B");
    expect(isA || isB).toBe(true);
    // No cross-version mix across the three session files.
    expect(history.includes("VERSION_A") && history.includes("VERSION_B")).toBe(
      false,
    );
    expect(events.includes("VERSION_A") && events.includes("VERSION_B")).toBe(
      false,
    );
    expect(state.includes("VERSION_A") && state.includes("VERSION_B")).toBe(
      false,
    );
    if (isA) {
      expect(events).not.toContain("VERSION_B");
      expect(state).not.toContain("VERSION_B");
    } else {
      expect(events).not.toContain("VERSION_A");
      expect(state).not.toContain("VERSION_A");
    }
  });
});
