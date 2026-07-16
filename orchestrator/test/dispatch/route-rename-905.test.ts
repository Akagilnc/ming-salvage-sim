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

import {
  agyAgent,
  agyInteractiveArgs,
  agyPrintInvocation,
  createAgyStreamParser,
} from "../../src/agyAgent.js";
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
    expect(agentForSlug("grok-4.5", "cursor").name).toBe("grok");
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
  it("builds headless agy with --sandbox and --print <prompt> (never opencode, never skip-permissions)", () => {
    const agent = agyAgent("");
    expect(agent.name).toBe("agy");
    const prompt = "Reply with exactly: nonce";
    const cmd = agent.buildPrintCommand({
      prompt,
      dangerouslySkipPermissions: true,
    });
    expect(cmd.command).toMatch(/\bagy\b/);
    expect(cmd.command).toContain("--sandbox");
    expect(cmd.command).toContain("--print");
    // #915: agy 1.1.2 rejects empty --print; prompt is the --print value.
    expect(cmd.command).toContain(prompt);
    expect(cmd.command).not.toContain("--print ''");
    expect(cmd.command).not.toContain("opencode");
    expect(cmd.command).not.toContain("--dangerously-skip-permissions");
  });

  it("B1: multi-line <merger> + STEP_COMPLETE keeps full body under last-wins result", () => {
    // Sandcastle: resultText = parsed.result on every result event (last wins).
    // Per-line result used to drop tags and keep only STEP_COMPLETE.
    const parse = createAgyStreamParser();
    const lines = [
      '<merger>{"resolved":true,"notes":"both sides kept"}</merger>',
      "MERGER_STEP_COMPLETE",
    ];
    let resultText = "";
    for (const line of lines) {
      for (const ev of parse(line)) {
        if (ev.type === "result") resultText = ev.result;
      }
    }
    expect(resultText).toContain("<merger>");
    expect(resultText).toContain('"resolved":true');
    expect(resultText).toContain("MERGER_STEP_COMPLETE");
    expect(resultText).toBe(lines.join("\n"));

    // Production agent instance shares the same accumulator contract.
    const agent = agyAgent("");
    let agentResult = "";
    for (const line of lines) {
      for (const ev of agent.parseStreamLine(line)) {
        if (ev.type === "result") agentResult = (ev as { result: string }).result;
      }
    }
    expect(agentResult).toBe(lines.join("\n"));
  });

  it("R5-1 class: print and interactive build* both reset stream body across maxIter", () => {
    // Sandcastle reuses one AgentProvider + parseStreamLine across maxIter.
    const agent = agyAgent("");
    let last = "";
    for (const line of ["ROUND1_TAG", "ROUND1_DONE"]) {
      for (const ev of agent.parseStreamLine(line)) {
        if (ev.type === "result") last = ev.result;
      }
    }
    expect(last).toContain("ROUND1_TAG");

    // Print iteration reset.
    agent.buildPrintCommand({
      prompt: "iter-2",
      dangerouslySkipPermissions: false,
    });
    last = "";
    for (const line of ["ROUND2_PRINT"]) {
      for (const ev of agent.parseStreamLine(line)) {
        if (ev.type === "result") last = ev.result;
      }
    }
    expect(last).toBe("ROUND2_PRINT");
    expect(last).not.toMatch(/ROUND1/);

    // Interactive iteration reset (same class of build* boundary).
    agent.buildInteractiveArgs!({
      prompt: "iter-3",
      dangerouslySkipPermissions: false,
    });
    last = "";
    for (const line of ["ROUND3_INTERACTIVE"]) {
      for (const ev of agent.parseStreamLine(line)) {
        if (ev.type === "result") last = ev.result;
      }
    }
    expect(last).toBe("ROUND3_INTERACTIVE");
    expect(last).not.toMatch(/ROUND1|ROUND2/);
  });
});

/**
 * #915 — agy 1.1.2 rejects empty `--print` (no stdin fallthrough).
 * Shared seam: bare-ping + AgentProvider both put the prompt as the
 * `--print` value; interactive uses `--prompt-interactive` only.
 */
describe("#915 agy print prompt delivery (real CLI form)", () => {
  it("print mode: --print value is the non-empty prompt (not empty placeholder)", () => {
    const prompt = "Reply with exactly: nonce-915";
    const print = agyPrintInvocation("", prompt);

    expect(print).toContain("--sandbox");
    expect(print).toContain("--print-timeout");
    expect(print).toContain("--print");
    const printIdx = print.indexOf("--print");
    expect(print[printIdx + 1]).toBe(prompt);
    expect(print[printIdx + 1]).not.toBe("");
    // Real CLI form: prompt is an argv token after --print (agy 1.1.2).
    expect(print).toContain(prompt);
  });

  it("bare-ping argv matches shared print helper (prompt on --print, not empty)", () => {
    const prompt = "Reply with exactly: nonce-915-bare";
    const built = barePingArgv("agy", "", prompt);
    const shared = agyPrintInvocation("", prompt);
    const agent = agyAgent("").buildPrintCommand({
      prompt,
      dangerouslySkipPermissions: true,
    });

    expect(built.file).toBe("agy");
    expect(built.args).toEqual([...shared]);
    expect(built.args[built.args.indexOf("--print") + 1]).toBe(prompt);
    expect(built.args).toContain(prompt);
    // #915 dead-channel delete: print delivery is argv-only (no stdin dual path).
    expect(built.input).toBeUndefined();
    expect(agent.stdin).toBeUndefined();
    // Same shape as production AgentProvider (shared helper, no second clone).
    expect(agent.command).toContain("--print");
    expect(agent.command).toContain(prompt);
    expect(agent.command).not.toContain("--print ''");
  });

  it("bare-ping with explicit model keeps --print <prompt> + Go-duration timeout", () => {
    const prompt = "nonce-model-915";
    const built = barePingArgv("agy", "Gemini 3.5 Flash", prompt);
    const shared = agyPrintInvocation("Gemini 3.5 Flash", prompt);
    expect(built.args).toEqual([...shared]);
    expect(built.args).toContain("--model");
    expect(built.args).toContain("Gemini 3.5 Flash");
    expect(built.args).toContain("--print-timeout");
    // Go duration with unit — bare "900000" is rejected by agy CLI.
    const timeoutIdx = built.args.indexOf("--print-timeout");
    expect(built.args[timeoutIdx + 1]).toMatch(/^\d+(ns|us|µs|ms|s|m|h)$/);
    expect(built.args[timeoutIdx + 1]).not.toMatch(/^\d+$/);
    expect(built.args[built.args.indexOf("--print") + 1]).toBe(prompt);
  });

  it("interactive mode never uses --print; seed rides --prompt-interactive", () => {
    const seed = "seed-prompt-body-915";
    const interactive = agyInteractiveArgs("Gemini 3.5 Flash", seed);
    expect(interactive[0]).toBe("agy");
    expect(interactive).toContain("--sandbox");
    expect(interactive).toContain("--prompt-interactive");
    expect(interactive).not.toContain("--print");
    expect(interactive[interactive.indexOf("--prompt-interactive") + 1]).toBe(
      seed,
    );

    const agent = agyAgent("Gemini 3.5 Flash");
    const agentInteractive = agent.buildInteractiveArgs!({
      prompt: seed,
      dangerouslySkipPermissions: false,
    });
    expect(agentInteractive).toEqual([...interactive]);

    // Class seam: print surface still puts seed after --print (not interactive).
    const agentPrint = agent.buildPrintCommand({
      prompt: seed,
      dangerouslySkipPermissions: false,
    });
    expect(agentPrint.command).toContain(seed);
    expect(agentPrint.command).toContain("--print");
    expect(agentPrint.command).not.toContain("--prompt-interactive");
  });

  it("never ends print argv with empty --print token (the #915 accident shape)", () => {
    const prompt = "must-not-be-dropped";
    for (const model of ["", "Gemini 3.5 Flash"] as const) {
      const args = agyPrintInvocation(model, prompt);
      const lastPrintIdx = args.lastIndexOf("--print");
      expect(lastPrintIdx).toBeGreaterThanOrEqual(0);
      expect(args[lastPrintIdx + 1]).toBe(prompt);
      // The fatal production shape was: ... --print-timeout 15m --print <empty>
      expect(args[lastPrintIdx + 1]?.length ?? 0).toBeGreaterThan(0);
    }
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
