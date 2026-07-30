/**
 * #1145 — shipped durable CLI is the sole worker capability (DecisionGate A).
 * Behavioral recovery is exercised via subprocess of bin.mjs, not a TS twin.
 */
import { mkdtempSync, rmSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
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

describe("#1145 durable bin.mjs CLI (sole capability)", () => {
  it("evidence-put → progress-classify resume → evidence-get same handle (no re-wait)", () => {
    const workingRepo = mkdtempSync(join(tmpdir(), "or-bin-1145-"));
    try {
      const { hostPath } = ensureOnlineReviewDurableDir(workingRepo);
      // Ensure shipped bytes match package scripts source.
      expect(readFileSync(join(hostPath, "bin.mjs"), "utf8")).toBe(
        readFileSync(BIN_SRC, "utf8"),
      );

      const init = runBin(hostPath, ["progress-init", "--round", "1"]);
      expect(init.status).toBe(0);

      const body = JSON.stringify({
        sparse: true,
        marker: "same-handle-1145",
      });
      const put = runBin(hostPath, ["evidence-put", "--round", "1", "--file", "-"], {
        stdin: body,
      });
      expect(put.status).toBe(0);
      const putJson = JSON.parse(put.stdout) as { handle?: string };
      expect(typeof putJson.handle).toBe("string");
      const handle = putJson.handle!;
      expect(handle.startsWith("blobs/")).toBe(true);

      // Second open (fresh process) sees resume + same handle.
      const classify = runBin(hostPath, ["progress-classify", "--round", "1"]);
      expect(classify.status).toBe(0);
      const classified = JSON.parse(classify.stdout) as {
        kind?: string;
        progress?: { evidenceHandle?: string };
      };
      expect(classified.kind).toBe("resume");
      expect(classified.progress?.evidenceHandle).toBe(handle);

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

  it("receipt-decide: attempted + applied → skip; unknown → escalate", () => {
    const workingRepo = mkdtempSync(join(tmpdir(), "or-bin-receipt-1145-"));
    try {
      const { hostPath } = ensureOnlineReviewDurableDir(workingRepo);
      const key = "resolve:discussion_r3652932124";
      const attempted = runBin(hostPath, [
        "receipt-attempted",
        "--round",
        "1",
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
        "--round",
        "1",
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
        "--round",
        "1",
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
        "--round",
        "1",
        "--seat",
        "verify",
        "--op",
        "reply",
        "--key",
        key2,
      ]);
      const decideUnknown = runBin(hostPath, [
        "receipt-decide",
        "--round",
        "1",
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

  it("parseCollectorOutcome: pointer-only is legal; any object body is verbatim; missing body is not fate", () => {
    const pointerOnly = parseCollectorOutcome(
      `<collector>${JSON.stringify({
        cargoPointer: "blobs/r1-handle-only",
      })}</collector>`,
    );
    expect(pointerOnly).toEqual({
      kind: "collector",
      cargoPointer: "blobs/r1-handle-only",
    });

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
      cargoPointer: "blobs/r1-both",
      evidence: {
        prUrl: "pr://x",
        headOid: "abc",
        marker: "kept",
      },
    });

    // Keyless body-only — no prUrl/headOid admission required.
    const keylessNested = parseCollectorOutcome(
      `<collector>${JSON.stringify({
        evidence: { sparse: true, marker: "keyless-body-1145" },
      })}</collector>`,
    );
    expect(keylessNested).toEqual({
      kind: "collector",
      evidence: { sparse: true, marker: "keyless-body-1145" },
    });

    // Top-level sidecar body (production form) — same keyless blob verbatim.
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
});
