/**
 * #617: `defer` is removed from the `Finding.action` union and its compile
 * closure. This test records the contract at the runtime validation seam,
 * the TypeScript type seam, and the zod schema seams used by the standalone
 * and family CMR reviewers.
 */

import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { findingSchema } from "../src/realBackend.js";
import { cmrReviewerFindingSchema } from "../src/family/realFamilyBackend.js";
import { isValidFinding } from "../src/validate.js";

const strayDeferFinding = {
  severity: "medium" as const,
  category: "correctness",
  claim_quote: "claim",
  location: "src/x.ts:1",
  suggested_fix: "fix it",
  action: "defer",
};

describe("#617 — defer removed from Finding.action", () => {
  it("rejects a finding whose action is defer", () => {
    expect(
      isValidFinding({
        severity: "medium",
        category: "correctness",
        claim_quote: "claim",
        location: "src/x.ts:1",
        suggested_fix: "fix it",
        action: "defer",
      }),
    ).toBe(false);
  });

  it("standalone reviewer zod schema rejects action: defer", () => {
    const result = findingSchema.safeParse(strayDeferFinding);
    expect(result.success).toBe(false);
  });

  it("family CMR reviewer zod schema rejects action: defer", () => {
    const result = cmrReviewerFindingSchema.safeParse(strayDeferFinding);
    expect(result.success).toBe(false);
  });

  it("type union does not include defer", () => {
    const dir = mkdtempSync(join(tmpdir(), "defer-removed-617-"));
    try {
      const typesPath = resolve(process.cwd(), "src/types.js");
      const checkFile = join(dir, "defer-check.ts");
      writeFileSync(
        checkFile,
        `import type { Finding } from ${JSON.stringify(typesPath)};\n` +
          `// @ts-expect-error\n` +
          `const _check: Finding["action"] = "defer";\n`,
        "utf8",
      );
      // If the union still includes "defer", the @ts-expect-error is unused and
      // tsc exits non-zero → the test fails (RED). Once "defer" is removed,
      // assigning it becomes a real error and the directive is satisfied (GREEN).
      const output = execFileSync(
        "npx",
        [
          "tsc",
          "--noEmit",
          "--strict",
          "--module",
          "NodeNext",
          "--moduleResolution",
          "NodeNext",
          "--target",
          "ES2022",
          "--skipLibCheck",
          checkFile,
        ],
        { encoding: "utf8", cwd: process.cwd() },
      );
      expect(output).toBe("");
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});
