/**
 * #899 — real Sandcastle `sc.run` harness for typed traffic-signal recovery.
 *
 * Exercises the public Output.object + maxRetries path with a scripted
 * AgentProvider (no LLM): provider/session recovery, exhaust, and
 * non-resumable providers. Production schemas / RECEIPT_MAX_RETRIES stay
 * owned by receiptRecovery; this only drives Sandcastle's native loop.
 */

import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import * as sc from "@ai-hero/sandcastle";
import type { AgentProvider, RunResult } from "@ai-hero/sandcastle";
import { noSandbox } from "@ai-hero/sandcastle/sandboxes/no-sandbox";
import type { z } from "zod";

/**
 * Versioned thin promptFile template — never inline `prompt` (orchestrator/CLAUDE.md).
 * Sandcastle requires the Output.object tag to appear in the resolved prompt; the
 * harness materialises a per-run copy that names the concrete tag under test.
 */
const SCRIPTED_STRUCTURED_OUTPUT_PROMPT_TEMPLATE = join(
  dirname(fileURLToPath(import.meta.url)),
  "fixtures",
  "scripted-structured-output.md",
);

export type ScriptedEmission = {
  /** JSON payload placed inside `<tag>…</tag>` (or raw text if already tagged). */
  readonly body: string;
};

export type ScriptedAgent = AgentProvider & {
  readonly callCount: number;
  readonly sessionId: string;
  readonly resumedSessions: ReadonlyArray<string | undefined>;
  setSessionRoot(root: string): void;
};

/**
 * Build a resumable (or deliberately non-resumable) agent that emits one
 * scripted stdout payload per `sc.run` invocation / same-session resume.
 */
export function createScriptedAgent(opts: {
  readonly tag: string;
  readonly emissions: ReadonlyArray<ScriptedEmission>;
  readonly sessionId?: string;
  /** When false, omit sessionStorage so maxRetries > 0 fails closed. */
  readonly resumable?: boolean;
  readonly name?: string;
}): ScriptedAgent {
  const sessionId = opts.sessionId ?? `sess-scripted-${opts.tag}`;
  const resumable = opts.resumable !== false;
  const sessions = new Map<string, string>();
  let sessionRoot = "";
  let callCount = 0;
  const resumedSessions: Array<string | undefined> = [];

  const sessionStorage = resumable
    ? {
        async captureToHost() {},
        async resumeIntoSandbox() {},
        async readHostSession() {
          return undefined;
        },
        async existsOnHost(_cwd: string, id: string) {
          return sessions.has(id);
        },
        hostSessionFilePath(_cwd: string, id: string) {
          return join(sessionRoot, id);
        },
        async findByIdOnHost(id: string) {
          return { path: sessions.get(id), searchedRoot: sessionRoot };
        },
      }
    : undefined;

  const agent: ScriptedAgent = {
    name: opts.name ?? (resumable ? "scripted-resumable" : "scripted-non-resumable"),
    env: {},
    captureSessions: resumable,
    ...(sessionStorage !== undefined ? { sessionStorage } : {}),
    get callCount() {
      return callCount;
    },
    get sessionId() {
      return sessionId;
    },
    get resumedSessions() {
      return resumedSessions;
    },
    setSessionRoot(root: string) {
      sessionRoot = root;
      mkdirSync(root, { recursive: true });
    },
    buildPrintCommand({ resumeSession }) {
      if (sessionRoot === "") {
        throw new Error("scripted agent session root not initialised");
      }
      resumedSessions.push(resumeSession);
      const index = Math.min(callCount, opts.emissions.length - 1);
      callCount += 1;
      const emission = opts.emissions[index]!;
      const path = join(sessionRoot, sessionId);
      writeFileSync(path, `session ${sessionId} attempt ${callCount}\n`);
      sessions.set(sessionId, path);
      const tagged = emission.body.includes(`<${opts.tag}>`)
        ? emission.body
        : `<${opts.tag}>${emission.body}</${opts.tag}>`;
      const lines = [
        JSON.stringify({ type: "text", text: tagged }),
        JSON.stringify({ type: "session_id", sessionId }),
      ];
      const script = lines
        .map((line) => `printf '%s\\n' ${JSON.stringify(line)}`)
        .join("; ");
      return { command: `sh -c ${JSON.stringify(script)}` };
    },
    parseStreamLine(line) {
      const trimmed = line.trim();
      if (!trimmed.startsWith("{")) return [];
      try {
        const obj = JSON.parse(trimmed) as Record<string, unknown>;
        if (obj.type === "text" && typeof obj.text === "string") {
          return [
            { type: "text" as const, text: obj.text },
            { type: "result" as const, result: obj.text },
          ];
        }
        if (obj.type === "session_id" && typeof obj.sessionId === "string") {
          return [{ type: "session_id" as const, sessionId: obj.sessionId }];
        }
      } catch {
        // ignore non-JSON stream noise
      }
      return [];
    },
  };

  return agent;
}

export type ScriptedStructuredRun = {
  readonly repo: string;
  readonly agent: ScriptedAgent;
  readonly result: RunResult & { readonly output: unknown };
};

/**
 * Run real `sc.run` with noSandbox + a scripted agent against a production
 * Output.object policy. Creates a throwaway git repo for the host cwd.
 */
export async function runScriptedStructuredOutput(opts: {
  readonly tag: string;
  readonly schema: z.ZodType;
  readonly emissions: ReadonlyArray<ScriptedEmission>;
  readonly maxRetries: number;
  readonly resumable?: boolean;
  readonly sessionId?: string;
  readonly name?: string;
  readonly cleanups: string[];
  /** Filled before `sc.run` so callers can inspect call counts after rejection. */
  readonly agentOut?: { agent?: ScriptedAgent };
}): Promise<ScriptedStructuredRun> {
  const repo = mkdtempSync(join(tmpdir(), "sc-native-so-"));
  opts.cleanups.push(repo);
  execFileSync("git", ["init", "-q"], { cwd: repo });
  execFileSync("git", ["config", "user.email", "t@t.t"], { cwd: repo });
  execFileSync("git", ["config", "user.name", "t"], { cwd: repo });
  execFileSync("git", ["commit", "--allow-empty", "-q", "-m", "root"], {
    cwd: repo,
  });

  const agent = createScriptedAgent({
    tag: opts.tag,
    emissions: opts.emissions,
    sessionId: opts.sessionId,
    resumable: opts.resumable,
    name: opts.name,
  });
  agent.setSessionRoot(join(repo, ".fake-sessions"));
  if (opts.agentOut !== undefined) opts.agentOut.agent = agent;

  // Materialise versioned thin template with the concrete Output.object tag so
  // Sandcastle's tag-in-prompt check passes without an inline `prompt` string.
  const template = readFileSync(SCRIPTED_STRUCTURED_OUTPUT_PROMPT_TEMPLATE, "utf8");
  const promptFile = join(repo, "scripted-structured-output.md");
  writeFileSync(promptFile, template.replaceAll("{{TAG}}", opts.tag), "utf8");

  const result = (await sc.run({
    agent,
    sandbox: noSandbox(),
    cwd: repo,
    // Absolute path: Sandcastle resolves promptFile against process.cwd().
    promptFile,
    maxIterations: 1,
    // #928: omit falls back to sandcastle's default password; [] disables.
    completionSignal: [],
    output: sc.Output.object({
      tag: opts.tag,
      schema: opts.schema,
      maxRetries: opts.maxRetries,
    }),
    logging: { type: "file", path: join(repo, "sc-native.log") },
    idleTimeoutSeconds: 30,
    completionTimeoutSeconds: 15,
  })) as RunResult & { readonly output: unknown };

  return { repo, agent, result };
}
