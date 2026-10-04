"""有序段登记表——段序的唯一真源（ADR 0150 决定 4）。

清单顺序即执行顺序与顺序约束的唯一真源。旧单体入口把「哭谏先于案卷执行、
人物 pre-issue 在局势段前而 post-issue 在其后、财政 removes→creates→changes、
人物变更先于 issue 路读人物态」这些约束只写在编排器注释与代码位置里；本表
把它们变成可读、可审的数据。

**不建 before/after 依赖声明机制**：约束图稀疏稳定，声明机制是投机通用性
（ADR 0150 决定 4 明文）。

登记走 lazy 路径字符串 + :func:`importlib.import_module`，不在 import 期同步
加载 ``issues`` / ``GameDB`` 等重模块（防循环依赖；沿 ADR 0010 决定 1 验收口径）。
无第二注册机制——本表是手写真源，``simulation.DECLARATION_EFFECT_FIELDS`` 由此
派生，不双写。
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Dict, Tuple


@dataclass(frozen=True)
class SectionSpec:
    """一段落库适配器的登记条目。

    name: 段名，同时是拒收报告的 ``section`` 名。
    path: 段适配器模块的 lazy 路径。
    attr: 模块内导出名（同一模块可登记多条：人物 pre/post、财政三段）。
    delta_keys: 本段消费的声明效果字段。
    """

    name: str
    path: str
    attr: str
    delta_keys: Tuple[str, ...]


# 段序＝旧单体入口的实读执行顺序（人物 pre → 局势 → 人物 post →
# 财政三段 removes→creates→changes → 密令推演副作用 → 信用事件 → 关系边事件）。
# 财政必须在局势之后：同批承诺去重要读局势段刚落下的月支载体。
#
# 两处顺序约束由编排器而非本表承担，因为它们不是「段序」而是「同批内交错」：
# ① C0 effects 数组按交代先后逐笔落账（#1844）：逐笔驱动 metric→实体→经济，
#    同一笔内先实体后钱；不按本表全局段序重排跨类因果。
# ② 人口段的「回流/加派」去重依赖同批加派段结果，故编排器在两段之间算
#    surcharge_claims（见 run.SettlementRun）。
_SECTIONS: Tuple[SectionSpec, ...] = (
    SectionSpec("breach_plea", "ming_sim.entities.breach_plea.delta_section",
                "apply", ()),
    SectionSpec("dossier_participants", "ming_sim.entities.dossier.delta_section",
                "apply_participants", ("dossier_participants",)),
    SectionSpec("secret_dossier_participants",
                "ming_sim.entities.dossier.delta_section",
                "apply_secret_dossier_participants",
                ("secret_dossier_participants",)),
    SectionSpec("dossier_executions", "ming_sim.entities.dossier.delta_section",
                "apply_executions", ("dossier_executions",)),
    SectionSpec("authority", "ming_sim.entities.authority.delta_section",
                "apply", ("authority_changes",)),
    SectionSpec("metric", "ming_sim.entities.metric.delta_section",
                "apply", ("metric_delta",)),
    SectionSpec("economy", "ming_sim.entities.economy.delta_section",
                "apply", ("economy_moves",)),
    SectionSpec("faction", "ming_sim.entities.faction.delta_section",
                "apply", ("faction_delta",)),
    SectionSpec("class", "ming_sim.entities.social_class.delta_section",
                "apply", ("class_delta",)),
    SectionSpec("surcharge", "ming_sim.entities.surcharge.delta_section",
                "apply", ("surcharge_decrees",)),
    SectionSpec("population", "ming_sim.entities.population.delta_section",
                "apply", ("population_transfers",)),
    SectionSpec("new_armies", "ming_sim.entities.army.delta_section",
                "apply_new_armies", ("new_armies",)),
    SectionSpec("region_changes", "ming_sim.entities.region.delta_section",
                "apply", ("region_delta",)),
    SectionSpec("army_changes", "ming_sim.entities.army.delta_section",
                "apply_deltas", ("army_delta",)),
    SectionSpec("power", "ming_sim.entities.power.delta_section",
                "apply", ("power_updates", "bandit_absorptions")),
    SectionSpec("person_pre", "ming_sim.entities.character.delta_section",
                "apply_pre_issue", ("人物变更",)),
    SectionSpec("issue", "ming_sim.entities.issue.delta_section",
                "apply",
                ("issue_advances", "new_issues", "close_issues", "cancels")),
    SectionSpec("affair", "ming_sim.entities.affair.delta_section",
                "apply", ("affair_declarations",)),
    SectionSpec("person_post", "ming_sim.entities.character.delta_section",
                "apply_post_issue", ("人物变更",)),
    SectionSpec("fiscal_removes", "ming_sim.entities.fiscal.delta_section",
                "apply_removes", ("fiscal_removes",)),
    SectionSpec("fiscal_creates", "ming_sim.entities.fiscal.delta_section",
                "apply_creates", ("fiscal_creates",)),
    SectionSpec("fiscal_changes", "ming_sim.entities.fiscal.delta_section",
                "apply_changes", ("fiscal_changes",)),
    SectionSpec("secret_order", "ming_sim.entities.secret_order.delta_section",
                "apply", ("secret_order_updates",)),
    SectionSpec("credit_event", "ming_sim.entities.credit_event.delta_section",
                "apply", ()),
    SectionSpec("relation_edge", "ming_sim.entities.relation.delta_section",
                "apply", ("relation_edge_events",)),
)

# 无落库段的声明效果字段：登记为框架条目，只为派生视图不缩键（ADR 0150 决定 4）。
_FRAMEWORK_KEYS: Tuple[str, ...] = (
    "world_advance", "emperor_fate", "事件结局", "dossier_progress_reports",
    "faction_denunciations", "dossier_reconciliations", "covert_exec_selections",
)


def section_specs() -> Tuple[SectionSpec, ...]:
    """有序登记表（段序真源）。返回不可变序列，调用方不得重排。"""
    return _SECTIONS




def delta_keys() -> Tuple[str, ...]:
    """全部有主落库段的声明效果字段，按登记表首次出现序去重。"""
    seen: list[str] = []
    for spec in _SECTIONS:
        for key in spec.delta_keys:
            if key not in seen:
                seen.append(key)
    return tuple(seen)


def derived_effect_fields() -> Dict[str, str]:
    """由登记表派生的声明效果字段真源（容器类型统一为 list 视图）。

    这是 ``simulation.DECLARATION_EFFECT_FIELDS`` 的**派生视图**，不是第二真源
    （ADR 0150 决定 4：登记表承接后消亡、改为派生视图，不双写）。真正的容器类型
    校验真源是 ADR 0150 之前的字段契约；派生视图只保证键集不缩。
    """
    return {key: "list" for key in (*delta_keys(), *_FRAMEWORK_KEYS)}


def load(spec: SectionSpec):
    """按 lazy 路径载入段适配器函数。

    路径写错 → ImportError 响亮上抛（不静默跳过；登记表漂移三种失败模式之一由
    本 fail-loud import 覆盖，ADR 0150 决定 4）。
    """
    module = importlib.import_module(spec.path)
    return getattr(module, spec.attr)


