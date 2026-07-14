/**
 * #807 — grok-build pool provider: custom AgentProvider + registry wiring.
 * Route smoke is bare-ping only (#884); old bash/nonce-file evidence helpers are gone.
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { describe, expect, it } from "vitest";

import {
  grokAgent,
  parseGrokStreamLine,
  shellEscape,
} from "../../src/grokAgent.js";
import {
  POOL_DISPATCH_BINDINGS,
  agentForSlug,
  resolveModelSlug,
  resolveModelSlugForPool,
} from "../../src/modelRegistry.js";
import { barePingArgv, barePingNonceSatisfied } from "../../src/realBackend.js";
import { routeSmokeEntries, resolveRouteModels } from "../../src/modelRoutes.js";

describe("#807 grokAgent AgentProvider", () => {
  it("builds a headless grok command with stdin prompt (not sc.pi)", () => {
    const agent = grokAgent("grok-4.5");
    expect(agent.name).toBe("grok");
    const cmd = agent.buildPrintCommand({
      prompt: "echo OK",
      dangerouslySkipPermissions: true,
    });
    expect(cmd.command).toContain("grok ");
    expect(cmd.command).toContain("--prompt-file /dev/stdin");
    expect(cmd.command).toContain("--output-format streaming-json");
    expect(cmd.command).toContain("--always-approve");
    expect(cmd.command).toContain("-m grok-4.5");
    expect(cmd.command).not.toMatch(/\bpi\b/);
    expect(cmd.stdin).toBe("echo OK");
  });

  it("is explicitly non-resumable while grok sessions are not persisted", () => {
    const agent = grokAgent("grok-4.5", { captureSessions: true });
    expect(agent.captureSessions).toBe(false);
    const cmd = agent.buildPrintCommand({
      prompt: "continue",
      resumeSession: "sess-807",
      dangerouslySkipPermissions: true,
    });
    expect(cmd.command).not.toContain("--resume");
  });

  it("parses streaming-json text + end session events", () => {
    expect(parseGrokStreamLine('{"type":"text","data":"OK"}')).toEqual([
      { type: "text", text: "OK" },
      { type: "result", result: "OK" },
    ]);
    expect(
      parseGrokStreamLine(
        '{"type":"end","stopReason":"EndTurn","sessionId":"sess-1"}',
      ),
    ).toEqual([{ type: "session_id", sessionId: "sess-1" }]);
  });

  it("maps run_terminal_cmd tool events to bash when present", () => {
    expect(
      parseGrokStreamLine(
        '{"type":"tool_call","name":"run_terminal_cmd","args":"echo OK"}',
      ),
    ).toEqual([{ type: "tool_call", name: "bash", args: "echo OK" }]);
  });

  it("shellEscape quotes unsafe tokens", () => {
    expect(shellEscape("grok-4.5")).toBe("grok-4.5");
    expect(shellEscape("a b")).toBe("'a b'");
  });
});

describe("#807 modelRegistry grok-build wiring", () => {
  it("binds the grok-build pool to the grok provider (not pi)", () => {
    expect(POOL_DISPATCH_BINDINGS["grok-build"]).toBe("grok");
    expect(resolveModelSlugForPool("grok-4.5", "grok-build")).toEqual({
      provider: "grok",
      model: "grok-4.5",
    });
    // #905: default registry is SuperGrok CLI; no cursor transit.
    expect(resolveModelSlug("grok-4.5").provider).toBe("grok");
  });

  it("agentForSlug(pool=grok-build) yields the grok CLI provider", () => {
    const agent = agentForSlug("grok-4.5", undefined, "grok-build");
    expect(agent.name).toBe("grok");
  });
});

describe("#807 grok bare-ping smoke wiring", () => {
  it("builds a one-shot grok CLI bare-ping argv (no docker/tool loop)", () => {
    const built = barePingArgv("grok", "grok-4.5", "Reply with exactly: nonce-807");
    expect(built.file).toBe("grok");
    // Same headless shape as grokAgent: prompt on stdin, not -p argv.
    expect(built.args).toContain("--prompt-file");
    expect(built.args).toContain("/dev/stdin");
    expect(built.input).toBe("Reply with exactly: nonce-807");
    expect(built.args).not.toContain("-p");
    expect(built.args).toContain("-m");
    expect(built.args).toContain("grok-4.5");
  });

  it("accepts full-line nonce stdout and rejects bare chatter", () => {
    expect(barePingNonceSatisfied("nonce-807\n", "nonce-807")).toBe(true);
    expect(barePingNonceSatisfied("nonce-807", "nonce-807")).toBe(true);
    expect(barePingNonceSatisfied("OK", "nonce-807")).toBe(false);
    expect(barePingNonceSatisfied("prefix-nonce-807-suffix", "nonce-807")).toBe(
      false,
    );
  });

  it("keeps the model slug independent from its billing pool", () => {
    const route = resolveRouteModels("normal", { coder: "grok-4.5" });
    const keys = routeSmokeEntries(route).map((e) => e.key);
    expect(keys.some((k) => k.includes("grok-4.5"))).toBe(true);
    expect(() => resolveModelSlug("grok-4.5-build")).toThrow(/unknown model slug/i);
  });

  it("pins the official Grok CLI package to an exact version", () => {
    const containerfile = readFileSync(
      join(dirname(fileURLToPath(import.meta.url)), "..", "..", "image", "Containerfile"),
      "utf8",
    );
    expect(containerfile).toMatch(/npm install -g @xai-official\/grok@0\.2\.93/);
    expect(containerfile).toMatch(/grok --version \| grep -F "0\.2\.93"/);
  });
});
