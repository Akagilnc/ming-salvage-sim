# Epic #330 — runner=纯调度器 / 每步是 worker — integration ledger

Slices merge to this base (`feat/330-pure-scheduler`) as per-slice cmr converges;
one family PR to main at the END (per family-slices-merge-to-base). Dependency
unblocking keys off THIS ledger (merged), NOT GitHub-closed.

## Merged
- **#332** 2a minimal coder image — `feat/330-s332` @ 5013fea — per-slice cmr: codex 3 findings (2 fixed, 1 deferred-downstream). Built `ming-orchestrator-coder:latest`; baked /tdd closure (tdd→codebase-design + diagnosing-bugs) + coder soul + CLAUDE.md `## Skill routing`. Demo verified: container agent Skill-invoked /tdd, test-first, RED→GREEN.

## Carried cross-slice notes (act in the named slice)
- → **#334** (or runner-refactor): drop the RealBackend runtime `skillsMount` bind-mount (`realBackend.ts` ~1750) — it masks #332's baked skills; until dropped, baked skills are shadowed at runtime. (Changing it = behavior change, so NOT #331 prefactor.)
- → **#333** (2b): builds on #332 image; bake ak-cross-m-review + gstack-ship + /review (with closures) + codex/agy CLI; agy auth via runtime-mounted token (`~/.sc-agy-oauth-token`), NOT baked; writable `CODEX_HOME` (per-issue copy); codex bwrap needs userns in non-privileged containers; then flip CLAUDE.md slice-end `/review` route from "reviewer worker / 2b" to active.

## Pending
- #331 (seam prefactor) running → on land: integrate, then unblock #322/#329 + #334/#335/#336.
- #333 (2b image) launchable now (←#332 merged).
- #337 (fix + runner 收口) last (←#334,#335,#336).
