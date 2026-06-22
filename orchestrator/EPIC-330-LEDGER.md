# Epic #330 — runner=纯调度器 / 每步是 worker — integration ledger

Slices merge to this base (`feat/330-pure-scheduler`) as per-slice cmr converges;
one family PR to main at the END (per family-slices-merge-to-base). Dependency
unblocking keys off THIS ledger (merged), NOT GitHub-closed.

## Merged
- **#334** coder→/tdd + reviewer→/review workers via seam; dropped runtime skillsMount — `feat/330-s334` @ d18fcd0 — tsc clean + 656 pass. e2e: container coder invoked /tdd. per-slice cmr: agy converged; codex 1 finding **deferred P2** → reviewer prompt/CLAUDE.md/baked-soul still say human "two passes per slice"; orchestrator decomposition = per-slice /review (loop) + ak-cross-m-review = integrated cmr (#335). Align prompt+CLAUDE.md+soul (+image rebuild) in #337 收口.
- **#333** 2b full-pack worker image — `feat/330-s333` @ 1a41f33 — extends 2a; baked full dev-skill pack + closures (tdd/codebase-design/diagnosing-bugs/improve-codebase-architecture/resolving-merge-conflicts/ak-cross-m-review/gstack-ship) + all souls (coder/reviewer/merger) + agy(Linux)/gh/bun; CLAUDE.md /review route active. e2e VERIFIED: ak-cross-m-review fanned out (codex rc=0 + agy file-token both caught injected bug), gstack-ship resolves+runs. codex review converged. image ming-orchestrator-coder:latest 3.52GB reproducible.
- **#329** S0 fetchIssueMeta slim view — `feat/330-s329` @ 0af2b56 — narrowed gh issue-view to number,labels (drop body/comments double-fetch); removed vestigial hasAgentBrief field; per-slice cmr codex+agy both converged R1. tests green.
- **#322** integrated cmr consumes llmResolvedChildren — `feat/330-s322` @ df14696 — additive FOCUS段 (names machine-touched children, full diff still reviewed; omit ⇒ back-compat). per-slice cmr: codex+agy both converged R1 (no findings; agy recovered). 644 pass.
- **#331** unified dispatchWorker seam (prefactor) — `feat/330-s331` @ f197d99 — per-slice cmr: codex R1→R7 converged; 本轮缺 gemini (agy down, codex-solo). tsc clean + 639 tests pass on merged base. Behavior unchanged (legacy wrapper); WorkerResult union + per-worker schemas + DispatchContext + ledger widened + all call-sites routed; ADR 0026 invariant enforced (normal fix never takes resumeSession).
- **#332** 2a minimal coder image — `feat/330-s332` @ 5013fea — per-slice cmr: codex 3 findings (2 fixed, 1 deferred-downstream). Built `ming-orchestrator-coder:latest`; baked /tdd closure (tdd→codebase-design + diagnosing-bugs) + coder soul + CLAUDE.md `## Skill routing`. Demo verified: container agent Skill-invoked /tdd, test-first, RED→GREEN.

## Carried cross-slice notes (act in the named slice)
- → **#334** (or runner-refactor): drop the RealBackend runtime `skillsMount` bind-mount (`realBackend.ts` ~1750, `realFamilyBackend.ts` ~374) — it masks #332/#333's baked skills; until dropped, baked skills are shadowed at runtime. (Changing it = behavior change, so NOT #331 prefactor.) #333's Containerfile comment is honest about this (bake makes skills present; #334 makes runtime use them).
- → **#335/#336** (cmr / ship workers): the 2b image (#333) bakes the CLIs + skills, but two pieces of RUNTIME wiring are still owed by the cmr/reviewer + ship worker steps:
  - **agy auth mount** — `box()` (`realBackend.ts`) today mounts ONLY codex auth. The reviewer/cmr worker needs the agy OAuth token mounted: host `~/.sc-agy-oauth-token` → container `/home/agent/.gemini/antigravity-cli/antigravity-oauth-token` (same copy/mount pattern as codex auth; spike+#333-verified the agy leg works with a file-mounted token). Without it the agy leg has no auth → cmr degrades to codex-only.
  - **codex userns** — codex's bundled bwrap can't make a userns in a non-privileged container → codex grounds on the hunk only (still caught the injected bug in #333 e2e). For full-repo codex grounding the worker's `docker(...)` launch needs userns enabled (`--security-opt seccomp=unconfined` + host `unprivileged_userns_clone=1`, or `--privileged`) OR codex's own sandbox disabled. Documented in #333 Containerfile.
  - **review-only cmr entrypoint** (nice-to-have): the reviewer worker runs `ak-cross-m-review` for findings only (the skill itself "does not commit — caller decides"; fix is the runner's fork per ADR 0026). A dedicated review-only cmr mode would make that explicit at the skill level.
- → **#332** (2a, retroactive): #333 closed a chain that was DANGLING in 2a — `diagnosing-bugs → improve-codebase-architecture` (improve wasn't baked in 2a). 2b bakes the full closure incl. `improve → {codebase-design, grilling, domain-modeling}`.

## Deferred (P2, address before family PR)
- review-decomposition consistency (#334 codex): per-slice /review vs human two-pass — align prompt/CLAUDE.md/reviewer-soul to the orchestrator split (per-slice /review + integrated ak-cross-m-review) + rebuild 2b image; do in #337.

## Pending
- #322/#329 (follow-ups, off #331 seam) running.
- #334/#335/#336 await #333 (need #331✓ + #333).
- #333 (2b image) launchable now (←#332 merged).
- #337 (fix + runner 收口) last (←#334,#335,#336).
