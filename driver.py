"""探针 driver —— 确定性结算入口（step1）。

形态(1) 我在对话里直接当 runtime+LLM：自产邸报叙事 + 中文 schema 形态的稀疏 delta，
driver 负责把 delta 规范化后跑引擎的确定性结算核（pre_settle + settle_with_delta），
绕过引擎自带的 extractor / 章节记忆 LLM 步。真实流程与本 driver 共用同一结算核（ADR 0004）。
"""

from __future__ import annotations

import argparse
import json

from ming_sim.context import bind_content
from ming_sim.decree import pre_settle, settle_with_delta
import ming_sim.issues as issues_mod
from ming_sim.content import GameContent
from ming_sim.db import GameDB
from ming_sim.simulation import EMPTY_EXTRACTION, _canonicalize_extraction

DEFAULT_DB = "data/probe.db"


def _validate_delta_shape(extracted: dict) -> None:
    """canonical delta 各顶层字段的容器类型必须匹配 schema（dict / list），否则**结算前**响亮报错。

    driver 只跑 `_canonicalize_extraction`（归一 key），不跑真实流程的 `_sanitize_module_output`
    白名单/清洗。畸形模块值（如 `国势变化:"foo"` → metric_delta="foo"）若直送 apply 会在结算
    中途崩 `.items()`，叠加非原子结算 = 半落库（cmr red-team RT-1）。在 pre_settle 动 DB 前校验，
    崩前拦住、回合不半推进。
    """
    for key, value in extracted.items():
        expected = EMPTY_EXTRACTION.get(key)
        if isinstance(expected, dict) and not isinstance(value, dict):
            raise SystemExit(f"delta 字段 {key} 必须是 object(dict)，实得 {type(value).__name__}")
        if isinstance(expected, list) and not isinstance(value, list):
            raise SystemExit(f"delta 字段 {key} 必须是 array(list)，实得 {type(value).__name__}")


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
    """
    extracted = _canonicalize_extraction(raw_delta or {})
    _validate_delta_shape(extracted)  # 崩前拦畸形模块值,避免 pre_settle 动 DB 后半落库(RT-1)
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
    )


def main(argv=None, *, game=None) -> int:
    """CLI 入口：state（打印盘面）/ settle --delta <json>（注入 delta 结算）/ dump（盘面快照）。

    game=(db,state,content) 可注入（测试用）；否则按 --db 打开存档。
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
        # delta 必须是 object;非 dict 响亮报错,不静默吞成空 delta 照样推进回合(cmr codex-P2b)。
        if not isinstance(raw_delta, dict):
            raise SystemExit(
                f"settle 的 delta 必须是 object(dict),实得 {type(raw_delta).__name__}。"
                '信封形态 {"narrative":..., "delta":{...}},或直接给裸 delta dict。'
            )
        report = run_settle(
            db, state, content, raw_delta, narrative=narrative, decree_text=decree_text
        )
        print(report)
        return 0
    if args.cmd == "dump":
        _dump_board(db, state)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
