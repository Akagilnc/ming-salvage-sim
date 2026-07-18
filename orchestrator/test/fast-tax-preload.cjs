const blocked = () => {
  throw new Error("[fast-tax-guard] native process spawn reached");
};
process.binding("spawn_sync").spawn = blocked;
process.binding("process_wrap").Process.prototype.spawn = blocked;

const childProcess = require("node:child_process");
const { syncBuiltinESMExports } = require("node:module");

for (const api of [
  "exec",
  "execFile",
  "execFileSync",
  "execSync",
  "fork",
  "spawn",
  "spawnSync",
]) {
  childProcess[api] = () => {
    throw new Error(`[fast-tax-guard] real process API reached: ${api}`);
  };
}

syncBuiltinESMExports();
