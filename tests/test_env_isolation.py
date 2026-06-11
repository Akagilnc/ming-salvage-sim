"""user-data 隔离兜底 pin(cmr S1 r2 P1)。

实证:测试文件漏设 MING_SIM_USER_DATA_DIR 时,run_settle 的错误包/拒收镜像全写进
真实 data/error_packs(积 18 包 75MB、假行混真 jsonl、attempt 序号被灌高)。
conftest autouse 集中兜底——本 pin 钉住「任何测试里 user_data_dir 永不指向仓内 data/」。
"""

from __future__ import annotations

import os
from pathlib import Path


def test_user_data_dir_is_isolated_from_repo_data():
    from ming_sim.paths import user_data_dir

    assert os.environ.get("MING_SIM_USER_DATA_DIR"), "autouse 兜底未生效"
    repo_data = Path(__file__).resolve().parent.parent / "data"
    assert Path(str(user_data_dir())).resolve() != repo_data.resolve()
