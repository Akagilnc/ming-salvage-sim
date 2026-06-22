# Epic #330 — runner=纯调度器 / 每步是 worker — integration ledger

Slices merge to this base (`feat/330-pure-scheduler`) as per-slice cmr converges;
one family PR to main at the END (per family-slices-merge-to-base). Dependency
unblocking keys off THIS ledger (merged), NOT GitHub-closed.

## Merged
- **#322** integrated cmr consumes llmResolvedChildren — `feat/330-s322` @ df14696 — additive FOCUS段 (names machine-touched children, full diff still reviewed; omit ⇒ back-compat). per-slice cmr: codex+agy both converged R1 (no findings; agy recovered). 644 pass.
- **#331** unified dispatchWorker seam (prefactor) — `feat/330-s331` @ f197d99 — per-slice cmr: codex R1→R7 converged; 本轮缺 gemini (agy down, codex-solo). tsc clean + 639 tests pass on merged base. Behavior unchanged (legacy wrapper); WorkerResult union + per-worker schemas + DispatchContext + ledger widened + all call-sites routed; ADR 0026 invariant enforced (normal fix never takes resumeSession).
- **#332** 2a minimal coder image — `feat/330-s332` @ 5013fea — per-slice cmr: codex 3 findings (2 fixed, 1 deferred-downstream). Built `ming-orchestrator-coder:latest`; baked /tdd closure (tdd→codebase-design + diagnosing-bugs) + coder soul + CLAUDE.md `## Skill routing`. Demo verified: container agent Skill-invoked /tdd, test-first, RED→GREEN.

## Carried cross-slice notes (act in the named slice)
- → **#334** (or runner-refactor): drop the RealBackend runtime `skillsMount` bind-mount (`realBackend.ts` ~1750) — it masks #332's baked skills; until dropped, baked skills are shadowed at runtime. (Changing it = behavior change, so NOT #331 prefactor.)
- → **#333** (2b): builds on #332 image; bake ak-cross-m-review + gstack-ship + /review (with closures) + codex/agy CLI; agy auth via runtime-mounted token (`~/.sc-agy-oauth-token`), NOT baked; writable `CODEX_HOME` (per-issue copy); codex bwrap needs userns in non-privileged containers; then flip CLAUDE.md slice-end `/review` route from "reviewer worker / 2b" to active.

## Pending
- #322/#329 (follow-ups, off #331 seam) running.
- #334/#335/#336 await #333 (need #331✓ + #333).
- #333 (2b image) launchable now (←#332 merged).
- #337 (fix + runner 收口) last (←#334,#335,#336).
