// Round-2 编排器 dogfood — vanilla 启动 #362。
// 严禁注入 sh / 过滤 / 补丁（orchestrator/CLAUDE.md 规则）：读真实 tracker、默认 sh。
import { runFamilyDriver } from "./dist/familyDriver.js";

const ORCH = "/Users/akagilnc/WorkSpace/Ming_LLM/orchestrator";

const result = await runFamilyDriver({
  epicIssue: 362,
  // clone-from = LOCAL repo (git hardlinks objects on same FS → near-instant, no
  // 400MB network download); push-to (remote) stays GitHub so ship opens the PR upstream.
  sourceRepo: "/Users/akagilnc/WorkSpace/Ming_LLM",
  remote: "https://github.com/Akagilnc/ming-salvage-sim.git",
  repo: "Akagilnc/ming-salvage-sim",
  familyBase: "family/362-base",
  base: "main",
  promptsDir: `${ORCH}/prompts`,
  familyPromptsDir: `${ORCH}/prompts`,
  ledgerDir: "/Users/akagilnc/.sc-orchestrator/dogfood-362-ledger",
  imageName: "ming-orchestrator-coder:latest",
  skillsMount: "/Users/akagilnc/.claude/skills",
  // 无 sh override、无 backend factory override = 真编排器 vanilla 跑
});

console.log("\n===== FAMILY RUN RESULT =====");
console.log(JSON.stringify(result, null, 2));
