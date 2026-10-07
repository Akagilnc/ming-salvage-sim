"""哭谏段位（#623 / #1835 J11）。

旧 extraction 抢先消费已退出。坚持撤由 issue tracker 在已校验 cancel 实入后
调用 finalize_persist；本段不再读原申报、不落副作用。段位保留以免登记表断链。
"""

from __future__ import annotations

from ming_sim.applier import SectionResult


def apply(run) -> SectionResult:
    return SectionResult(applied=[], rejected=[])
