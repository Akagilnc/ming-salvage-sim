# Epic #330 — runner=纯调度器 / 每步是 worker — integration ledger

Slices merge to this base (`feat/330-pure-scheduler`) as per-slice cmr converges;
one family PR to main at the END (per family-slices-merge-to-base). Dependency
unblocking keys off THIS ledger (merged), NOT GitHub-closed.

## Merged
- **#332** 2a minimal coder image — `feat/330-s332` @ 5013fea — per-slice cmr: codex 3 findings (2 fixed, 1 deferred-downstream). Built `ming-orchestrator-coder:latest`; baked /tdd closure (tdd→codebase-design + diagnosing-bugs) + coder soul + CLAUDE.md `## Skill routing`. Demo verified: container agent Skill-invoked /tdd, test-first, RED→GREEN.

## Carried cross-slice notes (act in the named slice)
- → **#334** (or runner-refactor): drop the RealBackend runtime `skillsMount` bind-mount (`realBackend.ts` ~1750, `realFamilyBackend.ts` ~374) — it masks #332/#333's baked skills; until dropped, baked skills are shadowed at runtime. (Changing it = behavior change, so NOT #331 prefactor.) #333's Containerfile comment is honest about this (bake makes skills present; #334 makes runtime use them).
- → **#335/#336** (cmr / ship workers): the 2b image (#333) bakes the CLIs + skills, but two pieces of RUNTIME wiring are still owed by the cmr/reviewer + ship worker steps:
  - **agy auth mount** — `box()` (`realBackend.ts`) today mounts ONLY codex auth. The reviewer/cmr worker needs the agy OAuth token mounted: host `~/.sc-agy-oauth-token` → container `/home/agent/.gemini/antigravity-cli/antigravity-oauth-token` (same copy/mount pattern as codex auth; spike+#333-verified the agy leg works with a file-mounted token). Without it the agy leg has no auth → cmr degrades to codex-only.
  - **codex userns** — codex's bundled bwrap can't make a userns in a non-privileged container → codex grounds on the hunk only (still caught the injected bug in #333 e2e). For full-repo codex grounding the worker's `docker(...)` launch needs userns enabled (`--security-opt seccomp=unconfined` + host `unprivileged_userns_clone=1`, or `--privileged`) OR codex's own sandbox disabled. Documented in #333 Containerfile.
  - **review-only cmr entrypoint** (nice-to-have): the reviewer worker runs `ak-cross-m-review` for findings only (the skill itself "does not commit — caller decides"; fix is the runner's fork per ADR 0026). A dedicated review-only cmr mode would make that explicit at the skill level.
- → **#332** (2a, retroactive): #333 closed a chain that was DANGLING in 2a — `diagnosing-bugs → improve-codebase-architecture` (improve wasn't baked in 2a). 2b bakes the full closure incl. `improve → {codebase-design, grilling, domain-modeling}`.

## Pending
- #331 (seam prefactor) running → on land: integrate, then unblock #322/#329 + #334/#335/#336.
- #333 (2b image) launchable now (←#332 merged).
- #337 (fix + runner 收口) last (←#334,#335,#336).
