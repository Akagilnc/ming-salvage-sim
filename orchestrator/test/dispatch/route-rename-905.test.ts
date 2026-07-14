/**
 * #905 — route rename: agy = real agy CLI, grok-4.5 via grok-build, opencode out.
 *
 * Seams (issue AC):
 *   - modelRegistry has no provider:"opencode"; agy → real agy (gemini) CLI
 *   - all grok-4.5 routing → provider:"grok"
 *   - opencode gone from registry / routes / image bake / auth mounts
 */

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { agyAgent, agyPrintInvocation } from "../../src/agyAgent.js";
import {
  POOL_DISPATCH_BINDINGS,
  SUPPORTED_MODEL_PROVIDER_FACTORIES,
  agentForSlug,
  resolveModelSlug,
  resolveModelSlugForPool,
} from "../../src/modelRegistry.js";
import { resolveRouteModels } from "../../src/modelRoutes.js";
import { barePingArgv } from "../../src/realBackend.js";
import { poolForModelRef, probeConfigForPool, runPoolProbe } from "../../src/quotaProbe.js";

const here = dirname(fileURLToPath(import.meta.url));
const orchestratorRoot = join(here, "..", "..");

describe("#905 modelRegistry route rename", () => {
  it("points agy at the real agy (gemini) CLI provider, not opencode/grok", () => {
    expect(resolveModelSlug("agy")).toEqual({
      provider: "agy",
      model: expect.any(String),
    });
    expect(resolveModelSlug("agy").provider).toBe("agy");
    expect(resolveModelSlug("agy").provider).not.toBe("opencode");
    expect(resolveModelSlug("agy").provider).not.toBe("grok");
    expect(agentForSlug("agy").name).toBe("agy");
  });

  it("routes every grok-4.5 resolution through the SuperGrok CLI (provider grok)", () => {
    expect(resolveModelSlug("grok-4.5")).toEqual({
      provider: "grok",
      model: "grok-4.5",
    });
    expect(resolveModelSlugForPool("grok-4.5", "grok-build").provider).toBe("grok");
    // #905: no cursor / opencode transit for this model, regardless of pool.
    expect(resolveModelSlugForPool("grok-4.5", "cursor").provider).toBe("grok");
    expect(resolveModelSlugForPool("grok-4.5", "zai").provider).toBe("grok");
    expect(agentForSlug("grok-4.5").name).toBe("grok");
    expect(agentForSlug("grok-4.5", undefined, "cursor").name).toBe("grok");
  });

  it("has zero registry entries with provider opencode (incl. glm-5.2 / opencode-grok slugs)", () => {
    expect(() => resolveModelSlug("opencode-grok")).toThrow(/unknown model slug/);
    expect(() => resolveModelSlug("glm-5.2")).toThrow(/unknown model slug/);
    expect(SUPPORTED_MODEL_PROVIDER_FACTORIES).not.toContain("opencode");
    expect(Object.values(POOL_DISPATCH_BINDINGS)).not.toContain("opencode");
  });

  it("keeps route presets referencing agy as an optional CMR leg (degrade path intact)", () => {
    const route = resolveRouteModels("normal", {});
    const agyLeg = route.legCollections.cmrReview.find((leg) => leg.slug === "agy");
    expect(agyLeg).toMatchObject({ family: "agy", slug: "agy", optional: true });
    expect(resolveModelSlug(agyLeg!.slug).provider).toBe("agy");
  });
});

describe("#905 agy AgentProvider + bare-ping", () => {
  it("builds headless agy with --sandbox and stdin prompt (never opencode, never skip-permissions)", () => {
    const agent = agyAgent("");
    expect(agent.name).toBe("agy");
    const cmd = agent.buildPrintCommand({
      prompt: "Reply with exactly: nonce",
      dangerouslySkipPermissions: true,
    });
    expect(cmd.command).toMatch(/\bagy\b/);
    expect(cmd.command).toContain("--sandbox");
    expect(cmd.command).toContain("--print");
    expect(cmd.command).not.toContain("opencode");
    expect(cmd.command).not.toContain("--dangerously-skip-permissions");
    expect(cmd.stdin).toBe("Reply with exactly: nonce");
  });

  it("bare-ping argv matches agyAgent / gemini.sh (--print '' + stdin, never argv prompt)", () => {
    const prompt = "Reply with exactly: nonce-905";
    const built = barePingArgv("agy", "", prompt);
    const shared = agyPrintInvocation("", prompt);
    const agent = agyAgent("").buildPrintCommand({
      prompt,
      dangerouslySkipPermissions: true,
    });

    expect(built).toEqual({
      file: "agy",
      args: shared.args,
      input: prompt,
    });
    // gemini.sh: --print takes empty string; prompt rides stdin (no ARG_MAX).
    expect(built.args).toContain("--print");
    expect(built.args[built.args.indexOf("--print") + 1]).toBe("");
    expect(built.args).not.toContain(prompt);
    expect(built.input).toBe(prompt);
    // Same shape as production AgentProvider (shared helper, no second clone).
    expect(agent.stdin).toBe(prompt);
    expect(agent.command).toContain("--print ''");
    expect(agent.command).not.toContain(prompt);
  });

  it("bare-ping with an explicit model still uses empty --print + stdin", () => {
    const prompt = "nonce-model";
    const built = barePingArgv("agy", "Gemini 3.5 Flash", prompt);
    expect(built.args).toEqual([
      "--sandbox",
      "--model",
      "Gemini 3.5 Flash",
      "--print",
      "",
    ]);
    expect(built.input).toBe(prompt);
  });
});

describe("#905 residual opencode eviction + zai fail-closed", () => {
  it("does not bind empty zai pool to cursor (no silent rewrite surface)", () => {
    expect(POOL_DISPATCH_BINDINGS.zai).toBeUndefined();
    // Non-pinned slug stays on its registry provider under zai — no rewrite.
    expect(resolveModelSlugForPool("sonnet", "zai")).toEqual(resolveModelSlug("sonnet"));
    expect(resolveModelSlugForPool("gpt-5.6-terra", "zai")).toEqual(
      resolveModelSlug("gpt-5.6-terra"),
    );
  });

  it("never spawns the opencode binary from quota probe paths", async () => {
    // Retired pool → fail-safe error; no runCommand hook remains to spawn.
    const result = await runPoolProbe("opencode-go", {});
    expect(result.kind).toBe("error");
    expect(probeConfigForPool("opencode-go").kind).toBe("none");
    // Historical model refs no longer route to a live opencode-go probe pool.
    expect(poolForModelRef("opencode-go/glm-5.2")).not.toBe("opencode-go");
    expect(poolForModelRef("kimi-k2")).not.toBe("opencode-go");

    const probeSrc = readFileSync(
      join(orchestratorRoot, "src", "quotaProbe.ts"),
      "utf8",
    );
    expect(probeSrc).not.toMatch(/runOpencodePongProbe/);
    // No argv spawn of the bare opencode binary (probe-table only).
    expect(probeSrc).not.toMatch(/\bopencode\s+run\b/);
    expect(probeSrc).not.toMatch(/--dangerously-skip-permissions/);
    // Dep surface: no injectable shell runner for a PONG path.
    expect(probeSrc).not.toMatch(/runCommand\??:/);
    expect(probeSrc).not.toMatch(/opencodeGoModel/);
  });
});

describe("#905 opencode eviction from image + auth mounts", () => {
  it("does not bake opencode into the worker image", () => {
    const containerfile = readFileSync(
      join(orchestratorRoot, "image", "Containerfile"),
      "utf8",
    );
    expect(containerfile).not.toMatch(/opencode-ai/);
    expect(containerfile).not.toMatch(/npm install --global opencode/);
    expect(containerfile).not.toMatch(/\/usr\/local\/bin\/opencode/);
    // agy remains the Gemini review CLI.
    expect(containerfile).toMatch(/\bagy\b/);
  });

  it("exposes no opencode auth mount helpers / sandbox path in realBackend", () => {
    const src = readFileSync(join(orchestratorRoot, "src", "realBackend.ts"), "utf8");
    expect(src).not.toMatch(/SANDBOX_OPENCODE_AUTH_FILE/);
    expect(src).not.toMatch(/opencodeAuthMount/);
    expect(src).not.toMatch(/hostOpenCodeAuthFile/);
    expect(src).not.toMatch(/appendOpenCodeAuthMount/);
    expect(src).not.toMatch(/applyUniformCredentialProvisioning/);
    expect(src).not.toMatch(/opencodeAuthFile/);
    expect(src).not.toMatch(/\.local\/share\/opencode/);
  });
});
