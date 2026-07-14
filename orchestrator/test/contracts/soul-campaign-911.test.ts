/**
 * #911 — Soul campaign: Chinese character souls + container home env layer +
 * shared skills pool + project CLAUDE.md hygiene.
 *
 * Seams (issue AC):
 *   - soulsDir / REQUIRED_SOUL_FILES accepts the new soul set (cmr_* → verify.md
 *     relative symlinks; no output_protocol.md)
 *   - home environment dual-mount (claude CLAUDE.md + codex AGENTS.md replacement)
 *   - Containerfile skills → ~/.agents/skills + compat symlink from .claude/skills
 */

import {
  existsSync,
  lstatSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  readlinkSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { afterAll, afterEach, describe, expect, it } from "vitest";

import {
  REQUIRED_SOUL_FILES,
  RealBackend,
  SANDBOX_CODEX_DIR,
  SANDBOX_HOME_CLAUDE_MD,
  homeClaudeMount,
  homeEnvFileFromSoulsDir,
  provisionCodexHomeAgents,
  soulsDirError,
  soulsMount,
} from "../../src/realBackend.js";
import { RealFamilyBackend } from "../../src/family/realFamilyBackend.js";

const here = dirname(fileURLToPath(import.meta.url));
const imageDir = join(here, "..", "..", "image");
const soulsDir = join(imageDir, "souls");
const homeEnvFile = join(imageDir, "home", "CLAUDE.md");
const promptsDir = join(here, "..", "..", "prompts");
const containerfile = join(imageDir, "Containerfile");
const repoRoot = join(here, "..", "..", "..");

const tempHomes: string[] = [];
function cleanup(): void {
  while (tempHomes.length > 0) {
    const home = tempHomes.pop();
    if (home !== undefined) rmSync(home, { recursive: true, force: true });
  }
}
afterEach(cleanup);
afterAll(cleanup);

function norm(text: string): string {
  return text.replace(/\s+/g, " ").trim();
}

describe("#911 souls inventory + REQUIRED_SOUL_FILES", () => {
  it("REQUIRED_SOUL_FILES matches on-disk souls and excludes output_protocol.md", () => {
    const onDisk = readdirSync(soulsDir)
      .filter((name) => !name.startsWith("."))
      .sort();
    const required = [...REQUIRED_SOUL_FILES].sort();
    expect(required).toEqual(onDisk);
    expect(REQUIRED_SOUL_FILES).not.toContain("output_protocol.md");
    expect(existsSync(join(soulsDir, "output_protocol.md"))).toBe(false);
    expect(REQUIRED_SOUL_FILES).toContain("verify.md");
    expect(REQUIRED_SOUL_FILES).toContain("cmr_completeness.md");
    expect(REQUIRED_SOUL_FILES).toContain("cmr_correctness.md");
  });

  it("cmr_completeness.md and cmr_correctness.md are relative symlinks to verify.md", () => {
    for (const name of ["cmr_completeness.md", "cmr_correctness.md"]) {
      const path = join(soulsDir, name);
      expect(lstatSync(path).isSymbolicLink()).toBe(true);
      expect(readlinkSync(path)).toBe("verify.md");
      // existsSync follows the link — target must resolve.
      expect(existsSync(path)).toBe(true);
      expect(readFileSync(path, "utf8")).toBe(
        readFileSync(join(soulsDir, "verify.md"), "utf8"),
      );
    }
  });

  it("soulsDirError accepts the real image/souls set with zero missing", () => {
    const missing = REQUIRED_SOUL_FILES.filter((f) => !existsSync(join(soulsDir, f)));
    expect(missing).toEqual([]);
    expect(soulsDirError(soulsDir, true, true, [])).toBeUndefined();
  });

  it("cmr.md index points both pass souls at verify.md via symlink names", () => {
    const index = readFileSync(join(soulsDir, "cmr.md"), "utf8");
    expect(index).toMatch(/cmr_completeness\.md/);
    expect(index).toMatch(/cmr_correctness\.md/);
    expect(index).toMatch(/verify\.md/);
  });

  it("role souls are the Chinese character editions (verbatim anchors)", () => {
    const coder = readFileSync(join(soulsDir, "coder.md"), "utf8");
    expect(coder).toMatch(/# Coder soul（切片工匠）/);
    expect(coder).toMatch(/简洁是第一美德/);
    expect(coder).toMatch(/refusedFindingIdentityKeys/);

    const reviewer = readFileSync(join(soulsDir, "reviewer.md"), "utf8");
    expect(reviewer).toMatch(/# Reviewer soul（per-slice 评审）/);
    expect(reviewer).toMatch(/测试的质量重于代码的质量/);
    expect(reviewer).toMatch(/交卷契约/);

    const verify = readFileSync(join(soulsDir, "verify.md"), "utf8");
    expect(verify).toMatch(/# Verify soul（审卷官）/);
    expect(verify).toMatch(/钉子令牌/);
    expect(verify).toMatch(/钉上刻字/);
    expect(verify).toMatch(/accepted_suppressed/);

    const fixer = readFileSync(join(soulsDir, "fixer.md"), "utf8");
    expect(fixer).toMatch(/# Fixer soul（线上 PR 评审环修复工）/);
    expect(fixer).toMatch(/过度防御/);
    expect(fixer).toMatch(/修类不修点/);

    for (const [name, title] of [
      ["merger.md", "# Merger soul（orchestrator worker）"],
      ["ship.md", "# Ship soul（orchestrator worker）"],
      ["docRelease.md", "# DocRelease soul（文档发布 / S12）"],
    ] as const) {
      expect(readFileSync(join(soulsDir, name), "utf8")).toContain(title);
    }
  });
});

describe("#911 container home environment dual-mount", () => {
  it("image/home/CLAUDE.md exists with the container work-env body", () => {
    expect(existsSync(homeEnvFile)).toBe(true);
    const body = readFileSync(homeEnvFile, "utf8");
    expect(body).toMatch(/# 容器工作环境（worker 必读）/);
    expect(body).toMatch(/没 commit 的等于没做/);
    expect(body).toMatch(/~\/\.agents\/skills/);
  });

  it("homeEnvFileFromSoulsDir resolves sibling image/home/CLAUDE.md", () => {
    expect(homeEnvFileFromSoulsDir(soulsDir)).toBe(homeEnvFile);
  });

  it("homeClaudeMount is readonly at /home/agent/.claude/CLAUDE.md", () => {
    expect(homeClaudeMount(homeEnvFile)).toEqual({
      hostPath: homeEnvFile,
      sandboxPath: SANDBOX_HOME_CLAUDE_MD,
      readonly: true,
    });
    expect(SANDBOX_HOME_CLAUDE_MD).toBe("/home/agent/.claude/CLAUDE.md");
  });

  it("provisionCodexHomeAgents writes AGENTS.md into the per-issue auth dir", () => {
    const authDir = mkdtempSync(join(tmpdir(), "codex-auth-911-"));
    tempHomes.push(authDir);
    provisionCodexHomeAgents(authDir, homeEnvFile);
    const agents = join(authDir, "AGENTS.md");
    expect(existsSync(agents)).toBe(true);
    expect(readFileSync(agents, "utf8")).toBe(readFileSync(homeEnvFile, "utf8"));
  });

  class StubBackend extends RealBackend {
    protected override cloneDirExists(): boolean {
      return true;
    }
    protected override sh(file: string, args: string[]): string {
      if (file === "git" && args[0] === "rev-parse" && args[1] === "--git-common-dir") {
        return ".git";
      }
      return "";
    }
    public config(spec: {
      role: "coder";
      soul: "coder";
      model?: string;
    }): {
      mounts: ReadonlyArray<{ hostPath: string; sandboxPath: string; readonly?: boolean }>;
    } {
      return this.boxConfig(
        { authDir: "/tmp/auth-911", claudeToken: "tok", ghToken: "gho_test" },
        spec,
        911,
      );
    }
    public mount(issueNumber: number) {
      return this.mountAuth(issueNumber);
    }
  }

  function makeBackend(home: string): StubBackend {
    return new StubBackend({
      sourceRepo: "/tmp/source",
      remote: "https://github.com/owner/name.git",
      runKey: 911,
      repo: "owner/name",
      imageName: "ming-orchestrator-coder:latest",
      promptsDir,
      soulsDir,
      home,
    });
  }

  it("boxConfig live-mounts home CLAUDE.md (same freshness discipline as souls)", () => {
    const home = mkdtempSync(join(tmpdir(), "rb-home-911-"));
    tempHomes.push(home);
    const cfg = makeBackend(home).config({ role: "coder", soul: "coder" });
    expect(cfg.mounts).toContainEqual(homeClaudeMount(homeEnvFile));
    expect(cfg.mounts).toContainEqual(soulsMount(soulsDir));
  });

  it("mountAuth replaces AGENTS.md in the codex auth dir with the container home body", () => {
    const home = mkdtempSync(join(tmpdir(), "rb-home-911-auth-"));
    tempHomes.push(home);
    // Simulate a host AGENTS.md that must NOT leak into the worker.
    mkdirSync(join(home, ".codex"), { recursive: true });
    writeFileSync(join(home, ".codex", "AGENTS.md"), "# HOST OWNER AGENTS — must be replaced\n");
    writeFileSync(join(home, ".codex", "auth.json"), '{"tokens":{}}\n');

    const { authDir } = makeBackend(home).mount(911);
    expect(authDir.startsWith(join(home, ".sc-orchestrator"))).toBe(true);
    expect(existsSync(join(authDir, "AGENTS.md"))).toBe(true);
    expect(readFileSync(join(authDir, "AGENTS.md"), "utf8")).toBe(
      readFileSync(homeEnvFile, "utf8"),
    );
    expect(readFileSync(join(authDir, "AGENTS.md"), "utf8")).not.toMatch(
      /HOST OWNER AGENTS/,
    );
    // Codex mount still points at the per-issue auth dir.
    const cfg = makeBackend(home).config({ role: "coder", soul: "coder" });
    expect(cfg.mounts.some((m) => m.sandboxPath === SANDBOX_CODEX_DIR)).toBe(true);
  });
});

describe("#911 Containerfile skills shared pool", () => {
  it("bakes skills into ~/.agents/skills and keeps a .claude/skills compat symlink", () => {
    const cf = readFileSync(containerfile, "utf8");
    expect(cf).toMatch(/COPY skills\/\s+\/home\/agent\/\.agents\/skills\//);
    expect(cf).toMatch(
      /ln\s+-s(?:fn)?\s+\/home\/agent\/\.agents\/skills\s+\/home\/agent\/\.claude\/skills/,
    );
    // Old direct bake path must not remain as the primary COPY target.
    expect(cf).not.toMatch(/COPY skills\/\s+\/home\/agent\/\.claude\/skills\//);
    // codex bwrap userns runtime commentary removed (#911).
    expect(cf).not.toMatch(/codex ships its own bwrap sandbox/i);
  });
});

describe("#911 prompts: STEP_COMPLETE is mandatory multi-iter terminator, not optional telemetry", () => {
  const prompts = [
    "coder_implement.md",
    "coder_fix.md",
    "reviewer_review.md",
    "family_ship.md",
    "integrated_cmr_completeness.md",
    "integrated_cmr_correctness.md",
    "merger_resolve_conflict.md",
    "fixer.md",
    "verify.md",
    "docRelease.md",
  ];

  it("no dispatch prompt still calls STEP_COMPLETE optional telemetry (incl. split lines)", () => {
    for (const name of prompts) {
      const text = readFileSync(join(promptsDir, name), "utf8");
      const collapsed = norm(text);
      // Collapse whitespace so "optional\\ntelemetry" split-line misses fail.
      expect(collapsed, name).not.toMatch(
        /for optional telemetry, you may print \w+_step_complete/i,
      );
      expect(collapsed, name).not.toMatch(
        /completion signal is optional telemetry/i,
      );
      expect(collapsed, name).not.toMatch(
        /optional telemetry (and may be printed|line below may follow)/i,
      );
      // Positive: still frames STEP_COMPLETE as required terminator somewhere.
      expect(collapsed, name).toMatch(
        /must print \w+_step_complete|required sandcastle terminator|multi-iter completion signal is a required/i,
      );
    }
  });

  it("each multi-iter / terminal worker prompt still names its STEP_COMPLETE signal", () => {
    for (const [name, signal] of [
      ["coder_implement.md", "CODER_STEP_COMPLETE"],
      ["coder_fix.md", "CODER_STEP_COMPLETE"],
      ["reviewer_review.md", "REVIEWER_STEP_COMPLETE"],
      ["family_ship.md", "SHIP_STEP_COMPLETE"],
      ["integrated_cmr_completeness.md", "CMR_STEP_COMPLETE"],
      ["integrated_cmr_correctness.md", "CMR_STEP_COMPLETE"],
      ["merger_resolve_conflict.md", "MERGER_STEP_COMPLETE"],
      ["fixer.md", "FIXER_STEP_COMPLETE"],
      ["verify.md", "VERIFY_STEP_COMPLETE"],
      ["docRelease.md", "DOCRELEASE_STEP_COMPLETE"],
    ] as const) {
      const text = readFileSync(join(promptsDir, name), "utf8");
      expect(text).toContain(signal);
    }
  });

  it("every dispatch prompt documents $ORCHESTRATOR_OUTCOME_PATH after output_protocol deletion", () => {
    for (const name of prompts) {
      const text = readFileSync(join(promptsDir, name), "utf8");
      expect(text, name).toMatch(/\$ORCHESTRATOR_OUTCOME_PATH/);
    }
  });

  // B2: after #911 symlink-to-verify, integrated CMR prompts must still order
  // workers to read/obey runner-written focus+route parameter files FIRST.
  it("integrated CMR prompts mandate reading and obeying .cmr-focus.md + .cmr-route.json FIRST", () => {
    for (const name of [
      "integrated_cmr_completeness.md",
      "integrated_cmr_correctness.md",
    ] as const) {
      const text = readFileSync(join(promptsDir, name), "utf8");
      const collapsed = norm(text);
      expect(collapsed, name).toMatch(/\.cmr-focus\.md/);
      expect(collapsed, name).toMatch(/\.cmr-route\.json/);
      // Thin mandatory discipline — not merely "runner writes".
      // Filenames may be bare or fenced in backticks in the prompt prose.
      expect(collapsed, name).toMatch(
        /read and obey `?\.cmr-focus\.md`? and `?\.cmr-route\.json`? at the repo root FIRST/i,
      );
    }
  });

  // B3: when-path-is-set write obligation (not only the without-path tag fallback).
  it("integrated CMR prompts require writing terminal JSON to $ORCHESTRATOR_OUTCOME_PATH when set", () => {
    for (const name of [
      "integrated_cmr_completeness.md",
      "integrated_cmr_correctness.md",
    ] as const) {
      const text = readFileSync(join(promptsDir, name), "utf8");
      const collapsed = norm(text);
      expect(collapsed, name).toMatch(
        /when `?\$ORCHESTRATOR_OUTCOME_PATH`? is set,? write (the same terminal JSON object|.*JSON.*) (directly )?to that path/i,
      );
    }
  });
});

describe("#911 family dual-mount (RealFamilyBackend)", () => {
  class FamilyProbe extends RealFamilyBackend {
    public mergerCfg() {
      return this.mergerSandboxConfig({});
    }
    public shipCfg() {
      return this.shipSandboxConfig({ claudeToken: "tok" });
    }
    public cmrCfg() {
      return this.cmrSandboxConfig(
        { claudeToken: "tok" },
        [{ family: "codex", slug: "gpt-5.6-sol" }],
      );
    }
    public familyCoderCfg() {
      return this.familyCoderSandboxConfig(
        { claudeToken: "tok" },
        "sonnet",
        {},
        { path: "/tmp/outcome-911.json", sandboxPath: "/tmp/outcome.json" },
      );
    }
    public familyReviewLoopCfg() {
      return this.familyReviewLoopSandboxConfig(
        { claudeToken: "tok" },
        {
          id: "S3",
          kind: "reviewer",
          role: "reviewer",
          soul: "READ-ONLY",
          host: "claude",
          session: "fresh",
          contextRetention: "clean",
          promptFile: "reviewer_review.md",
          completionSignal: "REVIEWER_STEP_COMPLETE",
          maxIter: 1,
          model: "sonnet",
          toolchain: [],
        },
        {},
      );
    }
    public mountMerger() {
      return this.mountMergerAuth();
    }
    public mountCmr() {
      return this.mountCmrAuth();
    }
    public mountShip() {
      return this.mountShipAuth();
    }
  }

  function familyOpts(over: {
    home?: string;
    homeEnvFile?: string;
    workingRepo?: string;
    ledgerDir?: string;
  } = {}) {
    const home = over.home ?? mkdtempSync(join(tmpdir(), "fam-home-911-"));
    if (!over.home) tempHomes.push(home);
    const workingRepo = over.workingRepo ?? mkdtempSync(join(tmpdir(), "fam-repo-911-"));
    if (!over.workingRepo) tempHomes.push(workingRepo);
    const ledgerDir = over.ledgerDir ?? mkdtempSync(join(tmpdir(), "fam-ledger-911-"));
    if (!over.ledgerDir) tempHomes.push(ledgerDir);
    return {
      workingRepo,
      familyBase: "family/911-base",
      ledgerDir,
      repo: "owner/name",
      base: "main",
      promptsDir,
      soulsDir,
      imageName: "img",
      home,
      homeEnvFile: over.homeEnvFile,
    };
  }

  it("family merger + ship sandboxes live-mount home CLAUDE.md", () => {
    const be = new FamilyProbe(familyOpts());
    const expected = homeClaudeMount(homeEnvFile);
    expect(be.mergerCfg().mounts).toContainEqual(expected);
    expect(be.shipCfg().mounts).toContainEqual(expected);
  });

  // B6: more family sandbox configs must carry the home dual-mount (same mount helper).
  it("family cmr + coder-fix + review-loop sandboxes live-mount home CLAUDE.md", () => {
    const be = new FamilyProbe(familyOpts());
    const expected = homeClaudeMount(homeEnvFile);
    expect(be.cmrCfg().mounts).toContainEqual(expected);
    expect(be.familyCoderCfg().mounts).toContainEqual(expected);
    expect(be.familyReviewLoopCfg().mounts).toContainEqual(expected);
  });

  it("family mountMergerAuth writes container AGENTS.md into the codex auth dir", () => {
    const home = mkdtempSync(join(tmpdir(), "fam-auth-911-"));
    tempHomes.push(home);
    mkdirSync(join(home, ".codex"), { recursive: true });
    writeFileSync(join(home, ".codex", "auth.json"), '{"tokens":{}}\n');
    writeFileSync(join(home, ".codex", "AGENTS.md"), "# HOST OWNER — must be replaced\n");

    const be = new FamilyProbe(familyOpts({ home }));
    const auth = be.mountMerger();
    expect(auth.codexAuthDir).toBeTruthy();
    const agents = join(auth.codexAuthDir as string, "AGENTS.md");
    expect(existsSync(agents)).toBe(true);
    expect(readFileSync(agents, "utf8")).toBe(readFileSync(homeEnvFile, "utf8"));
    expect(readFileSync(agents, "utf8")).not.toMatch(/HOST OWNER/);
  });

  // B6: more codex auth provision paths replace host AGENTS.md with container home body.
  it("family mountCmrAuth + mountShipAuth write container AGENTS.md into codex auth dirs", () => {
    const home = mkdtempSync(join(tmpdir(), "fam-auth-911-cmr-ship-"));
    tempHomes.push(home);
    mkdirSync(join(home, ".codex"), { recursive: true });
    writeFileSync(join(home, ".codex", "auth.json"), '{"tokens":{}}\n');
    writeFileSync(join(home, ".codex", "AGENTS.md"), "# HOST OWNER — must be replaced\n");

    const be = new FamilyProbe(familyOpts({ home }));
    const expectedBody = readFileSync(homeEnvFile, "utf8");
    for (const [label, auth] of [
      ["cmr", be.mountCmr()],
      ["ship", be.mountShip()],
    ] as const) {
      expect(auth.codexAuthDir, label).toBeTruthy();
      const agents = join(auth.codexAuthDir as string, "AGENTS.md");
      expect(existsSync(agents), label).toBe(true);
      expect(readFileSync(agents, "utf8"), label).toBe(expectedBody);
      expect(readFileSync(agents, "utf8"), label).not.toMatch(/HOST OWNER/);
    }
  });

  it("missing home env file fails loud at RealFamilyBackend construction", () => {
    expect(
      () =>
        new FamilyProbe(
          familyOpts({ homeEnvFile: join(tmpdir(), "no-such-home-env-911-CLAUDE.md") }),
        ),
    ).toThrow(/home env file missing/);
  });
});

describe("#911 project CLAUDE.md / AGENTS.md hygiene", () => {
  it("drops global-duplicated rules and adds ADR 0062 skill-routing summary", () => {
    const claude = readFileSync(join(repoRoot, "Claude.md"), "utf8");
    // Deleted (global or relocated).
    expect(claude).not.toMatch(/所有 user-facing 输出用中文/);
    expect(claude).not.toMatch(/改仓库内容前要明确授权/);
    expect(claude).not.toMatch(/评审轮 = 独立 commit，禁止 amend/);
    expect(claude).not.toMatch(/PR 合并默认 merge commit/);
    expect(claude).not.toMatch(/PR 标题冠平台前缀/);
    expect(claude).not.toMatch(/设计文档（ADR\/契约\/spec）与代码同等评审/);
    expect(claude).not.toMatch(/进 ship-pre \/ CMR 评审循环前必须确认 feature 全闭环完成/);
    // Kept project knowledge.
    expect(claude).toMatch(/金手指/);
    // ADR 0062 summary in Skill routing.
    expect(claude).toMatch(/ADR 0062/);
    expect(norm(claude)).toMatch(/三信号|three signals|三.?信号/i);
  });

  it("AGENTS.md is a thin pointer to CLAUDE.md", () => {
    const agents = readFileSync(join(repoRoot, "Agents.md"), "utf8");
    expect(agents).toMatch(/CLAUDE\.md/);
    expect(agents).not.toMatch(/评审轮 = 独立 commit/);
    expect(agents).not.toMatch(/改仓库内容前要明确授权词/);
  });

  it("ship-pre DoD closed-loop checklist lives in docs/DEV_WORKFLOW.md", () => {
    const doc = readFileSync(join(repoRoot, "docs", "DEV_WORKFLOW.md"), "utf8");
    expect(doc).toMatch(/ship-pre/);
    expect(doc).toMatch(/全闭环|Definition of Done|DoD/);
    expect(doc).toMatch(/写入端/);
  });
});
