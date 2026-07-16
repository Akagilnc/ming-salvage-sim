/**
 * Hotfix (owner B ruling, 2026-07-16 #934 W1 first flight) — Sandcastle
 * `Output.object` with maxRetries > 0 requires a provider that supports
 * session resumption; the grok provider does not (first-flight RUD: all three
 * W1 coders threw at dispatch). Typed receipts stay attached everywhere, but
 * maxRetries follows provider capability: resume-capable providers keep the
 * native in-session re-ask (2); the rest attach 0 and a bad envelope falls
 * through to the established process-root retry path (#934 ID-006 SO-exhaust).
 */
import { describe, expect, it } from "vitest";
import {
  RECEIPT_MAX_RETRIES,
  coderReceiptOutput,
  workerReceiptOutput,
} from "../../src/receiptRecovery.js";
import { resumeCapableForSlug } from "../../src/modelRegistry.js";
import { z } from "zod";

describe("resumeCapableForSlug — registry knows which providers can resume", () => {
  it("grok cannot resume; codex and claude slugs can", () => {
    expect(resumeCapableForSlug("grok-4.5")).toBe(false);
    expect(resumeCapableForSlug("gpt-5.6-sol")).toBe(true);
    expect(resumeCapableForSlug("gpt-5.6-terra")).toBe(true);
    expect(resumeCapableForSlug("sonnet")).toBe(true);
    expect(resumeCapableForSlug("opus")).toBe(true);
  });
});

describe("receipt attach helpers gate maxRetries on resume capability", () => {
  const schema = z.object({ ok: z.boolean() });

  it("defaults keep the native re-ask (backward compatible)", () => {
    expect(workerReceiptOutput("judge", schema).maxRetries).toBe(
      RECEIPT_MAX_RETRIES,
    );
  });

  it("resume-incapable providers attach maxRetries 0, receipt still typed", () => {
    const def = workerReceiptOutput("judge", schema, false);
    expect(def.maxRetries).toBe(0);
    expect(def.tag).toBe("judge");
  });

  it("wrapper helpers thread the capability through", () => {
    expect(coderReceiptOutput(schema, "coder", false).maxRetries).toBe(0);
    expect(coderReceiptOutput(schema, "coder", true).maxRetries).toBe(
      RECEIPT_MAX_RETRIES,
    );
  });
});
