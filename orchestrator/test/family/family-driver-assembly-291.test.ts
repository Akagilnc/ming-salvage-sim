/**
 * #291 Unit B — the family DRIVER's pure assembly pieces (no container, no live
 * GitHub): epic-read from `gh`, FamilyEpic build, local family-base cut.
 *
 *   - parseSubIssueNumbers: extract child issue NUMBERS from `gh … --json subIssues`.
 *   - buildFamilyEpic:      compose the FamilyEpic from children + blocked_by edges.
 *   - readFamilyEpic:       the gh-read end-to-end with an injected `sh`.
 *   - cutFamilyBase:        the LOCAL family-base cut on a real temp clone +
 *                           idempotent resume reuse.
 *   - runIntegratedCmr TODO-seam: the RealFamilyBackend's default throws (the real
 *     `ak-cross-m-review` form is the main orchestrator's decision — documented).
 */

import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));
const realPromptsDir = join(here, "..", "..", "prompts");

import {
  assertExternalBlockersCleared,
  buildFamilyEpic,
  cutFamilyBase,
  FamilyExternalBlockerError,
  parseSubIssueNumbers,
  readFamilyEpic,
  type Sh,
} from "../../src/familyDriver.js";
import { RealFamilyBackend } from "../../src/family/realFamilyBackend.js";
import type { GhBlockedBy } from "../../src/realBackend.js";

function git(cwd: string, ...args: string[]): string {
  return execFileSync("git", args, { cwd, encoding: "utf8" }).trim();
}
const cleanups: string[] = [];
afterEach(() => {
  while (cleanups.length > 0) {
    const p = cleanups.pop();
    if (p !== undefined) rmSync(p, { recursive: true, force: true });
  }
});

describe("#291 parseSubIssueNumbers", () => {
  it("reads child numbers from the {subIssues:{nodes,totalCount}} object", () => {
    const parsed = { subIssues: { nodes: [{ number: 11 }, { number: 12 }], totalCount: 2 } };
    expect(parseSubIssueNumbers(parsed)).toEqual([11, 12]);
  });
  it("de-dupes (first-seen order) and skips non-numeric / odd shapes", () => {
    const parsed = {
      subIssues: { nodes: [{ number: 11 }, { number: 11 }, { foo: 1 }, { number: 13 }] },
    };
    expect(parseSubIssueNumbers(parsed)).toEqual([11, 13]);
  });
  it("returns [] for a missing / non-object subIssues (never throws)", () => {
    expect(parseSubIssueNumbers({})).toEqual([]);
    expect(parseSubIssueNumbers({ subIssues: null })).toEqual([]);
    expect(parseSubIssueNumbers({ subIssues: { nodes: "nope" } })).toEqual([]);
  });
});

describe("#291 buildFamilyEpic", () => {
  it("maps children + blocked_by edges into the FamilyEpic", () => {
    const blockedBy = new Map<number, GhBlockedBy[]>([
      [11, []],
      [12, [{ number: 11, state: "open" }]],
    ]);
    const epic = buildFamilyEpic(291, [11, 12], blockedBy);
    expect(epic).toEqual({
      issue: 291,
      children: [
        { issue: 11, blockedBy: [] },
        { issue: 12, blockedBy: [11] },
      ],
    });
  });
  it("a child with no blocked_by entry gets an empty blockedBy", () => {
    const epic = buildFamilyEpic(291, [11], new Map());
    expect(epic.children).toEqual([{ issue: 11, blockedBy: [] }]);
  });
});

describe("#291 assertExternalBlockersCleared — family-admission external-blocker gate (online R1 #1; user 2026-06-22, ADR 0022 dec6③)", () => {
  // An EXTERNAL blocked_by (an issue NOT among this epic's children) is never merged
  // into the family ledger, so the scheduler cannot clear it. Rather than leaning on
  // each child's family-mode S0 (which dec6③ rewired to a ledger-merged criterion, so
  // it does NOT reliably reject an open external blocker), validate them EXPLICITLY at
  // admission against the live GitHub `state`: any external blocker still open fails
  // the WHOLE family run up front, with the concrete offending list.
  it("throws FamilyExternalBlockerError with the concrete list when an external blocker is still OPEN", () => {
    const blockedBy = new Map<number, GhBlockedBy[]>([
      [11, []],
      [12, [{ number: 11, state: "open" }, { number: 999, state: "open" }]], // 11 intra-family, 999 external+open
    ]);
    let err: unknown;
    try {
      assertExternalBlockersCleared([11, 12], blockedBy);
    } catch (e) {
      err = e;
    }
    expect(err).toBeInstanceOf(FamilyExternalBlockerError);
    expect((err as FamilyExternalBlockerError).openBlockers).toEqual([{ child: 12, blocker: 999 }]);
    // the message names the concrete child + external issue so the rejection is actionable
    expect((err as Error).message).toContain("#12");
    expect((err as Error).message).toContain("#999");
  });
  it("a CLOSED external blocker is satisfied ⇒ no throw (the child may schedule)", () => {
    const blockedBy = new Map<number, GhBlockedBy[]>([
      [12, [{ number: 999, state: "closed" }]],
    ]);
    expect(() => assertExternalBlockersCleared([11, 12], blockedBy)).not.toThrow();
  });
  it("an INTRA-family blocker (even open) is NOT an external blocker ⇒ no throw (the scheduler clears it)", () => {
    const blockedBy = new Map<number, GhBlockedBy[]>([
      [12, [{ number: 11, state: "open" }]], // 11 IS a family child
    ]);
    expect(() => assertExternalBlockersCleared([11, 12], blockedBy)).not.toThrow();
  });
  it("no blocked_by at all ⇒ no throw", () => {
    expect(() => assertExternalBlockersCleared([11, 12], new Map())).not.toThrow();
  });
  it("collects EVERY open external blocker across children (the list is complete, not first-only)", () => {
    const blockedBy = new Map<number, GhBlockedBy[]>([
      [11, [{ number: 900, state: "open" }]],
      [12, [{ number: 901, state: "open" }, { number: 11, state: "open" }]],
    ]);
    let err: FamilyExternalBlockerError | undefined;
    try {
      assertExternalBlockersCleared([11, 12], blockedBy);
    } catch (e) {
      err = e as FamilyExternalBlockerError;
    }
    expect(err?.openBlockers).toEqual([
      { child: 11, blocker: 900 },
      { child: 12, blocker: 901 },
    ]);
  });
});

describe("#291 readFamilyEpic (injected gh sh)", () => {
  it("reads sub-issues + each child's blocked_by and builds the epic", () => {
    const sh: Sh = (file, args) => {
      expect(file).toBe("gh");
      if (args[0] === "issue") {
        return JSON.stringify({ subIssues: { nodes: [{ number: 11 }, { number: 12 }] } });
      }
      // gh api repos/.../issues/<n>/dependencies/blocked_by
      const n = Number(/issues\/(\d+)\//.exec(args[1] ?? "")?.[1]);
      return n === 12 ? JSON.stringify([{ number: 11, state: "open" }]) : "[]";
    };
    const epic = readFamilyEpic(291, "Akagilnc/ming-salvage-sim", sh);
    expect(epic).toEqual({
      issue: 291,
      children: [
        { issue: 11, blockedBy: [] },
        { issue: 12, blockedBy: [11] },
      ],
    });
  });
});

describe("#291 cutFamilyBase (real local clone)", () => {
  function makeClone(): string {
    const src = mkdtempSync(join(tmpdir(), "cfb-src-"));
    cleanups.push(src);
    git(src, "init", "-q", "-b", "main");
    git(src, "config", "user.email", "t@t.t");
    git(src, "config", "user.name", "t");
    execFileSync("git", ["commit", "--allow-empty", "-q", "-m", "root"], { cwd: src });
    const clone = mkdtempSync(join(tmpdir(), "cfb-clone-"));
    cleanups.push(clone);
    const dir = join(clone, "repo");
    git(clone, "clone", "-q", src, dir);
    return dir;
  }
  function makeLedgerDir(): string {
    const d = mkdtempSync(join(tmpdir(), "cfb-ledger-"));
    cleanups.push(d);
    return d;
  }
  const realSh: Sh = (file, args) => execFileSync(file, args, { encoding: "utf8" }).trim();

  it("cuts the LOCAL family base from origin/main and returns its start head", () => {
    const clone = makeClone();
    const head = cutFamilyBase(clone, "family/291-base", "main", realSh, makeLedgerDir());
    expect(head).toBe(git(clone, "rev-parse", "origin/main"));
    // the local branch exists now.
    expect(git(clone, "rev-parse", "family/291-base")).toBe(head);
  });

  it("persists the cut SHA so resume returns the ORIGINAL start head, NOT the advanced HEAD (cmr R2 #2)", () => {
    // cmr R2 #2: the empty-ledger crash-window net (reconcile.ts) compares the live
    // family head to the recorded START head; if cutFamilyBase returned the CURRENT
    // (advanced) HEAD on resume, `liveHead === startHead` trivially → the net is
    // silently disabled (fail-OPEN). The cut SHA must be PERSISTED at first cut and
    // re-READ on resume, so the start head stays the divergence point even after the
    // base has accumulated merges.
    const clone = makeClone();
    const ledgerDir = makeLedgerDir();
    const first = cutFamilyBase(clone, "family/291-base", "main", realSh, ledgerDir);
    // advance the family base with a commit (a prior wave's merge).
    git(clone, "checkout", "-q", "family/291-base");
    execFileSync("git", ["commit", "--allow-empty", "-q", "-m", "wave1"], { cwd: clone });
    const advanced = git(clone, "rev-parse", "family/291-base");
    expect(advanced).not.toBe(first);
    // a second cut REUSES the branch (no re-cut, no lost waves) but returns the
    // PERSISTED ORIGINAL start head — NOT the advanced HEAD.
    const resumed = cutFamilyBase(clone, "family/291-base", "main", realSh, ledgerDir);
    expect(resumed).toBe(first);
    expect(resumed).not.toBe(advanced);
  });

  it("fails CLOSED on resume when the persisted start head is missing/unreadable (no fall-back to live HEAD)", () => {
    // If the branch already exists (resume) but the persisted start-head file is
    // gone (manual deletion / corruption), cutFamilyBase must NOT silently fall back
    // to the live HEAD (which defeats the crash-window net) — it must throw so the
    // caller fails closed.
    const clone = makeClone();
    const ledgerDir = makeLedgerDir(); // empty: branch will exist but no persisted head
    // Create the branch WITHOUT going through cutFamilyBase (simulate a stale resume
    // where the branch survives but the persisted start head does not).
    git(clone, "branch", "family/291-base", "origin/main");
    expect(() => cutFamilyBase(clone, "family/291-base", "main", realSh, ledgerDir)).toThrow(
      /start head|persist|fail.?closed/i,
    );
  });

  it("cuts from the CONFIGURED base (not hardcoded main) when the PR target differs", () => {
    // agy R1: the driver advertises a configurable target base (options.base), but a
    // hardcoded "main" would cut the family base off the WRONG branch when the PR
    // targets e.g. "develop" — and familyBaseDiff (`base...familyBase`) would then
    // emit a wrong/polluted diff. Prove the cut honors the passed base.
    const src = mkdtempSync(join(tmpdir(), "cfb-dev-src-"));
    cleanups.push(src);
    git(src, "init", "-q", "-b", "main");
    git(src, "config", "user.email", "t@t.t");
    git(src, "config", "user.name", "t");
    execFileSync("git", ["commit", "--allow-empty", "-q", "-m", "root"], { cwd: src });
    // A "develop" branch that DIVERGES from main (a unique commit), so cutting from
    // the wrong branch is observable (different head than origin/main).
    git(src, "checkout", "-q", "-b", "develop");
    execFileSync("git", ["commit", "--allow-empty", "-q", "-m", "develop-only"], { cwd: src });
    git(src, "checkout", "-q", "main");
    const clone = mkdtempSync(join(tmpdir(), "cfb-dev-clone-"));
    cleanups.push(clone);
    const dir = join(clone, "repo");
    git(clone, "clone", "-q", src, dir);

    const head = cutFamilyBase(dir, "family/291-base", "develop", realSh, makeLedgerDir());
    // The family base head is origin/develop's head, NOT origin/main's.
    expect(head).toBe(git(dir, "rev-parse", "origin/develop"));
    expect(head).not.toBe(git(dir, "rev-parse", "origin/main"));
  });
});

describe("#291 runIntegratedCmr TODO-seam", () => {
  it("the RealFamilyBackend's default runIntegratedCmr throws (real ak-cross-m-review form is the orchestrator's decision)", async () => {
    const repo = mkdtempSync(join(tmpdir(), "cmr-seam-"));
    cleanups.push(repo);
    git(repo, "init", "-q");
    const b = new RealFamilyBackend({
      workingRepo: repo,
      familyBase: "family/291-base",
      ledgerDir: mkdtempSync(join(tmpdir(), "cmr-ledger-")),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      imageName: "img",
      skillsMount: "/tmp/skills",
    });
    await expect(b.runIntegratedCmr({ familyBase: "family/291-base" })).rejects.toThrow(
      /ak-cross-m-review|driver|manual-smoke/i,
    );
  });
});
