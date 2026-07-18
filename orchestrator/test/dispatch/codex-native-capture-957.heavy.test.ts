/**
 * #957 — restore Sandcastle-native Codex session capture + resume.
 *
 * #883 disabled captureSessions as a symptom fix after capture threw
 * "session not found". Root cause was cargo-culting host-side CMR
 * `--ephemeral` into the container story; Sandcastle's sc.codex never
 * adds that flag. This ticket re-opens capture at the registry factory
 * and pins the native provider surface: no --ephemeral, sessionStorage
 * present, resume → `codex exec resume`, SO maxRetries from #934.
 *
 * AC also requires a real Sandcastle-facing capture → resume proof for
 * the same dialogue context (not factory/command pins alone). This file
 * exercises sc.codex sessionStorage captureToHost + resumeIntoSandbox on
 * the provider object (deepest offline entry; no host-invented transfer).
 *
 * Host-side CMR legs keep --ephemeral (out of this file). Grok is
 * untouched (already resumable via #955; do not flip non-resumable).
 */
import { execFile } from "node:child_process";
import {
  copyFileSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import type { BindMountSandboxHandle } from "@ai-hero/sandcastle";
import * as sc from "@ai-hero/sandcastle";
import { afterEach, describe, expect, it } from "vitest";
import {
  agentForSlug,
} from "../../src/modelRegistry.js";

const tempDirs: string[] = [];
afterEach(() => {
  while (tempDirs.length > 0) {
    rmSync(tempDirs.pop()!, { recursive: true, force: true });
  }
});

function tmp(prefix: string): string {
  const d = mkdtempSync(join(tmpdir(), prefix));
  tempDirs.push(d);
  return d;
}

/**
 * Local-shell sandbox handle. Codex sessionStorage uses copyFileOut/In for
 * JSONL transfer (unlike grok's tar-over-exec), so those must be real.
 */
function localHandle(worktreePath: string): BindMountSandboxHandle {
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
    copyFileIn: async (hostPath: string, sandboxPath: string) => {
      mkdirSync(dirname(sandboxPath), { recursive: true });
      copyFileSync(hostPath, sandboxPath);
    },
    copyFileOut: async (sandboxPath: string, hostPath: string) => {
      mkdirSync(dirname(hostPath), { recursive: true });
      copyFileSync(sandboxPath, hostPath);
    },
    close: async () => {},
  };
}

const CODEX_SLUGS = [
  "gpt-5.6-sol",
  "gpt-5.6-sol-high",
  "gpt-5.6-sol-low",
  "gpt-5.6-luna",
  "gpt-5.6-terra",
] as const;

const STORAGE_METHODS = [
  "captureToHost",
  "resumeIntoSandbox",
  "readHostSession",
  "existsOnHost",
  "hostSessionFilePath",
  "findByIdOnHost",
] as const;

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
