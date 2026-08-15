"""#63 class 2：模块 extractor 输出里混进「属其它模块」的合法字段，被 _sanitize_module_output
按白名单静默剔除（合法 delta 无声蒸发）。本刀加 surface 留痕（不 reroute、不改剔除行为）。

契约：
  1) 错放字段仍被剔除（行为不变）；
  2) 同时经 tlog 点名「键 → 它本该去的模块」（misroute 可观测）；
  3) 不误报——本模块合法字段、以及无主/垃圾键都不触发 misroute 日志（避免噪音）。
"""

import ming_sim.simulation as sim

def _capture_tlog(monkeypatch):
    msgs: list[str] = []
    monkeypatch.setattr(sim, "tlog", lambda m: msgs.append(m))
    return msgs

def test_misrouted_field_dropped_and_surfaced(monkeypatch):
    # army_delta 属 military_external，错放进 internal 模块输出。
    data = {"metric_delta": {"国库": 10}, "army_delta": {"guanning": {"morale": -1}}}

    msgs = _capture_tlog(monkeypatch)
    out = sim._sanitize_module_output("internal", data)

    # 行为不变：本模块合法字段保留，错放字段被剔除（不在 internal 白名单）。
    assert out.get("metric_delta") == {"国库": 10}
    assert "army_delta" not in out
    # 可观测：tlog 点名 army_delta，且指出它应属 military_external。
    surfaced = [m for m in msgs if "misroute" in m and "army_delta" in m]
    assert surfaced, msgs
    assert "military_external" in surfaced[0], surfaced

def test_in_module_fields_do_not_surface(monkeypatch):
    # 全是 internal 自己的合法字段——不应报 misroute。
    data = {"metric_delta": {"民心": 5}, "faction_delta": {}}

    msgs = _capture_tlog(monkeypatch)
    sim._sanitize_module_output("internal", data)

    assert not [m for m in msgs if "misroute" in m], msgs

def test_issues_module_accepts_event_outcomes_alias_without_misroute(monkeypatch):
    data = {"event_outcomes": {"jisi_lubian": "入塞被遏"}}

    msgs = _capture_tlog(monkeypatch)
    out = sim._sanitize_module_output("issues", data)

    assert out["事件结局"] == {"jisi_lubian": "入塞被遏"}
    assert "event_outcomes" not in out
    assert not [m for m in msgs if "misroute" in m], msgs

def test_garbage_key_does_not_surface(monkeypatch):
    # 无主/垃圾键（不属任何模块）——不报 misroute（只报「属其它模块」的错放，避免噪音）。
    data = {"metric_delta": {"皇威": 1}, "totally_made_up_key": 123}

    msgs = _capture_tlog(monkeypatch)
    out = sim._sanitize_module_output("internal", data)

    assert "totally_made_up_key" not in out  # 仍被剔除
    assert not [m for m in msgs if "misroute" in m], msgs

