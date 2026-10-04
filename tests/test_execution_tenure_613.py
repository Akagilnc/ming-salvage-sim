"""#613 号令力/任别纯函数契约（旧 execution_side 读端已随 simulator 退役）。"""
from ming_sim.appointment_tenure import (
    AUTHORITY_COMMAND_RELIEF,
    COMMAND_POWER_RANK,
    command_power_rank,
    execution_distortion_weight,
)
from ming_sim.authority_privileges import AUTHORITY_PRIVILEGES, AUTHORITY_PRIVILEGE_SET

VALID_TENURES = ("真除", "兼署", "署理", "加衔")


def test_command_power_four_tier_strict_order_and_jianshu_not_collapsed():
    """TD-8 纯函数：真除＞兼署＞署理＞加衔；兼署不得与相邻档混同；无双逆表。"""
    ranks = {tenure: command_power_rank(tenure) for tenure in VALID_TENURES}
    assert ranks["真除"] > ranks["兼署"] > ranks["署理"] > ranks["加衔"]
    assert ranks["兼署"] != ranks["真除"]
    assert ranks["兼署"] != ranks["署理"]
    assert set(COMMAND_POWER_RANK) == set(VALID_TENURES)
    weights = {tenure: execution_distortion_weight(tenure) for tenure in VALID_TENURES}
    assert weights["真除"] < weights["兼署"] < weights["署理"] < weights["加衔"]
    assert weights["兼署"] != weights["真除"]
    assert weights["兼署"] != weights["署理"]
    max_rank = max(COMMAND_POWER_RANK.values())
    for tenure in VALID_TENURES:
        assert weights[tenure] == max_rank - ranks[tenure]


def test_authority_command_relief_single_source_from_privileges():
    """特权名唯一来自 authority_privileges，不在任别模块第二份拼写。"""
    assert tuple(AUTHORITY_COMMAND_RELIEF.keys()) == AUTHORITY_PRIVILEGES
    assert set(AUTHORITY_COMMAND_RELIEF) == AUTHORITY_PRIVILEGE_SET
    assert AUTHORITY_COMMAND_RELIEF["尚方剑密授"] > AUTHORITY_COMMAND_RELIEF["便宜行事"]


def test_held_authority_privileges_reduce_distortion_weight():
    base = execution_distortion_weight("署理", [])
    for privilege in AUTHORITY_PRIVILEGES:
        eased = execution_distortion_weight("署理", [{"privilege": privilege}])
        assert eased < base, privilege
    assert execution_distortion_weight("署理", [{"privilege": "尚方剑密授"}]) < execution_distortion_weight(
        "署理", [{"privilege": "便宜行事"}]
    )
