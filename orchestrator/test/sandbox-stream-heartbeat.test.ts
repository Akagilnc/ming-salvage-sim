/**
 * #899 hotfix — monitored-bridge stream heartbeat.
 *
 * The #684 idle monitor watches ONLY the bridge child's stdout (worker-logs
 * step log). Sandcastle in log-to-file mode writes the whole agent stream to
 * its own file and keeps stdout byte-silent between startup and final output,
 * so any healthy sandbox step longer than the idle threshold was killed as a
 * hang (#899 S2 died 3× at exactly the 10-minute tier; #808 widened Claude's
 * tier for the same disease instead of fixing the channel).
 *
 * withMonitorStreamHeartbeat injects sandcastle file-logging with an
 * onAgentStreamEvent callback that forwards real agent activity to stdout as
 * a throttled heartbeat: live agent ⇒ monitored log grows; truly silent agent
 * ⇒ no heartbeat ⇒ idle threshold still fires.
 */
import { describe, expect, it } from "vitest";
import { join } from "node:path";
import {
  STREAM_HEARTBEAT_THROTTLE_MS,
  withMonitorStreamHeartbeat,
} from "../src/sandboxStreamHeartbeat.js";

type FileLogging = {
  readonly type: "file";
  readonly path: string;
  readonly onAgentStreamEvent?: (event: unknown) => void;
};

const streamEvent = { type: "text", text: "chunk" };

function harness(nowStart = 1_000) {
  let nowMs = nowStart;
  const lines: string[] = [];
  const dirs: string[] = [];
  const deps = {
    writeLine: (line: string) => lines.push(line),
    now: () => nowMs,
    ensureDir: (dir: string) => dirs.push(dir),
  };
  return {
    deps,
    lines,
    dirs,
    advance: (ms: number) => {
      nowMs += ms;
    },
  };
}

describe("withMonitorStreamHeartbeat", () => {
  it("injects file logging under <cwd>/.sandcastle/logs with a sanitized step name", () => {
    const h = harness();
    const out = withMonitorStreamHeartbeat(
      { cwd: "/work/tree", name: "S2-coder" },
      h.deps,
    );
    const logging = out.logging as FileLogging;
    expect(logging.type).toBe("file");
    expect(logging.path).toBe(
      join("/work/tree", ".sandcastle", "logs", "s2-coder.log"),
    );
    expect(h.dirs).toEqual([join("/work/tree", ".sandcastle", "logs")]);
    expect(typeof logging.onAgentStreamEvent).toBe("function");
  });

  it("sanitizes hostile name characters in the log filename", () => {
    const h = harness();
    const out = withMonitorStreamHeartbeat(
      { cwd: "/w", name: "A/B:C weird*Name" },
      h.deps,
    );
    expect((out.logging as FileLogging).path).toBe(
      join("/w", ".sandcastle", "logs", "a-b-c-weird-name.log"),
    );
  });

  it("leaves options untouched when a logging config is already present", () => {
    const h = harness();
    const explicit = { type: "file", path: "/elsewhere.log" } as const;
    const options = { cwd: "/w", name: "S2-coder", logging: explicit };
    const out = withMonitorStreamHeartbeat(options, h.deps);
    expect(out).toBe(options);
    expect(out.logging).toBe(explicit);
    expect(h.dirs).toEqual([]);
  });

  it("beats on the first stream event, then throttles until the window elapses", () => {
    const h = harness();
    const out = withMonitorStreamHeartbeat(
      { cwd: "/w", name: "S2-coder" },
      h.deps,
    );
    const onEvent = (out.logging as FileLogging).onAgentStreamEvent!;

    onEvent(streamEvent);
    expect(h.lines).toHaveLength(1);
    expect(h.lines[0]).toContain("S2-coder");

    // Inside the throttle window: stays silent no matter how chatty the agent is.
    onEvent(streamEvent);
    h.advance(STREAM_HEARTBEAT_THROTTLE_MS - 1);
    onEvent(streamEvent);
    expect(h.lines).toHaveLength(1);

    // Window elapsed: next event beats again.
    h.advance(1);
    onEvent(streamEvent);
    expect(h.lines).toHaveLength(2);
  });

  it("writes no heartbeat when the agent emits no events (idle stays detectable)", () => {
    const h = harness();
    withMonitorStreamHeartbeat({ cwd: "/w", name: "S2-coder" }, h.deps);
    h.advance(STREAM_HEARTBEAT_THROTTLE_MS * 100);
    expect(h.lines).toEqual([]);
  });

  it("preserves every other sandbox option verbatim", () => {
    const h = harness();
    const options = {
      cwd: "/w",
      name: "S5-coder",
      maxIterations: 5,
      completionSignal: "CODER_STEP_COMPLETE",
    };
    const out = withMonitorStreamHeartbeat(options, h.deps);
    expect(out.maxIterations).toBe(5);
    expect(out.completionSignal).toBe("CODER_STEP_COMPLETE");
    expect(out.cwd).toBe("/w");
  });

  it("falls back to a generic name when the sandbox run is unnamed", () => {
    const h = harness();
    const out = withMonitorStreamHeartbeat({ cwd: "/w" }, h.deps);
    expect((out.logging as FileLogging).path).toBe(
      join("/w", ".sandcastle", "logs", "agent.log"),
    );
  });

  it("falls back to sandcastle default logging when the log dir cannot be created (online r1)", () => {
    const warns: string[] = [];
    const orig = console.warn;
    console.warn = (m?: unknown) => { warns.push(String(m)); };
    try {
      const options = { cwd: "/w", name: "S2-coder" };
      const out = withMonitorStreamHeartbeat(options, {
        ensureDir: () => { throw new Error("EACCES"); },
      });
      expect(out).toBe(options);
      expect((out as { logging?: unknown }).logging).toBeUndefined();
      expect(warns.some((w) => w.includes("heartbeat disabled"))).toBe(true);
    } finally {
      console.warn = orig;
    }
  });
});
