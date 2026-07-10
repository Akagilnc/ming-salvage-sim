import { describe, it, expect, afterEach, vi } from "vitest";
import { coderModel } from "../src/runner.js";

// The S2 coder worker's model is switchable via ORCHESTRATOR_CODER_MODEL so the
// coder backend can be swapped (claude sonnet ↔ codex gpt-5.5 ↔ …) by env alone —
// no code change, no image rebuild. `coderModel()` is the resolver; S2 worker specs
// reads it. The auth mount is best-effort for both legs (realBackend mountAuth),
// so switching the model needs no auth-wiring change.

describe("coderModel() — switchable coder backend (ORCHESTRATOR_CODER_MODEL)", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("defaults to the normal-route terra coder when the env is unset", () => {
    expect(coderModel()).toBe("gpt-5.6-terra");
  });

  it("returns the env slug when set (e.g. switch to a Codex coder)", () => {
    vi.stubEnv("ORCHESTRATOR_CODER_MODEL", "gpt-5.5");
    expect(coderModel()).toBe("gpt-5.5");
  });

  it("trims and falls back to the default on a blank/whitespace env value", () => {
    vi.stubEnv("ORCHESTRATOR_CODER_MODEL", "   ");
    expect(coderModel()).toBe("gpt-5.6-terra");
  });
});
