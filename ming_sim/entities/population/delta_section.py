"""人口守恒转移（``population_transfers``）落库段（#649 / 0087）。

单记录双写：源阶级减 N、目标阶级增 N，同事务原子。两条「唯一拥有」闸：

- 「回流」只由赈济/招抚屯田 recovery 单核写入，LLM 自由抽取一律拒收（防同源双写）。
- 同一道加派旨的人口后果已由加派账拥有（认领表由加派段交编排器，见 surcharge 段）。
"""

from __future__ import annotations

from typing import Dict, List

from ming_sim.applier import section_from_rows


def apply(run):
    from ming_sim.issues import _apply_population_transfers

    transfer_items: List[object] = []
    transfer_rejections: List[Dict[str, object]] = []
    for item in (run.current_extracted.get("population_transfers") or []):
        source = str(item.get("source") or "") if isinstance(item, dict) else ""
        region_id = source.rpartition("@")[2]
        claim = (
            (str(item.get("origin_ref") or ""), region_id) if isinstance(item, dict)
            else ("", "")
        )
        if isinstance(item, dict) and str(item.get("reason") or "").strip() == "回流":
            transfer_rejections.append({
                "rejected": True, "category": "invalid_enum",
                "reason": "回流仅由赈济/招抚屯田 recovery 单核写入，extractor 不得自由申报",
                "item": item,
            })
        elif isinstance(item, dict) and item.get("reason") == "加派" and claim in run.surcharge_claims:
            transfer_rejections.append({
                "rejected": True, "category": "invalid_enum",
                "reason": "同一道加派旨的人口后果已由加派账唯一拥有",
                "item": item,
            })
        else:
            transfer_items.append(item)

    applied_transfers, primitive_rejections = _apply_population_transfers(
        run.db, transfer_items, commit=False,
    )
    return section_from_rows(
        [*applied_transfers, *transfer_rejections, *primitive_rejections],
        run.ctx.source, category="population_transfers",
    )
