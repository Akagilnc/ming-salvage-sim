"""#1721 B2: stale importable agno must reach POST /api/menu/new_game as typed facts."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import ming_sim.llm_model as llm_model
import web_app
from ming_sim.constants import ROOT_DIR


class _StaleSqliteDb:
    """Importable Agno 2-shaped store: no runs_table kwarg."""

    def __init__(
        self,
        db_file=None,
        session_table=None,
        memory_table=None,
        spans_table=None,
        **kwargs,
    ):
        if "runs_table" in kwargs:
            raise TypeError(
                "SqliteDb.__init__() got an unexpected keyword argument 'runs_table'"
            )


def _agno_requirement_line() -> str:
    for raw in Path(ROOT_DIR, "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        name = line.split("[", 1)[0]
        for sep in (">=", "==", "~=", "<=", ">", "<", "!="):
            name = name.split(sep, 1)[0]
        if name.strip().lower() == "agno":
            return line
    raise AssertionError("requirements.txt missing agno line")


def test_new_game_stale_agno_returns_typed_dependency_facts(tmp_path, monkeypatch):
    monkeypatch.setattr(llm_model, "SqliteDb", _StaleSqliteDb)
    monkeypatch.setenv("MING_SIM_DB", str(tmp_path / "ming.db"))
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(web_app, "load_runtime_llm", lambda: {})
    monkeypatch.setattr(web_app, "web_game", None)

    response = TestClient(web_app.app).post("/api/menu/new_game")
    assert response.status_code == 500
    detail = response.json()["detail"]
    assert isinstance(detail, dict)
    assert detail["package"] == "agno"
    assert detail["requirement"] == _agno_requirement_line()
    assert "message" in detail and str(detail["message"]).strip()
