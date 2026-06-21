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
  buildFamilyEpic,
  cutFamilyBase,
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
  const realSh: Sh = (file, args) => execFileSync(file, args, { encoding: "utf8" }).trim();

  it("cuts the LOCAL family base from origin/main and returns its start head", () => {
    const clone = makeClone();
    const head = cutFamilyBase(clone, "family/291-base", realSh);
    expect(head).toBe(git(clone, "rev-parse", "origin/main"));
    // the local branch exists now.
    expect(git(clone, "rev-parse", "family/291-base")).toBe(head);
  });

  it("is idempotent on resume: an existing family base is reused (its current head)", () => {
    const clone = makeClone();
    const first = cutFamilyBase(clone, "family/291-base", realSh);
    // advance the family base with a commit (a prior wave's merge).
    git(clone, "checkout", "-q", "family/291-base");
    execFileSync("git", ["commit", "--allow-empty", "-q", "-m", "wave1"], { cwd: clone });
    const advanced = git(clone, "rev-parse", "family/291-base");
    expect(advanced).not.toBe(first);
    // a second cut REUSES the branch and returns its CURRENT (advanced) head — it
    // does NOT re-cut from main (no lost waves).
    expect(cutFamilyBase(clone, "family/291-base", realSh)).toBe(advanced);
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
