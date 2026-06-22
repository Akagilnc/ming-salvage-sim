/**
 * #292 — pure host-side logic for the dedicated-clone isolation base (ADR 0024).
 *
 * Zero-container, zero-git unit tests for the three pure helpers the
 * clone-isolation work introduces:
 *   - repoSlug:        sourceRepo (+remote) → a stable, collision-free slug
 *   - clonePathFor:    (home, slug, runKey) → the dedicated clone path
 *   - checkOwnGitDir:  git --git-common-dir verdict (own .git vs linked worktree)
 *
 * These mirror the codebase pattern (exported pure functions unit-tested without
 * a container), so the clone build + fail-closed guard logic is provable without
 * a real `git clone`.
 */

import { describe, expect, it } from "vitest";
import {
  checkOwnGitDir,
  clonePathFor,
  repoSlug,
} from "../src/realBackend.js";

describe("#292 repoSlug — collision-free slug for the clone path", () => {
  it("uses owner_repo when a github https remote is given", () => {
    expect(repoSlug("/anything", "https://github.com/Akagilnc/ming-salvage-sim.git")).toBe(
      "Akagilnc_ming-salvage-sim",
    );
  });

  it("uses owner_repo for a github ssh remote", () => {
    expect(repoSlug("/anything", "git@github.com:Akagilnc/ming-salvage-sim.git")).toBe(
      "Akagilnc_ming-salvage-sim",
    );
  });

  it("distinguishes same-named repos under different owners", () => {
    const a = repoSlug("/x", "https://github.com/alice/sim.git");
    const b = repoSlug("/x", "https://github.com/bob/sim.git");
    expect(a).not.toBe(b);
    expect(a).toBe("alice_sim");
    expect(b).toBe("bob_sim");
  });

  it("falls back to a hash for a non-parseable remote URL", () => {
    const slug = repoSlug("/x", "weird::not-a-url");
    expect(slug).toMatch(/^[0-9a-f]+$/);
  });

  it("falls back to a hash of the source abs path when there is NO remote", () => {
    const slug = repoSlug("/Users/me/WorkSpace/Ming_LLM", undefined);
    expect(slug).toMatch(/^[0-9a-f]+$/);
  });

  it("a no-remote local source gives a STABLE slug across calls (deterministic)", () => {
    const a = repoSlug("/Users/me/WorkSpace/Ming_LLM", undefined);
    const b = repoSlug("/Users/me/WorkSpace/Ming_LLM", undefined);
    expect(a).toBe(b);
  });

  it("distinct local sources without remotes give distinct slugs", () => {
    const a = repoSlug("/Users/me/repoA", undefined);
    const b = repoSlug("/Users/me/repoB", undefined);
    expect(a).not.toBe(b);
  });

  // ADR 0024 dec.1: "two distinct sources can never collide on one clone dir".
  // A non-GitHub nested-group remote must NOT slug down to its last two path
  // segments (which would collide groupA/sub/repo with groupB/sub/repo).
  it("distinct nested-group remotes under different top-level groups do NOT collide", () => {
    const a = repoSlug("/x", "https://gitlab.com/groupA/sub/repo.git");
    const b = repoSlug("/x", "https://gitlab.com/groupB/sub/repo.git");
    expect(a).not.toBe(b);
  });

  // The human-readable owner_repo slug is reserved for GitHub remotes (the only
  // host whose 2-segment owner/repo is the whole identity); anything else hashes
  // the FULL remote so no two distinct remotes can share a slug.
  it("a non-github 2-segment remote still does not collide with a same-tail github repo", () => {
    const gh = repoSlug("/x", "https://github.com/sub/repo.git");
    const gl = repoSlug("/x", "https://gitlab.com/sub/repo.git");
    expect(gh).not.toBe(gl);
  });

  // E (P3): a remote with trailing whitespace must still yield the human-readable
  // owner_repo slug, not silently fall back to a hash (repoSlug gates on trim()
  // but must also parse the trimmed value).
  it("a github remote with trailing whitespace still yields owner_repo", () => {
    expect(
      repoSlug("/x", "https://github.com/Akagilnc/ming-salvage-sim.git \n"),
    ).toBe("Akagilnc_ming-salvage-sim");
  });

  // ADR 0024 dec.1 (r2 codex): a NON-github remote that merely embeds
  // `@github.com` / `/github.com` in its PATH must NOT be slugged as a github
  // owner_repo — that would let it collide with the genuine github repo of the
  // same owner/name. github.com must be the actual HOST, not a path substring.
  it("a non-github remote with @github.com in its path does NOT slug as github", () => {
    const spoof = repoSlug(
      "/x",
      "https://evil.example/path@github.com/Akagilnc/ming-salvage-sim.git",
    );
    const real = repoSlug(
      "/x",
      "https://github.com/Akagilnc/ming-salvage-sim.git",
    );
    expect(spoof).not.toBe(real);
    expect(spoof).not.toBe("Akagilnc_ming-salvage-sim");
  });

  it("a non-github remote with /@github.com in its path does NOT slug as github", () => {
    const spoof = repoSlug("/x", "https://example.com/@github.com/sub/repo.git");
    expect(spoof).not.toBe("sub_repo");
    expect(spoof).toMatch(/^[0-9a-f]+$/); // hashed full remote
  });

  // D (P1, ADR + JSDoc): a no-remote LOCAL source must hash its ABSOLUTE path,
  // so the same repo referenced relatively (from any cwd) maps to one stable
  // clone — otherwise crash-resume lands on a different clone and breaks
  // idempotency (ADR 0024 dec.1 "退化为 source 绝对路径的 hash").
  it("a relative no-remote source hashes the same as its absolute form", () => {
    const abs = repoSlug(`${process.cwd()}/some-local-repo`, undefined);
    const rel = repoSlug("some-local-repo", undefined);
    expect(rel).toBe(abs);
  });
});

describe("#292 clonePathFor — dedicated clone path is run-key-addressed", () => {
  it("builds <home>/.sc-orchestrator/<slug>-iso-<runKey>", () => {
    expect(clonePathFor("/home/me", "Akagilnc_ming-salvage-sim", 291)).toBe(
      "/home/me/.sc-orchestrator/Akagilnc_ming-salvage-sim-iso-291",
    );
  });

  it("same run key → same path (idempotent addressing)", () => {
    const a = clonePathFor("/home/me", "slug", 292);
    const b = clonePathFor("/home/me", "slug", 292);
    expect(a).toBe(b);
  });

  it("different run keys → different paths (per-invocation isolation)", () => {
    const fam = clonePathFor("/home/me", "slug", 291);
    const single = clonePathFor("/home/me", "slug", 292);
    expect(fam).not.toBe(single);
  });
});

describe("#292 checkOwnGitDir — fail-closed guard verdict", () => {
  const clone = "/home/me/.sc-orchestrator/slug-iso-291";

  it("accepts when --git-common-dir is the clone's own .git (absolute)", () => {
    const v = checkOwnGitDir(`${clone}/.git`, clone);
    expect(v.ok).toBe(true);
  });

  it("accepts when --git-common-dir is the literal relative '.git'", () => {
    // git prints `.git` (relative) when run from the repo root of a normal clone.
    const v = checkOwnGitDir(".git", clone);
    expect(v.ok).toBe(true);
  });

  it("rejects a linked-worktree common dir pointing at a DIFFERENT repo's .git", () => {
    const v = checkOwnGitDir("/Users/me/WorkSpace/Ming_LLM/.git", clone);
    expect(v.ok).toBe(false);
    expect(v.commonDir).toBe("/Users/me/WorkSpace/Ming_LLM/.git");
  });

  it("rejects a worktrees/ subpath (linked worktree admin dir)", () => {
    const v = checkOwnGitDir(
      "/Users/me/WorkSpace/Ming_LLM/.git/worktrees/Ming_LLM-design",
      clone,
    );
    expect(v.ok).toBe(false);
  });
});
