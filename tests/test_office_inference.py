"""office_type 推断走 offices.json 参考表（替代旧正则词表）。

无 CLI 后端时 LLM 兜底不触发（表查不中→待铨），故这里只测表命中的确定性分类，
重点覆盖旧版漏判进『待铨』的：后宫/武职/民间。
"""

from __future__ import annotations

import pytest

import ming_sim.cli_backend as cb
import ming_sim.db as dbmod
from ming_sim.db import infer_office_type_from_office as infer
from ming_sim.models import LLMConfig


@pytest.mark.parametrize("office,expected", [
    # 内阁优先：复合衔『礼部尚书,东阁大学士』归内阁，不归礼部
    ("礼部尚书,东阁大学士", "内阁"),
    ("内阁首辅", "内阁"),
    # 六部优先于都察院：『兵部尚书,左都御史』首衔为主→兵部
    ("兵部尚书,左都御史", "兵部"),
    ("户部郎中", "户部"),
    ("南京兵部尚书", "兵部"),
    ("吏部尚书", "吏部"),
    # 都察院（纯）
    ("都察院右佥都御史", "都察院"),
    # 翰林/詹事
    ("少詹事,掌南京翰林院", "翰林院"),
    ("翰林院编修", "翰林院"),
    ("庶常", "翰林院"),          # 庶常=庶吉士，翰林储才；曾误归生员(民)，PR gemini 纠正
    # 宦官/卫
    ("司礼监掌印太监", "司礼监"),       # 经「司礼监」stem 命中，不靠 bare「掌印太监」
    ("司礼监秉笔太监,东厂提督", "司礼监"),
    ("御马监掌印太监", "内廷"),          # 二十四衙门掌印不归司礼监(PR gemini:去 bare 掌印太监 stem)
    ("锦衣卫都指挥使", "锦衣卫"),
    ("内廷大总管", "内廷"),
    # 地方（督抚总督不被边镇地名吞）
    ("蓟辽总督", "地方"),
    ("陕西巡抚", "地方"),
    ("永城知县", "地方"),
    # 边镇/武职（旧版漏判的将军类）
    ("荡寇将军", "边镇"),
    ("辽东游击将军", "边镇"),
    ("山海关总兵", "边镇"),
    ("京畿防务总理统蓟镇宣大", "边镇"),
    # 后宫（旧版进待铨）
    ("中宫皇后", "后宫"),
    ("贵妃", "后宫"),
    ("奉圣夫人（先帝乳母）", "后宫"),
    # 民间（旧版进待铨）
    ("诸生（应天府学）", "生员"),
    ("陕北流寇首领", "流寇"),
])
def test_office_type_from_table(office, expected):
    assert infer(office) == expected


def test_后宫_current_type_short_circuits():
    assert infer("妃", current_type="后宫") == "后宫"


def test_unknown_falls_to_daiquan_without_backend(monkeypatch):
    # 无 CLI 后端 + 表查不中 → 待铨（不误判、不崩）
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    assert infer("绝无此名的杜撰怪衔甲乙丙") == "待铨"


def test_api_channel_unknown_office_does_not_use_backend_env(monkeypatch):
    dbmod._OFFICE_TYPE_LLM_CACHE.clear()
    called = []
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "agy")
    monkeypatch.setattr(cb, "_run_backend", lambda prompt: called.append(prompt) or ("边镇", 1))
    cfg = LLMConfig(
        api_key="sk-test",
        base_url="https://api.example.com/v1",
        model="gpt-api",
        channel="api",
    )

    assert infer("绝无此名的杜撰怪衔丁戊己", llm_config=cfg) == "待铨"
    assert called == []


def test_runtime_cli_unknown_office_uses_configured_runner_without_env(monkeypatch):
    dbmod._OFFICE_TYPE_LLM_CACHE.clear()
    seen = {}
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)

    def fake_run(prompt, llm_config=None):
        seen["prompt"] = prompt
        seen["config"] = llm_config
        return "边镇", 1

    monkeypatch.setattr(cb, "_run_backend_for_config", fake_run)
    cfg = LLMConfig(
        api_key="cli-backend",
        base_url="",
        model="api-fallback",
        channel="cli",
        cli_runner="codex",
        cli_model="gpt-5.5",
        cli_timeout_seconds=240,
    )

    assert infer("绝无此名的杜撰怪衔庚辛壬", llm_config=cfg) == "边镇"
    assert "官名：绝无此名的杜撰怪衔庚辛壬" in seen["prompt"]
    assert seen["config"] is cfg
