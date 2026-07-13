/**
 * #884 S8-T — static sole external-call chokepoint guard.
 *
 * Owner structural ruling: every external wait (subprocess exec, provider HTTP,
 * probe, relay ping, spawn, pipe) must pass the public surface of
 * `externalCall.ts` (`execFileWithTimeout` / `execFileAsyncWithTimeout` /
 * `withProviderTimeout` / `shWithClock` / `spawnDetached`). Clocks only —
 * retry lives in #879 `legTransientRetry`. A new unclocked seam is a red
 * test, not a reviewer finding.
 *
 * This test fails if source under `orchestrator/src/**` contains bare external
 * primitives outside the chokepoint allowlist.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));
const SRC_ROOT = join(here, "..", "..", "src");

/**
 * Sole home for value imports of node:child_process primitives and the timed
 * wrappers that production code must call.
 */
const CHOKEPOINT_RELS = new Set(["externalCall.ts"]);

/**
 * Sandcastle container runs already carry Sandcastle's own idle clock
 * (`idleTimeoutSeconds` on every production `sc.run`) plus #683 quota-probe
 * disposition on `AgentIdleTimeoutError` via `runAgentSandbox` /
 * family equivalents. Re-wrapping the third-party API would not add a stronger
 * wall; allow only the documented invoker seams that always pass idleTimeout.
 */
const SC_RUN_ALLOWLIST = new Set([
  "realBackend.ts",
  "family/realFamilyBackend.ts",
]);

/**
 * Global `fetch(` is only legal when raced under `withProviderTimeout`
 * (provider band). Sole production call site = zai probe in quotaProbe.ts.
 */
const FETCH_ALLOWLIST = new Set(["quotaProbe.ts"]);

function listTsFiles(dir: string): string[] {
  const out: string[] = [];
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    const st = statSync(full);
    if (st.isDirectory()) {
      out.push(...listTsFiles(full));
      continue;
    }
    if (name.endsWith(".ts") && !name.endsWith(".d.ts")) {
      out.push(full);
    }
  }
  return out;
}

/** Strip line/block comments so narrative mentions do not false-positive. */
function stripComments(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, (block) => block.replace(/[^\n]/g, " "))
    .replace(/(^|[^:])\/\/.*$/gm, "$1");
}

function valueBindingsFromChildProcessImport(importClause: string): string[] {
  // type-only import: `import type { ChildProcess } from …`
  if (/^\s*type\b/.test(importClause)) return [];
  const brace = importClause.match(/\{([^}]*)\}/);
  if (brace === null) {
    // default / namespace import of child_process is also a bare seam
    return importClause.trim().length > 0 ? ["*"] : [];
  }
  return brace[1]!
    .split(",")
    .map((part) => part.trim())
    .filter((part) => part.length > 0)
    .filter((part) => !/^type\s+/.test(part))
    .map((part) => {
      const [name] = part.split(/\s+as\s+/);
      return (name ?? part).trim();
    })
    .filter((name) => name.length > 0);
}

interface GuardFinding {
  readonly file: string;
  readonly kind: string;
  readonly detail: string;
}

function findingsFor(rel: string, raw: string): GuardFinding[] {
  const findings: GuardFinding[] = [];
  const src = stripComments(raw);
  const isChokepoint = CHOKEPOINT_RELS.has(rel);

  // Value import from node:child_process / child_process.
  // Clause is braced bindings OR namespace/default — never spans another import.
  const importRe =
    /import\s+((?:type\s+)?\{[^}]*\}|\*\s+as\s+[A-Za-z_$][\w$]*|[A-Za-z_$][\w$]*)\s+from\s+["'](?:node:)?child_process["']/g;
  let m: RegExpExecArray | null;
  while ((m = importRe.exec(src)) !== null) {
    const bindings = valueBindingsFromChildProcessImport(m[1] ?? "");
    if (bindings.length === 0) continue; // type-only OK everywhere
    if (!isChokepoint) {
      findings.push({
        file: rel,
        kind: "child_process-value-import",
        detail: `value import { ${bindings.join(", ")} } — route through externalCall.ts`,
      });
    }
  }

  // Bare call sites (even if re-exported) — chokepoint may call them.
  const callChecks: Array<{ re: RegExp; kind: string; allow: boolean }> = [
    {
      re: /\bexecFileSync\s*\(/g,
      kind: "bare-execFileSync",
      allow: isChokepoint,
    },
    {
      re: /\bexecFile\s*\(/g,
      kind: "bare-execFile",
      allow: isChokepoint,
    },
    {
      re: /\bspawnSync\s*\(/g,
      kind: "bare-spawnSync",
      allow: isChokepoint,
    },
    {
      re: /\bspawn\s*\(/g,
      kind: "bare-spawn",
      allow: isChokepoint,
    },
    {
      re: /\bnet\.connect\s*\(/g,
      kind: "bare-net.connect",
      allow: false,
    },
  ];
  for (const check of callChecks) {
    if (check.allow) continue;
    if (check.re.test(src)) {
      findings.push({
        file: rel,
        kind: check.kind,
        detail: "must go through externalCall chokepoint wrappers",
      });
    }
  }

  // sc.run — allow only documented sandcastle invokers (idleTimeoutSeconds clock).
  if (/\bsc\.run\s*\(/g.test(src) && !SC_RUN_ALLOWLIST.has(rel)) {
    findings.push({
      file: rel,
      kind: "bare-sc.run",
      detail:
        "Sandcastle sc.run only allowed in realBackend/realFamilyBackend (idleTimeoutSeconds + #683)",
    });
  }

  // raw fetch( — allow only probe path that races under withProviderTimeout.
  if (/\bfetch\s*\(/g.test(src) && !FETCH_ALLOWLIST.has(rel) && !isChokepoint) {
    findings.push({
      file: rel,
      kind: "bare-fetch",
      detail: "outbound fetch must race under withProviderTimeout (or live in allowlisted probe)",
    });
  }

  return findings;
}

describe("#884 S8-T sole external-call chokepoint (static guard)", () => {
  it("no bare exec/spawn/fetch/sc.run/net.connect outside chokepoint allowlist", () => {
    const files = listTsFiles(SRC_ROOT);
    expect(files.length).toBeGreaterThan(20);

    const all: GuardFinding[] = [];
    for (const full of files) {
      const rel = relative(SRC_ROOT, full).split("\\").join("/");
      const raw = readFileSync(full, "utf8");
      all.push(...findingsFor(rel, raw));
    }

    if (all.length > 0) {
      const report = all
        .map((f) => `  - ${f.file}: ${f.kind} — ${f.detail}`)
        .join("\n");
      expect.fail(
        `bare external seams outside chokepoint (route through externalCall.ts):\n${report}`,
      );
    }
  });

  it("chokepoint module still owns the child_process primitives", () => {
    const raw = readFileSync(join(SRC_ROOT, "externalCall.ts"), "utf8");
    expect(raw).toMatch(/from\s+["']node:child_process["']/);
    expect(raw).toMatch(/\bexecFile(?:Sync)?\b/);
    expect(raw).toMatch(/\bspawn\b/);
    // Public surface the rest of src must use (sync or async export form):
    for (const name of [
      "execFileWithTimeout",
      "execFileAsyncWithTimeout",
      "withProviderTimeout",
      "shWithClock",
      "spawnDetached",
    ]) {
      expect(raw).toMatch(
        new RegExp(`export (?:async )?function ${name}\\b`),
      );
    }
  });
});
