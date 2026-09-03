"""#1721 B2: stale importable agno must reach POST /api/menu/new_game as typed facts."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
STALE_AGNO_WHEEL = REPO / "tests" / "fixtures" / "agno-2.7.3-py3-none-any.whl"


@pytest.fixture(scope="session")
def stale_agno_site(tmp_path_factory):
    site = tmp_path_factory.mktemp("stale-agno")
    with zipfile.ZipFile(STALE_AGNO_WHEEL) as wheel:
        wheel.extractall(site)
    return site


def test_new_game_stale_agno_returns_typed_dependency_facts(tmp_path, stale_agno_site):
    env = os.environ.copy()
    env["PYTHONPATH"] = str(stale_agno_site) + os.pathsep + env.get("PYTHONPATH", "")
    env["MING_SIM_DB"] = str(tmp_path / "ming.db")
    env["MING_SIM_USER_DATA_DIR"] = str(tmp_path / "ud")
    env["OPENAI_API_KEY"] = "sk-test"
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
    assert detail["package"] == "agno"
    requirement_lines = {
        line.strip()
        for line in (REPO / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    assert detail["requirement"] in requirement_lines
    assert "message" in detail and str(detail["message"]).strip()
