// Round-2 编排器 dogfood — vanilla 启动 #362。
// 严禁注入 sh / 过滤 / 补丁（orchestrator/CLAUDE.md 规则）：读真实 tracker、默认 sh。
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";

// Derive paths from the script location + $HOME (gemini #384 R4: no hard-coded
// absolute home path, so it runs on any machine / for any user).
const ORCH = dirname(fileURLToPath(import.meta.url)); // .../orchestrator
const REPO = dirname(ORCH); // the repo root this orchestrator lives in

// #372 unconditional rebuild by construction: launcher always runs npx tsc +
// docker build BEFORE any worker dispatch (and before dynamic import of driver).
// Docker layer cache makes no-op near-zero cost; changed layers rebuild only
// affected parts. No staleness/ drift checks ever.
//
// When IMAGE_TAG is set, resolve once via shared resolver (exported from
// familyDriver) and pin the exact same tag for build.sh (env) + dispatch (imageName).
// Single source of truth prevents tag mismatch breaking the freshness guarantee.
console.log("[launcher] #372 unconditional: npx tsc + image build (before dispatch)");
// #859: build BESIDE the serving dist, then swap. The old "rm -rf dist" +
// rebuild left dist DELETED whenever any later step threw (missing npx, tsc
// error) — the serving copy every host worker resolves per-dispatch died with
// it. Building into dist.new keeps the serving dist intact until the fresh
// build fully exists; the same fresh-dist guarantee (no orphaned dist/*.js:
// the swap replaces the whole directory).
execFileSync("rm", ["-rf", "dist.new", "dist.old"], { cwd: ORCH, stdio: "inherit" });
execFileSync("npx", ["tsc", "--outDir", "dist.new"], { cwd: ORCH, stdio: "inherit" });
if (existsSync(join(ORCH, "dist"))) {
  execFileSync("mv", ["dist", "dist.old"], { cwd: ORCH, stdio: "inherit" });
}
execFileSync("mv", ["dist.new", "dist"], { cwd: ORCH, stdio: "inherit" });
execFileSync("rm", ["-rf", "dist.old"], { cwd: ORCH, stdio: "inherit" });

// Dynamic import AFTER recompile so this process gets fresh dist (static top
// import would have loaded stale compiled code even after disk rebuild).
// Import resolver too so launcher + driver share the exact same tag resolution.
const { runFamilyDriver, resolveImageTag, familyDriverExitCode } = await import(
  "./dist/familyDriver.js"
);
const imageTag = resolveImageTag(process.env.IMAGE_TAG);

execFileSync("bash", [join(ORCH, "image", "build.sh")], {
  cwd: ORCH,
  stdio: "inherit",
  env: { ...process.env, IMAGE_TAG: imageTag },
});

const result = await runFamilyDriver({
  epicIssue: 362,
  // clone-from = LOCAL repo (git hardlinks objects on same FS → near-instant, no
  // 400MB network download); push-to (remote) stays GitHub so ship opens the PR upstream.
  sourceRepo: REPO,
  remote: "https://github.com/Akagilnc/ming-salvage-sim.git",
  repo: "Akagilnc/ming-salvage-sim",
  familyBase: "family/362-base",
  base: "main",
  promptsDir: `${ORCH}/prompts`,
  familyPromptsDir: `${ORCH}/prompts`,
  soulsDir: `${ORCH}/image/souls`,
  ledgerDir: join(homedir(), ".sc-orchestrator", "dogfood-362-ledger"),
  imageName: imageTag,
  // 无 sh override、无 backend factory override = 真编排器 vanilla 跑
});

console.log("\n===== FAMILY RUN RESULT =====");
console.log(JSON.stringify(result, null, 2));
// #929 — business failures exit non-zero so drivers/cron classify without
// parsing logs. success / already_done → 0; every other terminal → unique code.
const exitCode = familyDriverExitCode(result);
console.log(`[launcher] exit ${exitCode} (terminal=${result.status})`);
process.exit(exitCode);
