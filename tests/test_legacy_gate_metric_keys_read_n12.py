"""N12：legacy modifiers 读端须跟 GATE_METRIC_KEYS，不另内联四元组。

Web `_humanize_legacy_effect` 与 models `_legacy_effect_has_work` 读同一份
legacy modifiers 顶层账目键；真源变更时读端行为须跟着变。
"""

from __future__ import annotations

import web_app
from ming_sim import models


def test_humanize_legacy_effect_follows_gate_metric_keys(monkeypatch):
    """web 读端：只 humanize 真源里的账目键。"""
    monkeypatch.setattr(web_app, "GATE_METRIC_KEYS", ("民心",))
    text = web_app._humanize_legacy_effect(
        {"国库": 10, "内库": -2, "民心": 5, "皇威": -3},
        content=None,
    )
    assert text == "民心+5%"


def test_legacy_effect_has_work_follows_gate_metric_keys(monkeypatch):
    """models 读端：work 判定只认真源账目键。"""
    monkeypatch.setattr(models, "GATE_METRIC_KEYS", ("民心",))
    assert models._legacy_effect_has_work({"modifiers": {"国库": 10}}) is False
    assert models._legacy_effect_has_work({"modifiers": {"民心": 5}}) is True
