"""#542 r4: SETTLEMENT_FLOW scene_registry contract + unused close-scene wrapper deletion.

Seams:
- docs/SETTLEMENT_FLOW.md must document production scene_registry on the three
  settlement auto-close owners (advance_without_edict / pre_settle / resolve_directives).
- GameSession / beat_orchestration must not keep zero-call production wrappers that
  bypass the start/join parallel path used by close_night.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from ming_sim import beat_orchestration as bo
from ming_sim.decree import advance_without_edict, pre_settle, resolve_directives
from ming_sim.session import GameSession

ROOT = Path(__file__).resolve().parents[1]
SETTLEMENT_FLOW = ROOT / "docs" / "SETTLEMENT_FLOW.md"


def _flow_text() -> str:
    return SETTLEMENT_FLOW.read_text(encoding="utf-8")


def test_settlement_flow_documents_scene_registry_contract_on_three_seams():
    """C1: settlement contract names scene_registry + ownership + fail + join-before-finalize."""
    text = _flow_text()
    for name, fn in (
        ("advance_without_edict", advance_without_edict),
        ("pre_settle", pre_settle),
        ("resolve_directives", resolve_directives),
    ):
        assert "scene_registry" in inspect.signature(fn).parameters, name
        assert f"{name}" in text and "scene_registry" in text

    # Caller ownership: session-held ChatTurnSceneRegistry; never a second registry.
    assert "scene_registry" in text
    assert "ChatTurnSceneRegistry" in text
    assert "session._scene_registry" in text or "调用方既有" in text
    assert "不在此新建" in text or "不自建第二" in text or "不新建" in text

    # Failure drain / abort surface (night stays open; settle does not enter settling).
    assert "abandon" in text or "失败" in text
    assert "OPEN" in text or "保持开" in text or "夜保持" in text

    # join-before-finalize invariant
    assert "join" in text
    assert "终局" in text or "finalize" in text.lower() or "join-before-finalize" in text


def test_unused_close_scene_production_wrappers_are_gone():
    """C2: zero-call start_chat_turn_close_scene / run_close_scene_on_registry deleted."""
    assert not hasattr(GameSession, "start_chat_turn_close_scene")
    assert not hasattr(bo, "run_close_scene_on_registry")
    # Production path kept: registry + start/join pair (no second executor/coordinator).
    assert hasattr(bo, "ChatTurnSceneRegistry")
    assert hasattr(bo, "start_close_scene_on_registry")
    assert hasattr(bo, "join_close_scene_on_registry")


def test_repo_py_has_no_call_sites_for_deleted_close_wrappers():
    """C2 class sweep: no remaining def/call references to the deleted wrappers."""
    banned = ("start_chat_turn_close_scene", "run_close_scene_on_registry")
    hits: list[str] = []
    for path in ROOT.rglob("*.py"):
        if any(part in {"__pycache__", ".venv", "node_modules", ".git"} for part in path.parts):
            continue
        # This contract file names the banned symbols in string literals only.
        if path.resolve() == Path(__file__).resolve():
            continue
        src = path.read_text(encoding="utf-8")
        if not any(name in src for name in banned):
            continue
        tree = ast.parse(src, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in banned:
                hits.append(f"{path}:{node.lineno}:def {node.name}")
            elif isinstance(node, ast.Name) and node.id in banned:
                hits.append(f"{path}:{node.lineno}:{node.id}")
            elif isinstance(node, ast.Attribute) and node.attr in banned:
                hits.append(f"{path}:{node.lineno}:{node.attr}")
    assert hits == [], hits
