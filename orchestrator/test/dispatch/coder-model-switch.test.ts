import { describe, it, expect, afterEach, vi } from "vitest";
import { coderModel } from "../../src/runner.js";

// #936: per-slot ORCHESTRATOR_CODER_MODEL override deleted. Coder model comes
// from ORCHESTRATOR_ROUTE presets (+ issue Coder-Rec at admission).

describe("coderModel() — route-preset coder backend (#936)", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("defaults to the normal-route terra coder when the env is unset", () => {
    expect(coderModel()).toBe("gpt-5.6-terra");
  });

  it("negative: leftover CODER_MODEL env does not restaff (override deleted)", () => {
    vi.stubEnv("ORCHESTRATOR_CODER_MODEL", "gpt-5.6-sol");
    expect(coderModel()).toBe("gpt-5.6-terra");
  });

  it("route preset switches the coder (claude-tight → grok)", () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "claude-tight");
    expect(coderModel()).toBe("grok-4.5");
  });

  it("trims and falls back to the default on a blank/whitespace env value", () => {
    vi.stubEnv("ORCHESTRATOR_CODER_MODEL", "   ");
    expect(coderModel()).toBe("gpt-5.6-terra");
  });
});
