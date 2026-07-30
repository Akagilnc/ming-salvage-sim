/**
 * #1145 — shipped durable CLI is the sole worker capability (DecisionGate A).
 * Behavioral recovery is exercised via subprocess of bin.mjs, not a TS twin.
 */
import {
  mkdtempSync,
  rmSync,
  readFileSync,
  writeFileSync,
  existsSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { execFileSync, spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import {
  ensureOnlineReviewDurableDir,
  ONLINE_REVIEW_DURABLE_PATH_ENV,
} from "../src/family/onlineReviewActionDurable.js";
import { parseCollectorOutcome } from "../src/family/realFamilyBackend.js";

const BIN_SRC = fileURLToPath(
  new URL("../scripts/online-review-durable-bin.mjs", import.meta.url),
);

function runBin(
  hostPath: string,
  args: ReadonlyArray<string>,
  opts?: { readonly stdin?: string },
): { readonly status: number | null; readonly stdout: string; readonly stderr: string } {
  const result = spawnSync(process.execPath, [join(hostPath, "bin.mjs"), ...args], {
    env: {
      ...process.env,
      [ONLINE_REVIEW_DURABLE_PATH_ENV]: hostPath,
    },
    encoding: "utf8",
    input: opts?.stdin,
  });
  return {
    status: result.status,
    stdout: result.stdout ?? "",
    stderr: result.stderr ?? "",
  };
}

const HEAD_A = "head-a-1145";
const HEAD_B = "head-b-1145";
const PR_A = "pr://family/1145-a";
const PR_B = "pr://family/1145-b";

/** Namespace args: (round, head, resolved-current-PR). */
function ns(
  round: string | number,
  head: string,
  pr: string,
): readonly string[] {
  return ["--round", String(round), "--head", head, "--pr", pr];
}

/** Mirror bin.mjs processStarttime so lock identity fixtures match production. */
function processStarttime(pid: number): string | undefined {
  try {
    const raw = readFileSync(`/proc/${pid}/stat`, "utf8");
    const closeParen = raw.lastIndexOf(")");
    if (closeParen >= 0) {
      const rest = raw.slice(closeParen + 2).trim().split(/\s+/);
      const st = rest[19];
      if (typeof st === "string" && /^\d+$/.test(st)) return `linux:${st}`;
    }
  } catch {
    /* not Linux */
  }
  try {
    const out = execFileSync("ps", ["-o", "lstart=", "-p", String(pid)], {
      encoding: "utf8",
    }).trim();
    if (out.length > 0) return `ps:${out}`;
  } catch {
    /* ps unavailable */
  }
  return undefined;
}

describe("#1145 durable bin.mjs CLI (sole capability)", () => {
  it("evidence-put → progress-classify resume → evidence-get same handle (no re-wait)", () => {
    const workingRepo = mkdtempSync(join(tmpdir(), "or-bin-1145-"));
    try {
      const { hostPath } = ensureOnlineReviewDurableDir(workingRepo);
      // Ensure shipped bytes match package scripts source.
      expect(readFileSync(join(hostPath, "bin.mjs"), "utf8")).toBe(
        readFileSync(BIN_SRC, "utf8"),
      );

      const init = runBin(hostPath, ["progress-init", ...ns(1, HEAD_A, PR_A)]);
      expect(init.status).toBe(0);

      const body = JSON.stringify({
        sparse: true,
        marker: "same-handle-1145",
      });
      const put = runBin(
        hostPath,
        ["evidence-put", ...ns(1, HEAD_A, PR_A), "--file", "-"],
        { stdin: body },
      );
      expect(put.status).toBe(0);
      const putJson = JSON.parse(put.stdout) as { handle?: string };
      expect(typeof putJson.handle).toBe("string");
      const handle = putJson.handle!;
      expect(handle.startsWith("blobs/")).toBe(true);

      // Second open (fresh process) sees resume + same handle.
      const classify = runBin(hostPath, [
        "progress-classify",
        ...ns(1, HEAD_A, PR_A),
      ]);
      expect(classify.status).toBe(0);
      const classified = JSON.parse(classify.stdout) as {
        kind?: string;
        progress?: { evidenceHandle?: string; head?: string; pr?: string };
      };
      expect(classified.kind).toBe("resume");
      expect(classified.progress?.evidenceHandle).toBe(handle);
      expect(classified.progress?.head).toBe(HEAD_A);
      expect(classified.progress?.pr).toBe(PR_A);

      // evidence-get is handle-only; handle came from PR-scoped progress.
      const get = runBin(hostPath, ["evidence-get", "--handle", handle]);
      expect(get.status).toBe(0);
      expect(JSON.parse(get.stdout)).toEqual({
        sparse: true,
        marker: "same-handle-1145",
      });
    } finally {
      rmSync(workingRepo, { recursive: true, force: true });
    }
  });

  it("same-round new-head does not resume old evidence or old receipts", () => {
    const workingRepo = mkdtempSync(join(tmpdir(), "or-bin-headns-1145-"));
    try {
      const { hostPath } = ensureOnlineReviewDurableDir(workingRepo);
      const body = JSON.stringify({ marker: "old-head-evidence" });
      const put = runBin(
        hostPath,
        ["evidence-put", ...ns(1, HEAD_A, PR_A), "--file", "-"],
        { stdin: body },
      );
      expect(put.status).toBe(0);
      const handle = (JSON.parse(put.stdout) as { handle: string }).handle;

      const key = "resolve:discussion_old";
      expect(
        runBin(hostPath, [
          "receipt-succeeded",
          ...ns(1, HEAD_A, PR_A),
          "--key",
          key,
        ]).status,
      ).toBe(0);

      // Same round, new head → pristine (must not return A's handle/receipts).
      const classifyB = runBin(hostPath, [
        "progress-classify",
        ...ns(1, HEAD_B, PR_A),
      ]);
      expect(classifyB.status).toBe(0);
      expect(JSON.parse(classifyB.stdout)).toEqual({ kind: "pristine" });

      const receiptB = runBin(hostPath, [
        "receipt-get",
        ...ns(1, HEAD_B, PR_A),
        "--key",
        key,
      ]);
      expect(receiptB.status).toBe(0);
      expect(receiptB.stdout.trim()).toBe("null");

      // Old head still resumes its own namespace.
      const classifyA = runBin(hostPath, [
        "progress-classify",
        ...ns(1, HEAD_A, PR_A),
      ]);
      expect(JSON.parse(classifyA.stdout)).toMatchObject({
        kind: "resume",
        progress: { evidenceHandle: handle, head: HEAD_A, pr: PR_A },
      });
      const receiptA = runBin(hostPath, [
        "receipt-get",
        ...ns(1, HEAD_A, PR_A),
        "--key",
        key,
      ]);
      expect(JSON.parse(receiptA.stdout)).toMatchObject({
        state: "succeeded",
        head: HEAD_A,
        pr: PR_A,
      });
    } finally {
      rmSync(workingRepo, { recursive: true, force: true });
    }
  });

  it("same-round same-head replacement PR is pristine; old PR still resumes", () => {
    const workingRepo = mkdtempSync(join(tmpdir(), "or-bin-prns-1145-"));
    try {
      const { hostPath } = ensureOnlineReviewDurableDir(workingRepo);
      const sharedHead = HEAD_A;
      const body = JSON.stringify({ marker: "pr-a-evidence-1145" });

      // PR A: write evidence + succeeded retrigger/Verify receipt.
      const putA = runBin(
        hostPath,
        ["evidence-put", ...ns(1, sharedHead, PR_A), "--file", "-"],
        { stdin: body },
      );
      expect(putA.status).toBe(0);
      const handleA = (JSON.parse(putA.stdout) as { handle: string }).handle;
      expect(handleA.startsWith("blobs/")).toBe(true);

      const retriggerKey = "retrigger:bot-comment";
      const verifyKey = "resolve:discussion_r_pr_a";
      expect(
        runBin(hostPath, [
          "receipt-succeeded",
          ...ns(1, sharedHead, PR_A),
          "--seat",
          "collector",
          "--op",
          "retrigger",
          "--key",
          retriggerKey,
        ]).status,
      ).toBe(0);
      expect(
        runBin(hostPath, [
          "receipt-succeeded",
          ...ns(1, sharedHead, PR_A),
          "--seat",
          "verify",
          "--op",
          "resolve",
          "--key",
          verifyKey,
        ]).status,
      ).toBe(0);

      // Identical round/head, replacement PR B → pristine; no A handle/receipt.
      const classifyB = runBin(hostPath, [
        "progress-classify",
        ...ns(1, sharedHead, PR_B),
      ]);
      expect(classifyB.status).toBe(0);
      expect(JSON.parse(classifyB.stdout)).toEqual({ kind: "pristine" });

      const receiptRetriggerB = runBin(hostPath, [
        "receipt-get",
        ...ns(1, sharedHead, PR_B),
        "--key",
        retriggerKey,
      ]);
      expect(receiptRetriggerB.status).toBe(0);
      expect(receiptRetriggerB.stdout.trim()).toBe("null");

      const receiptVerifyB = runBin(hostPath, [
        "receipt-get",
        ...ns(1, sharedHead, PR_B),
        "--key",
        verifyKey,
      ]);
      expect(receiptVerifyB.status).toBe(0);
      expect(receiptVerifyB.stdout.trim()).toBe("null");

      // PR A still resumes its own namespace (handle + both receipts).
      const classifyA = runBin(hostPath, [
        "progress-classify",
        ...ns(1, sharedHead, PR_A),
      ]);
      expect(JSON.parse(classifyA.stdout)).toMatchObject({
        kind: "resume",
        progress: {
          evidenceHandle: handleA,
          head: sharedHead,
          pr: PR_A,
        },
      });
      expect(
        JSON.parse(
          runBin(hostPath, [
            "receipt-get",
            ...ns(1, sharedHead, PR_A),
            "--key",
            retriggerKey,
          ]).stdout,
        ),
      ).toMatchObject({ state: "succeeded", head: sharedHead, pr: PR_A });
      expect(
        JSON.parse(
          runBin(hostPath, [
            "receipt-get",
            ...ns(1, sharedHead, PR_A),
            "--key",
            verifyKey,
          ]).stdout,
        ),
      ).toMatchObject({ state: "succeeded", head: sharedHead, pr: PR_A });

      // Missing --pr fails closed on progress/receipt ops (not evidence-get).
      const missingPr = runBin(hostPath, [
        "progress-classify",
        "--round",
        "1",
        "--head",
        sharedHead,
      ]);
      expect(missingPr.status).not.toBe(0);
      expect(missingPr.stderr).toMatch(/--pr/i);
    } finally {
      rmSync(workingRepo, { recursive: true, force: true });
    }
  });

  it("receipt-decide: attempted + applied → skip; unknown → escalate", () => {
    const workingRepo = mkdtempSync(join(tmpdir(), "or-bin-receipt-1145-"));
    try {
      const { hostPath } = ensureOnlineReviewDurableDir(workingRepo);
      const key = "resolve:discussion_r3652932124";
      const attempted = runBin(hostPath, [
        "receipt-attempted",
        ...ns(1, HEAD_A, PR_A),
        "--seat",
        "verify",
        "--op",
        "resolve",
        "--key",
        key,
        "--handle",
        "discussion_r3652932124",
      ]);
      expect(attempted.status).toBe(0);

      const decideApplied = runBin(hostPath, [
        "receipt-decide",
        ...ns(1, HEAD_A, PR_A),
        "--key",
        key,
        "--fact",
        "applied",
      ]);
      expect(decideApplied.status).toBe(0);
      expect(JSON.parse(decideApplied.stdout)).toMatchObject({
        action: "skip_already_done",
      });

      // After applied decide, receipt is succeeded — second decide still skips.
      const decideAgain = runBin(hostPath, [
        "receipt-decide",
        ...ns(1, HEAD_A, PR_A),
        "--key",
        key,
        "--fact",
        "applied",
      ]);
      expect(JSON.parse(decideAgain.stdout)).toMatchObject({
        action: "skip_already_done",
      });

      // Fresh key with attempted + unknown → escalate (no blind replay).
      const key2 = "reply:discussion_r999";
      runBin(hostPath, [
        "receipt-attempted",
        ...ns(1, HEAD_A, PR_A),
        "--seat",
        "verify",
        "--op",
        "reply",
        "--key",
        key2,
      ]);
      const decideUnknown = runBin(hostPath, [
        "receipt-decide",
        ...ns(1, HEAD_A, PR_A),
        "--key",
        key2,
        "--fact",
        "unknown",
      ]);
      expect(decideUnknown.status).toBe(0);
      expect(JSON.parse(decideUnknown.stdout)).toMatchObject({
        action: "escalate",
      });
    } finally {
      rmSync(workingRepo, { recursive: true, force: true });
    }
  });

  it("parseCollectorOutcome: entire body opaque incl. cargoPointer; no sidecar handle extract", () => {
    // Body shaped like a handle is still opaque evidence — transport handle
    // arrives only via typed station envelope merge, never sidecar extraction.
    const pointerShapedBody = parseCollectorOutcome(
      `<collector>${JSON.stringify({
        cargoPointer: "blobs/r1-handle-only",
      })}</collector>`,
    );
    expect(pointerShapedBody).toEqual({
      kind: "collector",
      evidence: { cargoPointer: "blobs/r1-handle-only" },
    });

    // cargoPointer key stays inside opaque body with siblings.
    const bodyAndPointer = parseCollectorOutcome(
      `<collector>${JSON.stringify({
        cargoPointer: "blobs/r1-both",
        evidence: {
          prUrl: "pr://x",
          headOid: "abc",
          marker: "kept",
        },
      })}</collector>`,
    );
    expect(bodyAndPointer).toEqual({
      kind: "collector",
      evidence: {
        cargoPointer: "blobs/r1-both",
        evidence: {
          prUrl: "pr://x",
          headOid: "abc",
          marker: "kept",
        },
      },
    });

    // Mixed body with top-level evidence object + siblings — no unwrap, full body.
    const mixed = parseCollectorOutcome(
      `<collector>${JSON.stringify({
        evidence: { threads: [{ id: "t1" }] },
        checkRuns: [{ name: "ci", status: "completed" }],
        marker: "mixed-body-1145",
      })}</collector>`,
    );
    expect(mixed).toEqual({
      kind: "collector",
      evidence: {
        evidence: { threads: [{ id: "t1" }] },
        checkRuns: [{ name: "ci", status: "completed" }],
        marker: "mixed-body-1145",
      },
    });

    // Top-level sidecar body (production form) — keyless blob verbatim.
    const keylessTopLevel = parseCollectorOutcome(
      `<collector>${JSON.stringify({
        sparse: true,
        marker: "keyless-body-1145",
      })}</collector>`,
    );
    expect(keylessTopLevel).toEqual({
      kind: "collector",
      evidence: { sparse: true, marker: "keyless-body-1145" },
    });

    // Empty / off-shape → opaque miss cargo (not throw / not process fail).
    expect(parseCollectorOutcome("<collector>{}</collector>")).toEqual({
      kind: "cargo",
    });
  });

  it("truncated final JSONL record after valid progress/receipt → progress-classify corrupt; blocks mutate", () => {
    const workingRepo = mkdtempSync(join(tmpdir(), "or-bin-corrupt-1145-"));
    try {
      const { hostPath } = ensureOnlineReviewDurableDir(workingRepo);

      expect(
        runBin(hostPath, ["progress-init", ...ns(1, HEAD_A, PR_A)]).status,
      ).toBe(0);

      const attempted = runBin(hostPath, [
        "receipt-attempted",
        ...ns(1, HEAD_A, PR_A),
        "--seat",
        "verify",
        "--op",
        "reply",
        "--key",
        "k-trunc-1145",
      ]);
      expect(attempted.status).toBe(0);

      const statePath = join(hostPath, "state.jsonl");
      const before = readFileSync(statePath, "utf8");
      expect(before.endsWith("\n")).toBe(true);
      // Crash mid-append: truncated final record, no trailing newline.
      writeFileSync(statePath, `${before}{"v":1,"kind":"collection_progress","round":1,"hea`);

      const classify = runBin(hostPath, [
        "progress-classify",
        ...ns(1, HEAD_A, PR_A),
      ]);
      expect(classify.status).toBe(0);
      const classified = JSON.parse(classify.stdout) as {
        kind?: string;
        reason?: string;
      };
      expect(classified.kind).toBe("corrupt");
      expect(classified.reason).toBe("unparseable_event");
      // Must not look pristine / resume past the broken tail.
      expect(classified.kind).not.toBe("pristine");
      expect(classified.kind).not.toBe("resume");

      // Mutation/append blocked — refuse to join the truncated fragment.
      const blockedInit = runBin(hostPath, [
        "progress-init",
        ...ns(2, HEAD_B, PR_B),
      ]);
      expect(blockedInit.status).not.toBe(0);
      expect(blockedInit.stderr).toMatch(/corrupt/i);

      const blockedReceipt = runBin(hostPath, [
        "receipt-attempted",
        ...ns(1, HEAD_A, PR_A),
        "--key",
        "k-after-corrupt",
      ]);
      expect(blockedReceipt.status).not.toBe(0);
      expect(blockedReceipt.stderr).toMatch(/corrupt/i);

      // File still ends with the truncated fragment (no silent join-append).
      expect(readFileSync(statePath, "utf8")).toBe(
        `${before}{"v":1,"kind":"collection_progress","round":1,"hea`,
      );
    } finally {
      rmSync(workingRepo, { recursive: true, force: true });
    }
  });

  it("host durable module is mount/copy surface only", async () => {
    const mod = await import("../src/family/onlineReviewActionDurable.js");
    expect(Object.keys(mod).sort()).toEqual(
      [
        "ONLINE_REVIEW_DURABLE_DIR",
        "ONLINE_REVIEW_DURABLE_PATH_ENV",
        "ONLINE_REVIEW_DURABLE_SANDBOX_PATH",
        "ensureOnlineReviewDurableDir",
        "onlineReviewDurableMount",
      ].sort(),
    );
  });

  it("owner-instance lease: live owner never stolen for age; stale other-container reclaimable", () => {
    const workingRepo = mkdtempSync(join(tmpdir(), "or-bin-lock-1145-"));
    try {
      const { hostPath } = ensureOnlineReviewDurableDir(workingRepo);
      const lockPath = join(hostPath, "state.jsonl.lock");

      const selfStart = processStarttime(process.pid);
      expect(selfStart).toBeTypeOf("string");

      // Crashed owner wreckage: lock file with a dead pid must not block forever.
      writeFileSync(
        lockPath,
        `${JSON.stringify({
          pid: 2_147_483_647,
          token: "dead-sandbox",
          starttime: "ps:Thu Jan  1 00:00:00 1970",
          ts: Date.now() - 60_000,
        })}\n`,
        "utf8",
      );
      const afterCrash = runBin(hostPath, [
        "progress-init",
        ...ns(1, HEAD_A, PR_A),
      ]);
      expect(afterCrash.status).toBe(0);
      expect(existsSync(lockPath)).toBe(false);

      // Fresh live lease: recent ts + matching live identity → CLI must time out.
      writeFileSync(
        lockPath,
        `${JSON.stringify({
          pid: process.pid,
          token: "live-holder",
          starttime: selfStart,
          ts: Date.now(),
        })}\n`,
        "utf8",
      );
      const blocked = runBin(hostPath, [
        "progress-set-epochs",
        ...ns(1, HEAD_A, PR_A),
        "--epochs",
        "1",
      ]);
      expect(blocked.status).not.toBe(0);
      expect(blocked.stderr).toMatch(/lock timeout/);
      expect(existsSync(lockPath)).toBe(true);

      // Live owner over TTL: same identity + old ts must still NOT be stolen.
      writeFileSync(
        lockPath,
        `${JSON.stringify({
          pid: process.pid,
          token: "live-over-ttl",
          starttime: selfStart,
          ts: Date.now() - 60_000,
        })}\n`,
        "utf8",
      );
      const stillBlocked = runBin(hostPath, [
        "progress-set-epochs",
        ...ns(1, HEAD_A, PR_A),
        "--epochs",
        "1",
      ]);
      expect(stillBlocked.status).not.toBe(0);
      expect(stillBlocked.stderr).toMatch(/lock timeout/);
      expect(existsSync(lockPath)).toBe(true);

      // Stale other-container: same numeric PID, different starttime, stale ts
      // → distinguishable and reclaimable.
      writeFileSync(
        lockPath,
        `${JSON.stringify({
          pid: process.pid,
          token: "stale-other-container",
          starttime: "ps:Thu Jan  1 00:00:00 1970",
          ts: Date.now() - 60_000,
        })}\n`,
        "utf8",
      );
      const recoveredCollision = runBin(hostPath, [
        "progress-set-epochs",
        ...ns(1, HEAD_A, PR_A),
        "--epochs",
        "1",
      ]);
      expect(recoveredCollision.status).toBe(0);
      expect(existsSync(lockPath)).toBe(false);

      // After owner dies (dead pid + stale ts), reclaim succeeds.
      writeFileSync(
        lockPath,
        `${JSON.stringify({
          pid: 2_147_483_647,
          token: "dead-again",
          starttime: "ps:Thu Jan  1 00:00:00 1970",
          ts: Date.now() - 60_000,
        })}\n`,
        "utf8",
      );
      const recovered = runBin(hostPath, [
        "progress-set-epochs",
        ...ns(1, HEAD_A, PR_A),
        "--epochs",
        "2",
      ]);
      expect(recovered.status).toBe(0);
      expect(existsSync(lockPath)).toBe(false);
    } finally {
      rmSync(workingRepo, { recursive: true, force: true });
    }
  }, 30_000);
});
