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

});
