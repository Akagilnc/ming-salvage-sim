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
