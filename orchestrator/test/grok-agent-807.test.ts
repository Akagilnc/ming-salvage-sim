/**
 * #807 — grok-build pool provider: custom AgentProvider + registry wiring.
 */

import { describe, expect, it } from "vitest";

import {
  grokAgent,
  parseGrokStreamLine,
  shellEscape,
} from "../src/grokAgent.js";
import {
  POOL_DISPATCH_BINDINGS,
  agentForSlug,
  resolveModelSlug,
  resolveModelSlugForPool,
} from "../src/modelRegistry.js";

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
    // Default registry alone stays on the cursor channel.
    expect(resolveModelSlug("grok-4.5").provider).toBe("cursor");
  });

  it("registers an explicit grok-4.5-build slug on the grok provider", () => {
    expect(resolveModelSlug("grok-4.5-build")).toEqual({
      provider: "grok",
      model: "grok-4.5",
    });
    const agent = agentForSlug("grok-4.5-build");
    expect(agent.name).toBe("grok");
  });

  it("agentForSlug(pool=grok-build) yields the grok CLI provider", () => {
    const agent = agentForSlug("grok-4.5", undefined, "grok-build");
    expect(agent.name).toBe("grok");
  });
});
