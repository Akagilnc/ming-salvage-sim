/**
 * #981 — grok-cap must ignore macOS AppleDouble `._*` and `.DS_Store`.
 * Sidecars break integrity when `._chat_history.jsonl` is parsed as JSONL.
 *
 * captureToHost: sidecars are planted into the staging tree immediately after
 * a successful host tar-extract (same chokepoint mock as #959). macOS bsdtar
 * cannot be relied on to round-trip `._*` as ordinary members (it treats them
 * as AppleDouble metadata and may exit non-zero), so the fixture injects them
 * where integrity actually walks: the staged session dir.
 *
 * resumeIntoSandbox: host session tree is seeded with real cargo plus `._*` /
 * `.DS_Store` already on disk (accumulated Finder/AFP garbage after capture).
 * Asserts push succeeds, sandbox tree has no OS metadata, cargo rewrites, and
 * the live host store is left untouched.
 */
import { execFile } from "node:child_process";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { BindMountSandboxHandle } from "@ai-hero/sandcastle";
import { afterEach, describe, expect, it, vi } from "vitest";

/** When set, plant OS metadata sidecars into staging after tar-extract. */
let plantSidecarsAfterExtract = false;

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
      if (
        plantSidecarsAfterExtract &&
        opts.stage === "grok-session:tar-extract"
      ) {
        const cIdx = args.indexOf("-C");
        const staging = cIdx >= 0 ? args[cIdx + 1] : undefined;
        if (staging) {
          // Binary AppleDouble resource-fork payloads (not JSON/JSONL).
          writeFileSync(
            join(staging, "._chat_history.jsonl"),
            Buffer.from([0x00, 0x05, 0x16, 0x07, 0xff, 0xfe]),
          );
          writeFileSync(
            join(staging, "._plan.json"),
            Buffer.from([0x00, 0x05, 0x16, 0x07, 0xaa, 0xbb]),
          );
          writeFileSync(
            join(staging, ".DS_Store"),
            Buffer.from("Bud1\0\0\0\0fake-ds-store"),
          );
        }
      }
      return result;
    },
  };
});

const { makeGrokSessionStorage } = await import("../../src/grokSessionStorage.js");

const tempDirs: string[] = [];
function tmp(prefix: string): string {
  const d = mkdtempSync(join(tmpdir(), prefix));
  tempDirs.push(d);
  return d;
}
afterEach(() => {
  plantSidecarsAfterExtract = false;
  while (tempDirs.length > 0) {
    rmSync(tempDirs.pop()!, { recursive: true, force: true });
  }
});

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

describe("#981 grok-cap ignores AppleDouble / .DS_Store", () => {
  it("capture succeeds when staged session has ._* and .DS_Store; landed tree excludes them", async () => {
    const hostRoot = tmp("grok-981-host-");
    const sandboxFs = tmp("grok-981-sbx-");
    const sandboxCwd = join(sandboxFs, "workspace");
    const hostCwd = tmp("grok-981-hostcwd-");
    const sessionId = "019f-981-sidecar";
    const sbxSessions = join(sandboxFs, "home-.grok-sessions");

    seedSandboxSession(sandboxFs, sbxSessions, sandboxCwd, sessionId, {
      "chat_history.jsonl": `{"cwd":"${sandboxCwd}","mark":"real-session"}\n`,
      "events.jsonl": `{"type":"end","mark":"real-session"}\n`,
      "plan.json": JSON.stringify({ step: 1 }),
    });

    plantSidecarsAfterExtract = true;
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
    expect(existsSync(join(captured, "chat_history.jsonl"))).toBe(true);
    expect(existsSync(join(captured, "events.jsonl"))).toBe(true);
    expect(existsSync(join(captured, "plan.json"))).toBe(true);

    // Manifest / landed tree must not carry OS metadata sidecars.
    const landedNames = readdirSync(captured);
    expect(landedNames).not.toContain("._chat_history.jsonl");
    expect(landedNames).not.toContain("._plan.json");
    expect(landedNames).not.toContain(".DS_Store");
    expect(landedNames.every((n) => !n.startsWith("._"))).toBe(true);

    const history = readFileSync(join(captured, "chat_history.jsonl"), "utf8");
    expect(history).toContain(hostCwd);
    expect(history).toContain('"mark":"real-session"');
    expect(history).not.toContain(sandboxCwd);
  });

  it("real chat_history.jsonl corruption still integrity-fails (sidecars do not relax checks)", async () => {
    const hostRoot = tmp("grok-981-host-");
    const sandboxFs = tmp("grok-981-sbx-");
    const sandboxCwd = join(sandboxFs, "workspace");
    const hostCwd = tmp("grok-981-hostcwd-neg-");
    const sessionId = "019f-981-corrupt";
    const sbxSessions = join(sandboxFs, "home-.grok-sessions");

    seedSandboxSession(sandboxFs, sbxSessions, sandboxCwd, sessionId, {
      "chat_history.jsonl": "this is not json\n",
      "events.jsonl": `{"type":"end"}\n`,
    });

    plantSidecarsAfterExtract = true;
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

    // No host session dir left behind from a failed capture.
    expect(
      existsSync(join(hostRoot, encodeURIComponent(hostCwd), sessionId)),
    ).toBe(false);
  });

  it("resumeIntoSandbox succeeds when host session has ._* and .DS_Store; sandbox tree excludes them", async () => {
    // Host sessions can accumulate Finder/AFP sidecars after capture lands.
    // resumeIntoSandbox must strip them from the scratch copy before push so
    // sandbox never receives AppleDouble / .DS_Store (real cargo still rewrites).
    const hostRoot = tmp("grok-981-res-host-");
    const sandboxFs = tmp("grok-981-res-sbx-");
    const sandboxCwd = join(sandboxFs, "workspace");
    const hostCwd = tmp("grok-981-res-hostcwd-");
    const sessionId = "019f-981-resume-sidecar";
    const sbxSessions = join(sandboxFs, "home-.grok-sessions");

    const hostDir = join(hostRoot, encodeURIComponent(hostCwd), sessionId);
    mkdirSync(hostDir, { recursive: true });
    writeFileSync(
      join(hostDir, "chat_history.jsonl"),
      `{"cwd":"${hostCwd}","mark":"resume-cargo"}\n`,
    );
    writeFileSync(
      join(hostDir, "events.jsonl"),
      `{"type":"end","mark":"resume-cargo"}\n`,
    );
    writeFileSync(join(hostDir, "plan.json"), JSON.stringify({ step: 2 }));
    // Binary AppleDouble / Finder metadata already on host store.
    writeFileSync(
      join(hostDir, "._chat_history.jsonl"),
      Buffer.from([0x00, 0x05, 0x16, 0x07, 0xff, 0xfe]),
    );
    writeFileSync(
      join(hostDir, "._plan.json"),
      Buffer.from([0x00, 0x05, 0x16, 0x07, 0xaa, 0xbb]),
    );
    writeFileSync(
      join(hostDir, ".DS_Store"),
      Buffer.from("Bud1\0\0\0\0fake-ds-store"),
    );

    const storage = makeGrokSessionStorage({
      hostSessionsDir: hostRoot,
      sandboxSessionsDir: sbxSessions,
    });
    await storage.resumeIntoSandbox({
      hostCwd,
      sandboxCwd,
      sessionId,
      handle: localHandleWithStdin(sandboxFs),
    });

    const pushed = join(sbxSessions, encodeURIComponent(sandboxCwd), sessionId);
    expect(existsSync(join(pushed, "chat_history.jsonl"))).toBe(true);
    expect(existsSync(join(pushed, "events.jsonl"))).toBe(true);
    expect(existsSync(join(pushed, "plan.json"))).toBe(true);

    const sandboxNames = readdirSync(pushed);
    expect(sandboxNames).not.toContain("._chat_history.jsonl");
    expect(sandboxNames).not.toContain("._plan.json");
    expect(sandboxNames).not.toContain(".DS_Store");
    expect(sandboxNames.every((n) => !n.startsWith("._"))).toBe(true);

    const history = readFileSync(join(pushed, "chat_history.jsonl"), "utf8");
    expect(history).toContain(sandboxCwd);
    expect(history).toContain('"mark":"resume-cargo"');
    expect(history).not.toContain(hostCwd);

    // Host store remains untouched (scratch copy was stripped, not the live dir).
    const hostNames = readdirSync(hostDir);
    expect(hostNames).toContain("._chat_history.jsonl");
    expect(hostNames).toContain(".DS_Store");
  });
});
