import { describe, expect, it } from "vitest";
import { resolveReasoningSupported } from "./reasoningSupport";

const API_SETTINGS = {
  currentChannel: "api" as const,
  baseUrl: "https://api.example.com/v1",
  model: "gpt-5",
  advancedBaseUrl: "",
  advancedModel: "",
  cliRunner: "agy",
};

describe("resolveReasoningSupported", () => {
  it("uses backend reasoning_supported while the backend snapshot is current", () => {
    expect(resolveReasoningSupported({
      ...API_SETTINGS,
      backendSupported: false,
      backendCurrent: true,
    })).toBe(false);
  });

  it("falls back to API heuristics when the backend snapshot is stale", () => {
    expect(resolveReasoningSupported({
      ...API_SETTINGS,
      backendSupported: false,
      backendCurrent: false,
    })).toBe(true);
  });

  it("trims edited API fields before applying fallback heuristics", () => {
    expect(resolveReasoningSupported({
      ...API_SETTINGS,
      baseUrl: " https://api.example.com/v1 ",
      model: " gpt-5 ",
      backendSupported: false,
      backendCurrent: false,
    })).toBe(true);
  });

  it("falls back to CLI runner support when the backend snapshot is stale", () => {
    expect(resolveReasoningSupported({
      currentChannel: "cli",
      baseUrl: "",
      model: "",
      advancedBaseUrl: "",
      advancedModel: "",
      cliRunner: "agy",
      backendSupported: true,
      backendCurrent: false,
      cliReasoningRunners: ["codex", "claude", "grok"],
    })).toBe(false);
  });

  it("falls back to true for grok when the capability list includes grok (#1271)", () => {
    expect(resolveReasoningSupported({
      currentChannel: "cli",
      baseUrl: "",
      model: "",
      advancedBaseUrl: "",
      advancedModel: "",
      cliRunner: "grok",
      backendSupported: false,
      backendCurrent: false,
      cliReasoningRunners: ["codex", "claude", "grok"],
    })).toBe(true);
  });

  it("does not hardcode codex/claude when the capability list is empty (#1271)", () => {
    expect(resolveReasoningSupported({
      currentChannel: "cli",
      baseUrl: "",
      model: "",
      advancedBaseUrl: "",
      advancedModel: "",
      cliRunner: "codex",
      backendSupported: true,
      backendCurrent: false,
      cliReasoningRunners: [],
    })).toBe(false);
  });
});
