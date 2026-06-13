# AGENTS.md — Ming_LLM

本仓 agent 指令真源 = [`CLAUDE.md`](CLAUDE.md)，**所有 agent（Claude / codex / 其它）一律先读它并遵守**。本文件只重申最易被各 agent 默认行为踩翻的几条硬规则，细节与背景全在 CLAUDE.md。

## 最易踩，单独重申

- **评审轮 = 独立 commit，禁止 amend 折叠多轮**：每一轮 cmr/评审 fix 提一个**新 commit**（如 `cmr S3 r5: …`），**严禁 `git commit --amend` 把多轮压进同一个 commit**。过程史 > 干净历史（同「不 squash」doctrine）。reflog 不算数（本地、90 天 gc、不推远端、PR 不可见）。切片级一 slice 一 commit 可，slice 内每轮必须新 commit。
- **改仓库内容前要明确授权词**（开始改 / 动手 / proceed / go / 做 / 写 / 合并）；纯叙事文档（docs/*.md、README body）可直接改但写完主动告知。
- **任何代码工作先开分支再动手**，main 保持干净（主工作区多 agent 共用、会被切分支——commit 前当场 `git branch --show-current` 核对；main 向写走独立 worktree）。纯文档可直接在 main 改并提交。
- **行为变更默认 TDD**（红→绿→重构→真实测试输出）；状态结论（测试/PR/分支/提交/部署）报告前先 query 实际系统、附命令+输出，不凭记忆。
- **设计文档（ADR/契约/spec）与代码同等评审**，不因「只是文档」跳步。

其余（语言、PR merge 不 squash、探针铁律 P1–P4、issue tracker、domain docs 等）见 [`CLAUDE.md`](CLAUDE.md)。
