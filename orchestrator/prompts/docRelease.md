# 文档发布 worker entrypoint (#735 / S12)

Soul: `docRelease` (`/home/agent/.orchestrator/souls/docRelease.md`)

Invoke the baked **`/gstack-document-release`** skill on the current PR head
branch (non-interactive / spawned session — auto-decide VERSION-bump style
prompts; do not hang waiting for a human). Do not invent a parallel doc-writing
method outside the skill.

## Success contract

- Skill finishes successfully, **including 文档发布空跑** (no doc debt, no
  commit) → report `released: true`.
- If the skill created a commit, **you** push it to the PR head branch before
  reporting success. Push is part of S12 success; a local-only commit must not
  unlock merge against a stale remote tip.
- **Retry / residual HEAD**: if local branch is **ahead of remote PR tip**
  (e.g. prior attempt committed then crashed before push, and mechanical retry
  preserved that commit), **push that ahead HEAD** even when this skill run is
  a 文档发布空跑 with no *new* commit. `released:true` requires remote tip to
  match local HEAD when local was ahead.
- Do **not** wait for CI green inside this step. Merge-stage live readiness is
  the single wait point for checks / threads / ruleset.

## Failure

Worker crash, non-interactive hang/block, explicit skill failure, or required
push failure → `released: false` (or no valid tag). Auto-merge must not proceed.

## Output

Emit `<docRelease>` JSON. `DOCRELEASE_STEP_COMPLETE` is optional telemetry. Thin schema only:

```json
{"released": true}
```

or

```json
{"released": false}
```

Rules:

- `kind` is implied by the tag; JSON body is `{ "released": boolean }` only.
- No path-allowlist self-check is a success criterion (ADR 0123).
- Once the verdict is final, `DOCRELEASE_STEP_COMPLETE` is available as optional telemetry.
