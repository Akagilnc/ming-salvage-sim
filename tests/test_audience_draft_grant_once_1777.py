"""#1783 真入口 tracer：一卷宗原句 → 一件事一案（钱+期限同案）。

#1842：殿上 scene_chat 转译双桩产出 grant commission（含 #1778 承办/
#1783 期限既有 staging 字段）→ pending；「准」→ promises 应允。
收夜后 economy_ledger 恰一条 −15、decree_dossiers 恰一份 grant_allocation，
无以召对记录为正文的平行交办案卷。stub 仅 LLM 边界。

#1778 并存：承办人来自声明名单（郭允厚），不是当前召对大臣；
本票不回写配人。
"""

from __future__ import annotations




_EDICT = "着户部自国库拨银十五万两，专解关宁军前补发欠饷，不得加派于民。钦此。"
_UTTERANCE = (
    "着户部尚书郭允厚从国库拨银十五万两，解赴关宁军前专补欠饷，"
    "十日内奏报实发数目，不得加派于民。卿即拟旨呈览。"
)
