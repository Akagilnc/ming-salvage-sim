/**
 * #335 — REAL-CONTAINER e2e for the family cmr worker.
 *
 * Gated behind RUN_CMR_E2E (it needs the 2b image `ming-orchestrator-coder:latest`
 * + live codex/agy/claude auth + docker), so the normal suite skips it. Run with:
 *
 *   RUN_CMR_E2E=1 npx vitest run test/family/cmr-worker-e2e-335.test.ts
 *
 * It builds a real git repo with a family base whose diff carries an INJECTED
 * cross-slice bug, then drives `RealFamilyBackend.dispatchWorker(cmrWorkerSpec())`
 * — the container's top-level claude invokes ak-cross-m-review (1 Agent + 2 CLI
 * legs) over the base diff and returns a verdict. We require the worker to RUN TO A
 * VERDICT: `completed` + a `cmr` payload + a boolean `converged` (codex cmr R3 — a
 * lenient `["completed","escalated","malformed"]` assertion passes even when the
 * fan-out never happened, so it proves nothing; this path must reach a real verdict).
 * We log but do NOT hard-assert `converged:false`: the LLM legs' judgement is the
 * system under proof, not deterministic. An escalate/malformed degradation is a
 * SEPARATE concern, not counted here as proof the path works.
 */

import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { homedir, tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it } from "vitest";

import { RealFamilyBackend } from "../../src/family/realFamilyBackend.js";
import { cmrWorkerSpec } from "../../src/family/dispatchFamilyWorker.js";

const here = dirname(fileURLToPath(import.meta.url));
const promptsDir = join(here, "..", "..", "prompts");
const soulsDir = join(here, "..", "..", "image", "souls");

const RUN = process.env.RUN_CMR_E2E !== undefined;

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

describe.skipIf(!RUN)("#335 cmr worker e2e — real 2b container fan-out", () => {
  it(
    "invokes ak-cross-m-review in-container and returns a structured verdict",
    async () => {
      // ── a real repo with main + a family base carrying an injected cross-slice bug ──
      // MUST live under $HOME: colima shares $HOME into the Docker VM, $TMPDIR is
      // NOT shared (the same spike constraint codex auth hit) — a repo under
      // $TMPDIR mounts EMPTY in the container → "not a git repository".
      const e2eRoot = join(homedir(), ".sc-orchestrator", "cmr-e2e");
      mkdirSync(e2eRoot, { recursive: true });
      const repo = mkdtempSync(join(e2eRoot, "repo-"));
      cleanups.push(repo);
      git(repo, "init", "-q", "-b", "main");
      git(repo, "config", "user.email", "t@t.t");
      git(repo, "config", "user.name", "t");
      git(repo, "config", "commit.gpgsign", "false");
      // slice A: a producer using a field name `userId`.
      writeFileSync(join(repo, "a.ts"), "export function emit() { return { userId: 1 }; }\n");
      git(repo, "add", "-A");
      execFileSync("git", ["commit", "-q", "-m", "main: slice A"], { cwd: repo });
      const startHead = git(repo, "rev-parse", "HEAD");

      const familyBase = "family/330-e2e";
      git(repo, "checkout", "-q", "-b", familyBase);
      // slice B merged onto the family base CONSUMES the wrong field name (`user_id`)
      // — a cross-slice seam bug per-slice review could not see.
      writeFileSync(
        join(repo, "b.ts"),
        "import { emit } from './a.js';\nexport function use() { return emit().user_id; }\n",
      );
      git(repo, "add", "-A");
      execFileSync("git", ["commit", "-q", "-m", "family: slice B (cross-slice mismatch)"], {
        cwd: repo,
      });

      const ledgerDir = mkdtempSync(join(tmpdir(), "cmr-e2e-ledger-"));
      cleanups.push(ledgerDir);

      const be = new RealFamilyBackend({
        workingRepo: repo,
        familyBase,
        ledgerDir,
        repo: "Akagilnc/ming-salvage-sim",
        base: "main",
        promptsDir,
        soulsDir,
        imageName: "ming-orchestrator-coder:latest",
        familyBaseStartHead: startHead,
      });

      const res = await be.dispatchWorker(cmrWorkerSpec(), { familyBase });

      // eslint-disable-next-line no-console
      console.log("[cmr-e2e] WorkerResult =", JSON.stringify(res, null, 2));
      if (process.env.CMR_E2E_OUT !== undefined) {
        writeFileSync(process.env.CMR_E2E_OUT, JSON.stringify(res, null, 2));
      }

      // The path is only PROVEN when the worker fanned out and converged a real
      // verdict (codex cmr R3): require completed + a cmr payload + a boolean
      // verdict. A malformed / escalate (no-fan-out) result is NOT proof — it would
      // pass a lenient `toContain` assertion while proving nothing about the path.
      // (If a degradation case is wanted, it belongs in its own explicit test.)
      expect(res.kind).toBe("completed");
      if (res.kind !== "completed") throw new Error(`cmr e2e: expected completed, got ${res.kind}`);
      expect(res.output.kind).toBe("cmr");
      if (res.output.kind !== "cmr") throw new Error("cmr e2e: expected a cmr payload");
      expect(typeof res.output.converged).toBe("boolean");
      // eslint-disable-next-line no-console
      console.log(
        `[cmr-e2e] converged=${res.output.converged}`,
        res.output.reason ?? "",
      );
    },
    20 * 60 * 1000, // up to 20 min: real cross-model fan-out in a container.
  );
});
