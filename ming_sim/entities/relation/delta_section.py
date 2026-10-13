"""大臣互动边事件段（``relation_edge_events``；#633 / ADR 0082）。

邸报里的大臣互动 → 边事件，同 atomic 当场落库，走 ``record_relation_edge_event``
唯一写口。坏项逐条拒收留痕，不阻塞其它段。

端点资格＝批内 pre∪post 名册并集（#633 T1 r5 owner 裁决 B 案）：同批退场者与同批
入场者的互动都算；前后均不合格（幻觉 / 皇帝入大臣端）仍拒收。此处已在该批人物
变更全部落定之后，live 投影即 post-roster。

案卷来源锁本批冻结输入闭集（缺集按空闭集 fail-closed，V2）。
"""

from __future__ import annotations

from ming_sim.applier import SectionResult


def apply(run):
    from ming_sim.relations import resolve_relation_edge_events_from_extraction

    resolutions, rejections = resolve_relation_edge_events_from_extraction(
        run.db, run.state, run.current_extracted, source=run.ctx.source,
        dossier_ids_at_input=run.ctx.dossier_ids_at_input,
        allowed_endpoint_names=run.relation_pre_roster | {
            row["name"] for row in run.db.characters.current_court_rows(run.state.year, run.state.period)
        },
    )
    return SectionResult(applied=resolutions, rejected=rejections)
