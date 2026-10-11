"""坏持久效果须在真实月度漂移入口响亮失败，事务回滚不留半月进度。

容器容忍由 test_effect_origin_558 的结案/持续效果案承接；
enrich 建筑容器由 test_issue_entities 的国策立项案承接。
"""
from __future__ import annotations

import pytest


@pytest.mark.parametrize("bad", [
    '"oops"', "5", "true", "[1,2]", "null", "不是合法json",
])
def test_inertia_ongoing_non_dict_no_crash(game, bad):
    """#117/#1889：脏 ongoing_effects 不得被吞成空对象蒙混过月；须响亮失败。"""
    from ming_sim.situation_drift import apply_situation_monthly_drift

    db, state, _content = game
    iid = db.insert_issue(state, kind="situation", title="畸形ongoing测试", bar_value=50, inertia=1)
    from ming_sim.applier import StoredDocumentError, atomic
    db.conn.execute("UPDATE issues SET ongoing_effects=? WHERE id=?", (str(bad), iid))
    db.conn.commit()
    before = db.conn.execute("SELECT bar_value, status FROM issues WHERE id=?", (iid,)).fetchone()
    with pytest.raises(StoredDocumentError), atomic(db):
        apply_situation_monthly_drift(db, state)
    after = db.conn.execute("SELECT bar_value, status FROM issues WHERE id=?", (iid,)).fetchone()
    assert tuple(after) == tuple(before)
