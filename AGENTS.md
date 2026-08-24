# AGENTS.md — Ming_LLM

本仓 agent 指令真源 = [`CLAUDE.md`](CLAUDE.md)，**所有 agent（Claude / codex / 其它）一律先读它并遵守**——首读其「探针设计铁律」节（**宪法级**：总纲+P1-P7，一切立法/票面/判词不得绕开）。

全局纪律（授权词、输出语言、分支/评审/merge/PR 前缀等）见 owner 全局规则；项目知识、探针铁律、issue tracker 等均在 CLAUDE.md，本文件不重复。

**commit / PR 标题必须冠平台前缀**（如 `ak-roles:` / `codex:` / `claude:`，置于 conventional-commit 前缀之前；真源=owner 全局规则 #10，沙箱 worker 看不到全局文件故在此复述）。

## 测试执行（owner 2026-08-22 暂记）

全量测试验证一律用 `python -m pytest tests/ -q -n auto`（与 CI 同参；`-n auto` = pytest-xdist 多核并行，全量 ~2 分钟，不带它串行跑同一套要 10 分钟+）。切片轮次仍按 #1185 只跑聚焦测试。
