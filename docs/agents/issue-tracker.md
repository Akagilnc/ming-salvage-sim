# Issue tracker: GitHub

Issues and PRDs for this repo live as GitHub issues in `Akagilnc/ming-salvage-sim`. Use the `gh` CLI for all operations.

## ⚠️ Always pass `--repo Akagilnc/ming-salvage-sim`

This repo is a fork (upstream = `wangwei-ying3/ming-salvage-sim`). `gh` resolves to **upstream** by default, so every `gh issue` / `gh pr` / `gh label` command MUST include `--repo Akagilnc/ming-salvage-sim`. Never rely on automatic repo inference.

## Conventions

- **Create an issue**: `gh issue create --repo Akagilnc/ming-salvage-sim --title "..." --body "..."`. Use a heredoc for multi-line bodies.
- **Read an issue**: `gh issue view <number> --repo Akagilnc/ming-salvage-sim --comments`, filtering comments by `jq` and also fetching labels.
- **List issues**: `gh issue list --repo Akagilnc/ming-salvage-sim --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'` with appropriate `--label` and `--state` filters.
- **Comment on an issue**: `gh issue comment <number> --repo Akagilnc/ming-salvage-sim --body "..."`
- **Apply / remove labels**: `gh issue edit <number> --repo Akagilnc/ming-salvage-sim --add-label "..."` / `--remove-label "..."`
- **Close**: `gh issue close <number> --repo Akagilnc/ming-salvage-sim --comment "..."`

Labels are **Matt-pure** (2026-06-17): only the seven — `bug` / `enhancement` (category) + `needs-triage` / `needs-info` / `ready-for-agent` / `ready-for-human` / `wontfix` (state). The old `priority/*` / `type/*` / `area/*` system was deleted. See [triage-labels.md](triage-labels.md) and [../DEV_WORKFLOW.md](../DEV_WORKFLOW.md).

## When a skill says "publish to the issue tracker"

Create a GitHub issue (with `--repo Akagilnc/ming-salvage-sim`).

## When a skill says "fetch the relevant ticket"

Run `gh issue view <number> --repo Akagilnc/ming-salvage-sim --comments`.
