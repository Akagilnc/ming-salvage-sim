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

Labels are **Matt-pure** (2026-06-17): only the seven — `bug` / `enhancement` (category) + `needs-triage` / `needs-info` / `ready-for-agent` / `ready-for-human` / `wontfix` (state). The old `priority/*` / `type/*` / `area/*` system was deleted. See [triage-labels.md](triage-labels.md).

## ⚠️ `Closes #N` 是子串匹配 — 想*引用* issue 而不关它，别用关闭动词

GitHub 的自动关解析器把 PR body 里的 `Closes` / `Fixes` / `Resolves #N` 当**子串**扫描。动词后面的任何限定词（**包括中文**）都**挡不住**自动关；合并进默认分支（`main`）时，整条 issue 被自动关闭。

- **实证踩坑（2026-06-18，#208 → #63）**：PR #208 的 body 写「`Closes #63` 的**设计悬置**」，本意是「收口 #63 的*设计*问题」。GitHub 只看到 `Closes #63` 子串、不认后面的中文限定，合并 `main` 时把整条 #63 关掉了——而 #63 的*实现*尚未做，本应保持 OPEN + `ready-for-agent`。
- **想引用 issue 而不关它**：绝不写 `Closes` / `Fixes` / `Resolves #N`；改用「见 #N」「关联 #N」「#N 的设计」等不带关闭动词的表述。
- **只在该 PR 真的会关掉整条 issue 时**才用 `Closes #N`。
- **若已误关**：`gh issue reopen <N> --repo Akagilnc/ming-salvage-sim` + 复原 label（如 `ready-for-agent`）+ 留一条说明误关原因的评论。

## When a skill says "publish to the issue tracker"

Create a GitHub issue (with `--repo Akagilnc/ming-salvage-sim`).

## When a skill says "fetch the relevant ticket"

Run `gh issue view <number> --repo Akagilnc/ming-salvage-sim --comments`.
