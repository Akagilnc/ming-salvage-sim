/**
 * #291 Unit B — the family DRIVER's pure assembly pieces (no container, no live
 * GitHub): epic-read from `gh`, FamilyEpic build, local family-base cut.
 *
 *   - buildFamilyEpic:      compose the FamilyEpic from children + blocked_by edges.
 *   - readFamilyEpic:       the gh-read end-to-end with an injected `sh`.
 *   - cutFamilyBase:        the LOCAL family-base cut on a real temp clone +
 *                           idempotent resume reuse.
 *   - runIntegratedCmr legacy seam: the RealFamilyBackend's per-method default
 *     throws — #335 routes the real `ak-cross-m-review` as the CONTAINER cmr
 *     WORKER via `dispatchWorker`, so the legacy per-method path is a guarded
 *     bypass (a throw, never a silent fabricated pass).
 */

import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it, vi } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));
const realPromptsDir = join(here, "..", "..", "..", "prompts");
const realSoulsDir = join(here, "..", "..", "..", "image", "souls");

import {
  buildFamilyEpic,
  cutFamilyBase,
  discoverSubprojects,
  filterExternalBlockedChildren,
  FamilyRootBlockerError,
  inferVerifyCwd,
  parseSubIssueAdmission,
  readFamilyEpic,
  type Sh,
} from "../../../src/familyDriver.js";
import { RealFamilyBackend } from "../../../src/family/realFamilyBackend.js";
import type { GhBlockedBy } from "../../../src/realBackend.js";

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

// ─── #4: verifyCwd inference from the family diff ────────────────────────────
//
// The dogfood mis-verified orchestrator/ when the change was in web/. The driver
// now infers verifyCwd from the diff: the top-level subproject (a dir holding a
// package.json) the changed files land in. `subprojects` is the ordered list of
// such dirs (relative to the clone root; "" = root). Pure → unit-tested.

describe("#4 inferVerifyCwd (diff → verifyCwd)", () => {
  const root = "/clone/root";
  const subprojects = ["orchestrator", "web"]; // top-level package.json dirs

  it("picks the subproject the changed files land in (web change → web)", () => {
    const changed = ["web/src/App.tsx", "web/tests/foo.test.ts"];
    expect(inferVerifyCwd(changed, subprojects, root)).toBe(join(root, "web"));
  });

  it("picks orchestrator when the change is in orchestrator/", () => {
    const changed = ["orchestrator/src/runner.ts"];
    expect(inferVerifyCwd(changed, subprojects, root)).toBe(join(root, "orchestrator"));
  });

  it("picks the subproject with the MOST changed files when several are touched", () => {
    // 1 orchestrator file vs 3 web files → web wins.
    const changed = [
      "orchestrator/src/x.ts",
      "web/a.ts",
      "web/b.ts",
      "web/c.ts",
    ];
    expect(inferVerifyCwd(changed, subprojects, root)).toBe(join(root, "web"));
  });

  it("returns undefined when no changed file maps to a known subproject (caller falls back to default)", () => {
    expect(inferVerifyCwd(["docs/README.md", "content/x.json"], subprojects, root)).toBeUndefined();
  });

  it("returns undefined for an empty diff (caller falls back to default)", () => {
    expect(inferVerifyCwd([], subprojects, root)).toBeUndefined();
  });
});

describe("#436 parseSubIssueAdmission", () => {
  it("returns admitted children plus visible skip reasons for full family admission", () => {
    const parsed = [
      { number: 341, state: "CLOSED", labels: [{ name: "ready-for-agent" }] },
      { number: 370, state: "OPEN", labels: [{ name: "enhancement" }] },
      {
        number: 378,
        state: "OPEN",
        labels: [{ name: "ready-for-agent" }],
        sub_issues_summary: { total: 2 },
      },
      { number: 99, state: "OPEN", labels: [{ name: "ready-for-agent" }] },
    ];

    expect(parseSubIssueAdmission(parsed)).toEqual({
      admitted: [99],
      skipped: [
        {
          issue: 341,
          reason: "closed",
          message: "family admission skipped child #341: issue is CLOSED",
        },
        {
          issue: 370,
          reason: "not_ready_for_agent",
          message: "family admission skipped child #370: missing ready-for-agent label",
        },
        {
          issue: 378,
          reason: "parent_issue",
          message: "family admission skipped child #378: issue is a parent issue",
        },
      ],
    });
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

describe("#934 filterExternalBlockedChildren — per-child visible filter (ID-002)", () => {
  // Ordinary external blockers only filter the affected child; siblings continue.
  it("filters a child with an OPEN external blocker and keeps runnable siblings", () => {
    const blockedBy = new Map<number, GhBlockedBy[]>([
      [11, []],
      [12, [{ number: 11, state: "open" }, { number: 999, state: "open" }]], // 11 intra-family, 999 external+open
    ]);
    const result = filterExternalBlockedChildren([11, 12], blockedBy);
    expect(result.runnable).toEqual([11]);
    expect(result.skipped).toEqual([
      {
        issue: 12,
        reason: "open_external_blocker",
        message: "family admission skipped child #12: open external blocker(s) #999",
      },
    ]);
    expect(result.openBlockers).toEqual([{ child: 12, blocker: 999 }]);
  });
  it("a CLOSED external blocker is satisfied ⇒ child remains runnable", () => {
    const blockedBy = new Map<number, GhBlockedBy[]>([
      [12, [{ number: 999, state: "closed" }]],
    ]);
    const result = filterExternalBlockedChildren([11, 12], blockedBy);
    expect(result.runnable).toEqual([11, 12]);
    expect(result.skipped).toEqual([]);
  });
  it("an INTRA-family blocker (even open) is NOT an external blocker ⇒ runnable", () => {
    const blockedBy = new Map<number, GhBlockedBy[]>([
      [12, [{ number: 11, state: "open" }]], // 11 IS a family child
    ]);
    const result = filterExternalBlockedChildren([11, 12], blockedBy);
    expect(result.runnable).toEqual([11, 12]);
    expect(result.skipped).toEqual([]);
  });
  it("no blocked_by at all ⇒ all runnable", () => {
    const result = filterExternalBlockedChildren([11, 12], new Map());
    expect(result.runnable).toEqual([11, 12]);
    expect(result.skipped).toEqual([]);
  });
  it("collects EVERY open external blocker across children (list is complete)", () => {
    const blockedBy = new Map<number, GhBlockedBy[]>([
      [11, [{ number: 900, state: "open" }]],
      [12, [{ number: 901, state: "open" }, { number: 11, state: "open" }]],
    ]);
    const result = filterExternalBlockedChildren([11, 12], blockedBy);
    expect(result.runnable).toEqual([]);
    expect(result.openBlockers).toEqual([
      { child: 11, blocker: 900 },
      { child: 12, blocker: 901 },
    ]);
    expect(result.skipped.map((s) => s.issue)).toEqual([11, 12]);
  });
});

describe("#934 parseSubIssueAdmission schema fail-closed (ID-003)", () => {
  it("throws on non-array / malformed sub_issues payloads (never soft-empty)", () => {
    expect(() => parseSubIssueAdmission({ unexpected: [] })).toThrow(/sub_issues schema error/);
    expect(() => parseSubIssueAdmission(null)).toThrow(/sub_issues schema error/);
    expect(() => parseSubIssueAdmission("weird")).toThrow(/sub_issues schema error/);
    expect(() => parseSubIssueAdmission({ subIssues: { nodes: "x" } })).toThrow(
      /sub_issues schema error/,
    );
  });
  it("accepts a valid GraphQL-shaped {subIssues.nodes} payload", () => {
    expect(
      parseSubIssueAdmission({
        subIssues: {
          nodes: [{ number: 99, state: "OPEN", labels: [{ name: "ready-for-agent" }] }],
        },
      }),
    ).toEqual({ admitted: [99], skipped: [] });
  });
  it("throws on missing/non-finite number entries (never soft-skip into all-filtered)", () => {
    expect(() =>
      parseSubIssueAdmission([
        { number: 10, state: "OPEN", labels: [{ name: "ready-for-agent" }] },
        { state: "OPEN", labels: [{ name: "ready-for-agent" }] },
      ]),
    ).toThrow(/sub_issues entry schema error|missing or non-finite number/i);
    expect(() =>
      parseSubIssueAdmission([{ number: "12", state: "OPEN" }]),
    ).toThrow(/sub_issues entry schema error|missing or non-finite number/i);
    expect(() =>
      parseSubIssueAdmission([{ number: Number.NaN, state: "OPEN" }]),
    ).toThrow(/sub_issues entry schema error|missing or non-finite number/i);
    expect(() => parseSubIssueAdmission([null, { number: 1, state: "OPEN" }])).toThrow(
      /sub_issues entry schema error|expected object/i,
    );
  });
  it("dedupes repeated finite numbers without treating them as schema garbage", () => {
    expect(
      parseSubIssueAdmission([
        { number: 99, state: "OPEN", labels: [{ name: "ready-for-agent" }] },
        { number: 99, state: "OPEN", labels: [{ name: "ready-for-agent" }] },
      ]),
    ).toEqual({ admitted: [99], skipped: [] });
  });
});

describe("#291 readFamilyEpic (injected gh sh)", () => {
  it("uses only gh issue view JSON fields supported by the real CLI", () => {
    const issueViewFields: string[] = [];
    const sh: Sh = (file, args) => {
      expect(file).toBe("gh");
      if (args[0] === "issue" && args[1] === "view") {
        issueViewFields.push(String(args[6]));
        return JSON.stringify({
          number: Number(args[2]),
          body: "",
          author: { login: "Akagilnc" },
        });
      }
      if (String(args[1]).includes("/sub_issues")) {
        return JSON.stringify([{ number: 11 }]);
      }
      return "[]";
    };

    readFamilyEpic(291, "Akagilnc/ming-salvage-sim", sh);

    expect(issueViewFields).toEqual(["number,body,author", "number,body,author"]);
  });

  it("reads sub-issues + each child's blocked_by and builds the epic", () => {
    const sh: Sh = (file, args) => {
      expect(file).toBe("gh");
      if (args[0] === "issue" && args[1] === "view") {
        return JSON.stringify({
          number: Number(args[2]),
          body: "",
          author: { login: "Akagilnc" },
        });
      }
      if (String(args[1]).includes("/sub_issues")) {
        return JSON.stringify([{ number: 11 }, { number: 12 }]);
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
  it("parses parent and child Module Declaration issue bodies into the FamilyEpic", () => {
    const sh: Sh = (file, args) => {
      expect(file).toBe("gh");
      if (args[0] === "issue" && args[1] === "view") {
        const issue = Number(args[2]);
        const body =
          issue === 291
            ? "## Module Declaration\n```yaml\nmodule: parent-fiscal\nmodule_scope:\n  - docs/fiscal\n```"
            : issue === 12
              ? "## Module Declaration\n```yaml\nmodule: child-hub\nmodule_scope:\n  - orchestrator/src/family\n```"
              : "";
        return JSON.stringify({ number: issue, body, author: { login: "Akagilnc" } });
      }
      if (String(args[1]).includes("/sub_issues")) {
        return JSON.stringify([{ number: 11 }, { number: 12 }]);
      }
      return "[]";
    };

    const epic = readFamilyEpic(291, "Akagilnc/ming-salvage-sim", sh);

    expect(epic.moduleDeclaration).toEqual({
      module: "parent-fiscal",
      moduleScope: ["docs/fiscal"],
      source: "family_issue",
      issue: 291,
    });
    expect(epic.children[0]?.moduleDeclaration).toBeUndefined();
    expect(epic.children[1]?.moduleDeclaration).toEqual({
      module: "child-hub",
      moduleScope: ["orchestrator/src/family"],
      source: "child_issue",
      issue: 12,
    });
  });
  it("ignores Module Declaration issue bodies that are not authored by the repo owner", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const sh: Sh = (file, args) => {
      expect(file).toBe("gh");
      if (args[0] === "issue" && args[1] === "view") {
        const issue = Number(args[2]);
        const owner = issue === 291 ? "Akagilnc" : "external-contributor";
        const body =
          issue === 291
            ? "## Module Declaration\n```yaml\nmodule: parent-fiscal\nmodule_scope:\n  - docs/fiscal\n```"
            : "## Module Declaration\n```yaml\nmodule: child-hub\nmodule_scope:\n  - orchestrator/src/family\n```";
        return JSON.stringify({ number: issue, body, author: { login: owner } });
      }
      if (String(args[1]).includes("/sub_issues")) {
        return JSON.stringify([{ number: 11 }]);
      }
      return "[]";
    };

    try {
      const epic = readFamilyEpic(291, "Akagilnc/ming-salvage-sim", sh);

      expect(epic.moduleDeclaration).toEqual({
        module: "parent-fiscal",
        moduleScope: ["docs/fiscal"],
        source: "family_issue",
        issue: 291,
      });
      expect(epic.children[0]?.moduleDeclaration).toBeUndefined();
      expect(warn.mock.calls.map((call) => String(call[0]))).toContain(
        "family module declaration ignored for issue #11: author external-contributor is not trusted owner Akagilnc",
      );
    } finally {
      warn.mockRestore();
    }
  });
  it("ignores Module Declaration issue bodies from organization members", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const sh: Sh = (file, args) => {
      expect(file).toBe("gh");
      if (args[0] === "issue" && args[1] === "view") {
        const issue = Number(args[2]);
        const body =
          issue === 291
            ? "## Module Declaration\n```yaml\nmodule: parent-fiscal\nmodule_scope:\n  - docs/fiscal\n```"
            : "## Module Declaration\n```yaml\nmodule: child-hub\nmodule_scope:\n  - orchestrator/src/family\n```";
        return JSON.stringify({
          number: issue,
          body,
          author: { login: "org-member" },
        });
      }
      if (String(args[1]).match(/repos\/MingOrg\/ming-salvage-sim\/issues\/\d+$/)) {
        return "member";
      }
      if (String(args[1]).includes("/sub_issues")) {
        return JSON.stringify([{ number: 11 }]);
      }
      return "[]";
    };

    try {
      const epic = readFamilyEpic(291, "MingOrg/ming-salvage-sim", sh);

      expect(epic.moduleDeclaration).toBeUndefined();
      expect(epic.children[0]?.moduleDeclaration).toBeUndefined();
      expect(warn.mock.calls.map((call) => String(call[0]))).toContain(
        "family module declaration ignored for issue #291: author org-member is not trusted owner MingOrg",
      );
      expect(warn.mock.calls.map((call) => String(call[0]))).toContain(
        "family module declaration ignored for issue #11: author org-member is not trusted owner MingOrg",
      );
    } finally {
      warn.mockRestore();
    }
  });
  it("fails closed when a module declaration issue body cannot be read", () => {
    const sh: Sh = (file, args) => {
      expect(file).toBe("gh");
      if (args[0] === "issue" && args[1] === "view") {
        throw new Error(`gh failed for #${args[2]}`);
      }
      if (String(args[1]).includes("/sub_issues")) {
        return JSON.stringify([{ number: 11 }]);
      }
      return "[]";
    };

    expect(() => readFamilyEpic(291, "Akagilnc/ming-salvage-sim", sh)).toThrow(
      /failed to read issue #291 body/i,
    );
  });
  it("fails closed when gh issue view returns a non-object payload", () => {
    const sh: Sh = (file, args) => {
      expect(file).toBe("gh");
      if (args[0] === "issue" && args[1] === "view") {
        return "null";
      }
      if (String(args[1]).includes("/sub_issues")) {
        return JSON.stringify([{ number: 11 }]);
      }
      return "[]";
    };

    expect(() => readFamilyEpic(291, "Akagilnc/ming-salvage-sim", sh)).toThrow(
      /unexpected gh issue payload/i,
    );
  });
  it("admits only OPEN ready-for-agent leaf children, logs every skipped non-runnable child, and continues", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    try {
      const sh: Sh = (file, args) => {
        expect(file).toBe("gh");
        if (args[0] === "issue" && args[1] === "view") {
          return JSON.stringify({ number: Number(args[2]), body: "" });
        }
        if (String(args[1]).includes("/sub_issues")) {
          return JSON.stringify([
            {
              number: 11,
              state: "open",
              labels: [{ name: "ready-for-agent" }],
              sub_issues_summary: { total: 0 },
            },
            {
              number: 12,
              state: "open",
              labels: [{ name: "enhancement" }],
              sub_issues_summary: { total: 0 },
            },
            {
              number: 13,
              state: "closed",
              labels: [{ name: "ready-for-agent" }],
              sub_issues_summary: { total: 0 },
            },
            {
              number: 14,
              state: "open",
              labels: [{ name: "ready-for-agent" }],
              sub_issues_summary: { total: 2 },
            },
          ]);
        }
        // Root epic + admitted children reach dependency lookup (ID-002).
        expect(String(args[1])).toMatch(
          /repos\/Akagilnc\/ming-salvage-sim\/issues\/(291|11)\/dependencies\/blocked_by/,
        );
        return "[]";
      };
      const epic = readFamilyEpic(291, "Akagilnc/ming-salvage-sim", sh);
      expect(epic.children).toEqual([{ issue: 11, blockedBy: [] }]);
      expect(warn.mock.calls.map((c) => String(c[0]))).toEqual([
        "family admission skipped child #12: missing ready-for-agent label",
        "family admission skipped child #13: issue is CLOSED",
        "family admission skipped child #14: issue is a parent issue",
      ]);
    } finally {
      warn.mockRestore();
    }
  });
  it("paginates native sub-issues so children after the first REST page are admitted", () => {
    const subIssueCalls: string[] = [];
    const sh: Sh = (file, args) => {
      expect(file).toBe("gh");
      if (args[0] === "issue" && args[1] === "view") {
        return JSON.stringify({ number: Number(args[2]), body: "" });
      }
      if (String(args[1]).includes("/sub_issues")) {
        subIssueCalls.push(String(args[1]));
        const page = Number(/[?&]page=(\d+)/.exec(String(args[1]))?.[1] ?? "1");
        if (page === 1) {
          return JSON.stringify(Array.from({ length: 100 }, (_, i) => ({ number: 1000 + i })));
        }
        if (page === 2) return JSON.stringify([{ number: 2000 }]);
        return "[]";
      }
      return "[]";
    };
    const epic = readFamilyEpic(291, "Akagilnc/ming-salvage-sim", sh);
    expect(epic.children.map((c) => c.issue)).toEqual([
      ...Array.from({ length: 100 }, (_, i) => 1000 + i),
      2000,
    ]);
    expect(subIssueCalls).toEqual([
      "repos/Akagilnc/ming-salvage-sim/issues/291/sub_issues?per_page=100&page=1",
      "repos/Akagilnc/ming-salvage-sim/issues/291/sub_issues?per_page=100&page=2",
    ]);
  });
  it("normalizes a leaf issue to one family child", () => {
    const sh: Sh = (_file, args) => {
      if (String(args[1]).includes("/sub_issues")) return "[]";
      if (args[0] === "issue" && args[1] === "view") {
        return JSON.stringify({ number: 404, body: "", author: { login: "Akagilnc" } });
      }
      if (String(args[1]).includes("/dependencies/blocked_by")) return "[]";
      return "OWNER";
    };
    expect(readFamilyEpic(404, "Akagilnc/ming-salvage-sim", sh)).toMatchObject({
      issue: 404,
      children: [{ issue: 404, blockedBy: [] }],
    });
  });

  it("returns an empty family with visible inventory when all children are skipped", () => {
    const sh: Sh = (_file, args) => {
      if (String(args[1]).includes("/sub_issues")) {
        return JSON.stringify([{ number: 405, state: "CLOSED" }]);
      }
      if (args[0] === "issue" && args[1] === "view") {
        return JSON.stringify({ number: 404, body: "", author: { login: "Akagilnc" } });
      }
      return "[]";
    };
    expect(readFamilyEpic(404, "Akagilnc/ming-salvage-sim", sh)).toMatchObject({
      issue: 404,
      children: [],
      admissionSkipped: [{ issue: 405, reason: "closed" }],
    });
  });

  it("aggregates sub_issues failure with root blocked_by (does not abort before root)", () => {
    const calls: string[] = [];
    const sh: Sh = (_file, args) => {
      const key = String(args[1] ?? args[0]);
      calls.push(key);
      if (String(args[1]).includes("/sub_issues")) {
        throw new Error("sub_issues boom");
      }
      if (String(args[1]).includes("/dependencies/blocked_by")) {
        throw new Error("root blocked_by boom");
      }
      if (args[0] === "issue" && args[1] === "view") {
        return JSON.stringify({ number: 291, body: "", author: { login: "Akagilnc" } });
      }
      return "[]";
    };
    expect(() => readFamilyEpic(291, "Akagilnc/ming-salvage-sim", sh)).toThrow(
      /issue metadata unavailable \(2 errors\).*sub_issues.*blocked_by/s,
    );
    expect(calls.some((c) => c.includes("/sub_issues"))).toBe(true);
    expect(calls.some((c) => c.includes("/dependencies/blocked_by"))).toBe(true);
  });
});

describe("#934 readFamilyEpic root blocked_by + external filter (ID-002)", () => {
  it("parks via FamilyRootBlockerError when the root epic has an OPEN blocker", () => {
    const sh: Sh = (file, args) => {
      expect(file).toBe("gh");
      if (args[0] === "issue" && args[1] === "view") {
        return JSON.stringify({
          number: Number(args[2]),
          body: "",
          author: { login: "Akagilnc" },
        });
      }
      if (String(args[1]).includes("/sub_issues")) {
        return JSON.stringify([{ number: 11 }, { number: 12 }]);
      }
      // root epic blocked_by
      if (String(args[1]).includes("/issues/291/dependencies/blocked_by")) {
        return JSON.stringify([{ number: 100, state: "open" }]);
      }
      return "[]";
    };
    expect(() => readFamilyEpic(291, "Akagilnc/ming-salvage-sim", sh)).toThrow(
      FamilyRootBlockerError,
    );
    try {
      readFamilyEpic(291, "Akagilnc/ming-salvage-sim", sh);
    } catch (e) {
      expect(e).toBeInstanceOf(FamilyRootBlockerError);
      expect((e as FamilyRootBlockerError).openBlockers).toEqual([100]);
    }
  });

  it("OPEN root blocker still finishes enumerable child metadata before park (no first-error return)", () => {
    const childBlockedByReads: number[] = [];
    const sh: Sh = (file, args) => {
      expect(file).toBe("gh");
      if (args[0] === "issue" && args[1] === "view") {
        return JSON.stringify({
          number: Number(args[2]),
          body: "",
          author: { login: "Akagilnc" },
        });
      }
      if (String(args[1]).includes("/sub_issues")) {
        return JSON.stringify([
          { number: 11, state: "OPEN", labels: [{ name: "ready-for-agent" }] },
          { number: 12, state: "OPEN", labels: [{ name: "ready-for-agent" }] },
        ]);
      }
      if (String(args[1]).includes("/issues/291/dependencies/blocked_by")) {
        return JSON.stringify([{ number: 100, state: "open" }]);
      }
      const child = Number(/issues\/(\d+)\//.exec(String(args[1]) ?? "")?.[1]);
      if (child === 11 || child === 12) {
        childBlockedByReads.push(child);
        if (child === 11) {
          throw new Error("child #11 blocked_by unavailable");
        }
        return "[]";
      }
      return "[]";
    };
    try {
      readFamilyEpic(291, "Akagilnc/ming-salvage-sim", sh);
      expect.unreachable("expected FamilyRootBlockerError");
    } catch (e) {
      expect(e).toBeInstanceOf(FamilyRootBlockerError);
      const err = e as FamilyRootBlockerError;
      expect(err.openBlockers).toEqual([100]);
      // Both enumerable children were read despite the OPEN root blocker.
      expect(childBlockedByReads.sort((a, b) => a - b)).toEqual([11, 12]);
      // Child metadata failure is retained in park diagnostics (not dropped).
      expect(err.message).toMatch(/child #11 blocked_by/);
      expect(err.diagnostics.some((d) => /child #11 blocked_by/.test(d))).toBe(
        true,
      );
    }
  });

  it("visibly filters a child with open external blocker and admits the sibling", () => {
    const sh: Sh = (file, args) => {
      expect(file).toBe("gh");
      if (args[0] === "issue" && args[1] === "view") {
        return JSON.stringify({
          number: Number(args[2]),
          body: "",
          author: { login: "Akagilnc" },
        });
      }
      if (String(args[1]).includes("/sub_issues")) {
        return JSON.stringify([
          { number: 11, state: "OPEN", labels: [{ name: "ready-for-agent" }] },
          { number: 12, state: "OPEN", labels: [{ name: "ready-for-agent" }] },
        ]);
      }
      if (String(args[1]).includes("/issues/291/dependencies/blocked_by")) {
        return "[]"; // root clear
      }
      const n = Number(/issues\/(\d+)\//.exec(String(args[1]) ?? "")?.[1]);
      if (n === 12) {
        return JSON.stringify([{ number: 999, state: "open" }]);
      }
      return "[]";
    };
    const epic = readFamilyEpic(291, "Akagilnc/ming-salvage-sim", sh);
    expect(epic.children.map((c) => c.issue)).toEqual([11]);
    expect(epic.admissionSkipped).toEqual([
      {
        issue: 12,
        reason: "open_external_blocker",
        message: "family admission skipped child #12: open external blocker(s) #999",
      },
    ]);
  });
});

describe("#934 discoverSubprojects operational errors fail closed (ID-011)", () => {
  it("throws when readdir fails (never soft-returns [])", () => {
    expect(() => discoverSubprojects("/definitely/missing/path-934-subprojects")).toThrow(
      /^family verify: failed to readdir subprojects at /,
    );
  });
});
