/**
 * #978 / ADR 0138 — 判词即包: judge continue authors the coder-fix packet body;
 * runner transports it verbatim; bare findings packing path is deleted.
 *
 * Seams:
 * 1. Continue schema requires non-empty `fixPacketBody` (traffic; non-transforming)
 * 2. Pure requireFixPacketBody — verbatim / loud empty
 * 3. Landing write carries body only (no blockingFindings pack); open set without
 *    body fails loud via shared materializeLandingFixPacketBody
 * 4. Residual dual-path ban: source scan for bare findings pack sites
 * 5. Souls + ADR authority path present
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
  materializeLandingFixPacketBody,
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
const REPO_ROOT = join(ROOT, "..");

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

  it("continue schema preserves leading/trailing whitespace verbatim (P1)", () => {
    // nonEmptyString.trim() would rewrite; fixPacketBody must not.
    const body = "  keep leading and trailing  \nline2";
    const verdict: JudgeVerdict = {
      station: "judge",
      status: "continue",
      findingDispositions: [
        { identityKey: "correctness|src/x.ts:1|claim", action: "live" },
      ],
      fixPacketBody: body,
    };
    const decoded = decodeJudgeVerdict(encodeJudgeVerdict(verdict));
    expect(decoded.ok).toBe(true);
    if (decoded.ok) {
      expect(decoded.value).toMatchObject({ fixPacketBody: body });
      expect(
        (decoded.value as { fixPacketBody: string }).fixPacketBody,
      ).toBe(body);
    }
    // Direct decode path (SO / raw) also non-transforming.
    const raw = decodeJudgeVerdict({
      station: "judge",
      status: "continue",
      findingDispositions: [
        { identityKey: "correctness|src/x.ts:1|claim", action: "live" },
      ],
      fixPacketBody: body,
    });
    expect(raw.ok).toBe(true);
    if (raw.ok) {
      expect((raw.value as { fixPacketBody: string }).fixPacketBody).toBe(body);
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

  it("materializeLandingFixPacketBody is shared fail-loud helper (S3)", () => {
    // Verbatim when present.
    expect(
      materializeLandingFixPacketBody({
        fixPacketBody: "  body with spaces  ",
        blockingFindingIdentityKeys: ["k1"],
      }),
    ).toBe("  body with spaces  ");

    // Open set without body → fail loud (no soft-omit).
    expect(() =>
      materializeLandingFixPacketBody({
        blockingFindingIdentityKeys: ["k1"],
      }),
    ).toThrow(/fixPacketBody|open set|ADR 0138/i);
    expect(() =>
      materializeLandingFixPacketBody({
        fixPacketBody: "   ",
        blockingFindingCount: 1,
      }),
    ).toThrow(/fixPacketBody|open set|ADR 0138/i);

    // Raw-only / empty open set without body → omit (allowed).
    expect(
      materializeLandingFixPacketBody({
        blockingFindingIdentityKeys: [],
        blockingFindingCount: 0,
      }),
    ).toBeUndefined();
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

  it("S5 landing with open set and no fixPacketBody fails loud (S3)", async () => {
    const worktree: WorktreeHandle = {
      branch: "feat/978-empty",
      base: "main",
      path: mkdtempSync(join(tmpdir(), "978-empty-packet-")),
    };
    const stateDir = mkdtempSync(join(tmpdir(), "978-empty-packet-ledger-"));
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
        throw new Error("runStep must not be reached when landing lacks body");
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
      await expect(
        legacyDispatchWorker(
          backend,
          spec,
          {
            worktree,
            stateDir,
            blockingFindingIdentityKeys: [
              "correctness|src/y.ts:1|must not become packet body",
            ],
            blockingFindingCount: 1,
          },
          { blockingFindings: [finding] },
        ),
      ).rejects.toThrow(/fixPacketBody|open set|ADR 0138/i);
    } finally {
      rmSync(worktree.path, { recursive: true, force: true });
      rmSync(stateDir, { recursive: true, force: true });
    }
  });

  it("S5 raw-only landing (no open set) omits body without resurrecting bare findings", async () => {
    const worktree: WorktreeHandle = {
      branch: "feat/978-raw-only",
      base: "main",
      path: mkdtempSync(join(tmpdir(), "978-raw-only-")),
    };
    const stateDir = mkdtempSync(join(tmpdir(), "978-raw-only-ledger-"));
    let observedLanding: unknown;
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
          blockingFindingIdentityKeys: [],
          blockingFindingCount: 0,
        },
        { blockingFindings: [] },
      );
      expect(observedLanding).toEqual({
        blockingFindingIdentityKeys: [],
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

  it("source ban: dual landing writers share helper; no bare findings pack reintro", () => {
    const dispatchSrc = readRepoFileSync(
      join(ROOT, "src/dispatchWorker.ts"),
      "utf8",
    );
    const familySrc = readRepoFileSync(
      join(ROOT, "src/family/realFamilyBackend.ts"),
      "utf8",
    );
    const dogfoodSrc = readRepoFileSync(
      join(ROOT, "src/dogfoodReplay.ts"),
      "utf8",
    );
    const fixerSoul = readRepoFileSync(
      join(ROOT, "image/souls/fixer.md"),
      "utf8",
    );

    // Strengthened dual-path ban (nit): any landing assignment of bare findings
    // rows as packet content, or soft invent of empty body at projection.
    expect(dispatchSrc).not.toMatch(
      /blockingFindings\s*:\s*(findingsRows|landing\?\.blockingFindings|\[\s*\])/,
    );
    expect(dispatchSrc).not.toMatch(
      /landing\?\.blockingFindings\s*\?\?\s*\[\]/,
    );
    expect(familySrc).not.toMatch(
      /blockingFindings\s*:\s*(findingsRows|landing\?\.blockingFindings|\[\s*\])/,
    );
    expect(familySrc).not.toMatch(
      /landing\?\.blockingFindings\s*\?\?\s*\[\]/,
    );
    // S2: never invent empty string for missing fixPacketBody.
    expect(familySrc).not.toMatch(
      /fixPacketBody\s*:\s*(?:typeof[^?\n]*\?\s*[^:\n]*:\s*[\"'][\"']|[\"'][\"'])/,
    );
    // S3: both writers must call the shared helper (not dual soft-omit clones).
    expect(dispatchSrc).toMatch(/materializeLandingFixPacketBody/);
    expect(familySrc).toMatch(/materializeLandingFixPacketBody/);
    // Positive: both writers materialise fixPacketBody.
    expect(dispatchSrc).toMatch(/fixPacketBody/);
    expect(familySrc).toMatch(/fixPacketBody/);

    // Dogfood: no findings→body mint inside judge continue helper.
    expect(dogfoodSrc).not.toMatch(
      /findings\s*\.\s*map\s*\([\s\S]{0,120}claim_quote[\s\S]{0,80}\.join/,
    );
    expect(dogfoodSrc).toMatch(
      /requires explicit non-empty fixPacketBody/,
    );

    // S1: fixer soul teaches sole content = landing fixPacketBody verbatim.
    expect(fixerSoul).toMatch(/fixPacketBody/);
    expect(fixerSoul).toMatch(/ADR 0138|0138/);
    expect(fixerSoul).toMatch(/原样|verbatim|逐字/);

    // P2: ADR authority path present in worktree.
    expect(
      existsSync(join(REPO_ROOT, "docs/adr/0138-judge-authored-fix-packet.md")),
    ).toBe(true);
  });
});
