"""探针：用本地 CLI 后端（agy/codex）非交互跑完整一回合，验证全结算链。

跳大臣对话，直接塞诏书草案 → 颁诏 → 推演 → HITL 决策点自动选第一项 →
4 模块 extractor 出 JSON → apply 落库 → end_turn。最后打印邸报头 + 国库变化，
证明「脱 api key 整条结算链能跑」。

用法（脱 key）:
    MING_SIM_LLM_BACKEND=agy .venv/bin/python -m scripts.agy_turn_probe \
        --db /tmp/agy_test.db \
        --directive "着户部发太仓银三万两赈济陕西。"
"""

from __future__ import annotations

import argparse
import sys
import time

from ming_sim.models import LLMConfig
from ming_sim.session import GameSession, TurnPhase
from scripts.probe_directive_contract import add_narrative_probe_directive


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--db", required=True)
    p.add_argument("--directive", action="append", required=True)
    p.add_argument("--decree", default="", help="传入则跳过 LLM 写诏")
    ns = p.parse_args()

    # CLI 后端下这些值不会真用到（cli_backend 走 subprocess），给占位即可。
    cfg = LLMConfig(
        model="agy-local", api_key="none", base_url="http://localhost/v1",
        timeout_seconds=300, max_tokens=2048,
    )
    session = GameSession(ns.db, cfg, verify_llm=False)

    def on_event(kind, data):
        s = str(data)
        if kind in ("simulator_chunk", "extractor_chunk"):
            return
        print(f"  [evt] {kind}: {s[:120]}")

    snap = session.begin_turn()
    before = dict(session.state.metrics)
    print(f"[turn] {session.state.year}年{session.state.period}月 turn={session.state.turn} "
          f"国库={before.get('国库')} 民心={before.get('民心')} 皇威={before.get('皇威')}")

    for sequence, text in enumerate(ns.directive, start=1):
        v = add_narrative_probe_directive(
            session, text, notes="agy-probe",
            probe_id="agy-turn", sequence=sequence,
        )
        print(f"[directive] id={v.id} {text[:50]}")

    session.enter_review()
    t0 = time.monotonic()
    print("[resolve] 颁诏推演中（agy 调用，耐心等）...")
    result = session.resolve_turn(decree=ns.decree, on_event=on_event)

    # HITL：推演若出决策点，自动选第一项，续跑 phase2（含 4 模块 extractor）。
    rounds = 0
    while getattr(result, "awaiting", False):
        rounds += 1
        decisions = session.pending_decisions()
        print(f"[hitl] 第{rounds}轮决策点 {len(decisions)} 个，自动选第一项：")
        choices = []
        for d in sorted(decisions, key=lambda x: int(x["idx"])):
            opts = d.get("options") or []
            pick = opts[0] if opts else {}
            label = pick.get("label", "") if isinstance(pick, dict) else str(pick)
            print(f"   - #{d['idx']} {str(d.get('title'))[:40]} → 选「{label[:40]}」")
            choices.append({"label": label, "hint": pick.get("hint", "") if isinstance(pick, dict) else ""})
        report = session.submit_decisions(choices, on_event=on_event)
        # submit_decisions 返回报告字符串；置 ISSUED。再无 awaiting。
        result = type("R", (), {"awaiting": False, "report": report})()

    report_text = result.report if hasattr(result, "report") else str(result)
    dt = time.monotonic() - t0

    session.end_turn()
    after = dict(session.state.metrics)

    print(f"\n[resolve] 完成，耗时 {dt:.0f}s。phase={session.current_phase()}")
    print("---- 邸报头 400 字 ----")
    print((report_text or "")[:400])
    print("---- 盘面变化 ----")
    for k in ("国库", "内库", "民心", "皇威", "兵force" if "兵force" in after else "军心"):
        if k in before or k in after:
            print(f"  {k}: {before.get(k)} → {after.get(k)}")
    # 全量 diff（防上面 key 名猜错）
    print("  [全量 metric diff]", {k: (before.get(k), after.get(k))
                                   for k in sorted(set(before) | set(after))
                                   if before.get(k) != after.get(k)})
    return 0


if __name__ == "__main__":
    sys.exit(main())
