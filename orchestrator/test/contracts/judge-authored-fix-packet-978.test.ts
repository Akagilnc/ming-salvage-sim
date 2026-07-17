/**
 * #978 / ADR 0138 — 判词即包: judge continue authors the coder-fix packet body;
 * runner transports it verbatim; bare findings packing path is deleted.
 *
 * Seams:
 * 1. Continue schema requires non-empty `fixPacketBody` (traffic)
 * 2. Pure requireFixPacketBody — verbatim / loud empty
 * 3. Landing write carries body only (no blockingFindings pack)
 * 4. Residual dual-path ban: source scan for bare findings pack sites
 */

import { describe, expect, it } from "vitest";
import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { readFileSync as readRepoFileSync } from "node:fs";
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";

import {
  legacyDispatchWorker,
} from "../../src/dispatchWorker.js";
import {
  judgeResultFromVerdict,
  requireFixPacketBody,
} from "../../src/judgeStation.js";
import {
  decodeJudgeVerdict,
  encodeJudgeVerdict,
  type JudgeVerdict,
} from "../../src/stationReceiptContracts.js";
import type {
  Backend,
  Finding,
  WorkerSpec,
  WorktreeHandle,
} from "../../src/types.js";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "../..");

const SAMPLE_BODY =
  "live: correctness|src/x.ts:1|claim\n" +
  "authority: ADR 0131 runner zero judgment\n" +
  "boundary: assigned family only; delete dual pack path";

describe("#978 ADR 0138 judge-authored fix packet", () => {
  it("continue schema requires non-empty fixPacketBody (positive)", () => {
    const verdict: JudgeVerdict = {
      station: "judge",
      status: "continue",
      findingDispositions: [
        { identityKey: "correctness|src/x.ts:1|claim", action: "live" },
      ],
      fixPacketBody: SAMPLE_BODY,
    };
    const encoded = encodeJudgeVerdict(verdict);
    const decoded = decodeJudgeVerdict(encoded);
    expect(decoded).toEqual({ ok: true, value: verdict });
  });

  it("continue schema rejects missing fixPacketBody (negative)", () => {
    const parsed = decodeJudgeVerdict({
      station: "judge",
      status: "continue",
      findingDispositions: [
        { identityKey: "correctness|src/x.ts:1|claim", action: "live" },
      ],
    });
    expect(parsed.ok).toBe(false);
    if (!parsed.ok) {
      expect(parsed.reason).toMatch(/fixPacketBody/i);
    }
  });

  it("continue schema rejects empty / whitespace fixPacketBody (negative)", () => {
    for (const body of ["", "   ", "\n\t"]) {
      const parsed = decodeJudgeVerdict({
        station: "judge",
        status: "continue",
        findingDispositions: [],
        fixPacketBody: body,
      });
      expect(parsed.ok).toBe(false);
      if (!parsed.ok) {
        expect(parsed.reason).toMatch(/fixPacketBody/i);
      }
    }
  });

  it("requireFixPacketBody returns body verbatim (positive)", () => {
    const body = "  keep leading and trailing  \nline2";
    expect(
      requireFixPacketBody({ status: "continue", fixPacketBody: body }),
    ).toBe(body);
  });

  it("requireFixPacketBody fails loud on missing/empty (negative)", () => {
    expect(() =>
      requireFixPacketBody({ status: "continue" }),
    ).toThrow(/fixPacketBody/i);
    expect(() =>
      requireFixPacketBody({ status: "continue", fixPacketBody: "" }),
    ).toThrow(/empty|fixPacketBody/i);
    expect(() =>
      requireFixPacketBody({ status: "continue", fixPacketBody: "   " }),
    ).toThrow(/empty|fixPacketBody/i);
    expect(() =>
      requireFixPacketBody({ status: "converged", fixPacketBody: SAMPLE_BODY }),
    ).toThrow(/continue/i);
  });

  it("judgeResultFromVerdict maps fixPacketBody onto continue output", () => {
    const result = judgeResultFromVerdict(
      {
        station: "judge",
        status: "continue",
        findingDispositions: [
          { identityKey: "correctness|src/x.ts:1|claim", action: "live" },
        ],
        fixPacketBody: SAMPLE_BODY,
      },
      [],
    );
    expect(result).toMatchObject({
      kind: "judge",
      status: "continue",
      fixPacketBody: SAMPLE_BODY,
    });
  });

  it("S5 landing packet body is byte-identical to judge fixPacketBody (contract)", async () => {
    const worktree: WorktreeHandle = {
      branch: "feat/978",
      base: "main",
      path: mkdtempSync(join(tmpdir(), "978-fix-packet-")),
    };
    const stateDir = mkdtempSync(join(tmpdir(), "978-fix-packet-ledger-"));
    let observedLanding: unknown;
    const finding: Finding = {
      severity: "high",
      category: "correctness",
      claim_quote: "should not appear as packed content",
      location: "src/x.ts:1",
      suggested_fix: "do not pack bare rows",
      action: "fix_now",
    };
    const backend: Backend = {
      async smokeModelRoute(route) {
        return route;
      },
      async findResumeState() {
        return undefined;
      },
      async resumeSession() {
        throw new Error("not expected");
      },
      async fetchIssueMeta() {
        throw new Error("not expected");
      },
      async prepareWorktree() {
        throw new Error("not expected");
      },
      async runStep() {
        observedLanding = JSON.parse(
          readFileSync(join(stateDir, "fix-findings.json"), "utf8"),
        );
        return { kind: "coder", committed: true, commitsAdded: 1 };
      },
      async writeLedger() {},
    };
    const spec: WorkerSpec = {
      id: "S5",
      kind: "coder",
      role: "coder",
      host: "codex",
      session: "fresh",
      contextRetention: "retain",
      skill: "/tdd",
      promptFile: "coder_fix.md",
      maxIter: 1,
      model: "gpt-5.6-sol",
      soul: "coder",
      toolchain: [],
    };

    try {
      const result = await legacyDispatchWorker(
        backend,
        spec,
        {
          worktree,
          stateDir,
          blockingFindingIdentityKeys: ["correctness|src/x.ts:1|claim"],
          blockingFindingCount: 1,
        },
        {
          // If dual path survived, findings would be packed instead of / as well as body.
          fixPacketBody: SAMPLE_BODY,
          blockingFindings: [finding],
        },
      );
      expect(result.kind).toBe("completed");
      expect(observedLanding).toEqual({
        fixPacketBody: SAMPLE_BODY,
        blockingFindingIdentityKeys: ["correctness|src/x.ts:1|claim"],
      });
      // Explicit dual-path ban: bare findings rows must not appear on the packet.
      expect(
        (observedLanding as { blockingFindings?: unknown }).blockingFindings,
      ).toBeUndefined();
      // Verbatim identity (including any internal newlines / spacing).
      expect(
        (observedLanding as { fixPacketBody: string }).fixPacketBody,
      ).toBe(SAMPLE_BODY);
    } finally {
      rmSync(worktree.path, { recursive: true, force: true });
      rmSync(stateDir, { recursive: true, force: true });
    }
  });

  it("S5 landing without fixPacketBody does not resurrect bare findings packing", async () => {
    const worktree: WorktreeHandle = {
      branch: "feat/978-empty",
      base: "main",
      path: mkdtempSync(join(tmpdir(), "978-empty-packet-")),
    };
    const stateDir = mkdtempSync(join(tmpdir(), "978-empty-packet-ledger-"));
    let observedLanding: unknown;
    const finding: Finding = {
      severity: "high",
      category: "correctness",
      claim_quote: "must not become packet body",
      location: "src/y.ts:1",
      suggested_fix: "gone",
      action: "fix_now",
    };
    const backend: Backend = {
      async smokeModelRoute(route) {
        return route;
      },
      async findResumeState() {
        return undefined;
      },
      async resumeSession() {
        throw new Error("not expected");
      },
      async fetchIssueMeta() {
        throw new Error("not expected");
      },
      async prepareWorktree() {
        throw new Error("not expected");
      },
      async runStep() {
        observedLanding = JSON.parse(
          readFileSync(join(stateDir, "fix-findings.json"), "utf8"),
        );
        return { kind: "coder", committed: true, commitsAdded: 1 };
      },
      async writeLedger() {},
    };
    const spec: WorkerSpec = {
      id: "S5",
      kind: "coder",
      role: "coder",
      host: "codex",
      session: "fresh",
      contextRetention: "retain",
      skill: "/tdd",
      promptFile: "coder_fix.md",
      maxIter: 1,
      model: "gpt-5.6-sol",
      soul: "coder",
      toolchain: [],
    };

    try {
      await legacyDispatchWorker(
        backend,
        spec,
        {
          worktree,
          stateDir,
          blockingFindingIdentityKeys: ["correctness|src/y.ts:1|must not become packet body"],
          blockingFindingCount: 1,
        },
        { blockingFindings: [finding] },
      );
      expect(observedLanding).toEqual({
        blockingFindingIdentityKeys: [
          "correctness|src/y.ts:1|must not become packet body",
        ],
      });
      expect(
        (observedLanding as { blockingFindings?: unknown }).blockingFindings,
      ).toBeUndefined();
      expect(
        (observedLanding as { fixPacketBody?: unknown }).fixPacketBody,
      ).toBeUndefined();
    } finally {
      rmSync(worktree.path, { recursive: true, force: true });
      rmSync(stateDir, { recursive: true, force: true });
    }
  });

  it("source ban: writeFixFindings / family fix landing do not pack blockingFindings rows", () => {
    // Residual dual-path ban — if someone reintroduces
    // `blockingFindings: landing?.blockingFindings ?? []` the contract fails.
    const dispatchSrc = readRepoFileSync(
      join(ROOT, "src/dispatchWorker.ts"),
      "utf8",
    );
    const familySrc = readRepoFileSync(
      join(ROOT, "src/family/realFamilyBackend.ts"),
      "utf8",
    );
    expect(dispatchSrc).not.toMatch(
      /blockingFindings:\s*findingsRows|blockingFindings:\s*landing\?\.blockingFindings/,
    );
    expect(familySrc).not.toMatch(
      /blockingFindings:\s*landing\?\.blockingFindings\s*\?\?\s*\[\]/,
    );
    // Positive: both writers must materialise fixPacketBody.
    expect(dispatchSrc).toMatch(/fixPacketBody/);
    expect(familySrc).toMatch(/fixPacketBody/);
    // Smoke that ADR file exists on main copy optional — production code is the proof.
    expect(existsSync(join(ROOT, "src/judgeStation.ts"))).toBe(true);
  });
});
