/**
 * #1092 — resume-turn structured-output must restate the JSON schema, and a
 * parse failure on a resumed session must not burn six identical resume retries.
 *
 * Seams:
 *   1. {@link structuredOutputResumeInstruction} — resume/retry SO prompt text
 *   2. {@link withMechanicalRetry} — after resume SO parse fail → one fresh only
 */
import { describe, expect, it } from "vitest";
import { StructuredOutputError } from "@ai-hero/sandcastle";
import {
  ONLINE_REVIEW_RECEIPT_EXAMPLE_JSON,
  ONLINE_REVIEW_RECEIPT_SCHEMA_TEXT,
  structuredOutputResumeInstruction,
} from "../../src/receiptRecovery.js";
import { withMechanicalRetry } from "../../src/dispatchRetry.js";
import type {
  DispatchContext,
  WorkerResult,
  WorkerSpec,
} from "../../src/types.js";
import { ONLINE_REVIEW_RECEIPT_TAG } from "../../src/stationReceiptContracts.js";

function landingSpec(session: WorkerSpec["session"] = "fresh"): WorkerSpec {
  return {
    id: "S12",
    kind: "landing",
    role: "landing",
    host: "claude",
    session,
    contextRetention: "retain",
    skill: "gstack-document-release",
    promptFile: "prompts/landing.md",
    maxIter: 1,
    model: "sonnet",
    soul: "landing",
    toolchain: [],
  };
}

describe("#1092 structuredOutputResumeInstruction", () => {
  it("resume SO instruction restates full JSON schema plus a minimal valid example", () => {
    const text = structuredOutputResumeInstruction({
      tag: ONLINE_REVIEW_RECEIPT_TAG,
      schemaText: ONLINE_REVIEW_RECEIPT_SCHEMA_TEXT,
      exampleJson: ONLINE_REVIEW_RECEIPT_EXAMPLE_JSON,
      errorMessage: `Structured output tag <${ONLINE_REVIEW_RECEIPT_TAG}> contains invalid JSON`,
      rawMatched: "status: completed\nreleased: true\n",
    });
    expect(text).toContain(ONLINE_REVIEW_RECEIPT_SCHEMA_TEXT);
    expect(text).toContain(ONLINE_REVIEW_RECEIPT_EXAMPLE_JSON);
    expect(text).toContain(`<${ONLINE_REVIEW_RECEIPT_TAG}>`);
    expect(text).toMatch(/JSON/i);
    // Stronger than Sandcastle's stock "Emit only a corrected <tag> block"
    // (no schema) — we require schema + example above that closing line.
    expect(text).toContain("Required JSON schema");
    expect(text).toContain("Minimal valid JSON example");
  });
});

describe("#1092 withMechanicalRetry — resume SO parse-fail short-circuit", () => {
  it("parse-fail on resume → next attempt is fresh; does not burn 6 resume retries", async () => {
    const seen: Array<{ resumeSessionId?: string; session: WorkerSpec["session"] }> =
      [];
    let calls = 0;
    const soe = new StructuredOutputError(
      `Structured output tag <${ONLINE_REVIEW_RECEIPT_TAG}> contains invalid JSON`,
      {
        tag: ONLINE_REVIEW_RECEIPT_TAG,
        rawMatched: "status: completed\nreleased: true\n",
        cause: new SyntaxError("Unexpected token"),
        commits: [],
        branch: "family/1092",
        sessionId: "sess-resume-yaml",
      },
    );

    const dispatch = async (spec: WorkerSpec, ctx: DispatchContext) => {
      calls += 1;
      seen.push({
        ...(typeof ctx.resumeSessionId === "string"
          ? { resumeSessionId: ctx.resumeSessionId }
          : {}),
        session: spec.session,
      });
      // Every attempt throws the same deterministic SO parse failure.
      throw soe;
    };

    const result = await withMechanicalRetry(
      landingSpec("resume"),
      { resumeSessionId: "sess-resume-yaml" },
      dispatch,
      { sleepMs: async () => undefined },
    );

    expect(result.kind).toBe("failed");
    // Attempt 1 = resume (caller's ctx); attempt 2 = exactly one fresh; stop.
    expect(calls).toBe(2);
    expect(seen[0]?.resumeSessionId).toBe("sess-resume-yaml");
    expect(seen[1]?.resumeSessionId).toBeUndefined();
    expect(seen[1]?.session).toBe("fresh");
  });
});
