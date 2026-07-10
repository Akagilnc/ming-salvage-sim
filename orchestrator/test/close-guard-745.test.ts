/**
 * #745 Close Guard arm of orchestrator-outcome-guard.
 *
 * Seam (issue comment, 2026-07-10): when a worker terminal draft claims
 * success/completed but its body still contains unchecked `- [ ]` items,
 * reject the draft on the existing schema-rejection path (exit 1, no sidecar
 * write, no completion signal). No new states, no runner changes, no config.
 *
 * Semantic: announcing completion while carrying an open checklist is a
 * false-completion signal.
 */
import { execFileSync, spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import { describe, expect, it } from "vitest";

const GUARD = resolve(process.cwd(), "image/bin/orchestrator-outcome-guard");

function baseSuccessDraft(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    converged: true,
    successfulLegs: ["gpt-5.5"],
    claimedFixedFindingIdentityKeys: [],
    priorFindingDispositions: [],
    evidencePaths: ["cmr/review.json"],
    ...overrides,
  };
}

function baseBlockingDraft(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    converged: false,
    reason: "blocking findings remain",
    successfulLegs: ["gpt-5.5"],
    claimedFixedFindingIdentityKeys: [],
    priorFindingDispositions: [],
    findings: [
      {
        severity: "medium",
        category: "correctness",
        claim_quote: "still open work",
        location: "orchestrator/image/bin/orchestrator-outcome-guard",
        suggested_fix: "finish remaining items",
        action: "fix_now",
      },
    ],
    evidencePaths: ["cmr/review.json"],
    ...overrides,
  };
}

function runGuard(draft: Record<string, unknown>): {
  dir: string;
  draftPath: string;
  sidecarPath: string;
  status: number | null;
  stdout: string;
  stderr: string;
  sidecar: string;
} {
  const dir = mkdtempSync(join(tmpdir(), "close-guard-745-"));
  mkdirSync(join(dir, "cmr"), { recursive: true });
  writeFileSync(join(dir, "cmr", "review.json"), '{"ok":true}\n', "utf8");

  const draftPath = join(dir, "draft.json");
  const sidecarPath = join(dir, "outcome.json");
  writeFileSync(draftPath, JSON.stringify(draft), "utf8");
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

  return {
    dir,
    draftPath,
    sidecarPath,
    status: result.status,
    stdout: result.stdout ?? "",
    stderr: result.stderr ?? "",
    sidecar: readFileSync(sidecarPath, "utf8"),
  };
}

describe("#745 Close Guard arm — success draft with open checkboxes", () => {
  it("rejects a success (converged) draft whose body still has unchecked - [ ] items", () => {
    const run = runGuard(
      baseSuccessDraft({
        findings: [
          {
            severity: "low",
            category: "clarity",
            claim_quote: "remaining checklist still open",
            location: "docs/handoff.md",
            suggested_fix: ["remaining:", "- [ ] wire the landing file", "- [x] already done"].join(
              "\n",
            ),
            action: "wont_fix",
            disposition: {
              kind: "accepted_suppressed",
              source: "owner #745",
              scope: "this slice only",
              reason: "doc-only follow-up, not a code blocker",
              boundedReopen: "reopen if the handoff checklist is required for ship",
            },
          },
        ],
      }),
    );

    try {
      expect(run.status).toBe(1);
      expect(run.stdout).not.toContain("CMR_STEP_COMPLETE");
      expect(run.stderr).toMatch(/outcome guard rejected cmr draft:/i);
      expect(run.stderr).toMatch(/unchecked checklist|open checklist|- \[ \]/i);
      expect(run.sidecar).toBe("sentinel\n");
    } finally {
      rmSync(run.dir, { recursive: true, force: true });
    }
  });

  it("rejects a success draft with a bare open checkbox line", () => {
    const run = runGuard(
      baseSuccessDraft({
        findings: [
          {
            severity: "low",
            category: "clarity",
            claim_quote: "placeholder open item",
            location: "docs/handoff.md",
            suggested_fix: "- [ ]",
            action: "wont_fix",
            disposition: {
              kind: "accepted_suppressed",
              source: "issue #745",
              scope: "this slice only",
              reason: "empty checkbox is still open work",
              boundedReopen: "reopen when a real remaining item appears",
            },
          },
        ],
      }),
    );

    try {
      expect(run.status).toBe(1);
      expect(run.stdout).not.toContain("CMR_STEP_COMPLETE");
      expect(run.sidecar).toBe("sentinel\n");
    } finally {
      rmSync(run.dir, { recursive: true, force: true });
    }
  });

  it("rejects a success draft with star-bullet open items (* [ ])", () => {
    const run = runGuard(
      baseSuccessDraft({
        findings: [
          {
            severity: "low",
            category: "clarity",
            claim_quote: "star bullet open item",
            location: "docs/handoff.md",
            suggested_fix: "* [ ] still open via star bullet",
            action: "wont_fix",
            disposition: {
              kind: "accepted_suppressed",
              source: "ADR 0050",
              scope: "this slice only",
              reason: "star bullets count as open checklist items",
              boundedReopen: "reopen if star-bullet form is no longer recognized",
            },
          },
        ],
      }),
    );

    try {
      expect(run.status).toBe(1);
      expect(run.stdout).not.toContain("CMR_STEP_COMPLETE");
      expect(run.sidecar).toBe("sentinel\n");
    } finally {
      rmSync(run.dir, { recursive: true, force: true });
    }
  });

  it("rejects a success draft with plus-bullet open items (+ [ ])", () => {
    const run = runGuard(
      baseSuccessDraft({
        findings: [
          {
            severity: "low",
            category: "clarity",
            claim_quote: "plus bullet open item",
            location: "docs/handoff.md",
            suggested_fix: "+ [ ] still open via plus bullet",
            action: "wont_fix",
            disposition: {
              kind: "accepted_suppressed",
              source: "issue #745",
              scope: "this slice only",
              reason: "plus bullets count as open checklist items",
              boundedReopen: "reopen if plus-bullet form is no longer recognized",
            },
          },
        ],
      }),
    );

    try {
      expect(run.status).toBe(1);
      expect(run.stdout).not.toContain("CMR_STEP_COMPLETE");
      expect(run.sidecar).toBe("sentinel\n");
    } finally {
      rmSync(run.dir, { recursive: true, force: true });
    }
  });

  it("rejects numbered open checklist items (1. [ ] / 1) [ ])", () => {
    const run = runGuard(
      baseSuccessDraft({
        findings: [
          {
            severity: "low",
            category: "clarity",
            claim_quote: "numbered open items",
            location: "docs/handoff.md",
            suggested_fix: ["1. [ ] finish landing", "1) [ ] verify the guard"].join("\n"),
            action: "wont_fix",
            disposition: {
              kind: "accepted_suppressed",
              source: "issue #745",
              scope: "this slice only",
              reason: "numbered checklist items count as open work",
              boundedReopen: "reopen if a numbered item remains unchecked",
            },
          },
        ],
      }),
    );

    try {
      expect(run.status).toBe(1);
      expect(run.stdout).not.toContain("CMR_STEP_COMPLETE");
      expect(run.sidecar).toBe("sentinel\n");
    } finally {
      rmSync(run.dir, { recursive: true, force: true });
    }
  });

  it("keeps checklist-looking source quotes out of the close-guard scan", () => {
    const draft = baseSuccessDraft({
      findings: [
        {
          severity: "low",
          category: "clarity",
          claim_quote: ["source example:", "- [ ] this is quoted source text"].join("\n"),
          location: "docs/handoff.md",
          suggested_fix: "quote only; no remaining work",
          action: "wont_fix",
          disposition: {
            kind: "accepted_suppressed",
            source: "issue #745",
            scope: "this slice only",
            reason: "source quote is not a draft checklist",
            boundedReopen: "reopen if the finding becomes actionable work",
          },
        },
      ],
    });
    const run = runGuard(draft);

    try {
      expect(run.status).toBe(0);
      expect(run.stdout).toContain("CMR_STEP_COMPLETE");
      expect(JSON.parse(run.sidecar)).toEqual(draft);
    } finally {
      rmSync(run.dir, { recursive: true, force: true });
    }
  });

  it("keeps governance metadata fields out of the close-guard scan", () => {
    const draft = baseSuccessDraft({
      findings: [
        {
          severity: "low",
          category: "clarity",
          claim_quote: "governance metadata may quote a checklist",
          location: "orchestrator/image/bin/orchestrator-outcome-guard",
          suggested_fix: "no code change",
          action: "wont_fix",
          disposition_reason: "accepted because the quoted record says:\n- [ ] follow up later",
          disposition: {
            kind: "accepted_suppressed",
            source: "issue #745 review record",
            scope: "this slice only",
            reason: "the source rationale includes:\n- [ ] preserve the historical wording",
            boundedReopen: "reopen if:\n- [ ] the bounded condition changes",
            findingIdentity: "finding text:\n- [ ] exact identity is preserved",
          },
        },
      ],
    });
    const run = runGuard(draft);

    try {
      expect(run.status).toBe(0);
      expect(run.stdout).toContain("CMR_STEP_COMPLETE");
      expect(JSON.parse(run.sidecar)).toEqual(draft);
    } finally {
      rmSync(run.dir, { recursive: true, force: true });
    }
  });

  it("keeps nested skipped-leg governance reasons out of the close-guard scan", () => {
    const draft = baseSuccessDraft({
      skippedLegs: [
        {
          slug: "agy",
          reason: "quota unavailable; record the deferred work:\n- [ ] retry agy when quota refreshes",
        },
      ],
    });
    const run = runGuard(draft);

    try {
      expect(run.status).toBe(0);
      expect(run.stdout).toContain("CMR_STEP_COMPLETE");
      expect(JSON.parse(run.sidecar)).toEqual(draft);
    } finally {
      rmSync(run.dir, { recursive: true, force: true });
    }
  });

  it("keeps a line continuation out of the rejected checklist preview", () => {
    const run = runGuard(
      baseSuccessDraft({
        findings: [
          {
            severity: "low",
            category: "clarity",
            claim_quote: "open item with continuation",
            location: "docs/handoff.md",
            suggested_fix: ["- [ ]", "continuation text"].join("\n"),
            action: "wont_fix",
            disposition: {
              kind: "accepted_suppressed",
              source: "issue #745",
              scope: "this slice only",
              reason: "open item remains",
              boundedReopen: "reopen if the item is not completed",
            },
          },
        ],
      }),
    );

    try {
      expect(run.status).toBe(1);
      expect(run.stderr).toMatch(/- \[ \]/);
      expect(run.stderr).not.toContain("continuation text");
    } finally {
      rmSync(run.dir, { recursive: true, force: true });
    }
  });

  it("accepts a success draft whose checklist items are all closed ([x] / [~])", () => {
    const draft = baseSuccessDraft({
      findings: [
        {
          severity: "low",
          category: "clarity",
          claim_quote: "all checklist items closed",
          location: "docs/handoff.md",
          suggested_fix: ["closed ledger:", "- [x] verified done", "- [~] deferred: user approved"].join(
            "\n",
          ),
          action: "wont_fix",
          disposition: {
            kind: "accepted_suppressed",
            source: "user #745",
            scope: "this slice only",
            reason: "closed or deferred items are not open work",
            boundedReopen: "reopen if a deferred item is un-deferred without completion",
          },
        },
      ],
    });
    const run = runGuard(draft);

    try {
      expect(run.status).toBe(0);
      expect(run.stdout).toContain("CMR_STEP_COMPLETE");
      expect(JSON.parse(run.sidecar)).toEqual(draft);
    } finally {
      rmSync(run.dir, { recursive: true, force: true });
    }
  });

  it("does not reject a non-success (converged:false) draft that still has open checkboxes", () => {
    const draft = baseBlockingDraft({
      reason: ["not done yet:", "- [ ] remaining fix", "- [ ] second item"].join("\n"),
    });
    const run = runGuard(draft);

    try {
      expect(run.status).toBe(0);
      expect(run.stdout).toContain("CMR_STEP_COMPLETE");
      expect(JSON.parse(run.sidecar)).toEqual(draft);
    } finally {
      rmSync(run.dir, { recursive: true, force: true });
    }
  });

  it("does not reject an escalate draft that still has open checkboxes", () => {
    const draft = {
      escalate: {
        reason: "human decision needed",
        diagnosis: ["blocked on:", "- [ ] decide disposition of deferred finding"].join("\n"),
      },
    };
    const run = runGuard(draft);

    try {
      expect(run.status).toBe(0);
      expect(run.stdout).toContain("CMR_STEP_COMPLETE");
      expect(JSON.parse(run.sidecar)).toEqual(draft);
    } finally {
      rmSync(run.dir, { recursive: true, force: true });
    }
  });

  it("accepts a clean success draft with no checklist text at all", () => {
    const draft = baseSuccessDraft();
    const dir = mkdtempSync(join(tmpdir(), "close-guard-745-clean-"));
    try {
      mkdirSync(join(dir, "cmr"), { recursive: true });
      writeFileSync(join(dir, "cmr", "review.json"), '{"ok":true}\n', "utf8");
      const draftPath = join(dir, "draft.json");
      const sidecarPath = join(dir, "outcome.json");
      writeFileSync(draftPath, JSON.stringify(draft), "utf8");
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

      expect(JSON.parse(readFileSync(sidecarPath, "utf8"))).toEqual(draft);
      expect(stdout).toContain("CMR_STEP_COMPLETE");
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});
