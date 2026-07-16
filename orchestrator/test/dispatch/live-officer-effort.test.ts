import { describe, expect, it } from "vitest";

import {
  VERIFY_CODEX_SLUG,
  agentForSlug,
  resolveModelSlug,
} from "../../src/modelRegistry.js";

/**
 * #916 constitutional pin: reasoning effort authority is the registry row
 * (selected via route-preset slug), never a role/soul/smokeKey hard override
 * at dispatch. verify/cmr seats on `gpt-5.6-sol` → medium; utility seats on
 * `gpt-5.6-sol-low` → low. The deleted `effortForLiveOfficer` xhigh path must
 * not reappear.
 */
describe("live officer effort — registry/route authority only", () => {
  it("gpt-5.6-sol registry row is medium (verify/cmr default path)", () => {
    expect(resolveModelSlug(VERIFY_CODEX_SLUG)).toMatchObject({
      provider: "codex",
      model: "gpt-5.6-sol",
      options: { effort: "medium" },
    });
  });

  it("agentForSlug(gpt-5.6-sol) dispatches medium — role cannot force xhigh", () => {
    const command = agentForSlug(VERIFY_CODEX_SLUG)
      .buildPrintCommand({ prompt: "test", dangerouslySkipPermissions: false })
      .command;
    expect(command).toContain('model_reasoning_effort="medium"');
    expect(command).not.toContain('model_reasoning_effort="xhigh"');
  });

  it("gpt-5.6-sol-low registry row is low (ship/utility seats)", () => {
    expect(resolveModelSlug("gpt-5.6-sol-low")).toMatchObject({
      provider: "codex",
      model: "gpt-5.6-sol",
      options: { effort: "low" },
    });
    const command = agentForSlug("gpt-5.6-sol-low")
      .buildPrintCommand({ prompt: "test", dangerouslySkipPermissions: false })
      .command;
    expect(command).toContain('model_reasoning_effort="low"');
  });

  it("effortForLiveOfficer role-force helper is gone", async () => {
    const mod = await import("../../src/modelRegistry.js");
    expect(
      Object.prototype.hasOwnProperty.call(mod, "effortForLiveOfficer"),
    ).toBe(false);
  });

  // #916 F9: residual codexEffort overlay parameter deleted — signature is
  // agentForSlug(slug, pool?) only; effort is never call-site overlaid.
  it("agentForSlug accepts at most (slug, pool) — no codexEffort overlay", () => {
    expect(agentForSlug.length).toBe(2);
  });
});
