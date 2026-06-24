#!/usr/bin/env bash
# Build the Ming orchestrator worker image (#332 2a → #333 2b full pack;
# ADR 0026 / ADR 0016 bake).
#
# 2a (#332) baked the /tdd closure + coder soul so the coder worker could run.
# 2b (#333) EXTENDS that to the FULL coherent dev-skill pack so the cmr / ship /
# review / fix / merger workers can each invoke their skill — including each
# skill's internal-call closure (a missing internally-invoked skill breaks the
# chain). Non-cherry-pick: the coherent set the wiki + ADR 0016/0026 reference.
#
# Reproducible: this script stages a clean build context (resolving the host skill
# SYMLINKS into real dirs via `cp -RL`, so the closure is materialised into the
# image — not bind-mounted at runtime), then builds the Containerfile against it.
#
# Usage:
#   image/build.sh                 # build tag ming-orchestrator-coder:latest
#   IMAGE_TAG=foo:bar image/build.sh
#   BASE_IMAGE=sc-pipeline@sha256:... image/build.sh   # pin base by digest
#
# Requires: docker (colima ok) + the host dev skills present at
# ~/.claude/skills/{...} (symlinks ok), + the gstack plugin at ~/gstack
# (gstack-ship's closure lives under ~/.claude/skills/gstack -> ~/gstack).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
IMAGE_TAG="${IMAGE_TAG:-ming-orchestrator-coder:latest}"
BASE_IMAGE="${BASE_IMAGE:-sc-pipeline:latest}"
SKILLS_SRC="${SKILLS_SRC:-$HOME/.claude/skills}"

# ── The 2b full dev-skill pack + its internal-call closure ───────────────────
# Reference list traced from:
#   - ADR 0016 §spike 发现4 (the slice-dev skill group, line 40):
#       tdd + codebase-design + diagnosing-bugs + improve-codebase-architecture
#       + resolving-merge-conflicts  (+ `review`, which is a BUILTIN command, not
#       a disk skill — nothing to bake; the route stays active in CLAUDE.md)
#   - ADR 0026 (supersedes 0016's cmr/gstack exclusion): cmr/ship now bake too →
#       ak-cross-m-review + gstack-ship
# Internal-call closure (traced from each SKILL.md, must all be present or a chain
# breaks — see Containerfile comment for the graph):
#   tdd                            → codebase-design
#   diagnosing-bugs                → improve-codebase-architecture
#   improve-codebase-architecture  → codebase-design, grilling, domain-modeling
#   ak-cross-m-review              → diagnosing-bugs (cmr non-trivial-fix path)
#   codebase-design                → leaf
#   resolving-merge-conflicts      → leaf
#   grilling                       → leaf  (HITL design-tree walk; degrades to
#                                            prose in a headless worker, but baked
#                                            so the chain is not dangling)
#   domain-modeling                → leaf  (keeps the domain model current; HITL)
# So the disk-skill set below is closed under internal invocation.
SKILL_CLOSURE=(
  tdd
  codebase-design
  diagnosing-bugs
  improve-codebase-architecture
  resolving-merge-conflicts
  ak-cross-m-review
  grilling
  domain-modeling
)
# gstack-ship is handled separately (below): its on-disk layout is a symlink into
# the ~/gstack plugin and it hardcodes ~/.claude/skills/gstack/... helper paths,
# so it needs its closure subtree baked at that exact path — not a flat cp.
GSTACK_SRC="${GSTACK_SRC:-$HOME/gstack}"
# The roles whose souls we bake (all worker roles — ADR 0026 / #333 "全部角色 soul").
SOUL_ROLES=(coder reviewer merger cmr)

STAGE="$(mktemp -d "${TMPDIR:-/tmp}/ming-coder-img.XXXXXX")"
trap 'rm -rf "$STAGE"' EXIT

echo "[build] staging context at $STAGE"
mkdir -p "$STAGE/skills" "$STAGE/souls"

# ── 1. Resolve + copy the dev-skill closure (cp -RL dereferences symlinks) ────
# Prune each skill's run-artifact / eval / test cruft so the image stays lean and
# the content manifest hashes only the skill ITSELF (not stale local run dumps).
# Decide ONCE whether rsync is available. The `cp -RL` fallback exists ONLY for
# hosts that lack rsync — a present-but-FAILING rsync (rc 23 on a dangling symlink,
# rc 11 on disk-full, etc.) must FAIL-CLOSED, not silently fall back to a `cp -RL`
# that drops the exclude behaviour (esp. `.antigravitycli/` — the dangling-symlink
# dir the excludes are there to skip; a blanket cp would re-introduce that abort or
# bake the stray link). online review r1 (3 bots): the old `rsync || cp` masked a
# real rsync failure as a fail-open.
if command -v rsync >/dev/null 2>&1; then HAVE_RSYNC=1; else HAVE_RSYNC=0; fi
for skill in "${SKILL_CLOSURE[@]}"; do
  src="$SKILLS_SRC/$skill"
  if [ ! -e "$src" ]; then
    echo "[build] ERROR: required skill '$skill' not found at $src" >&2
    exit 1
  fi
  echo "[build]   baking skill: $skill"
  # rsync resolves symlinks (-L) like `cp -RL`, while EXCLUDING the run-artifact /
  # scratch dirs that aren't part of a skill's bakeable content. `.antigravitycli/`
  # is excluded specifically because it holds a stray runtime symlink that dangles
  # (points at a since-deleted host gemini config) — a plain `cp -RL` aborts the
  # whole copy on that dangling link (the bug this exclude fixes). NOTE: rsync -aL
  # still errors (rc 23) on ANY OTHER dangling symlink it encounters; we rely on
  # the excludes covering the known offenders rather than blanket-skipping dangling
  # links — and a real rsync error here is FATAL (fail-closed), never a silent cp.
  if [ "$HAVE_RSYNC" -eq 1 ]; then
    # rsync present: a non-zero exit is a REAL failure (dangling symlink not yet
    # excluded, disk full, etc.). Fail-closed so the broken closure can't ship.
    if ! rsync -aL --quiet \
        --exclude='outputs/' --exclude='eval/' --exclude='tests/' \
        --exclude='__pycache__/' --exclude='.antigravitycli/' \
        "$src/" "$STAGE/skills/$skill/"; then
      echo "[build] ERROR: rsync failed copying skill '$skill' from $src" >&2
      echo "[build]   (NOT falling back to cp -RL: that would drop the excludes —" >&2
      echo "[build]    esp. .antigravitycli/ — and either abort on the dangling link" >&2
      echo "[build]    or bake the stray symlink. Add an --exclude for the new" >&2
      echo "[build]    offender, or fix the source tree.)" >&2
      exit 1
    fi
  else
    # rsync ABSENT only: fall back to cp -RL (no exclude support; the dangling
    # `.antigravitycli/` link would abort it — but that is the no-rsync-host case
    # the comment above documents as the sole fallback path).
    cp -RL "$src" "$STAGE/skills/$skill"
  fi
  if [ ! -f "$STAGE/skills/$skill/SKILL.md" ]; then
    echo "[build] ERROR: $skill has no SKILL.md after copy" >&2
    exit 1
  fi
  # Drop non-runtime cruft (run outputs, evals, tests, __pycache__) — keeps the
  # manifest stable across local runs and the image small. backends/lib/scripts/
  # prompts are KEPT (ak-cross-m-review needs backends/{codex-review.sh,gemini.sh}
  # + lib + prompts).
  rm -rf "$STAGE/skills/$skill/outputs" \
         "$STAGE/skills/$skill/eval" \
         "$STAGE/skills/$skill/tests" 2>/dev/null || true
  find "$STAGE/skills/$skill" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
done

# ── 1b. gstack-ship + its hardcoded ~/.claude/skills/gstack closure ──────────
# gstack-ship/SKILL.md is a symlink into ~/gstack/ship and references 60+ helper
# files by the ABSOLUTE path ~/.claude/skills/gstack/{bin,scripts,ship,review,...}.
# So we bake a SUBSET of the gstack plugin at exactly that path (NOT the 1.1G
# whole plugin — only the closure gstack-ship actually reads, traced from
# ship/SKILL.md + ship/sections grep of ~/.claude/skills/gstack/ refs):
#   bin/        (config/diff-scope/version/etc. helper scripts — some need bun)
#   scripts/    (jargon-list.json + helpers)
#   ship/       (the gstack-ship SKILL.md + sections)
#   review/     (specialists + design-checklist read by ship's review-army)
#   ETHOS.md, gstack-upgrade/SKILL.md
# The big compiled helper bin/gstack-global-discover (58M) is NOT in the closure
# → excluded to keep the image lean.
if [ ! -d "$GSTACK_SRC" ]; then
  echo "[build] ERROR: gstack plugin not found at $GSTACK_SRC (gstack-ship closure)" >&2
  exit 1
fi
echo "[build]   baking skill: gstack-ship (+ gstack/ closure subtree)"
mkdir -p "$STAGE/skills/gstack-ship" "$STAGE/skills/gstack"
# Top-level gstack-ship/ skill dir: real SKILL.md (resolve symlink) + sections.
cp -L "$GSTACK_SRC/ship/SKILL.md" "$STAGE/skills/gstack-ship/SKILL.md"
cp -RL "$GSTACK_SRC/ship/sections" "$STAGE/skills/gstack-ship/sections"
# The hardcoded ~/.claude/skills/gstack closure subtree.
cp -RL "$GSTACK_SRC/ship"    "$STAGE/skills/gstack/ship"
cp -RL "$GSTACK_SRC/review"  "$STAGE/skills/gstack/review"
cp -RL "$GSTACK_SRC/bin"     "$STAGE/skills/gstack/bin"
cp -RL "$GSTACK_SRC/scripts" "$STAGE/skills/gstack/scripts"
# lib/ : several baked bin helpers import sibling `../lib/*` modules
# (gstack-redact → ../lib/redact-engine, gstack-decision-log → ../lib/gstack-decision,
# gstack-question-log → ../lib/jsonl-store.ts, gstack-telemetry-log → ../lib/*).
# Without lib/ those helpers fail at runtime mid-ship → bake it.
cp -RL "$GSTACK_SRC/lib"     "$STAGE/skills/gstack/lib"
cp -L  "$GSTACK_SRC/ETHOS.md" "$STAGE/skills/gstack/ETHOS.md" 2>/dev/null || true
if [ -d "$GSTACK_SRC/gstack-upgrade" ]; then
  cp -RL "$GSTACK_SRC/gstack-upgrade" "$STAGE/skills/gstack/gstack-upgrade"
fi
# gstack-ship Step 18 (pr-body.md) dispatches /document-release as a subagent that
# reads ~/.claude/skills/gstack/document-release/SKILL.md. Bake it so that internal
# call in the ship closure is not dangling (it degrades gracefully if missing, but
# #333 wants the full functional closure). Its own deps (bin/scripts/gstack-upgrade)
# are already baked above.
if [ -d "$GSTACK_SRC/document-release" ]; then
  cp -RL "$GSTACK_SRC/document-release" "$STAGE/skills/gstack/document-release"
fi
# gstack-ship's review-army (Step 9, ship/sections/review-army.md) reads the
# review checklists by the LITERAL path `.claude/skills/review/checklist.md`
# (also design-checklist.md / greptile-triage.md / TODOS-format.md) — i.e. a
# top-level `review/` skill dir, NOT under gstack/. review-army STOPs if
# checklist.md is unreadable. The host source for these is ~/gstack/review/, so
# bake them ALSO at skills/review/ to satisfy that literal lookup (the gstack/
# copy above keeps the ~/.claude/skills/gstack/review/... absolute refs working).
mkdir -p "$STAGE/skills/review"
cp -RL "$GSTACK_SRC/review/." "$STAGE/skills/review/"
# CRITICAL (CLAUDE.md ## Skill routing: per-slice review = the BUILTIN /review,
# single-vendor, one pass; ADR 0016 发现4: gstack is NOT in the implementation
# legs): gstack's review/ ships a SKILL.md (name: gstack-review). Baking it at the
# top-level skills/review/ registers a `/review` DISK skill that SHADOWS the builtin
# /review the coder must use — so the coder's `/review` resolved to gstack's
# multi-specialist review (wrong). review-army only READS the data files here
# (checklist.md / design-checklist.md / greptile-triage.md / TODOS-format.md /
# specialists), never the SKILL.md, so DROP the SKILL.md (+ tmpl): the checklist
# reads keep working AND /review stays the builtin.
rm -f "$STAGE/skills/review/SKILL.md" "$STAGE/skills/review/SKILL.md.tmpl"
# Exclude the 58M compiled discover helper — not in the ship closure.
rm -f "$STAGE/skills/gstack/bin/gstack-global-discover" 2>/dev/null || true
if [ ! -f "$STAGE/skills/gstack-ship/SKILL.md" ]; then
  echo "[build] ERROR: gstack-ship has no SKILL.md after copy" >&2
  exit 1
fi

# ── 1c. Skill content manifest (reproducibility pin) ─────────────────────────
# The skill SOURCE is mutable host state ($HOME/.claude/skills symlinks +
# ~/gstack), so the same git commit can bake different skill bytes on a different
# machine / after a skill update. Emit a content hash of exactly what we baked so
# a built image is auditable + a CI check can fail against an expected manifest.
# EXPECTED_SKILLS_SHA, if set, is enforced here → fail-closed on drift.
(
  cd "$STAGE/skills"
  find . -type f | LC_ALL=C sort | while read -r f; do
    printf '%s  ' "$f"
    if command -v sha256sum >/dev/null 2>&1; then sha256sum "$f" | awk '{print $1}';
    else shasum -a 256 "$f" | awk '{print $1}'; fi
  done
) > "$STAGE/skills-manifest.txt"
if command -v sha256sum >/dev/null 2>&1; then
  MANIFEST_SHA=$(sha256sum "$STAGE/skills-manifest.txt" | awk '{print $1}')
else
  MANIFEST_SHA=$(shasum -a 256 "$STAGE/skills-manifest.txt" | awk '{print $1}')
fi
echo "$MANIFEST_SHA" > "$STAGE/skills-manifest.sha256"
echo "[build]   baked-skills manifest sha256: $MANIFEST_SHA"
if [ -n "${EXPECTED_SKILLS_SHA:-}" ] && [ "$EXPECTED_SKILLS_SHA" != "$MANIFEST_SHA" ]; then
  echo "[build] ERROR: baked skills sha256 $MANIFEST_SHA != expected $EXPECTED_SKILLS_SHA (skill drift)" >&2
  exit 1
fi

# ── 2. All worker-role souls ─────────────────────────────────────────────────
# Bake each role's soul TEXT. We key the file BOTH by role name (human-clear,
# e.g. reviewer.md) AND by the ORCHESTRATOR_SOUL env VALUE the orchestrator
# actually injects, so a future entrypoint (#335/#336 soul activation) can map
# either to a file without surprise:
#   role "coder"    → env "coder"     (soulForStep)        → coder.md
#   role "reviewer" → env "READ-ONLY" (soulForStep)        → reviewer.md + READ-ONLY.md
#   role "merger"   → env "merger"    (MERGER_SOUL)        → merger.md
#   (cmr worker)    → env "cmr"       (CMR_SOUL)           → cmr.md (integrated-cmr fixer)
# Prompt entrypoints read the baked soul files directly, and ORCHESTRATOR_SOUL is
# also kept as the runtime role signal. Keep the env-value alias so either lookup
# path resolves to the same reviewed role text.
# NOTE: macOS ships bash 3.2 (no associative arrays / `declare -A`), and this
# script's shebang resolves to it — so we map role→env-alias with a portable
# case, NOT an assoc array, to keep the build reproducible on a macOS host.
soul_env_alias() {
  case "$1" in
    reviewer) echo "READ-ONLY" ;;   # soulForStep → StepSoul "READ-ONLY"
    *)        echo "$1" ;;          # coder→coder, merger→merger (MERGER_SOUL)
  esac
}
for role in "${SOUL_ROLES[@]}"; do
  if [ ! -f "$HERE/souls/$role.md" ]; then
    echo "[build] ERROR: soul '$role' not found at $HERE/souls/$role.md" >&2
    exit 1
  fi
  cp "$HERE/souls/$role.md" "$STAGE/souls/$role.md"
  alias_name="$(soul_env_alias "$role")"
  if [ "$alias_name" != "$role" ]; then
    cp "$HERE/souls/$role.md" "$STAGE/souls/$alias_name.md"
    echo "[build]   baking soul: $role (+ env-value alias $alias_name.md)"
  else
    echo "[build]   baking soul: $role"
  fi
done

# ── 3. Repo-root CLAUDE.md (carries the machine-executable ## Skill routing) ──
cp "$REPO_ROOT/CLAUDE.md" "$STAGE/CLAUDE.routing.md"
if ! grep -q '^## Skill routing' "$STAGE/CLAUDE.routing.md"; then
  echo "[build] ERROR: repo CLAUDE.md is missing the '## Skill routing' section (#332)" >&2
  exit 1
fi

# ── 4. Containerfile into the staging context ────────────────────────────────
cp "$HERE/Containerfile" "$STAGE/Containerfile"

echo "[build] docker build -> $IMAGE_TAG (base $BASE_IMAGE)"
docker build \
  --build-arg "BASE_IMAGE=$BASE_IMAGE" \
  -f "$STAGE/Containerfile" \
  -t "$IMAGE_TAG" \
  "$STAGE"

echo "[build] done: $IMAGE_TAG"
echo "[build] baked dev skills:" "${SKILL_CLOSURE[@]}" "gstack-ship"
echo "[build] baked souls:" "${SOUL_ROLES[@]}"
