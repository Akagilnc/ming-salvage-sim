#!/usr/bin/env bash
# Build the Ming orchestrator coder-worker image (#332, ADR 0026 / ADR 0016 bake).
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
# ~/.claude/skills/{tdd,codebase-design,diagnosing-bugs} (symlinks ok).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
IMAGE_TAG="${IMAGE_TAG:-ming-orchestrator-coder:latest}"
BASE_IMAGE="${BASE_IMAGE:-sc-pipeline:latest}"
SKILLS_SRC="${SKILLS_SRC:-$HOME/.claude/skills}"

# The /tdd closure to bake (traced from SKILL.md cross-references, #332):
#   tdd → codebase-design (refactor step) ; diagnosing-bugs = CLAUDE.md route target.
SKILL_CLOSURE=(tdd codebase-design diagnosing-bugs)

STAGE="$(mktemp -d "${TMPDIR:-/tmp}/ming-coder-img.XXXXXX")"
trap 'rm -rf "$STAGE"' EXIT

echo "[build] staging context at $STAGE"
mkdir -p "$STAGE/skills" "$STAGE/souls"

# ── 1. Resolve + copy the skill closure (cp -RL dereferences symlinks) ───────
for skill in "${SKILL_CLOSURE[@]}"; do
  src="$SKILLS_SRC/$skill"
  if [ ! -e "$src" ]; then
    echo "[build] ERROR: required skill '$skill' not found at $src" >&2
    exit 1
  fi
  echo "[build]   baking skill: $skill"
  cp -RL "$src" "$STAGE/skills/$skill"
  if [ ! -f "$STAGE/skills/$skill/SKILL.md" ]; then
    echo "[build] ERROR: $skill has no SKILL.md after copy" >&2
    exit 1
  fi
done

# ── 1b. Skill content manifest (reproducibility pin) ─────────────────────────
# The skill SOURCE is mutable host state ($HOME/.claude/skills symlinks), so the
# same git commit can bake different skill bytes on a different machine / after a
# skill update. Emit a content hash of exactly what we baked so a built image is
# auditable + a CI check can fail against an expected manifest. EXPECTED_SKILLS_SHA,
# if set, is enforced here → fail-closed on drift.
(
  cd "$STAGE/skills"
  # Stable order, hash every regular file's path+content.
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

# ── 2. Coder soul ────────────────────────────────────────────────────────────
cp "$HERE/souls/coder.md" "$STAGE/souls/coder.md"

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
echo "[build] baked skills:" "${SKILL_CLOSURE[@]}"
