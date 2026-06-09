"""探针 driver —— 确定性结算入口（step1）。

形态(1) 我在对话里直接当 runtime+LLM：自产邸报叙事 + 中文 schema 形态的稀疏 delta，
driver 负责把 delta 规范化后跑引擎的确定性结算核（pre_settle + settle_with_delta），
绕过引擎自带的 extractor / 章节记忆 LLM 步。真实流程与本 driver 共用同一结算核（ADR 0004）。
"""

from __future__ import annotations

import argparse
import json
import sys

from ming_sim.context import bind_content
from ming_sim.decree import pre_settle, settle_with_delta
import ming_sim.issues as issues_mod
from ming_sim.issues import apply_score_extraction, validate_delta_shape as _validate_delta_shape
from ming_sim.content import GameContent
from ming_sim.db import GameDB
from ming_sim.models import LLMConfig
from ming_sim.simulation import _canonicalize_extraction

DEFAULT_DB = "data/probe.db"

# 探针 driver 显式确定性(#54 / ADR-0004):对话里的我已是 LLM、自产完整 delta,落库核绝不该
# 再 spawn 第二个 LLM 做 issue/office enrichment。传 channel=api 空配置 → cli_backend_active
# 恒 False(见其首个分支),屏蔽所有 CLI-gated LLM 调用,**含 legacy MING_SIM_LLM_BACKEND env
# 回落**;且不触发任何 API 调用(enrichment/office 推断纯 CLI-gated,api 通道直接跳过)。
_DETERMINISTIC_LLM = LLMConfig(api_key="", base_url="", model="", channel="api")

# delta 容器/二级类型校验的单一真源已抽到 ming_sim.issues.validate_delta_shape(#57):
# driver 在 pre_settle 前调一次防 pre_settle 半改;落库核 apply_score_extraction 自身也调一次
# 防 apply 内部半落库。两路径共用同一契约,真实流不再缺二级校验。


def open_game(db_path: str = DEFAULT_DB):
    """打开存档：load content + bind + GameDB + load_state。返回 (db, state, content)。"""
    content = GameContent.load()
    bind_content(content)
    issues_mod.bind_content(content)
    db = GameDB(db_path, content)
    state = db.load_state()
    return db, state, content


def _print_state(state) -> None:
    print(f"回合 turn={state.turn}  纪年={state.year}年{state.period}月")
    metrics = getattr(state, "metrics", None) or {}
    if metrics:
        print("国势：" + "  ".join(f"{k}={v}" for k, v in metrics.items()))


def _dump_board(db, state) -> None:
    """盘面快照：当前回合 + 各地区民心/动乱/城防炮。"""
    _print_state(state)
    print("\n地区：")
    rows = db.conn.execute(
        "SELECT id, public_support, unrest, cannon FROM regions ORDER BY id"
    ).fetchall()
    for r in rows:
        print(f"  {r['id']}：民心{r['public_support']} 动乱{r['unrest']} 城防炮{r['cannon']}门")


def run_settle(db, state, content, raw_delta, *, narrative="", decree_text="", registry=None) -> str:
    """收一份中文 schema 形态的稀疏 delta（+ 我产的邸报 narrative / 诏书 decree_text）→
    规范化（中文 key→英文 canonical）→ pre_settle（财政 tick + auto_trigger）→
    settle_with_delta（落库→inertia→结局→推进），推进一回合。返回结算报告文本。

    narrative 落 turn_logs/turn_reports 作下月前文 + 玩家邸报;canonical delta 以 JSON 落
    turn_extractions.extractor_output 作 replay/timeline 重建痕迹（memories 读此字段）。
    章节记忆 / 结局总评不注入（driver 无 llm_config），由对话里的我另行产出。
    畸形 delta 抛 `ValueError`（库语义）；CLI 由 `main()` 转退出码。
    """
    # public 边界:None 当空回合;falsy/非 dict([]/""/0/str)不静默吞成空结算照样推进(codex-P1a)。
    if raw_delta is None:
        raw_delta = {}
    if not isinstance(raw_delta, dict):
        raise ValueError(f"delta 必须是 object(dict)，实得 {type(raw_delta).__name__}")
    extracted = _canonicalize_extraction(raw_delta)
    _validate_delta_shape(extracted)  # 崩前拦畸形/未知字段,避免 pre_settle 动 DB 后半落库(RT-1/P1b)
    before_turn = state.turn
    pre_settle(state, db)
    return settle_with_delta(
        state,
        db,
        extracted,
        before_turn=before_turn,
        content=content,
        registry=registry,
        narrative=narrative,
        decree_text=decree_text,
        extractor_output=json.dumps(extracted, ensure_ascii=False),
        # 注入确定性 applier:落库不走 legacy env CLI enrichment,driver 纯确定性(#54)。
        delta_applier=lambda d, s, ex, ct, rg: apply_score_extraction(
            d, s, ex, content=ct, registry=rg, llm_config=_DETERMINISTIC_LLM
        ),
    )


def main(argv=None, *, game=None) -> int:
    """CLI 入口：state（打印盘面）/ settle --delta <json>（注入 delta 结算）/ dump（盘面快照）。

    game=(db,state,content) 可注入（测试用）；否则按 --db 打开存档。
    库层校验抛 ValueError，CLI 在此 catch、打到 stderr、返回退出码 1（不让 ValueError 透到用户）。
    """
    parser = argparse.ArgumentParser(prog="driver", description="探针确定性结算 driver")
    parser.add_argument("--db", default=DEFAULT_DB, help="存档路径")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("state", help="打印当前盘面（回合/纪年/国势）")
    p_settle = sub.add_parser("settle", help="注入 delta JSON 跑确定性结算并推进一回合")
    p_settle.add_argument("--delta", required=True, help="中文 schema delta 的 JSON 文件路径")
    sub.add_parser("dump", help="盘面快照（回合 + 各地区民心/动乱/城防炮）")
    args = parser.parse_args(argv)

    db, state, content = game if game is not None else open_game(args.db)

    if args.cmd == "state":
        _print_state(state)
        return 0
    if args.cmd == "settle":
        with open(args.delta, encoding="utf-8") as f:
            obj = json.load(f)
        # 信封形态 {narrative, decree_text, delta}（我每回合的完整产出）;否则裸 delta（兼容）。
        if isinstance(obj, dict) and "delta" in obj:
            raw_delta = obj["delta"]
            narrative = str(obj.get("narrative") or "")
            decree_text = str(obj.get("decree_text") or "")
        else:
            raw_delta, narrative, decree_text = obj, "", ""
        # run_settle 抛 ValueError（畸形/未知/非 dict delta，含信封 delta 非 object）→ CLI 转退出码。
        try:
            report = run_settle(
                db, state, content, raw_delta, narrative=narrative, decree_text=decree_text
            )
        except ValueError as exc:
            print(f"settle 失败：{exc}", file=sys.stderr)
            return 1
        print(report)
        return 0
    if args.cmd == "dump":
        _dump_board(db, state)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
