/**
 * #899 — host-only reviewer artifact pointers must become sandbox-visible
 * before the fixer container reads the fix-findings landing.
 */
import {
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import {
  materializeRawReviewerArtifactsForSandbox,
  RAW_REVIEWER_SIDECAR_SANDBOX_FILE,
  RAW_REVIEWER_STDOUT_SANDBOX_FILE,
} from "../../src/rawReviewerArtifacts.js";

const dirs: string[] = [];
afterEach(() => {
  while (dirs.length > 0) {
    const d = dirs.pop();
    if (d !== undefined) rmSync(d, { recursive: true, force: true });
  }
});

function tempDir(prefix: string): string {
  const d = mkdtempSync(join(tmpdir(), prefix));
  dirs.push(d);
  return d;
}

describe("materializeRawReviewerArtifactsForSandbox", () => {
  it("copies host stdout/sidecar into sandbox cwd and rewrites paths", () => {
    const host = tempDir("raw-art-host-");
    const sandbox = tempDir("raw-art-sandbox-");
    const hostStdout = join(host, "S3.log");
    const hostSidecar = join(host, "S3.result.json");
    writeFileSync(hostStdout, "stdout body\n", "utf8");
    writeFileSync(hostSidecar, '{"findingsCount":2}\n', "utf8");

    const out = materializeRawReviewerArtifactsForSandbox(
      {
        stdoutPath: hostStdout,
        sidecarPath: hostSidecar,
        reviewerSessionId: "sess-1",
        statement: "the previous reviewer raw artifacts are here",
      },
      sandbox,
    );

    expect(out).toEqual({
      stdoutPath: RAW_REVIEWER_STDOUT_SANDBOX_FILE,
      sidecarPath: RAW_REVIEWER_SIDECAR_SANDBOX_FILE,
      reviewerSessionId: "sess-1",
      statement: "the previous reviewer raw artifacts are here",
    });
    expect(readFileSync(join(sandbox, RAW_REVIEWER_STDOUT_SANDBOX_FILE), "utf8")).toBe(
      "stdout body\n",
    );
    expect(readFileSync(join(sandbox, RAW_REVIEWER_SIDECAR_SANDBOX_FILE), "utf8")).toBe(
      '{"findingsCount":2}\n',
    );
  });

  it("omits missing host paths rather than leaving absolute host-only pointers", () => {
    const sandbox = tempDir("raw-art-missing-");
    const out = materializeRawReviewerArtifactsForSandbox(
      {
        stdoutPath: "/no/such/host/stdout.log",
        sidecarPath: "/no/such/host/sidecar.json",
        reviewerSessionId: "sess-missing",
        statement: "the previous reviewer raw artifacts are here",
      },
      sandbox,
    );
    expect(out).toEqual({
      reviewerSessionId: "sess-missing",
      statement: "the previous reviewer raw artifacts are here",
    });
    expect(out.stdoutPath).toBeUndefined();
    expect(out.sidecarPath).toBeUndefined();
  });
});
