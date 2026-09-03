"""#1721 B2: stale importable agno must reach POST /api/menu/new_game as typed facts."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
import pytest

REPO = Path(__file__).resolve().parents[1]
STALE_AGNO_WHEEL = REPO / "tests" / "fixtures" / "agno-2.7.3-py3-none-any.whl"


def _stale_agno_env(tmp_path: Path, stale_agno_site: Path) -> dict[str, str]:
    """#1721：stale agno 2.7.3 site 压在 PYTHONPATH 前端，DB/用户目录都指到 tmp。"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(stale_agno_site) + os.pathsep + env.get("PYTHONPATH", "")
    env["MING_SIM_DB"] = str(tmp_path / "ming.db")
    env["MING_SIM_USER_DATA_DIR"] = str(tmp_path / "ud")
    env["OPENAI_API_KEY"] = "sk-test"
    return env


def _requirements_lines() -> set[str]:
    return {
        line.strip()
        for line in (REPO / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


@pytest.fixture(scope="session")
def stale_agno_site(tmp_path_factory):
    site = tmp_path_factory.mktemp("stale-agno")
    with zipfile.ZipFile(STALE_AGNO_WHEEL) as wheel:
        wheel.extractall(site)
    return site


def test_new_game_stale_agno_returns_typed_dependency_facts(tmp_path, stale_agno_site):
    env = _stale_agno_env(tmp_path, stale_agno_site)
    probe = tmp_path / "probe.py"
    probe.write_text(
        """\
from importlib.metadata import version
from fastapi.testclient import TestClient
import json
import web_app

assert version("agno") == "2.7.3"
web_app.load_runtime_llm = lambda: {}
web_app.web_game = None
response = TestClient(web_app.app).post("/api/menu/new_game")
print(json.dumps({"status": response.status_code, "detail": response.json()["detail"]}))
""",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [sys.executable, str(probe)],
        cwd=str(REPO),
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    assert payload["status"] == 500
    detail = payload["detail"]
    # 与 continue SSE 共用同一 typed 投影：HTTP 面不得丢 code。
    assert detail["code"] == "dependency_mismatch"
    assert detail["package"] == "agno"
    req = Requirement(detail["requirement"])
    assert canonicalize_name(req.name) == canonicalize_name(detail["package"])
    assert detail["requirement"] in _requirements_lines()
    assert "message" in detail and str(detail["message"]).strip()


def test_continue_stale_agno_sse_carries_typed_dependency_facts(tmp_path, stale_agno_site):
    """#1721 B2：continue 的 DependencyMismatch 不得压成 message-only SSE。
    真实 POST /api/menu/continue 入口 → SSE error 须带 typed code/package/requirement/message。"""
    (tmp_path / "ming.db").touch()  # 菜单 continue 门：_has_main_db() 须为真
    env = _stale_agno_env(tmp_path, stale_agno_site)
    probe = tmp_path / "probe.py"
    probe.write_text(
        """\
from importlib.metadata import version
from fastapi.testclient import TestClient
import json
import web_app

assert version("agno") == "2.7.3"
web_app.load_runtime_llm = lambda: {}
web_app.web_game = None
response = TestClient(web_app.app).post("/api/menu/continue")
print(json.dumps({"sse": response.text}))
""",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [sys.executable, str(probe)],
        cwd=str(REPO),
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    # 复用 #1195 continue 流的同一 SSE 解析（不复制第二份）。
    from tests.test_menu_continue_stream_1195 import _parse_sse

    error_events = [data for name, data in _parse_sse(payload["sse"]) if name == "error"]
    assert len(error_events) == 1
    detail = error_events[0]
    assert detail["code"] == "dependency_mismatch"
    assert detail["package"] == "agno"
    req = Requirement(detail["requirement"])
    assert canonicalize_name(req.name) == canonicalize_name(detail["package"])
    assert detail["requirement"] in _requirements_lines()
    assert str(detail["message"]).strip()
