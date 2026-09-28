"""#1729 手拟受控目标字段须 exact 匹配，不拿散文拼接当 ID。"""

from __future__ import annotations

import pytest

from ming_sim.matching import canonical_army_id_exact, canonical_region_id_exact


@pytest.mark.parametrize(
    ("canonicalize", "raw"),
    [
        (canonical_region_id_exact, "京师赈务"),
        (canonical_region_id_exact, "请接济北直隶"),
        (canonical_region_id_exact, "@@beizhili"),
        (canonical_army_id_exact, "请拨给关宁军"),
        (canonical_army_id_exact, "宁锦防线欠饷"),
    ],
)
def test_exact_target_canonicalizers_reject_prose(content, canonicalize, raw):
    """受控别名/命名空间不放宽 exact seam 为子串或散文匹配。"""
    entities = content.regions if canonicalize is canonical_region_id_exact else content.armies
    assert canonicalize(raw, entities) is None
