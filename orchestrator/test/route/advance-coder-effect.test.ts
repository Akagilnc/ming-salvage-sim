/**
 * #919 / #926 — pure shared advanceCoder effect (one path for slice + family).
 */

import { describe, expect, it } from "vitest";

import { executeAdvanceCoderSuggestion } from "../../src/advanceCoderEffect.js";
import { lookupCoderRosterEntry } from "../../src/coderRoster.js";
import {
  applyRelayBatonToRoute,
  resolveActiveModelRoute,
  withCoderSlot,
} from "../../src/modelRoutes.js";

describe("#919 pure: executeAdvanceCoderSuggestion", () => {
  const baseRoute = () => resolveActiveModelRoute({});

  it("advanced applies applySlug (coder seat)", async () => {
    const route = baseRoute();
    const current = route.slots.coder;
    const effect = await executeAdvanceCoderSuggestion({
      suggestion: "sol@med",
      currentSlug: current,
      route,
      applySlug: (r, slug) => withCoderSlot(r, slug, { preserveCoderFix: false }),
    });
    expect(effect.kind).toBe("advanced");
    if (effect.kind !== "advanced") return;
    expect(effect.toSlug).toBe("gpt-5.6-sol");
    expect(effect.route.slots.coder).toBe("gpt-5.6-sol");
    expect(effect.route.slots.coderFix).toBe("gpt-5.6-sol");
    expect(effect.entry).toEqual(lookupCoderRosterEntry("sol@med"));
    expect(effect.audit).toMatchObject({
      event: "coder_advance",
      fromModelId: current,
      toModelId: "gpt-5.6-sol",
      state_summary: "sol@med",
    });
  });

  it("advanced applies coderFix-only applySlug (family seat shape)", async () => {
    const route = baseRoute();
    const currentFix = route.slots.coderFix;
    const effect = await executeAdvanceCoderSuggestion({
      suggestion: "sol@med",
      currentSlug: currentFix,
      route,
      applySlug: (r, slug) =>
        applyRelayBatonToRoute(r, { slug }, "S5", { slots: ["coderFix"] }),
    });
    expect(effect.kind).toBe("advanced");
    if (effect.kind !== "advanced") return;
    expect(effect.route.slots.coderFix).toBe("gpt-5.6-sol");
    // coder seat untouched — family court difference
    expect(effect.route.slots.coder).toBe(route.slots.coder);
  });

  it("unknown → stay_put (never invents a seat)", async () => {
    const route = baseRoute();
    const effect = await executeAdvanceCoderSuggestion({
      suggestion: "not-a-real-coder",
      currentSlug: route.slots.coder,
      route,
      applySlug: (r, slug) => withCoderSlot(r, slug),
    });
    expect(effect).toMatchObject({
      kind: "stay_put",
      reason: "unknown_target",
      suggestion: "not-a-real-coder",
      route,
    });
    if (effect.kind !== "stay_put") return;
    expect(effect.audit).toMatchObject({
      event: "coder_advance_stay_put",
      reason: "unknown_target",
      fromModelId: route.slots.coder,
      toModelId: route.slots.coder,
      state_summary: "not-a-real-coder",
    });
  });

  it("probe fail → stay_put unassignable_target", async () => {
    const route = baseRoute();
    const effect = await executeAdvanceCoderSuggestion({
      suggestion: "luna@med",
      currentSlug: route.slots.coder,
      route,
      applySlug: (r, slug) => withCoderSlot(r, slug),
      probe: async () => ({ ok: false, reason: "smoke unavailable" }),
    });
    expect(effect.kind).toBe("stay_put");
    if (effect.kind !== "stay_put") return;
    expect(effect.reason).toBe("unassignable_target");
    expect(effect.route).toBe(route);
    expect(effect.audit.reason).toBe("unassignable_target");
    expect(effect.audit.state_summary).toBe("luna@med");
  });

  it("noop empty suggestion", async () => {
    const route = baseRoute();
    const effect = await executeAdvanceCoderSuggestion({
      suggestion: "   ",
      currentSlug: route.slots.coder,
      route,
      applySlug: (r, slug) => withCoderSlot(r, slug),
    });
    expect(effect).toEqual({
      kind: "noop",
      reason: "empty_suggestion",
      route,
    });
  });

  it("noop already active", async () => {
    const route = baseRoute();
    const effect = await executeAdvanceCoderSuggestion({
      suggestion: route.slots.coder,
      currentSlug: route.slots.coder,
      route,
      applySlug: (r, slug) => withCoderSlot(r, slug),
    });
    expect(effect).toEqual({
      kind: "noop",
      reason: "already_active",
      route,
    });
  });

  it("probe ok returns smoked route on advanced", async () => {
    const route = baseRoute();
    const smoked = withCoderSlot(route, "gpt-5.6-sol");
    const effect = await executeAdvanceCoderSuggestion({
      suggestion: "sol@med",
      currentSlug: route.slots.coder,
      route,
      applySlug: (r, slug) => withCoderSlot(r, slug),
      probe: async () => ({ ok: true, route: smoked }),
    });
    expect(effect.kind).toBe("advanced");
    if (effect.kind !== "advanced") return;
    expect(effect.route).toBe(smoked);
  });
});
