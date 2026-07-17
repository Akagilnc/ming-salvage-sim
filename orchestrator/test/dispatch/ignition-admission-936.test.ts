/**
 * #936 — ignition admission before worksite + durable-truth re-entry.
 *
 * Production seams only (Testing Decisions / #934 ID-016):
 *   - public single-slice entry: runOrchestrator
 *   - public family entry: runFamilyDriver
 *   - Scene Recovery / local Git: discoverResidentScene, cutRefFor
 *
 * Contracts: #934 ID-002, ID-003, ID-005, ID-009, ID-015, ID-016.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import {
  admitCoderRec,
  admitPlannedRouteSmoke,
  admitRouteFromEnv,
  admitTightRoute,
  isGithubAuthFailure,
  readMetadataWithRetry,
} from "../../src/admissionPreflight.js";
import { discoverResidentScene } from "../../src/sceneAction.js";
import { cutRefFor } from "../../src/realBackend.js";
import { resolveRouteModels, type ResolvedModelRoute } from "../../src/modelRoutes.js";
import { runOrchestrator } from "../../src/runner.js";
import {
  cutFamilyBase,
  discoverFamilyResidentScene,
  planFamilyTerminalReplay,
  runFamilyDriver,
} from "../../src/familyDriver.js";
import { FAMILY_LEDGER_FILENAME } from "../../src/family/realFamilyBackend.js";
import { isCompleteFamilyEscalation } from "../../src/family/ledger.js";
import { entry, s8 } from "../helpers/resume-fixtures.js";
import type {
  Backend,
  IssueMeta,
  ResumeState,
  StepOutput,
  StepSpec,
  WorktreeHandle,
} from "../../src/types.js";

afterEach(() => {
  vi.unstubAllEnvs();
});

const META: IssueMeta = {
  number: 936,
  isClosed: false,
  isReadyForAgent: true,
  hasSubIssues: false,
  openBlockedBy: [],
  body: "Coder-Rec: grok-4.5 → sol@med → terra@med\n\n## What\nslice",
};

class CountingBackend implements Backend {
  calls: string[] = [];
  metaCalls = 0;
  smokeCalls = 0;
  prepareCalls = 0;
  resumeState: ResumeState | undefined;
  workingRepoCalls = 0;
  smokeFailure: Error | undefined;

  workingRepoPath(): string {
    this.workingRepoCalls += 1;
    return "/tmp/should-not-create-worksite";
  }

  async smokeModelRoute(route: import("../../src/modelRoutes.js").ResolvedModelRoute) {
    this.smokeCalls += 1;
    this.calls.push("smokeModelRoute");
    if (this.smokeFailure !== undefined) throw this.smokeFailure;
    const { smokeRouteModels } = await import("../../src/modelRoutes.js");
    return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
  }
  async findResumeState(issueNumber: number): Promise<ResumeState | undefined> {
    this.calls.push(`findResumeState(${issueNumber})`);
    return this.resumeState;
  }
  async resumeSession(): Promise<StepOutput> {
    throw new Error("not used");
  }
  async fetchIssueMeta(issueNumber: number): Promise<IssueMeta> {
    this.metaCalls += 1;
    this.calls.push(`fetchIssueMeta(${issueNumber})`);
    return META;
  }
  async prepareWorktree(issueNumber: number, base: string): Promise<WorktreeHandle> {
    this.prepareCalls += 1;
    this.calls.push(`prepareWorktree(${issueNumber},${base})`);
    return { branch: `feat/issue-${issueNumber}`, base, path: `/tmp/wt-${issueNumber}` };
  }
  async runStep(spec: StepSpec): Promise<StepOutput> {
    this.calls.push(`runStep(${spec.id})`);
    if (spec.role === "reviewer" || spec.role === "verify") {
      return { kind: "judge", status: "converged" };
    }
    return { kind: "coder", committed: true, commitsAdded: 1 };
  }
  async writeLedger(): Promise<void> {}
}

describe("#936 admission preflight (ID-002 / ID-003)", () => {
  it("positive: preset route admits without slot env overrides", () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "normal");
    const admitted = admitRouteFromEnv(process.env);
    expect(admitted.kind).toBe("ready");
    if (admitted.kind === "ready") {
      expect(admitted.route.slots.coder).toBe("gpt-5.6-terra");
    }
  });

  it("negative: leftover slot env override does not restaff (deleted)", () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "normal");
    vi.stubEnv("ORCHESTRATOR_CODER_MODEL", "grok-4.5");
    const admitted = admitRouteFromEnv(process.env);
    expect(admitted.kind).toBe("ready");
    if (admitted.kind === "ready") {
      expect(admitted.route.slots.coder).toBe("gpt-5.6-terra");
      expect(admitted.route.slots.coder).not.toBe("grok-4.5");
    }
  });

  it("negative: leftover CMR leg env override does not restaff (deleted)", () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "normal");
    vi.stubEnv("ORCHESTRATOR_CMR_REVIEW_LEG_SLUGS", "opus");
    const admitted = admitRouteFromEnv(process.env);
    expect(admitted.kind).toBe("ready");
    if (admitted.kind === "ready") {
      const legs = admitted.route.legCollections.cmrReview.map((l) => l.slug);
      expect(legs).toContain("gpt-5.6-sol");
      expect(legs).not.toEqual(["opus"]);
    }
  });

  it("negative: tight violation always stops (no interactive continue)", () => {
    const route = resolveRouteModels("claude-tight", { merger: "opus" });
    const decision = admitTightRoute(route);
    expect(decision.kind).toBe("stop");
  });

  it("positive+negative: Coder-Rec restaffs coder; broken mark fails closed", () => {
    const base = resolveRouteModels("normal", {});
    const ok = admitCoderRec(base, "Coder-Rec: grok-4.5 → sol@med\n");
    expect(ok.kind).toBe("ready");
    if (ok.kind === "ready") {
      expect(ok.route.slots.coder).toBe("grok-4.5");
    }
    const bad = admitCoderRec(base, "Coder-Rec: not-a-real-model\n");
    expect(bad.kind).toBe("stop");
  });

  it("public single-slice: scene discovery is the first backend call (ID-005 Recovery first)", async () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "normal");
    const backend = new CountingBackend();
    await runOrchestrator({ issueNumber: 936, backend });
    expect(backend.calls[0]).toBe("findResumeState(936)");
  });

  it("public family driver: unknown route stops before GitHub and clone", async () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "definitely-not-a-route-preset");
    let ghCalls = 0;
    let cloneCalls = 0;
    const result = await runFamilyDriver({
      epicIssue: 934,
      sourceRepo: "/tmp/no-such-source",
      repo: "Akagilnc/ming-salvage-sim",
      familyBase: "family/934-base",
      base: "main",
      promptsDir: "/tmp/prompts",
      familyPromptsDir: "/tmp/family-prompts",
      soulsDir: "/tmp/souls",
      ledgerDir: "/tmp/ledger-936",
      imageName: "img",
      sh: () => {
        ghCalls += 1;
        throw new Error("should not read GitHub after route admission stop");
      },
      realBackendFactory: () => {
        cloneCalls += 1;
        throw new Error("should not clone after route admission stop");
      },
    });
    expect(result.status).toBe("escalated");
    expect(result.escalation?.reason).toMatch(/startup route failure|unknown route/i);
    expect(ghCalls).toBe(0);
    expect(cloneCalls).toBe(0);
    expect(result.children).toEqual([]);
  });

  it("public family driver: all filtered children complete with visible skips and no worksite", async () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "normal");
    let cloneCalls = 0;
    const sh = (_file: string, args: string[]): string => {
      const joined = args.join(" ");
      if (joined.includes("sub_issues")) {
        return JSON.stringify([
          { number: 935, state: "CLOSED", labels: [{ name: "ready-for-agent" }] },
          { number: 936, state: "OPEN", labels: [] },
        ]);
      }
      if (joined.includes("dependencies/blocked_by")) return "[]";
      if (joined.includes("issue view")) {
        return JSON.stringify({ number: 934, body: "", author: { login: "Akagilnc" } });
      }
      throw new Error(`unexpected metadata call: ${joined}`);
    };
    const result = await runFamilyDriver({
      epicIssue: 934,
      sourceRepo: "/tmp/source",
      repo: "Akagilnc/ming-salvage-sim",
      familyBase: "family/934-base",
      base: "main",
      promptsDir: "/tmp/prompts",
      familyPromptsDir: "/tmp/prompts",
      soulsDir: "/tmp/souls",
      ledgerDir: "/tmp/ledger-936",
      imageName: "img",
      sh,
      realBackendFactory: () => {
        cloneCalls += 1;
        throw new Error("all-filtered admission must not create a worksite");
      },
    });
    expect(result.status).toBe("success");
    expect(result.children).toEqual([]);
    expect(result.admissionSkipped?.map((child) => child.issue)).toEqual([935, 936]);
    expect(cloneCalls).toBe(0);
  });

  it("public family driver: all-filtered success ignores invalid parent Coder-Rec", async () => {
    // #934 ID-002 / ID-003: all-filtered returns completed/0 with full skip
    // inventory. Parent is not a planned runnable slice on this path, so an
    // invalid epic Coder-Rec must not block success or create a worksite.
    vi.stubEnv("ORCHESTRATOR_ROUTE", "normal");
    let cloneCalls = 0;
    const sh = (_file: string, args: string[]): string => {
      const joined = args.join(" ");
      if (joined.includes("sub_issues")) {
        return JSON.stringify([
          { number: 935, state: "CLOSED", labels: [{ name: "ready-for-agent" }] },
          { number: 936, state: "OPEN", labels: [] },
        ]);
      }
      if (joined.includes("dependencies/blocked_by")) return "[]";
      if (joined.includes("issue view")) {
        return JSON.stringify({
          number: Number(args[2]),
          body: "Coder-Rec: missing-parent-model",
          author: { login: "Akagilnc" },
        });
      }
      throw new Error(`unexpected metadata call: ${joined}`);
    };
    const result = await runFamilyDriver({
      epicIssue: 934,
      sourceRepo: "/tmp/source",
      repo: "Akagilnc/ming-salvage-sim",
      familyBase: "family/934-base",
      base: "main",
      promptsDir: "/tmp/prompts",
      familyPromptsDir: "/tmp/prompts",
      soulsDir: "/tmp/souls",
      ledgerDir: "/tmp/ledger-936-all-filtered-bad-parent-rec",
      imageName: "img",
      sh,
      realBackendFactory: () => {
        cloneCalls += 1;
        throw new Error("all-filtered must not create a worksite for parent Coder-Rec");
      },
    });
    expect(result.status).toBe("success");
    expect(result.children).toEqual([]);
    expect(result.admissionSkipped?.map((child) => child.issue)).toEqual([935, 936]);
    expect(result.stopSummary?.reason).toBe("already_done");
    expect(result.escalation).toBeUndefined();
    expect(cloneCalls).toBe(0);
  });

  it("public family driver: malformed blocked_by schema fails closed before worksite", async () => {
    // #934 ID-003: deterministic dependency schema errors must not soft-empty
    // into unblocked admission.
    vi.stubEnv("ORCHESTRATOR_ROUTE", "normal");
    let cloneCalls = 0;
    const sh = (_file: string, args: string[]): string => {
      const joined = args.join(" ");
      if (joined.includes("sub_issues")) {
        return JSON.stringify([
          { number: 935, state: "OPEN", labels: [{ name: "ready-for-agent" }] },
        ]);
      }
      if (joined.includes("dependencies/blocked_by")) {
        // Non-array payload: old soft-decode returned [] and admitted the child.
        return JSON.stringify({ nodes: [{ number: 1, state: "open" }] });
      }
      if (joined.includes("issue view")) {
        return JSON.stringify({
          number: Number(args[2]),
          body: "Coder-Rec: grok-4.5",
          author: { login: "Akagilnc" },
        });
      }
      throw new Error(`unexpected metadata call: ${joined}`);
    };
    const result = await runFamilyDriver({
      epicIssue: 934,
      sourceRepo: "/tmp/source",
      repo: "Akagilnc/ming-salvage-sim",
      familyBase: "family/934-base",
      base: "main",
      promptsDir: "/tmp/prompts",
      familyPromptsDir: "/tmp/prompts",
      soulsDir: "/tmp/souls",
      ledgerDir: "/tmp/ledger-936-schema",
      imageName: "img",
      sh,
      realBackendFactory: () => {
        cloneCalls += 1;
        throw new Error("schema failure must precede clone");
      },
    });
    expect(result.status).toBe("escalated");
    expect(result.escalation?.diagnosis).toMatch(/blocked_by schema error|issue metadata unavailable/i);
    expect(cloneCalls).toBe(0);
  });

  it("public family driver aggregates every planned child Coder-Rec before worksite", async () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "normal");
    let cloneCalls = 0;
    const sh = (_file: string, args: string[]): string => {
      const joined = args.join(" ");
      if (joined.includes("sub_issues")) {
        return JSON.stringify([
          { number: 935, state: "OPEN", labels: [{ name: "ready-for-agent" }] },
          { number: 936, state: "OPEN", labels: [{ name: "ready-for-agent" }] },
        ]);
      }
      if (joined.includes("dependencies/blocked_by")) return "[]";
      if (joined.includes("issue view")) {
        const issue = Number(args[2]);
        const body = issue === 935
          ? "Coder-Rec: missing-model-a"
          : issue === 936
            ? "Coder-Rec: missing-model-b"
            : "Coder-Rec: terra@med";
        return JSON.stringify({ number: issue, body, author: { login: "Akagilnc" } });
      }
      throw new Error(`unexpected metadata call: ${joined}`);
    };
    const result = await runFamilyDriver({
      epicIssue: 934,
      sourceRepo: "/tmp/source",
      repo: "Akagilnc/ming-salvage-sim",
      familyBase: "family/934-base",
      base: "main",
      promptsDir: "/tmp/prompts",
      familyPromptsDir: "/tmp/prompts",
      soulsDir: "/tmp/souls",
      ledgerDir: "/tmp/ledger-936",
      imageName: "img",
      sh,
      realBackendFactory: () => {
        cloneCalls += 1;
        throw new Error("Coder-Rec aggregate failure must precede clone");
      },
    });
    expect(result.status).toBe("escalated");
    expect(result.escalation?.diagnosis).toMatch(/2 errors/);
    expect(result.escalation?.diagnosis).toContain("issue #935");
    expect(result.escalation?.diagnosis).toContain("issue #936");
    expect(cloneCalls).toBe(0);
  });

  it("public family driver aggregates parent + child Coder-Rec failures once (no parent short-circuit)", async () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "normal");
    let cloneCalls = 0;
    const sh = (_file: string, args: string[]): string => {
      const joined = args.join(" ");
      if (joined.includes("sub_issues")) {
        return JSON.stringify([
          { number: 935, state: "OPEN", labels: [{ name: "ready-for-agent" }] },
          { number: 936, state: "OPEN", labels: [{ name: "ready-for-agent" }] },
        ]);
      }
      if (joined.includes("dependencies/blocked_by")) return "[]";
      if (joined.includes("issue view")) {
        const issue = Number(args[2]);
        // Parent + both children malformed — inventory must list all three.
        const body =
          issue === 934
            ? "Coder-Rec: missing-parent-model"
            : issue === 935
              ? "Coder-Rec: missing-model-a"
              : issue === 936
                ? "Coder-Rec: missing-model-b"
                : "Coder-Rec: terra@med";
        return JSON.stringify({ number: issue, body, author: { login: "Akagilnc" } });
      }
      throw new Error(`unexpected metadata call: ${joined}`);
    };
    const result = await runFamilyDriver({
      epicIssue: 934,
      sourceRepo: "/tmp/source",
      repo: "Akagilnc/ming-salvage-sim",
      familyBase: "family/934-base",
      base: "main",
      promptsDir: "/tmp/prompts",
      familyPromptsDir: "/tmp/prompts",
      soulsDir: "/tmp/souls",
      ledgerDir: "/tmp/ledger-936-parent-child",
      imageName: "img",
      sh,
      realBackendFactory: () => {
        cloneCalls += 1;
        throw new Error("parent+child Coder-Rec aggregate must precede clone");
      },
    });
    expect(result.status).toBe("escalated");
    expect(result.escalation?.diagnosis).toMatch(/3 errors/);
    expect(result.escalation?.diagnosis).toContain("issue #934");
    expect(result.escalation?.diagnosis).toContain("issue #935");
    expect(result.escalation?.diagnosis).toContain("issue #936");
    expect(cloneCalls).toBe(0);
  });

  it("public family driver: final Coder-Rec route smoke fails before worksite creation", async () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "normal");
    const backend = new CountingBackend();
    backend.smokeFailure = new Error("nonce smoke failed");
    const sh = (_file: string, args: string[]): string => {
      const joined = args.join(" ");
      if (joined.includes("sub_issues")) return "[]";
      if (joined.includes("dependencies/blocked_by")) return "[]";
      if (joined.includes("issue view")) {
        return JSON.stringify({
          number: 934,
          body: "Coder-Rec: grok-4.5 → sol@med",
          author: { login: "Akagilnc" },
        });
      }
      throw new Error(`unexpected metadata call: ${joined}`);
    };
    const result = await runFamilyDriver({
      epicIssue: 934,
      sourceRepo: "/tmp/source",
      repo: "Akagilnc/ming-salvage-sim",
      familyBase: "family/934-base",
      base: "main",
      promptsDir: "/tmp/prompts",
      familyPromptsDir: "/tmp/prompts",
      soulsDir: "/tmp/souls",
      ledgerDir: "/tmp/ledger-936",
      imageName: "img",
      sh,
      realBackendFactory: () => backend,
    });
    expect(result.status).toBe("escalated");
    expect(result.escalation).toEqual({
      reason: "startup route smoke failure",
      diagnosis: "route smoke failed: nonce smoke failed",
    });
    expect(backend.smokeCalls).toBe(1);
    expect(backend.workingRepoCalls).toBe(0);
  });

  it("metadata transient retry uses six total attempts; deterministic failures use one", () => {
    let transientAttempts = 0;
    expect(() =>
      readMetadataWithRetry(() => {
        transientAttempts += 1;
        throw Object.assign(new Error("temporary reset"), { code: "ECONNRESET" });
      }),
    ).toThrow(/temporary reset/);
    expect(transientAttempts).toBe(6);

    let deterministicAttempts = 0;
    expect(() =>
      readMetadataWithRetry(() => {
        deterministicAttempts += 1;
        throw new SyntaxError("bad JSON contract");
      }),
    ).toThrow(/bad JSON contract/);
    expect(deterministicAttempts).toBe(1);
  });
});

describe("#936 scene recovery + local Git (ID-005 / ID-009 / ID-015)", () => {
  it("positive: no residue → typed fresh", async () => {
    const backend = new CountingBackend();
    const scene = await discoverResidentScene(backend, 936);
    expect(scene).toEqual({ kind: "fresh" });
  });

  it("positive: resident ledger → resident discovery (no second worksite invent)", async () => {
    const backend = new CountingBackend();
    backend.resumeState = {
      worktree: { branch: "feat/issue-936", base: "main", path: "/tmp/wt-936" },
      stateDir: "/tmp/ledger-936",
      ledger: [s8("success")],
    };
    const scene = await discoverResidentScene(backend, 936);
    expect(scene.kind).toBe("resident");
    if (scene.kind === "resident") {
      expect(scene.state.ledger[0]?.handoffStatus).toBe("success");
    }
  });

  it("negative: discovery throw → corrupted (preserve scene, no invent)", async () => {
    const backend = new CountingBackend();
    backend.findResumeState = async () => {
      throw new Error("disk unreadable");
    };
    const scene = await discoverResidentScene(backend, 936);
    expect(scene.kind).toBe("corrupted");
    if (scene.kind === "corrupted") {
      expect(scene.reason).toMatch(/disk unreadable/);
    }
  });

  it("negative: partial residue (worktree without ledger) is corrupted not fresh", async () => {
    const backend = new CountingBackend();
    backend.findResumeState = async () => {
      throw new Error(
        "resident worksite exists without readable ledger for #936 " +
          "(worktree=/tmp/wt-936, expected ledger=/tmp/.ledger-936); " +
          "refusing to treat partial residue as fresh (#936 / #934 ID-005)",
      );
    };
    const scene = await discoverResidentScene(backend, 936);
    expect(scene.kind).toBe("corrupted");
    if (scene.kind === "corrupted") {
      expect(scene.reason).toMatch(/partial residue|without readable ledger/i);
    }
    const result = await runOrchestrator({ issueNumber: 936, backend });
    expect(result.status).toBe("error");
    expect(result.errorPackage?.reason).toMatch(/without readable ledger|partial residue/i);
    expect(backend.prepareCalls).toBe(0);
    expect(backend.metaCalls).toBe(0);
  });

  it("public driver: durable success terminal replays with zero meta/smoke even if route is broken", async () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "definitely-not-a-route-preset");
    const backend = new CountingBackend();
    backend.resumeState = {
      worktree: { branch: "feat/issue-936", base: "main", path: "/tmp/wt-936" },
      stateDir: "/tmp/ledger-936",
      ledger: [
        entry("S2", { kind: "coder", committed: true, commitsAdded: 1 }),
        s8("success"),
      ],
    };
    const result = await runOrchestrator({ issueNumber: 936, backend });
    expect(result.status).toBe("success");
    expect(backend.metaCalls).toBe(0);
    expect(backend.smokeCalls).toBe(0);
    expect(backend.prepareCalls).toBe(0);
  });

  it("negative: with remote, fetch-fail does not fall back to stale local base", () => {
    expect(() =>
      cutRefFor("main", /*fetchedOk*/ false, /*localOnly*/ false, { hasRemote: true }),
    ).toThrow(/refusing stale local base fallback/i);
  });

  it("family base cut refuses a failed configured origin fetch", () => {
    const ledgerDir = mkdtempSync(join(tmpdir(), "family-base-fetch-"));
    const calls: string[] = [];
    try {
      expect(() =>
        cutFamilyBase("/repo", "family/934", "main", (_file, args) => {
          const command = args.slice(2).join(" ");
          calls.push(command);
          if (command === "rev-parse -q --verify refs/heads/family/934") {
            throw new Error("missing branch");
          }
          if (command === "remote get-url origin") return "https://example.invalid/repo.git";
          if (command === "fetch origin main") throw new Error("network down");
          throw new Error(`unexpected git command: ${command}`);
        }, ledgerDir),
      ).toThrow(/network down/);
      expect(calls).not.toContain("branch family/934 main");
    } finally {
      rmSync(ledgerDir, { recursive: true, force: true });
    }
  });

  it("family base cut refuses operational get-url failure (not missing-origin)", () => {
    const ledgerDir = mkdtempSync(join(tmpdir(), "family-base-geturl-"));
    const calls: string[] = [];
    try {
      expect(() =>
        cutFamilyBase("/repo", "family/934", "main", (_file, args) => {
          const command = args.slice(2).join(" ");
          calls.push(command);
          if (command === "rev-parse -q --verify refs/heads/family/934") {
            throw new Error("missing branch");
          }
          if (command === "remote get-url origin") {
            throw new Error("fatal: not a git repository");
          }
          throw new Error(`unexpected git command: ${command}`);
        }, ledgerDir),
      ).toThrow(/refusing stale local base fallback/i);
      expect(calls).not.toContain("branch family/934 main");
      expect(calls).not.toContain("fetch origin main");
    } finally {
      rmSync(ledgerDir, { recursive: true, force: true });
    }
  });

  it("family base cut allows precise missing-origin as local-only", () => {
    const ledgerDir = mkdtempSync(join(tmpdir(), "family-base-noremote-"));
    const calls: string[] = [];
    try {
      const head = cutFamilyBase("/repo", "family/934", "main", (_file, args) => {
        const command = args.slice(2).join(" ");
        calls.push(command);
        if (command === "rev-parse -q --verify refs/heads/family/934") {
          throw new Error("missing branch");
        }
        if (command === "remote get-url origin") {
          throw new Error("fatal: No such remote 'origin'");
        }
        if (command === "branch family/934 main") return "";
        if (command === "rev-parse family/934") return "abc123local";
        throw new Error(`unexpected git command: ${command}`);
      }, ledgerDir);
      expect(head).toBe("abc123local");
      expect(calls).toContain("branch family/934 main");
      expect(calls).not.toContain("fetch origin main");
    } finally {
      rmSync(ledgerDir, { recursive: true, force: true });
    }
  });

  it("positive: local-only source may use bare local base when fetch fails", () => {
    expect(cutRefFor("main", false, false, { hasRemote: false })).toBe("main");
  });

  it("positive: family localOnly always uses bare base", () => {
    expect(cutRefFor("family/934-base", true, true, { hasRemote: true })).toBe(
      "family/934-base",
    );
  });

  it("public family driver: durable post_merge_cleanup terminal replays with zero meta/clone/smoke", async () => {
    // #934 ID-005 via public family entry: completed durable scene must short-
    // circuit before route admission / GitHub / clone / smoke.
    vi.stubEnv("ORCHESTRATOR_ROUTE", "definitely-not-a-route-preset");
    const ledgerDir = mkdtempSync(join(tmpdir(), "family-terminal-replay-"));
    let ghCalls = 0;
    let cloneCalls = 0;
    try {
      writeFileSync(
        join(ledgerDir, FAMILY_LEDGER_FILENAME),
        [
          JSON.stringify({
            status: "merged",
            event: "reconciled",
            childIssue: 936,
            familyHeadAfter: "abc123",
          }),
          JSON.stringify({
            status: "post_merge_cleanup",
            event: "post_merge_cleanup",
            phase: "final",
            familyHeadAfter: "abc123",
            cleanupOutput: {
              kind: "cleanup",
              terminal: true,
              ok: true,
              branchOutcome: "already_gone",
            },
          }),
        ].join("\n") + "\n",
        "utf8",
      );
      const result = await runFamilyDriver({
        epicIssue: 934,
        sourceRepo: "/tmp/no-such-source",
        repo: "Akagilnc/ming-salvage-sim",
        familyBase: "family/934-base",
        base: "main",
        promptsDir: "/tmp/prompts",
        familyPromptsDir: "/tmp/family-prompts",
        soulsDir: "/tmp/souls",
        ledgerDir,
        imageName: "img",
        sh: () => {
          ghCalls += 1;
          throw new Error("terminal replay must not read GitHub");
        },
        realBackendFactory: () => {
          cloneCalls += 1;
          throw new Error("terminal replay must not clone");
        },
      });
      expect(result.status).toBe("success");
      expect(result.stopSummary?.reason).toBe("already_done");
      expect(result.familyHead).toBe("abc123");
      expect(result.children).toEqual([{ issue: 936, status: "already_done" }]);
      expect(ghCalls).toBe(0);
      expect(cloneCalls).toBe(0);
    } finally {
      rmSync(ledgerDir, { recursive: true, force: true });
    }
  });

  it("public family driver: corrupt resident ledger fails closed with zero external calls", async () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "normal");
    const ledgerDir = mkdtempSync(join(tmpdir(), "family-corrupt-ledger-"));
    let ghCalls = 0;
    let cloneCalls = 0;
    try {
      writeFileSync(
        join(ledgerDir, FAMILY_LEDGER_FILENAME),
        "{not-valid-jsonl\n",
        "utf8",
      );
      const result = await runFamilyDriver({
        epicIssue: 934,
        sourceRepo: "/tmp/no-such-source",
        repo: "Akagilnc/ming-salvage-sim",
        familyBase: "family/934-base",
        base: "main",
        promptsDir: "/tmp/prompts",
        familyPromptsDir: "/tmp/family-prompts",
        soulsDir: "/tmp/souls",
        ledgerDir,
        imageName: "img",
        sh: () => {
          ghCalls += 1;
          throw new Error("corrupt scene must not read GitHub");
        },
        realBackendFactory: () => {
          cloneCalls += 1;
          throw new Error("corrupt scene must not clone");
        },
      });
      expect(result.status).toBe("escalated");
      expect(result.escalation?.reason).toMatch(/resume state invalid/i);
      expect(result.escalation?.diagnosis).toMatch(/corrupt/i);
      expect(ghCalls).toBe(0);
      expect(cloneCalls).toBe(0);
    } finally {
      rmSync(ledgerDir, { recursive: true, force: true });
    }
  });

  it("discoverFamilyResidentScene: no ledger → fresh; planFamilyTerminalReplay non-terminal → undefined", () => {
    const ledgerDir = mkdtempSync(join(tmpdir(), "family-scene-fresh-"));
    try {
      expect(discoverFamilyResidentScene(ledgerDir)).toEqual({ kind: "fresh" });
      expect(planFamilyTerminalReplay([], "family/934-base")).toBeUndefined();
      expect(
        planFamilyTerminalReplay(
          [{ status: "merged", event: "reconciled", childIssue: 1 }],
          "family/934-base",
        ),
      ).toBeUndefined();
    } finally {
      rmSync(ledgerDir, { recursive: true, force: true });
    }
  });

  it("discoverFamilyResidentScene: worksite residue without ledger is corrupted not fresh (ID-005)", () => {
    const ledgerDir = mkdtempSync(join(tmpdir(), "family-scene-partial-"));
    const clonePath = mkdtempSync(join(tmpdir(), "family-clone-partial-"));
    try {
      // Resident clone with .git, no family ledger → partial residue.
      mkdirSync(join(clonePath, ".git"), { recursive: true });
      const scene = discoverFamilyResidentScene(ledgerDir, { clonePath });
      expect(scene.kind).toBe("corrupted");
      if (scene.kind === "corrupted") {
        expect(scene.reason).toMatch(/worksite exists without readable ledger|partial residue/i);
      }
    } finally {
      rmSync(ledgerDir, { recursive: true, force: true });
      rmSync(clonePath, { recursive: true, force: true });
    }
  });

  it("discoverFamilyResidentScene: family-base start-head without ledger is corrupted", () => {
    const ledgerDir = mkdtempSync(join(tmpdir(), "family-scene-starthead-"));
    try {
      writeFileSync(join(ledgerDir, "family-base-start-head"), "abc123\n", "utf8");
      const scene = discoverFamilyResidentScene(ledgerDir);
      expect(scene.kind).toBe("corrupted");
      if (scene.kind === "corrupted") {
        expect(scene.reason).toMatch(/worksite exists without readable ledger/i);
      }
    } finally {
      rmSync(ledgerDir, { recursive: true, force: true });
    }
  });

  it("discoverFamilyResidentScene: nonterminal ledger without worksite is corrupted (ID-005)", () => {
    const ledgerDir = mkdtempSync(join(tmpdir(), "family-scene-ledger-only-"));
    try {
      // Mid-run ledger (merged child, no terminal cleanup/escalation) + no worksite.
      writeFileSync(
        join(ledgerDir, FAMILY_LEDGER_FILENAME),
        `${JSON.stringify({
          status: "merged",
          event: "reconciled",
          childIssue: 936,
          familyHeadAfter: "deadbeef",
        })}\n`,
        "utf8",
      );
      const scene = discoverFamilyResidentScene(ledgerDir);
      expect(scene.kind).toBe("corrupted");
      if (scene.kind === "corrupted") {
        expect(scene.reason).toMatch(
          /ledger exists without worksite|nonterminal ledger-without-worksite/i,
        );
      }
    } finally {
      rmSync(ledgerDir, { recursive: true, force: true });
    }
  });

  it("discoverFamilyResidentScene: terminal cleanup ledger without worksite is resident (replayable)", () => {
    const ledgerDir = mkdtempSync(join(tmpdir(), "family-scene-terminal-ledger-"));
    try {
      writeFileSync(
        join(ledgerDir, FAMILY_LEDGER_FILENAME),
        `${JSON.stringify({
          status: "post_merge_cleanup",
          event: "post_merge_cleanup",
          phase: "final",
          familyHeadAfter: "abc123",
          cleanupOutput: { kind: "cleanup", terminal: true, ok: true, branchOutcome: "deleted" },
        })}\n`,
        "utf8",
      );
      const scene = discoverFamilyResidentScene(ledgerDir);
      expect(scene.kind).toBe("resident");
      if (scene.kind === "resident") {
        expect(planFamilyTerminalReplay(scene.ledger, "family/934-base")?.status).toBe(
          "success",
        );
      }
    } finally {
      rmSync(ledgerDir, { recursive: true, force: true });
    }
  });

  it("discoverFamilyResidentScene: nonterminal ledger WITH worksite residue remains resident", () => {
    const ledgerDir = mkdtempSync(join(tmpdir(), "family-scene-ledger-wt-"));
    try {
      writeFileSync(
        join(ledgerDir, FAMILY_LEDGER_FILENAME),
        `${JSON.stringify({
          status: "merged",
          event: "reconciled",
          childIssue: 936,
          familyHeadAfter: "deadbeef",
        })}\n`,
        "utf8",
      );
      writeFileSync(join(ledgerDir, "family-base-start-head"), "start0\n", "utf8");
      const scene = discoverFamilyResidentScene(ledgerDir);
      expect(scene.kind).toBe("resident");
      if (scene.kind === "resident") {
        expect(planFamilyTerminalReplay(scene.ledger, "family/934-base")).toBeUndefined();
      }
    } finally {
      rmSync(ledgerDir, { recursive: true, force: true });
    }
  });

  it("discoverFamilyResidentScene: incomplete escalated row is corrupted (not terminal replay)", () => {
    const ledgerDir = mkdtempSync(join(tmpdir(), "family-scene-malformed-esc-"));
    try {
      // status:escalated without event:escalated — mid-run pause shape, not terminal.
      writeFileSync(
        join(ledgerDir, FAMILY_LEDGER_FILENAME),
        `${JSON.stringify({
          status: "escalated",
          escalationKind: "decision",
          reason: "partial park row",
        })}\n`,
        "utf8",
      );
      const scene = discoverFamilyResidentScene(ledgerDir);
      expect(scene.kind).toBe("corrupted");
      if (scene.kind === "corrupted") {
        expect(scene.reason).toMatch(/incomplete status:escalated|damaged park/i);
      }
      expect(
        planFamilyTerminalReplay(
          [{ status: "escalated", escalationKind: "decision", reason: "partial" } as never],
          "family/934-base",
        ),
      ).toBeUndefined();
      expect(
        isCompleteFamilyEscalation({
          status: "escalated",
          event: "escalated",
          escalationKind: "decision",
        }),
      ).toBe(true);
      expect(
        isCompleteFamilyEscalation({
          status: "escalated",
          escalationKind: "decision",
        } as never),
      ).toBe(false);
    } finally {
      rmSync(ledgerDir, { recursive: true, force: true });
    }
  });

  it("discoverFamilyResidentScene: complete escalated decision without worksite is resident+replayable", () => {
    const ledgerDir = mkdtempSync(join(tmpdir(), "family-scene-complete-esc-"));
    try {
      writeFileSync(
        join(ledgerDir, FAMILY_LEDGER_FILENAME),
        `${JSON.stringify({
          status: "escalated",
          event: "escalated",
          phase: "final",
          escalationKind: "decision",
          reason: "need human",
          familyHeadAfter: "abc",
        })}\n`,
        "utf8",
      );
      const scene = discoverFamilyResidentScene(ledgerDir);
      expect(scene.kind).toBe("resident");
      if (scene.kind === "resident") {
        const replay = planFamilyTerminalReplay(scene.ledger, "family/934-base");
        expect(replay?.status).toBe("escalated");
        expect(replay?.stopSummary?.reason).toBe("decision_gate_park");
      }
    } finally {
      rmSync(ledgerDir, { recursive: true, force: true });
    }
  });

  it("isGithubAuthFailure: 401 / login prompts are auth; plain metadata errors are not", () => {
    expect(isGithubAuthFailure(Object.assign(new Error("HTTP 401"), { status: 401 }))).toBe(
      true,
    );
    expect(
      isGithubAuthFailure(new Error("To re-authenticate, please run: gh auth login")),
    ).toBe(true);
    expect(isGithubAuthFailure(new Error("unexpected gh issue payload"))).toBe(false);
    expect(isGithubAuthFailure(new SyntaxError("bad JSON contract"))).toBe(false);
  });

  it("admitPlannedRouteSmoke aggregates every required failure after Promise.all", async () => {
    const routeA = {
      slots: { coder: "codex/gpt-5.4" },
      smoke: {},
    } as unknown as ResolvedModelRoute;
    const routeB = {
      slots: { coder: "claude/opus" },
      smoke: {},
    } as unknown as ResolvedModelRoute;
    const backend = {
      async smokeModelRoute(route: ResolvedModelRoute) {
        const coder = route.slots.coder;
        throw new Error(`nonce smoke failed for ${coder}`);
      },
    } as unknown as Backend;
    const result = await admitPlannedRouteSmoke(backend, [routeA, routeB]);
    expect(result.kind).toBe("stop");
    if (result.kind === "stop") {
      expect(result.escalation.diagnosis).toMatch(/codex\/gpt-5\.4/);
      expect(result.escalation.diagnosis).toMatch(/claude\/opus/);
      expect(result.escalation.diagnosis).toMatch(/;/);
    }
  });

});
