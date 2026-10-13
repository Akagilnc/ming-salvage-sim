"""结算落库编排器的 typed 结果（ADR 0150 决定 2/6）。

:class:`SettlementOutcome` 取代旧单体入口返回的 39 键 ad-hoc dict。旧形状的
病灶正是本类型要消灭的东西，故此处**不再**提供 dict 投影 / ``[]`` 兼容访问：

- 无恒空兼容键（``appointments`` / ``character_status_changes`` /
  ``character_power_changes`` / ``office_changes`` 随 C0 声明契约退役）。
- 无双份键（``person_changes`` 是输入回声，与 ``applied_person_changes`` 重复）。
- 无独立 ``*_rejections`` 键——拒收走 :class:`~ming_sim.applier.RejectedItem`
  这一种形状（项级四字段 ``item/reason/category/source``）；``turn``/``section``
  由框架在拒收报告投影时补，段不携带。

``world_advance`` / ``emperor_fate`` / ``事件结局`` / ``dossier_progress_reports``
/ ``faction_denunciations``  /
``covert_exec_selections`` 是无落库段的 delta 键，登记在
:mod:`ming_sim.settlement.registry` 作框架段条目防派生缩键，故不进本类型。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ming_sim.applier import RejectedItem, SectionResult


@dataclass(frozen=True)
class FiscalSectionResult:
    """财政三段合看（段序 removes→creates→changes 由登记表承载，ADR 0150 决定 4）。

    三段各自独立留痕，故保留三个 SectionResult 而不合成一个——拒收原因与类别
    在三段间语义不同（裁撤目标不存在 / 新立项枚举非法 / 调率 delta 非整数）。
    """

    removes: SectionResult
    creates: SectionResult
    changes: SectionResult


@dataclass
class IssueSectionResult(SectionResult):
    """局势段。四个分子表即旧 ``issue_summary`` 的四段 applied；拒收单一形状。

    旧 ``issue_summary`` 的 ``touched_ids`` 子键无消费者（编排器自 advances
    派生），不入本类型。旧 ``pairing_warnings`` 恒空壳已随 F12 散文配对拆除一并删除。
    """

    applied: List[dict] = field(init=False)
    advances: List[dict] = field(default_factory=list)
    new_issues: List[dict] = field(default_factory=list)
    closes: List[dict] = field(default_factory=list)
    cancels: List[dict] = field(default_factory=list)
    # 局势路自带的人物变更（结案/推进时物化的实体后果）——与人物段的 applied
    # 分列，两者不是同一批：人物段是本批声明的人物变更，此处是局势效果带出的。
    applied_person_changes: List[dict] = field(default_factory=list)
    rejected: List[RejectedItem] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.applied = [*self.advances, *self.new_issues, *self.closes, *self.cancels]

    def merge(self, other: IssueSectionResult) -> IssueSectionResult:
        return IssueSectionResult(
            advances=self.advances + other.advances,
            new_issues=self.new_issues + other.new_issues,
            closes=self.closes + other.closes,
            cancels=self.cancels + other.cancels,
            applied_person_changes=self.applied_person_changes + other.applied_person_changes,
            rejected=self.rejected + other.rejected,
        )


@dataclass(frozen=True)
class SettlementOutcome:
    """一次声明落账的完整结果。

    每个字段是一个段的 :class:`SectionResult`：``applied`` 是已落账的原始项，
    ``rejected`` 是 canonical 拒收项。消费端读「哪些落了 / 哪些被拒」只经这两处，
    不再有第二套拒收键。
    """

    # 框架前置闸产物（sanitize / 误投），非段落格（ADR 0150 决定 2）。
    # shape_sections 与 shape_rejections 等长：拒收报告的 section 是净化时的原字段名
    # （#1745：不得改记成 validate_shape_rejections 这个假段名）。
    shape_rejections: List[RejectedItem] = field(default_factory=list)
    shape_sections: List[str] = field(default_factory=list)

    metric: SectionResult = field(default_factory=lambda: SectionResult([], []))
    economy: SectionResult = field(default_factory=lambda: SectionResult([], []))
    faction: SectionResult = field(default_factory=lambda: SectionResult([], []))
    social_class: SectionResult = field(default_factory=lambda: SectionResult([], []))
    surcharge: SectionResult = field(default_factory=lambda: SectionResult([], []))
    population: SectionResult = field(default_factory=lambda: SectionResult([], []))
    region: SectionResult = field(default_factory=lambda: SectionResult([], []))
    army: SectionResult = field(default_factory=lambda: SectionResult([], []))
    power: SectionResult = field(default_factory=lambda: SectionResult([], []))
    bandit: SectionResult = field(default_factory=lambda: SectionResult([], []))
    person: SectionResult = field(default_factory=lambda: SectionResult([], []))
    fiscal: Optional[FiscalSectionResult] = None
    issue: Optional[IssueSectionResult] = None
    dossier_participants: SectionResult = field(
        default_factory=lambda: SectionResult([], [])
    )
    dossier_executions: SectionResult = field(default_factory=lambda: SectionResult([], []))
    secret_dossier_participants: SectionResult = field(
        default_factory=lambda: SectionResult([], [])
    )
    authority: SectionResult = field(default_factory=lambda: SectionResult([], []))
    secret_order: SectionResult = field(default_factory=lambda: SectionResult([], []))
    credit_event: SectionResult = field(default_factory=lambda: SectionResult([], []))
    relation_edge: SectionResult = field(default_factory=lambda: SectionResult([], []))

    # 结局判定不是落库段，上浮编排器（ADR 0150 §4.3）。
    victory_status: Optional[Dict[str, object]] = None

    def sections(self) -> Dict[str, SectionResult]:
        """全部段落格的具名视图，供拒收报告集中投影与调试。

        ``fiscal`` / ``issue`` 是多段合看，展开为子段名以免框架漏投影其拒收。
        """
        flat: Dict[str, SectionResult] = {
            "metric_delta": self.metric,
            "economy_moves": self.economy,
            "faction_delta": self.faction,
            "class_delta": self.social_class,
            "surcharge_decrees": self.surcharge,
            "population_transfers": self.population,
            "region_changes": self.region,
            "army_changes": self.army,
            "power_changes": self.power,
            "bandit_absorptions": self.bandit,
            "applied_person_changes": self.person,
            "dossier_executions": self.dossier_executions,
            "dossier_participants": self.dossier_participants,
            "secret_dossier_participants": self.secret_dossier_participants,
            "authority_changes": self.authority,
            "secret_order_updates": self.secret_order,
            "credit_event_resolutions": self.credit_event,
            "relation_edge_event_resolutions": self.relation_edge,
        }
        if self.fiscal is not None:
            flat["fiscal_removes"] = self.fiscal.removes
            flat["fiscal_creates"] = self.fiscal.creates
            flat["fiscal_changes"] = self.fiscal.changes
        if self.issue is not None:
            flat["issue_summary"] = self.issue
        return flat
