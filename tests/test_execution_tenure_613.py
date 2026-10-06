"""#613 执行侧任别读端：号令力档位。"""
from ming_sim.appointment_tenure import COMMAND_POWER_RANK, command_power_rank

VALID_TENURES = ("真除", "兼署", "署理", "加衔")


def test_command_power_four_tier_strict_order_and_jianshu_not_collapsed():
    """TD-8 纯函数：真除＞兼署＞署理＞加衔；兼署不得与相邻档混同。"""
    ranks = {tenure: command_power_rank(tenure) for tenure in VALID_TENURES}
    assert ranks["真除"] > ranks["兼署"] > ranks["署理"] > ranks["加衔"]
    assert ranks["兼署"] != ranks["真除"]
    assert ranks["兼署"] != ranks["署理"]
    assert set(COMMAND_POWER_RANK) == set(VALID_TENURES)
