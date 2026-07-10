#!/usr/bin/env bash
# #746 — manual runner dispatch: linked worktree + APFS clonefile node_modules.
#
# Creates (or reuses) a sibling worktree of the main monorepo clone and provisions
# Node deps from the main clone's warm node_modules via `cp -cR` when package-lock
# hashes match. Falls back to `npm ci` / `npm install` per subproject otherwise.
#
# Usage:
#   orchestrator/scripts/provision-worktree.sh <issue-number> [base-branch]
#
# Example (from any checkout of the monorepo):
#   bash orchestrator/scripts/provision-worktree.sh 746
#   → ~/WorkSpace/Ming_LLM-746 on branch feat/746-provisioning-clonefile (or
#     feat/issue-746 if you pass a custom branch env), with orchestrator/ + web/
#     node_modules clonefiled from the main worktree when locks match.
#
# Env:
#   MAIN_REPO   absolute path of the main clone (default: git common-dir parent)
#   WORKTREE    absolute path for the new worktree (default: <parent>/Ming_LLM-<n>)
#   BRANCH      branch to create/checkout (default: feat/issue-<n>)
#   BASE        base ref to cut from when branch is new (default: main)
set -euo pipefail

ISSUE="${1:?usage: provision-worktree.sh <issue-number> [base-branch]}"
BASE_ARG="${2:-}"

# Resolve main repo = this script's monorepo root unless MAIN_REPO is set.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
MAIN_REPO="${MAIN_REPO:-$DEFAULT_ROOT}"

# If we're already inside a linked worktree, prefer the primary checkout as the
# template (git common-dir parent when common-dir ends with /.git).
if COMMON="$(git -C "$MAIN_REPO" rev-parse --git-common-dir 2>/dev/null)"; then
  case "$COMMON" in
    /*) COMMON_ABS="$COMMON" ;;
    *) COMMON_ABS="$(cd "$MAIN_REPO" && cd "$COMMON" && pwd)" ;;
  esac
  if [[ "$COMMON_ABS" == */.git ]]; then
    PRIMARY="${COMMON_ABS%/.git}"
    if [[ -d "$PRIMARY" ]]; then
      MAIN_REPO="$PRIMARY"
    fi
  fi
fi

PARENT="$(dirname "$MAIN_REPO")"
BASE_NAME="$(basename "$MAIN_REPO")"
# Strip a trailing -<digits> worktree suffix if invoked from a numbered tree
# (Ming_LLM-746 → Ming_LLM). Do NOT use ${name%-*} — that would mangle Ming_LLM.
if [[ "$BASE_NAME" =~ ^(.+)-[0-9]+$ ]]; then
  BASE_NAME="${BASH_REMATCH[1]}"
fi
# Prefer the primary name under parent: Ming_LLM (not Ming_LLM-746).
if [[ -d "$PARENT/$BASE_NAME" ]]; then
  MAIN_REPO="$PARENT/$BASE_NAME"
fi

WORKTREE="${WORKTREE:-$PARENT/${BASE_NAME}-${ISSUE}}"
BRANCH="${BRANCH:-feat/issue-${ISSUE}}"
BASE="${BASE_ARG:-${BASE:-main}}"

lock_hash() {
  local f="$1"
  if [[ ! -f "$f" ]]; then
    echo ""
    return
  fi
  shasum -a 256 "$f" | awk '{print $1}'
}

provision_project() {
  local target="$1"
  local template="$2"
  local label="$3"
  if [[ ! -f "$target/package.json" ]]; then
    return 0
  fi
  local t_lock="$target/package-lock.json"
  local m_lock="$template/package-lock.json"
  local t_hash m_hash
  t_hash="$(lock_hash "$t_lock")"
  m_hash="$(lock_hash "$m_lock")"
  if [[ -n "$t_hash" && "$t_hash" == "$m_hash" && -d "$template/node_modules" ]]; then
    local start end
    start="$(date +%s)"
    rm -rf "$target/node_modules"
    if cp -cR "$template/node_modules" "$target/node_modules"; then
      end="$(date +%s)"
      echo "[provision] $label: clonefile ok (${start}→${end}s wall≈$((end - start))s)"
      return 0
    fi
    echo "[provision] $label: clonefile failed; falling back to npm" >&2
  fi
  if [[ -f "$t_lock" ]]; then
    (cd "$target" && npm ci)
    echo "[provision] $label: npm ci"
  else
    (cd "$target" && npm install)
    echo "[provision] $label: npm install"
  fi
}

echo "[provision] main=$MAIN_REPO"
echo "[provision] worktree=$WORKTREE branch=$BRANCH base=$BASE"

if [[ -d "$WORKTREE" ]]; then
  echo "[provision] worktree exists; reusing"
  git -C "$WORKTREE" checkout "$BRANCH" 2>/dev/null || true
else
  # Fetch base when possible (best-effort).
  git -C "$MAIN_REPO" fetch origin "$BASE" 2>/dev/null || true
  if git -C "$MAIN_REPO" show-ref --verify --quiet "refs/heads/$BRANCH"; then
    git -C "$MAIN_REPO" worktree add "$WORKTREE" "$BRANCH"
  else
    # Prefer origin/base when present.
    CUT="$BASE"
    if git -C "$MAIN_REPO" show-ref --verify --quiet "refs/remotes/origin/$BASE"; then
      CUT="origin/$BASE"
    fi
    git -C "$MAIN_REPO" worktree add -b "$BRANCH" "$WORKTREE" "$CUT"
  fi
fi

# Immediate child Node projects + root (same rule as listNodeProjectDirs).
if [[ -f "$WORKTREE/package.json" ]]; then
  provision_project "$WORKTREE" "$MAIN_REPO" "root"
fi
for name in orchestrator web; do
  if [[ -f "$WORKTREE/$name/package.json" ]]; then
    provision_project "$WORKTREE/$name" "$MAIN_REPO/$name" "$name"
  fi
done

echo "[provision] done → $WORKTREE"
