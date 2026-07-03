import { execFileSync, spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { cmrOutcomeFromResult } from "../src/family/realFamilyBackend.js";

const GUARD = resolve(process.cwd(), "image/bin/orchestrator-outcome-guard");

describe("#549 worker outcome guard", () => {
  it("valid guarded CMR outcome writes the sidecar and emits compatibility completion after validation", () => {
    const dir = mkdtempSync(join(tmpdir(), "outcome-guard-valid-"));
    try {
      mkdirSync(join(dir, "cmr"), { recursive: true });
      writeFileSync(join(dir, "cmr", "review.json"), '{"ok":true}\n', "utf8");

      const outcome = {
        converged: true,
        successfulLegs: ["gpt-5.5"],
        claimedFixedFindingIdentityKeys: [],
        priorFindingDispositions: [],
        evidencePaths: ["cmr/review.json"],
      };
      const draftPath = join(dir, "draft.json");
      const sidecarPath = join(dir, "outcome.json");
      writeFileSync(draftPath, JSON.stringify(outcome), "utf8");
      writeFileSync(sidecarPath, "", "utf8");

      const stdout = execFileSync(
        GUARD,
        [
          "--role",
          "cmr",
          "--draft",
          draftPath,
          "--outcome",
          sidecarPath,
          "--evidence-root",
          dir,
          "--completion-signal",
          "CMR_STEP_COMPLETE",
        ],
        { encoding: "utf8" },
      );

      expect(JSON.parse(readFileSync(sidecarPath, "utf8"))).toEqual(outcome);
      expect(stdout).toBe(`${cmrTag(outcome)}\nCMR_STEP_COMPLETE\n`);

      const parsed = cmrOutcomeFromResult({
        completionSignal: "CMR_STEP_COMPLETE",
        stdout,
        outcomePath: sidecarPath,
        cmrReviewLegs: [{ slug: "gpt-5.5" }],
      });
      expect(parsed).toMatchObject({
        kind: "verdict",
        converged: true,
        successfulLegs: ["gpt-5.5"],
        evidencePaths: ["cmr/review.json"],
      });
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("valid guarded CMR blocking-finding outcome reaches the runner-compatible parser", () => {
    const dir = mkdtempSync(join(tmpdir(), "outcome-guard-red-"));
    try {
      mkdirSync(join(dir, "cmr"), { recursive: true });
      writeFileSync(join(dir, "cmr", "review.json"), '{"finding":true}\n', "utf8");

      const outcome = {
        converged: false,
        reason: "blocking findings remain",
        successfulLegs: ["gpt-5.5"],
        claimedFixedFindingIdentityKeys: [],
        priorFindingDispositions: [],
        findings: [
          {
            severity: "medium",
            category: "correctness",
            claim_quote: "guarded outcome must return to runner",
            location: "orchestrator/src/family/realFamilyBackend.ts",
            suggested_fix: "dispatch coder-fix in a separate worker",
            action: "fix_now",
          },
        ],
        evidencePaths: ["cmr/review.json"],
      };
      const draftPath = join(dir, "draft.json");
      const sidecarPath = join(dir, "outcome.json");
      writeFileSync(draftPath, JSON.stringify(outcome), "utf8");
      writeFileSync(sidecarPath, "", "utf8");

      const stdout = execFileSync(
        GUARD,
        [
          "--role",
          "cmr",
          "--draft",
          draftPath,
          "--outcome",
          sidecarPath,
          "--evidence-root",
          dir,
          "--completion-signal",
          "CMR_STEP_COMPLETE",
        ],
        { encoding: "utf8" },
      );

      const parsed = cmrOutcomeFromResult({
        completionSignal: "CMR_STEP_COMPLETE",
        stdout,
        outcomePath: sidecarPath,
        cmrReviewLegs: [{ slug: "gpt-5.5" }],
      });
      expect(parsed).toMatchObject({
        kind: "verdict",
        converged: false,
        reason: "blocking findings remain",
        successfulLegs: ["gpt-5.5"],
        evidencePaths: ["cmr/review.json"],
      });
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("malformed finding disposition is rejected before sidecar write or completion output", () => {
    const dir = mkdtempSync(join(tmpdir(), "outcome-guard-finding-disposition-"));
    try {
      mkdirSync(join(dir, "cmr"), { recursive: true });
      writeFileSync(join(dir, "cmr", "review.json"), '{"finding":true}\n', "utf8");

      const draftPath = join(dir, "draft.json");
      const sidecarPath = join(dir, "outcome.json");
      writeFileSync(
        draftPath,
        JSON.stringify({
          converged: false,
          reason: "blocking findings remain",
          successfulLegs: ["gpt-5.5"],
          claimedFixedFindingIdentityKeys: [],
          priorFindingDispositions: [],
          findings: [
            {
              severity: "medium",
              category: "correctness",
              claim_quote: "guard must reject malformed disposition payloads",
              location: "orchestrator/image/bin/orchestrator-outcome-guard",
              suggested_fix: "validate the disposition role schema",
              action: "fix_now",
              disposition: { kind: "bogus" },
            },
          ],
          evidencePaths: ["cmr/review.json"],
        }),
        "utf8",
      );
      writeFileSync(sidecarPath, "sentinel\n", "utf8");

      const result = spawnSync(
        GUARD,
        [
          "--role",
          "cmr",
          "--draft",
          draftPath,
          "--outcome",
          sidecarPath,
          "--evidence-root",
          dir,
          "--completion-signal",
          "CMR_STEP_COMPLETE",
        ],
        { encoding: "utf8" },
      );

      expect(result.status).toBe(1);
      expect(result.stdout).not.toContain("CMR_STEP_COMPLETE");
      expect(result.stderr).toContain("findings[0].disposition.kind is not a supported value");
      expect(readFileSync(sidecarPath, "utf8")).toBe("sentinel\n");
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it.each([
    {
      name: "critical/high findings cannot be deferred",
      finding: {
        severity: "high",
        category: "correctness",
        claim_quote: "P1 blockers must return to coder-fix",
        location: "orchestrator/src/family/verifyCmr.ts",
        suggested_fix: "mark this as fix_now",
        action: "defer",
        disposition: {
          kind: "same_module",
          reason: "same module but still high severity",
        },
      },
      error: "findings[0].action must be fix_now for critical/high severity",
    },
    {
      name: "defer requires an explicit disposition",
      finding: {
        severity: "medium",
        category: "standards",
        claim_quote: "defer needs an auditable reason",
        location: "orchestrator/src/family/verifyCmr.ts",
        suggested_fix: "include a non-suppression disposition",
        action: "defer",
      },
      error: "findings[0].disposition is required for defer",
    },
    {
      name: "defer cannot use accepted_suppressed",
      finding: {
        severity: "medium",
        category: "standards",
        claim_quote: "defer is not an accepted suppression",
        location: "orchestrator/src/family/verifyCmr.ts",
        suggested_fix: "use a non-suppression disposition or wont_fix",
        action: "defer",
        disposition: {
          kind: "accepted_suppressed",
          source: "issue #549 owner instruction",
          scope: "outcome guard",
          reason: "accepted only for this example",
          boundedReopen: "reopen if this scope changes",
        },
      },
      error: "findings[0].disposition must not be accepted_suppressed for defer",
    },
    {
      name: "wont_fix requires accepted_suppressed",
      finding: {
        severity: "medium",
        category: "standards",
        claim_quote: "wont_fix must carry accepted suppression evidence",
        location: "orchestrator/src/family/verifyCmr.ts",
        suggested_fix: "include accepted_suppressed disposition evidence",
        action: "wont_fix",
        disposition: {
          kind: "same_module",
          reason: "same-module is not enough to suppress a finding",
        },
      },
      error: "findings[0].disposition must be accepted_suppressed for wont_fix/rejected",
    },
    {
      name: "rejected accepted_suppressed requires bounded reopen evidence",
      finding: {
        severity: "medium",
        category: "standards",
        claim_quote: "suppression needs all required fields",
        location: "orchestrator/src/family/verifyCmr.ts",
        suggested_fix: "include boundedReopen",
        action: "rejected",
        disposition: {
          kind: "accepted_suppressed",
          source: "issue #549 owner instruction",
          scope: "outcome guard",
          reason: "accepted only for this example",
        },
      },
      error: "findings[0].disposition.boundedReopen is required",
    },
  ])(
    "runner-malformed finding action/disposition combination is rejected: $name",
    ({ finding, error }) => {
      expectGuardRejectsFinding(finding, error);
    },
  );

  it("valid guarded CMR escalation outcome reaches the runner-compatible parser", () => {
    const dir = mkdtempSync(join(tmpdir(), "outcome-guard-escalate-"));
    try {
      const outcome = {
        escalate: {
          reason: "review leg unavailable",
          diagnosis: "worker cannot run the selected leg set",
        },
      };
      const draftPath = join(dir, "draft.json");
      const sidecarPath = join(dir, "outcome.json");
      writeFileSync(draftPath, JSON.stringify(outcome), "utf8");
      writeFileSync(sidecarPath, "", "utf8");

      const stdout = execFileSync(
        GUARD,
        [
          "--role",
          "cmr",
          "--draft",
          draftPath,
          "--outcome",
          sidecarPath,
          "--evidence-root",
          dir,
          "--completion-signal",
          "CMR_STEP_COMPLETE",
        ],
        { encoding: "utf8" },
      );

      const parsed = cmrOutcomeFromResult({
        completionSignal: "CMR_STEP_COMPLETE",
        stdout,
        outcomePath: sidecarPath,
      });
      expect(parsed).toEqual({
        kind: "escalate",
        reason: "review leg unavailable",
        diagnosis: "worker cannot run the selected leg set",
      });
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("#258 CMR self-fix state is rejected before sidecar write or completion output", () => {
    const dir = mkdtempSync(join(tmpdir(), "outcome-guard-malformed-"));
    try {
      mkdirSync(join(dir, "cmr"), { recursive: true });
      writeFileSync(join(dir, "cmr", "review.json"), '{"ok":true}\n', "utf8");

      const draftPath = join(dir, "draft.json");
      const sidecarPath = join(dir, "outcome.json");
      writeFileSync(
        draftPath,
        JSON.stringify({
          converged: true,
          successfulLegs: ["gpt-5.5"],
          claimedFixedFindingIdentityKeys: [],
          priorFindingDispositions: [],
          evidencePaths: ["cmr/review.json"],
          fixLoopStarted: true,
        }),
        "utf8",
      );
      writeFileSync(sidecarPath, "sentinel\n", "utf8");

      const result = spawnSync(
        GUARD,
        [
          "--role",
          "cmr",
          "--draft",
          draftPath,
          "--outcome",
          sidecarPath,
          "--evidence-root",
          dir,
          "--completion-signal",
          "CMR_STEP_COMPLETE",
        ],
        { encoding: "utf8" },
      );

      expect(result.status).toBe(1);
      expect(result.stdout).not.toContain("CMR_STEP_COMPLETE");
      expect(result.stderr).toContain("unexpected field: fixLoopStarted");
      expect(readFileSync(sidecarPath, "utf8")).toBe("sentinel\n");
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("absolute evidence paths are rejected before completion even when the file exists", () => {
    const dir = mkdtempSync(join(tmpdir(), "outcome-guard-absolute-evidence-"));
    try {
      mkdirSync(join(dir, "cmr"), { recursive: true });
      const evidencePath = join(dir, "cmr", "review.json");
      writeFileSync(evidencePath, '{"ok":true}\n', "utf8");

      const draftPath = join(dir, "draft.json");
      const sidecarPath = join(dir, "outcome.json");
      writeFileSync(
        draftPath,
        JSON.stringify({
          converged: true,
          successfulLegs: ["gpt-5.5"],
          claimedFixedFindingIdentityKeys: [],
          priorFindingDispositions: [],
          evidencePaths: [evidencePath],
        }),
        "utf8",
      );
      writeFileSync(sidecarPath, "sentinel\n", "utf8");

      const result = spawnSync(
        GUARD,
        [
          "--role",
          "cmr",
          "--draft",
          draftPath,
          "--outcome",
          sidecarPath,
          "--evidence-root",
          dir,
          "--completion-signal",
          "CMR_STEP_COMPLETE",
        ],
        { encoding: "utf8" },
      );

      expect(result.status).toBe(1);
      expect(result.stdout).not.toContain("CMR_STEP_COMPLETE");
      expect(result.stderr).toContain("evidencePaths[0] must be relative");
      expect(readFileSync(sidecarPath, "utf8")).toBe("sentinel\n");
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("malformed prior finding disposition is rejected by the guard role schema", () => {
    const dir = mkdtempSync(join(tmpdir(), "outcome-guard-prior-disposition-"));
    try {
      mkdirSync(join(dir, "cmr"), { recursive: true });
      writeFileSync(join(dir, "cmr", "review.json"), '{"ok":true}\n', "utf8");

      const draftPath = join(dir, "draft.json");
      const sidecarPath = join(dir, "outcome.json");
      writeFileSync(
        draftPath,
        JSON.stringify({
          converged: true,
          successfulLegs: ["gpt-5.5"],
          claimedFixedFindingIdentityKeys: [],
          priorFindingDispositions: [{ status: "verified-closed" }],
          evidencePaths: ["cmr/review.json"],
        }),
        "utf8",
      );
      writeFileSync(sidecarPath, "sentinel\n", "utf8");

      const result = spawnSync(
        GUARD,
        [
          "--role",
          "cmr",
          "--draft",
          draftPath,
          "--outcome",
          sidecarPath,
          "--evidence-root",
          dir,
          "--completion-signal",
          "CMR_STEP_COMPLETE",
        ],
        { encoding: "utf8" },
      );

      expect(result.status).toBe(1);
      expect(result.stderr).toContain("priorFindingDispositions[0].identityKey is required");
      expect(readFileSync(sidecarPath, "utf8")).toBe("sentinel\n");
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("accepted_suppressed prior finding dispositions require explicit source and bounded reopen before sidecar write", () => {
    const dir = mkdtempSync(join(tmpdir(), "outcome-guard-prior-accepted-"));
    try {
      mkdirSync(join(dir, "cmr"), { recursive: true });
      writeFileSync(join(dir, "cmr", "review.json"), '{"ok":true}\n', "utf8");

      const draftPath = join(dir, "draft.json");
      const sidecarPath = join(dir, "outcome.json");
      writeFileSync(
        draftPath,
        JSON.stringify({
          converged: true,
          successfulLegs: ["gpt-5.5"],
          claimedFixedFindingIdentityKeys: [
            "standards|orchestrator/image/bin/orchestrator-outcome-guard|weak accepted suppression",
          ],
          priorFindingDispositions: [
            {
              identityKey:
                "standards|orchestrator/image/bin/orchestrator-outcome-guard|weak accepted suppression",
              status: "accepted_suppressed",
              reason: "reviewer prose says it is acceptable",
              source: "reviewer prose only",
              scope: "outcome guard",
              boundedReopen: "never",
            },
          ],
          evidencePaths: ["cmr/review.json"],
        }),
        "utf8",
      );
      writeFileSync(sidecarPath, "sentinel\n", "utf8");

      const result = spawnSync(
        GUARD,
        [
          "--role",
          "cmr",
          "--draft",
          draftPath,
          "--outcome",
          sidecarPath,
          "--evidence-root",
          dir,
          "--completion-signal",
          "CMR_STEP_COMPLETE",
        ],
        { encoding: "utf8" },
      );

      expect(result.status).toBe(1);
      expect(result.stdout).not.toContain("CMR_STEP_COMPLETE");
      expect(result.stderr).toContain(
        "priorFindingDispositions[0].source must name an explicit user/ADR/issue source",
      );
      expect(readFileSync(sidecarPath, "utf8")).toBe("sentinel\n");
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("worker image bake stages the guard binary and exposes it on PATH", () => {
    const buildScript = readFileSync(resolve(process.cwd(), "image/build.sh"), "utf8");
    const containerfile = readFileSync(
      resolve(process.cwd(), "image/Containerfile"),
      "utf8",
    );

    expect(buildScript).toMatch(/orchestrator-outcome-guard/);
    expect(buildScript).toMatch(/STAGE\/bin/);
    expect(containerfile).toMatch(/COPY bin\/ \/home\/agent\/\.orchestrator\/bin\//);
    expect(containerfile).toMatch(
      /\/usr\/local\/bin\/orchestrator-outcome-guard/,
    );
  });

  it("shared worker output protocol routes completion through the versioned guard", () => {
    const protocol = readFileSync(
      resolve(process.cwd(), "image/souls/output_protocol.md"),
      "utf8",
    );

    expect(protocol).toMatch(/orchestrator-outcome-guard/);
    expect(protocol).toMatch(/--draft/);
    expect(protocol).toMatch(/--outcome "\$ORCHESTRATOR_OUTCOME_PATH"/);
    expect(protocol).not.toMatch(/python3 -c 'import json/);
  });

  it("CMR worker entrypoint prompts route terminal output through the guard contract", () => {
    for (const promptName of [
      "integrated_cmr.md",
      "integrated_cmr_completeness.md",
      "integrated_cmr_correctness.md",
    ]) {
      const prompt = readFileSync(
        resolve(process.cwd(), "prompts", promptName),
        "utf8",
      );
      expect(prompt).toMatch(/orchestrator-outcome-guard/);
      expect(prompt).toMatch(/--role "cmr"/);
      expect(prompt).toMatch(/evidencePaths/);
    }
  });
});

function cmrTag(outcome: unknown): string {
  return `<cmr>${JSON.stringify(outcome)}</cmr>`;
}

function expectGuardRejectsFinding(
  finding: Record<string, unknown>,
  expectedError: string,
): void {
  const dir = mkdtempSync(join(tmpdir(), "outcome-guard-finding-combo-"));
  try {
    mkdirSync(join(dir, "cmr"), { recursive: true });
    writeFileSync(join(dir, "cmr", "review.json"), '{"finding":true}\n', "utf8");

    const draftPath = join(dir, "draft.json");
    const sidecarPath = join(dir, "outcome.json");
    writeFileSync(
      draftPath,
      JSON.stringify({
        converged: false,
        reason: "blocking findings remain",
        successfulLegs: ["gpt-5.5"],
        claimedFixedFindingIdentityKeys: [],
        priorFindingDispositions: [],
        findings: [finding],
        evidencePaths: ["cmr/review.json"],
      }),
      "utf8",
    );
    writeFileSync(sidecarPath, "sentinel\n", "utf8");

    const result = spawnSync(
      GUARD,
      [
        "--role",
        "cmr",
        "--draft",
        draftPath,
        "--outcome",
        sidecarPath,
        "--evidence-root",
        dir,
        "--completion-signal",
        "CMR_STEP_COMPLETE",
      ],
      { encoding: "utf8" },
    );

    expect(result.status).toBe(1);
    expect(result.stdout).not.toContain("CMR_STEP_COMPLETE");
    expect(result.stderr).toContain(expectedError);
    expect(readFileSync(sidecarPath, "utf8")).toBe("sentinel\n");
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}
