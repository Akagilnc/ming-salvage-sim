"""#389：事件亲裁选择→事件的绑定以**权威候选快照**为真源，不被 simulator 回显的
event_id 牵着走。

裁决（#389 选 1）：用 #345 那份权威候选事件快照确定性绑定 decision→event，不依赖
simulator 在自由文本里回显 event_id。整合 cmr（codex 完整性腿）r2 抓出残留：原实现对
**任何**已填 event_id 一律采信并跳过快照校验，于是 simulator 回显一个错/臆造的 id 时，
绑定会跟着错。本组把权威快照钉成真源：回显 id 只有确属本回合候选才采信，否则按快照唯一
标题重绑；同时保住「正常含 event_id 的路径行为不变」。
"""

from ming_sim.settlement_payload import bind_decisions_to_candidate_events


_SNAPSHOT = {"candidate_events": [{"id": "mao_wenlong", "title": "毛文龙裁断"}]}


def test_missing_event_id_binds_from_unique_title():
    """缺 id：从权威候选快照按唯一标题补绑（#389 主缺口）。"""
    out = bind_decisions_to_candidate_events(
        [{"title": "毛文龙裁断", "options": []}], _SNAPSHOT)
    assert out[0]["event_id"] == "mao_wenlong"


def test_valid_echoed_event_id_is_trusted_unchanged():
    """回显 id 确属本回合候选 → 采信、行为不变（决策标题可与候选标题不同也不影响）。"""
    out = bind_decisions_to_candidate_events(
        [{"title": "是否罢毛帅", "event_id": "mao_wenlong"}], _SNAPSHOT)
    assert out[0]["event_id"] == "mao_wenlong"


def test_offsnapshot_echoed_event_id_does_not_win_over_snapshot():
    """承重断言（codex r2 毒样本）：simulator 回显一个**不在候选快照里**的 id，但标题唯一
    命中另一候选 → 以快照为准重绑，不采信错 id。"""
    out = bind_decisions_to_candidate_events(
        [{"title": "毛文龙裁断", "event_id": "wrong_event"}], _SNAPSHOT)
    assert out[0]["event_id"] == "mao_wenlong"


def test_offsnapshot_id_with_no_title_match_is_unbound():
    """回显 id 不在快照、标题又无唯一匹配 → 解绑（去掉 event_id），不把这个非候选 id 当
    triggered 落库（codex correctness：留着它会把一个真实未来事件误标已触发、永久挡在候选池外；
    season_simulator 也明示非候选抉择不应带 event_id）。选择仍留在 pending_decisions。"""
    out = bind_decisions_to_candidate_events(
        [{"title": "某无关抉择", "event_id": "freeform_x"}], _SNAPSHOT)
    assert "event_id" not in out[0]


def test_ambiguous_title_remains_unbound():
    """候选快照里标题不唯一 → 不绑（避免错绑），保持原状。"""
    snapshot = {"candidate_events": [
        {"id": "evt_a", "title": "同名抉择"},
        {"id": "evt_b", "title": "同名抉择"},
    ]}
    out = bind_decisions_to_candidate_events(
        [{"title": "同名抉择", "options": []}], snapshot)
    assert "event_id" not in out[0]


def test_no_snapshot_returns_decisions_unchanged():
    """无快照（payload 非 dict / 无 candidate_events）→ 决策原样返回，不臆测。"""
    assert bind_decisions_to_candidate_events(
        [{"title": "t", "event_id": "x"}], None)[0]["event_id"] == "x"
    assert "event_id" not in bind_decisions_to_candidate_events(
        [{"title": "t"}], {"other": 1})[0]


def test_impeachment_surge_candidate_id_is_not_an_event_ledger_id():
    """#655 动态弹劾潮候选混进 candidate_events 后，simulator 按 season_simulator
    契约回显其 id 时，不得被当成事件账 id 采信——否则 submit_decisions →
    record_event_decision_choice → _ensure_event_parent 对未定义事件 ValueError，
    亲裁提交整笔回滚，回合卡在 awaiting_decision。"""
    surge_id = "impeachment_surge:commitment:5:deformation_exposure:东林"
    snapshot = {"candidate_events": [
        {"id": "mao_wenlong", "title": "毛文龙裁断"},
        {
            "id": surge_id,
            "origin_kind": "impeachment_surge",
            "title": "",
            "faction_id": "东林",
        },
    ]}
    echoed = bind_decisions_to_candidate_events(
        [{"title": "准劾温体仁", "event_id": surge_id, "options": []}],
        snapshot,
    )
    assert "event_id" not in echoed[0]
    real = bind_decisions_to_candidate_events(
        [{"title": "是否罢毛帅", "event_id": "mao_wenlong"}],
        snapshot,
    )
    assert real[0]["event_id"] == "mao_wenlong"
