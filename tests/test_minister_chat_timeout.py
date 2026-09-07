"""召对「等多久算死」= 设置页那一格（静默判死阈值）。#1465 切片③。

owner 2026-09-07 拍：设置页 `cli_timeout_seconds` 从「总超时」改接空转轴——距上次
新内容这么久没有动静，就判该次调用已死并重试；#353 的召对 90 / 结算 300 分档随硬墙
钟一同删（不再有第二套超时权威，CLI 与 API 同吃这一个阈值）。

本文件从真实入口证明这条线：设置 API 写阈值 → 召对流（CLI 通道）判死时点随之变。
受控推进时钟，不跑真墙钟、不起真 CLI 进程、不连真 LLM。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import ming_sim.cli_backend as cb
import web_app
from tests.cli_process_doubles import SilentUntilKilled, install_fake_cli_runner
from tests.test_chat_stream_failpaths_393 import _parse_sse, _post_chat_stream
from tests.test_cli_transport_1465 import _cli_web_game

# 受控时钟：每读一次表推进阈值的 1/4——判死落在第 4 次空转核查，时点确定不看真墙钟。
_CHECKS_TO_DEATH = 4


def _save_idle_threshold_via_settings_api(monkeypatch, tmp_path, seconds: float) -> float:
    """真实设置入口：POST /api/menu/llm（CLI 通道）写下静默判死阈值，落到临时 runtime 档。"""
    from ming_sim import llm_config as llm_config_mod

    monkeypatch.setattr(
        llm_config_mod, "RUNTIME_LLM_PATH", str(tmp_path / "runtime_llm.json")
    )
    # 保存前的连通性 smoke 会真起 CLI/网络调用，本测只验阈值这条线 → 只替换该边界。
    monkeypatch.setattr(web_app, "_verify_llm_configs_or_raise", lambda *_a, **_k: None)
    response = TestClient(web_app.app).post(
        "/api/menu/llm",
        json={
            "base_url": "",
            "model": "",
            "api_key": "",
            "channel": "cli",
            "cli_runner": "claude",
            "cli_model": "cli-model-test",
            "cli_timeout_seconds": seconds,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["llm"]["cli_timeout_seconds"] == seconds
    return seconds


@pytest.mark.parametrize("idle_seconds", [45.0, 120.0])
def test_minister_chat_idle_death_time_follows_settings_threshold(
    monkeypatch, tmp_path, game, idle_seconds,
):
    """设置页写下的静默阈值就是召对判死的时点：改这一格，判死时点随之变。

    注入 = 大臣的 CLI 子进程一个字都不出。观察面 = 相邻两次子进程起跑的时钟差
    （= 上一次熬到判死用掉的静默时长）+ 玩家侧结构化 error。时钟每被读一次推进
    阈值的 1/4，判死时点确定，不跑真墙钟。
    """
    idle = _save_idle_threshold_via_settings_api(monkeypatch, tmp_path, idle_seconds)
    step = idle / _CHECKS_TO_DEATH
    clock = {"t": 1000.0}

    def _advancing_clock() -> float:
        clock["t"] += step
        return clock["t"]

    monkeypatch.setattr(cb, "_cli_process_clock", _advancing_clock)
    script = install_fake_cli_runner(monkeypatch, [
        {"stdout": (SilentUntilKilled(),), "returncode": 0},
    ])
    starts: list[float] = []
    scripted_popen = cb.subprocess.Popen

    def _recording_popen(cmd, **kwargs):
        starts.append(clock["t"])  # 只读，不推进
        return scripted_popen(cmd, **kwargs)

    monkeypatch.setattr(cb.subprocess, "Popen", _recording_popen)
    web_game, minister = _cli_web_game(game)

    response = _post_chat_stream(monkeypatch, web_game, minister)
    assert response.status_code == 200, response.text
    events = _parse_sse(response.text)
    assert events[-1][0] == "error", events
    detail = events[-1][1]
    attempts = detail.get("transport_attempts") or []
    assert attempts, detail
    assert [a.get("code") for a in attempts] == ["llm_idle_timeout"] * len(attempts), attempts
    assert script.calls == len(attempts) >= 2

    # 每一次都熬满设置页写下的阈值才判死（上界 = 一次核查的粒度）
    spans = [b - a for a, b in zip(starts, starts[1:])]
    assert spans, starts
    for span in spans:
        assert idle <= span <= idle + 2 * step, (idle, spans)
